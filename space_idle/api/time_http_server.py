from __future__ import annotations

import ssl
from urllib.parse import parse_qs, urlsplit

from ..application_commands import (
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
    GetTransportAllocations,
    GetWorld,
    GetExternalEconomy,
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

        queries = {
            "world": GetWorld(),
            "global_issues": GetBottlenecks(),
            "research": GetResearch(),
            "scientific_explorations": GetScientificExplorations(),
            "contracts": GetContracts(),
            "logistics_summary": GetLogisticsSummary(),
            "logistics": GetLogistics(),
            "movement_plans": GetMovementPlans(include_modes=True),
            "fleet": GetFleet(),
            "transport_allocations": GetTransportAllocations(),
            "cargo_flows": GetCargoFlows(),
            "external_economy": GetExternalEconomy(),
        }
        if operational_node_id:
            queries.update({
                "operational_node": GetOperationalNode(operational_node_id),
                "flow": GetFlowReport(operational_node_id),
                "dependency_analytics": GetDependencyAnalytics("operational_nodes", node_ids=(operational_node_id,)),
                "projects": GetProjects(operational_node_id),
                "build_options": GetBuildOptions(operational_node_id),
                "bottlenecks": GetBottlenecks(operational_node_id),
                "surveys": GetSurveys(operational_node_id),
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
