from __future__ import annotations

import ssl
from urllib.parse import parse_qs, urlsplit

from ..application_commands import (
    GetBottlenecks,
    GetBuildOptions,
    GetCargoFlows,
    GetFleet,
    GetContracts,
    GetFlowReport,
    GetLocation,
    GetLogistics,
    GetLogisticsLanes,
    GetLogisticsSummary,
    GetProjects,
    GetResearch,
    GetScientificExplorations,
    GetRoutes,
    GetSurveys,
    GetSurfaceMap,
    GetTransportAllocations,
    GetWorld,
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
        location_values = params.get("location_id", [])
        if len(location_values) > 1:
            raise ApiPayloadError("location_id must appear once")
        location_id = location_values[0] if location_values else None
        surface_body_values = params.get("surface_body_id", [])
        if len(surface_body_values) > 1:
            raise ApiPayloadError("surface_body_id must appear once")
        surface_body_id = surface_body_values[0] if surface_body_values else None

        queries = {
            "world": GetWorld(),
            "global_issues": GetBottlenecks(),
            "research": GetResearch(),
            "scientific_explorations": GetScientificExplorations(),
            "contracts": GetContracts(),
            "logistics_summary": GetLogisticsSummary(),
            "logistics": GetLogistics(),
            "routes": GetRoutes(include_modes=True),
            "fleet": GetFleet(),
            "transport_allocations": GetTransportAllocations(),
            "cargo_flows": GetCargoFlows(),
            "lanes": GetLogisticsLanes(),
        }
        if location_id:
            queries.update({
                "location": GetLocation(location_id),
                "flow": GetFlowReport(location_id),
                "projects": GetProjects(location_id),
                "build_options": GetBuildOptions(location_id),
                "bottlenecks": GetBottlenecks(location_id),
                "surveys": GetSurveys(location_id),
            })
        if surface_body_id:
            queries["surface_map"] = GetSurfaceMap(surface_body_id)

        result = self.server.runtime.snapshot(queries)
        self._result(result, etag=f'"rev-{result.revision}"')

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
