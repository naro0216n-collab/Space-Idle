from __future__ import annotations

from hashlib import sha256

from ..shared import RouteId, SpatialNodeId, SurfaceCellId
from ..spatial import SpatialGraph
from .endpoints import great_circle_distance_km
from .models import RouteDef, RouteEndpoint, TransportOperationKind, TransportOperationRequirement

DERIVED_SURFACE_ACCESS_ROUTE_PREFIX = "derived.surface_access."


def derived_surface_access_route_id(
    origin_id: SpatialNodeId, destination_id: SpatialNodeId
) -> RouteId:
    """Stable identity for a derived Location-to-Location surface route.

    Location ids are player-controlled state, so keep them out of the route-id
    syntax itself.  The ordered pair remains the semantic identity while the
    physical access cells are derived from current developed territory.
    """
    payload = f"{origin_id}\0{destination_id}".encode("utf-8")
    digest = sha256(payload).hexdigest()[:24]
    return RouteId(f"{DERIVED_SURFACE_ACCESS_ROUTE_PREFIX}{digest}")


def _closest_access_cells(
    graph: SpatialGraph,
    origin_id: SpatialNodeId,
    destination_id: SpatialNodeId,
) -> tuple[SurfaceCellId, SurfaceCellId]:
    origin = graph.locations[origin_id]
    destination = graph.locations[destination_id]
    if origin.body_id != destination.body_id:
        raise ValueError("surface access route endpoints must share a celestial body")
    body = graph.bodies[origin.body_id]

    ranked: list[tuple[float, str, str, SurfaceCellId, SurfaceCellId]] = []
    for origin_cell_id in sorted(origin.developed_cell_ids, key=str):
        origin_cell = graph.surface_cells[origin_cell_id]
        for destination_cell_id in sorted(destination.developed_cell_ids, key=str):
            destination_cell = graph.surface_cells[destination_cell_id]
            distance = great_circle_distance_km(
                origin_cell.centroid,
                destination_cell.centroid,
                body.mean_radius_km,
            )
            ranked.append(
                (
                    distance,
                    str(origin_cell_id),
                    str(destination_cell_id),
                    origin_cell_id,
                    destination_cell_id,
                )
            )
    if not ranked:
        raise ValueError("surface Location has no developed access cell")
    _distance, _origin_key, _destination_key, origin_cell_id, destination_cell_id = min(ranked)
    return origin_cell_id, destination_cell_id


def build_derived_surface_access_routes(graph: SpatialGraph) -> dict[RouteId, RouteDef]:
    """Derive generic same-body Surface Transport routes from Location state.

    Surface Cells remain physical locators only.  Route count therefore scales
    with player-operated Locations, not with the number of Surface Cells.
    """
    routes: dict[RouteId, RouteDef] = {}
    locations = tuple(sorted(graph.locations.values(), key=lambda row: str(row.id)))
    for origin in locations:
        for destination in locations:
            if origin.id == destination.id or origin.body_id != destination.body_id:
                continue
            origin_cell_id, destination_cell_id = _closest_access_cells(
                graph, origin.id, destination.id
            )
            route_id = derived_surface_access_route_id(origin.id, destination.id)
            routes[route_id] = RouteDef(
                id=route_id,
                origin=RouteEndpoint(origin.id, access_cell_id=origin_cell_id),
                destination=RouteEndpoint(destination.id, access_cell_id=destination_cell_id),
                # SurfaceTransportCapability supplies the physical duration from
                # endpoint geometry and vehicle speed.  This fallback is only a
                # valid positive RouteDef baseline for unsupported modes.
                transit_days=1,
                operations=(
                    TransportOperationRequirement(TransportOperationKind.SURFACE_TRANSPORT),
                ),
                display_name=f"{origin.display_name} → {destination.display_name} 地表輸送",
            )
    return routes
