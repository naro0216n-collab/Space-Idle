from __future__ import annotations

from dataclasses import dataclass
import gzip
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ..application_commands import (
    ApplicationError, GetBottlenecks, GetBuildOptions, GetCatalog, GetCargoFlows,
    GetContracts, GetFleet, GetFlowReport, GetLocation, GetLogisticsLanes,
    GetLogisticsSummary, GetProjects, GetResearch, GetRoutes, GetSurveys,
    GetTransportAllocationOptions, GetTransportAllocations, GetWorld,
)
from ..persistence import SaveFormatError
from .codec import ApiPayloadError, command_schema, decode_command, to_jsonable
from .runtime import GameRuntime, RevisionConflict, RuntimeResult


@dataclass(frozen=True)
class ApiServerConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    cors_origins: tuple[str, ...] = ("*",)
    gzip_min_bytes: int = 1024
    tls_certfile: str | None = None
    tls_keyfile: str | None = None
    webui_dir: str | None = None


class SpaceIdleHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, runtime: GameRuntime, config: ApiServerConfig):
        super().__init__(server_address, handler_class)
        self.runtime = runtime
        self.api_config = config


class SpaceIdleRequestHandler(BaseHTTPRequestHandler):
    server: SpaceIdleHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)

    def _cors_headers(self) -> dict[str, str]:
        origin = self.headers.get("Origin")
        allowed = self.server.api_config.cors_origins
        if not origin:
            return {}
        if "*" in allowed:
            return {"Access-Control-Allow-Origin": "*"}
        if origin in allowed:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        return {}

    def _write_empty(self, status: int, *, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _write_static(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "asset not found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _webui_root(self) -> Path:
        configured = self.server.api_config.webui_dir
        if configured:
            return Path(configured)
        return Path(__file__).resolve().parent.parent / "webui"

    def _serve_webui(self, path: str) -> bool:
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }
        relative = "index.html" if path == "/" else unquote(path).lstrip("/")
        if not relative:
            return False

        root = self._webui_root().resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False

        content_type = content_types.get(candidate.suffix.lower())
        if content_type is None:
            return False
        if not candidate.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not_found", "asset not found")
            return True
        self._write_static(candidate, content_type)
        return True

    def _write_json(
        self,
        status: int,
        payload: Any,
        *,
        revision: int | None = None,
        etag: str | None = None,
        cache_control: str = "no-store",
    ) -> None:
        raw = json.dumps(to_jsonable(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        use_gzip = (
            len(raw) >= self.server.api_config.gzip_min_bytes
            and "gzip" in self.headers.get("Accept-Encoding", "").lower()
        )
        body = gzip.compress(raw, compresslevel=5) if use_gzip else raw
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache_control)
        if revision is not None:
            self.send_header("X-Space-Idle-Revision", str(revision))
        if etag is not None:
            self.send_header("ETag", etag)
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            return {}
        try:
            length = int(content_length)
        except ValueError as exc:
            raise ApiPayloadError("invalid Content-Length") from exc
        if length < 0 or length > 1_000_000:
            raise ApiPayloadError("request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiPayloadError("request body must be UTF-8 JSON") from exc

    def _result(self, result: RuntimeResult, *, etag: str | None = None, cache_control: str = "no-store") -> None:
        if etag is not None and self.headers.get("If-None-Match") == etag:
            self._write_empty(HTTPStatus.NOT_MODIFIED, headers={"ETag": etag})
            return
        self._write_json(
            HTTPStatus.OK,
            {"ok": True, "revision": result.revision, "data": result.data},
            revision=result.revision,
            etag=etag,
            cache_control=cache_control,
        )

    def _error(
        self, status: int, code: str, message: str, *,
        revision: int | None = None, details: dict[str, object] | None = None,
    ) -> None:
        error: dict[str, object] = {"code": code, "message": message}
        if details:
            error["details"] = details
        self._write_json(status, {"ok": False, "error": error}, revision=revision)

    def _query_result(self, query, *, catalog: bool = False) -> None:
        result = self.server.runtime.query(query)
        etag = (
            f'"catalog-{self.server.runtime.content_id}"'
            if catalog
            else f'"rev-{result.revision}"'
        )
        self._result(
            result,
            etag=etag,
            cache_control="private, max-age=3600" if catalog else "no-cache",
        )

    def _if_match_revision(self) -> int | None:
        value = self.headers.get("If-Match")
        if value is None:
            return None
        value = value.strip()
        if value == "*":
            return None
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        if not value.startswith("rev-"):
            raise ApiPayloadError("If-Match must be a revision ETag such as \"rev-3\"")
        try:
            revision = int(value[4:])
        except ValueError as exc:
            raise ApiPayloadError("If-Match revision is invalid") from exc
        if revision < 0:
            raise ApiPayloadError("If-Match revision is invalid")
        return revision

    def do_OPTIONS(self) -> None:
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, If-None-Match, If-Match",
            "Access-Control-Max-Age": "600",
        }
        self._write_empty(HTTPStatus.NO_CONTENT, headers=headers)

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except ApplicationError as exc:
            status = HTTPStatus.NOT_FOUND if exc.code == "not_found" else HTTPStatus.BAD_REQUEST
            if exc.code == "state_conflict":
                status = HTTPStatus.CONFLICT
            self._error(status, exc.code, exc.message)
        except (ApiPayloadError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")

    def _handle_get(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query, keep_blank_values=False)

        if self._serve_webui(path):
            return

        if path == "/api/v1/health":
            self._write_json(HTTPStatus.OK, {"ok": True, "status": "ok"}, cache_control="no-cache")
            return
        if path == "/api/v1/session":
            self._write_json(HTTPStatus.OK, {"ok": True, "data": self.server.runtime.metadata()}, cache_control="no-cache")
            return
        if path == "/api/v1/commands/schema":
            self._write_json(HTTPStatus.OK, {"ok": True, "data": command_schema()}, cache_control="private, max-age=3600")
            return
        if path == "/api/v1/catalog":
            self._query_result(GetCatalog(), catalog=True)
            return
        if path == "/api/v1/world":
            self._query_result(GetWorld())
            return
        if path == "/api/v1/bottlenecks":
            self._query_result(GetBottlenecks(_one(params, "location_id")))
            return
        if path == "/api/v1/projects":
            self._query_result(GetProjects(_one(params, "location_id")))
            return
        if path == "/api/v1/logistics/summary":
            self._query_result(GetLogisticsSummary())
            return
        if path == "/api/v1/logistics/routes":
            self._query_result(GetRoutes(
                origin_id=_one(params, "origin_id"),
                destination_id=_one(params, "destination_id"),
                route_id=_one(params, "route_id"),
                include_modes=_bool(params, "include_modes", False),
            ))
            return
        route_prefix = "/api/v1/logistics/routes/"
        if path.startswith(route_prefix):
            route_id = unquote(path[len(route_prefix):])
            if not route_id:
                raise ApiPayloadError("route id is required")
            self._query_result(GetRoutes(route_id=route_id, include_modes=True))
            return
        if path == "/api/v1/logistics/fleet":
            self._query_result(GetFleet(
                location_id=_one(params, "location_id"),
                vehicle_definition_id=_one(params, "vehicle_definition_id"),
            ))
            return
        if path == "/api/v1/logistics/transport-allocations":
            self._query_result(GetTransportAllocations())
            return
        if path == "/api/v1/logistics/cargo-flows":
            self._query_result(GetCargoFlows())
            return
        if path == "/api/v1/logistics/lanes":
            self._query_result(GetLogisticsLanes())
            return
        if path == "/api/v1/transport-allocation-options":
            source_id = _required(params, "source_id")
            destination_id = _required(params, "destination_id")
            self._query_result(GetTransportAllocationOptions(source_id, destination_id))
            return
        if path == "/api/v1/research":
            self._query_result(GetResearch())
            return
        if path == "/api/v1/surveys":
            self._query_result(GetSurveys(_one(params, "location_id")))
            return
        if path == "/api/v1/contracts":
            self._query_result(GetContracts())
            return

        prefix = "/api/v1/locations/"
        if path.startswith(prefix):
            rest = path[len(prefix):]
            if rest.endswith("/flow"):
                location_id = unquote(rest[:-5].rstrip("/"))
                if not location_id:
                    raise ApiPayloadError("location id is required")
                self._query_result(GetFlowReport(location_id))
                return
            if rest.endswith("/build-options"):
                location_id = unquote(rest[:-14].rstrip("/"))
                if not location_id:
                    raise ApiPayloadError("location id is required")
                self._query_result(GetBuildOptions(location_id))
                return
            location_id = unquote(rest)
            if location_id:
                self._query_result(GetLocation(location_id))
                return

        self._error(HTTPStatus.NOT_FOUND, "not_found", "endpoint not found")

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except RevisionConflict as exc:
            self._error(
                HTTPStatus.CONFLICT,
                "revision_conflict",
                str(exc),
                revision=exc.current_revision,
                details={
                    "expected_revision": exc.expected_revision,
                    "current_revision": exc.current_revision,
                },
            )
        except ApplicationError as exc:
            status = HTTPStatus.NOT_FOUND if exc.code == "not_found" else HTTPStatus.BAD_REQUEST
            if exc.code == "state_conflict":
                status = HTTPStatus.CONFLICT
            self._error(status, exc.code, exc.message)
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "save_not_found", "save slot not found")
        except SaveFormatError as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_save", str(exc))
        except (ApiPayloadError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "internal server error")

    def _handle_post(self) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        body = self._read_json()
        if path == "/api/v1/commands":
            result = self.server.runtime.execute(
                decode_command(body), expected_revision=self._if_match_revision(),
            )
            self._result(result, etag=f'"rev-{result.revision}"')
            return
        if path == "/api/v1/session/new":
            self._result(self.server.runtime.new_game())
            return
        if path == "/api/v1/session/save":
            if not isinstance(body, dict):
                raise ApiPayloadError("save body must be an object")
            slot = body.get("slot", "manual")
            self._result(self.server.runtime.save(slot))
            return
        if path == "/api/v1/session/load":
            if not isinstance(body, dict):
                raise ApiPayloadError("load body must be an object")
            slot = body.get("slot", "manual")
            apply_offline = body.get("apply_offline", True)
            if not isinstance(apply_offline, bool):
                raise ApiPayloadError("apply_offline must be boolean")
            self._result(self.server.runtime.load(slot, apply_offline=apply_offline))
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", "endpoint not found")


def _one(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    if len(values) != 1:
        raise ApiPayloadError(f"{key} must appear once")
    return values[0]


def _required(params: dict[str, list[str]], key: str) -> str:
    value = _one(params, key)
    if value is None or not value:
        raise ApiPayloadError(f"{key} is required")
    return value


def _bool(params: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _one(params, key)
    if value is None:
        return default
    if value.lower() in {"1", "true", "yes"}:
        return True
    if value.lower() in {"0", "false", "no"}:
        return False
    raise ApiPayloadError(f"{key} must be boolean")


def create_server(
    runtime: GameRuntime, config: ApiServerConfig = ApiServerConfig()
) -> SpaceIdleHTTPServer:
    if bool(config.tls_certfile) != bool(config.tls_keyfile):
        raise ValueError("tls_certfile and tls_keyfile must be provided together")
    server = SpaceIdleHTTPServer(
        (config.host, config.port), SpaceIdleRequestHandler,
        runtime=runtime, config=config,
    )
    if config.tls_certfile is not None and config.tls_keyfile is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(config.tls_certfile, config.tls_keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server
