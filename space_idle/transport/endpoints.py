from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from ..facilities import FacilityBook, FacilityPlacementScope
from ..shared import EntityId, SpatialNodeId, SurfaceCellId
from ..spatial import SpatialContextId, SurfacePoint
from .models import RouteDef, RouteEndpoint


@dataclass(frozen=True)
class ResolvedRouteEndpoint:
    location_id: SpatialNodeId
    locator_kind: str
    locator_id: str
    environment_context_id: SpatialContextId
    surface_cell_id: SurfaceCellId | None


@dataclass(frozen=True)
class RouteGeometrySnapshot:
    origin: ResolvedRouteEndpoint
    destination: ResolvedRouteEndpoint
    same_body_surface: bool
    distance_km: float | None


def resolve_route_endpoint(endpoint: RouteEndpoint, facilities: FacilityBook) -> ResolvedRouteEndpoint:
    graph = facilities.environment.graph
    if not graph.has_operational_node(endpoint.location_id):
        raise ValueError(f"unknown route endpoint location: {endpoint.location_id}")

    if endpoint.surface_interface_id is not None:
        facility = facilities.facilities.get(endpoint.surface_interface_id)
        if facility is None:
            raise ValueError(f"unknown route surface interface: {endpoint.surface_interface_id}")
        if facility.location_id != endpoint.location_id:
            raise ValueError("route surface interface belongs to another Location")
        definition = facilities.definitions[facility.definition_id]
        if definition.placement_scope is not FacilityPlacementScope.SURFACE_CELL:
            raise ValueError("route surface interface must be a SURFACE_CELL facility")
        if facility.site_cell_id is None:
            raise ValueError("route surface interface has no site cell")
        location = graph.locations.get(endpoint.location_id)
        if location is None or facility.site_cell_id not in location.developed_cell_ids:
            raise ValueError("route surface interface is outside developed territory")
        return ResolvedRouteEndpoint(
            endpoint.location_id,
            endpoint.locator_kind,
            endpoint.locator_id,
            facility.site_cell_id,
            facility.site_cell_id,
        )

    if endpoint.access_cell_id is not None:
        location = graph.locations.get(endpoint.location_id)
        if location is None:
            raise ValueError("route access cell requires a surface Location")
        cell = graph.surface_cells.get(endpoint.access_cell_id)
        if cell is None:
            raise ValueError(f"unknown route access cell: {endpoint.access_cell_id}")
        if cell.body_id != location.body_id:
            raise ValueError("route access cell belongs to another celestial body")
        if endpoint.access_cell_id not in location.developed_cell_ids:
            raise ValueError("route access cell is not developed by endpoint Location")
        return ResolvedRouteEndpoint(
            endpoint.location_id,
            endpoint.locator_kind,
            endpoint.locator_id,
            endpoint.access_cell_id,
            endpoint.access_cell_id,
        )

    if endpoint.location_id not in graph.nodes:
        raise ValueError("non-surface route interface requires a non-surface operational node")
    return ResolvedRouteEndpoint(
        endpoint.location_id,
        endpoint.locator_kind,
        endpoint.locator_id,
        endpoint.location_id,
        None,
    )


def great_circle_distance_km(a: SurfacePoint, b: SurfacePoint, radius_km: float) -> float:
    lat1, lon1 = radians(a.latitude_deg), radians(a.longitude_deg)
    lat2, lon2 = radians(b.latitude_deg), radians(b.longitude_deg)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2.0) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2.0) ** 2
    return 2.0 * radius_km * asin(min(1.0, sqrt(max(0.0, h))))


def route_geometry(route: RouteDef, facilities: FacilityBook) -> RouteGeometrySnapshot:
    graph = facilities.environment.graph
    origin = resolve_route_endpoint(route.origin, facilities)
    destination = resolve_route_endpoint(route.destination, facilities)
    if origin.surface_cell_id is None or destination.surface_cell_id is None:
        return RouteGeometrySnapshot(origin, destination, False, None)
    origin_cell = graph.surface_cells[origin.surface_cell_id]
    destination_cell = graph.surface_cells[destination.surface_cell_id]
    if origin_cell.body_id != destination_cell.body_id:
        return RouteGeometrySnapshot(origin, destination, False, None)
    body = graph.bodies[origin_cell.body_id]
    return RouteGeometrySnapshot(
        origin,
        destination,
        True,
        great_circle_distance_km(origin_cell.centroid, destination_cell.centroid, body.mean_radius_km),
    )
