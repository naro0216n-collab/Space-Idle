from __future__ import annotations

from hashlib import sha256
from http import HTTPStatus
import re
import ssl
from urllib.parse import parse_qs, urlsplit

from ..application_commands import (
    GetAttention,
    GetBottlenecks,
    GetBuildOptions,
    GetCargoFlows,
    GetFleet,
    GetContracts,
    GetDependencyAnalytics,
    GetFlowReport,
    GetOperationalNode,
    GetLogistics,
    GetLogisticsSummary,
    GetProjects,
    GetResearch,
    GetScientificExplorations,
    GetMovementPlans,
    GetSurveys,
    GetSurfaceMap,
    GetNonSurfaceFoundingOptions,
    GetTransportAllocations,
    GetWorld,
    GetMarket,
)
from .codec import ApiPayloadError
from .http_server import ApiServerConfig, SpaceIdleHTTPServer, SpaceIdleRequestHandler
from .runtime import GameRuntime


class TimeControlledRequestHandler(SpaceIdleRequestHandler):
    """HTTP adapter for runtime-owned clock controls and coherent UI snapshots."""

    def _handle_get(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != "/api/v1/ui-state":
            super()._handle_get()
            return

        params = parse_qs(parsed.query, keep_blank_values=False)
        operational_node_values = params.get("operational_node_id", [])
        if len(operational_node_values) > 1:
            raise ApiPayloadError("operational_node_id must appear once")
        operational_node_id = operational_node_values[0] if operational_node_values else None
        surface_body_values = params.get("surface_body_id", [])
        if len(surface_body_values) > 1:
            raise ApiPayloadError("surface_body_id must appear once")
        surface_body_id = surface_body_values[0] if surface_body_values else None

        founding_cell_ids = tuple(dict.fromkeys(params.get("founding_cell_id", ())))
        selected_context = params.get("founding_context_id", [""])
        if len(selected_context) != 1:
            raise ApiPayloadError("founding Context must appear at most once")
        founding_context_id = selected_context[0]

        # Map/Inspector reference one selected node without changing the
        # execution node. Selection scopes the Movement candidates as well.
        inspect_values = params.get("inspect_node_id", [])
        if len(inspect_values) > 1:
            raise ApiPayloadError("inspect_node_id must appear once")
        inspect_node_id = inspect_values[0] if inspect_values else None

        scope_key = f"{operational_node_id or ''}\0{surface_body_id or ''}\0{inspect_node_id or ''}\0{','.join(founding_cell_ids)}\0{founding_context_id}"
        scope_hash = sha256(scope_key.encode("utf-8")).hexdigest()[:12]
        known_revision = None
        known_view = self.headers.get("X-Space-Idle-Known-View", "").strip()
        match = re.fullmatch(rf'"ui-state-(\d+)-{scope_hash}"', known_view)
        if match is not None:
            known_revision = int(match.group(1))

        queries = {
            "world": GetWorld(),
            "global_issues": GetAttention(),
            "research": GetResearch(),
            "scientific_explorations": GetScientificExplorations(),
            "contracts": GetContracts(),
            "logistics_summary": GetLogisticsSummary(),
            "logistics": GetLogistics(),
            "fleet": GetFleet(),
            "transport_allocations": GetTransportAllocations(),
            "cargo_flows": GetCargoFlows(),
            "market": GetMarket(),
        }
        if inspect_node_id:
            queries["movement_plans"] = GetMovementPlans(touching_node_id=inspect_node_id, include_modes=True)
            if inspect_node_id != operational_node_id:
                queries["inspected_node"] = GetOperationalNode(inspect_node_id)
                queries["inspected_flow"] = GetFlowReport(inspect_node_id)
        if operational_node_id:
            queries.update({
                "operational_node": GetOperationalNode(operational_node_id),
                "flow": GetFlowReport(operational_node_id),
                "dependency_analytics_current": GetDependencyAnalytics("operational_nodes", node_ids=(operational_node_id,), time_basis="CURRENT"),
                "dependency_analytics_forecast": GetDependencyAnalytics("operational_nodes", node_ids=(operational_node_id,), time_basis="FORECAST"),
                "projects": GetProjects(operational_node_id),
                "build_options": GetBuildOptions(operational_node_id),
                "bottlenecks": GetBottlenecks(operational_node_id),
                "surveys": GetSurveys(operational_node_id, surface_body_id),
            })
        if surface_body_id:
            queries["surface_map"] = GetSurfaceMap(surface_body_id, founding_cell_ids)
            queries["non_surface_founding"] = GetNonSurfaceFoundingOptions(surface_body_id, founding_context_id)

        result = self.server.runtime.snapshot_if_changed(
            queries,
            known_revision=known_revision,
        )
        if result is None:
            assert known_revision is not None
            etag = f'"ui-state-{known_revision}-{scope_hash}"'
            self._write_json(
                HTTPStatus.OK,
                {"ok": True, "revision": known_revision, "data": {"unchanged": True}},
                revision=known_revision,
                etag=etag,
                cache_control="no-store",
            )
            return
        self._result(
            result,
            etag=f'"ui-state-{result.revision}-{scope_hash}"',
        )

    def _handle_post(self) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path != "/api/v1/time-control":
            super()._handle_post()
            return

        body = self._read_json()
        if not isinstance(body, dict):
            raise ApiPayloadError("time-control body must be an object")
        unknown = sorted(set(body) - {"paused", "speed_multiplier"})
        if unknown:
            raise ApiPayloadError(f"unknown time-control fields: {', '.join(unknown)}")
        result = self.server.runtime.set_time_control(
            paused=body.get("paused"),
            speed_multiplier=body.get("speed_multiplier"),
        )
        self._result(result, etag=f'"rev-{result.revision}"')


def create_server(runtime: GameRuntime, config: ApiServerConfig = ApiServerConfig()) -> SpaceIdleHTTPServer:
    if bool(config.tls_certfile) != bool(config.tls_keyfile):
        raise ValueError("tls_certfile and tls_keyfile must be provided together")
    server = SpaceIdleHTTPServer(
        (config.host, config.port),
        TimeControlledRequestHandler,
        runtime=runtime,
        config=config,
    )
    if config.tls_certfile is not None and config.tls_keyfile is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(config.tls_certfile, config.tls_keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server
