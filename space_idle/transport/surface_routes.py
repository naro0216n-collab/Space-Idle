from __future__ import annotations

from hashlib import sha256

from ..shared import DefinitionId, RouteId, SpatialNodeId, SurfaceCellId
from ..spatial import SpatialGraph
from .endpoints import great_circle_distance_km
from .models import (
    RouteDef,
    RouteEndpoint,
    SurfaceAccessRouteRule,
    TransportOperationKind,
    TransportOperationRequirement,
)

DERIVED_SURFACE_ACCESS_ROUTE_PREFIX = "derived.surface_access."


def _route_hash(*parts: object) -> str:
    return sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:24]


def derived_surface_access_route_id(
    origin_id: SpatialNodeId, destination_id: SpatialNodeId
) -> RouteId:
    """Stable identity for a derived same-body Location-to-Location route."""
    return RouteId(
        f"{DERIVED_SURFACE_ACCESS_ROUTE_PREFIX}surface.{_route_hash(origin_id, destination_id)}"
    )


def derived_node_surface_route_id(
    rule_id: DefinitionId,
    origin_id: SpatialNodeId,
    destination_id: SpatialNodeId,
) -> RouteId:
    """Stable route identity derived from a rule and runtime Location identity."""
    return RouteId(
        f"{DERIVED_SURFACE_ACCESS_ROUTE_PREFIX}node.{_route_hash(rule_id, origin_id, destination_id)}"
    )


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


def _generic_access_cell(graph: SpatialGraph, location_id: SpatialNodeId) -> SurfaceCellId:
    """Choose a stable physical access point without treating the core as permanent.

    Dedicated surface interfaces may supersede this generic access-cell rule in
    future route resolvers.  Until then every developed cell is eligible and
    the deterministic minimum prevents Location core identity from becoming a
    hidden route contract.
    """
    location = graph.locations[location_id]
    if not location.developed_cell_ids:
        raise ValueError("surface Location has no developed access cell")
    return min(location.developed_cell_ids, key=str)


def build_derived_surface_access_routes(
    graph: SpatialGraph,
    rules: tuple[SurfaceAccessRouteRule, ...] = (),
) -> dict[RouteId, RouteDef]:
    """Derive routes from authoritative Location state and content route rules.

    Surface Cells remain physical locators only.  The derived graph therefore
    scales with established operational Locations rather than Surface Cell
    count, and future Location ids never appear in static Content.
    """
    routes: dict[RouteId, RouteDef] = {}
    locations = tuple(sorted(graph.locations.values(), key=lambda row: str(row.id)))

    # Same-body Location-to-Location surface transport.
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
                transit_days=1,
                operations=(
                    TransportOperationRequirement(TransportOperationKind.SURFACE_TRANSPORT),
                ),
                display_name=f"{origin.display_name} → {destination.display_name} 地表輸送",
            )

    # Non-surface node <-> arbitrary player-created surface Location routes.
    for rule in sorted(rules, key=lambda row: str(row.id)):
        node = graph.nodes.get(rule.node_id)
        if node is None or node.body_id != rule.body_id:
            continue
        for location in locations:
            if location.body_id != rule.body_id:
                continue
            cell_id = _generic_access_cell(graph, location.id)
            down_id = derived_node_surface_route_id(rule.id, rule.node_id, location.id)
            routes[down_id] = RouteDef(
                id=down_id,
                origin=RouteEndpoint(rule.node_id, non_surface_interface="operational_node"),
                destination=RouteEndpoint(location.id, access_cell_id=cell_id),
                transit_days=rule.transit_days,
                operations=rule.descent_operations,
                display_name=f"{node.display_name} → {location.display_name}",
                origin_requirements=rule.node_requirements,
                destination_requirements=rule.surface_requirements,
            )
            up_id = derived_node_surface_route_id(rule.id, location.id, rule.node_id)
            routes[up_id] = RouteDef(
                id=up_id,
                origin=RouteEndpoint(location.id, access_cell_id=cell_id),
                destination=RouteEndpoint(rule.node_id, non_surface_interface="operational_node"),
                transit_days=rule.transit_days,
                operations=rule.ascent_operations,
                display_name=f"{location.display_name} → {node.display_name}",
                origin_requirements=rule.surface_requirements,
                destination_requirements=rule.node_requirements,
            )
    return routes
