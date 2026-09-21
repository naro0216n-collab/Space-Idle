from __future__ import annotations

from dataclasses import dataclass
from ..facilities import FacilityBook, FacilityPlacementScope
from ..shared import EntityId, SpatialNodeId, SurfaceCellId
from ..spatial import SpatialContextId, great_circle_distance_km
from .models import MovementEndpoint, MovementPlan


@dataclass(frozen=True)
class ResolvedMovementEndpoint:
    node_id: SpatialNodeId | None
    locator_kind: str
    locator_id: str
    environment_context_id: SpatialContextId
    surface_cell_id: SurfaceCellId | None


@dataclass(frozen=True)
class MovementGeometrySnapshot:
    origin: ResolvedMovementEndpoint
    destination: ResolvedMovementEndpoint
    same_body_surface: bool
    distance_km: float | None


def resolve_movement_endpoint(endpoint: MovementEndpoint, facilities: FacilityBook) -> ResolvedMovementEndpoint:
    graph = facilities.environment.graph
    if endpoint.physical_target_cell_id is not None:
        cell = graph.surface_cells.get(endpoint.physical_target_cell_id)
        if cell is None:
            raise ValueError(f"unknown movement physical target: {endpoint.physical_target_cell_id}")
        return ResolvedMovementEndpoint(
            None,
            endpoint.locator_kind,
            endpoint.locator_id,
            endpoint.physical_target_cell_id,
            endpoint.physical_target_cell_id,
        )

    if endpoint.physical_target_node_id is not None:
        node = graph.nodes.get(endpoint.physical_target_node_id)
        if node is None:
            raise ValueError(f"unknown non-surface movement physical target: {endpoint.physical_target_node_id}")
        return ResolvedMovementEndpoint(
            None,
            endpoint.locator_kind,
            endpoint.locator_id,
            endpoint.physical_target_node_id,
            None,
        )

    node_id = endpoint.node_id
    if not graph.has_operational_node(node_id):
        raise ValueError(f"unknown movement endpoint location: {node_id}")

    if endpoint.surface_interface_id is not None:
        facility = facilities.facilities.get(endpoint.surface_interface_id)
        if facility is None:
            raise ValueError(f"unknown movement surface interface: {endpoint.surface_interface_id}")
        if facility.operational_node_id != node_id:
            raise ValueError("movement surface interface belongs to another Location")
        definition = facilities.definitions[facility.definition_id]
        if definition.placement_scope is not FacilityPlacementScope.SURFACE_CELL:
            raise ValueError("movement surface interface must be a SURFACE_CELL facility")
        if facility.site_cell_id is None:
            raise ValueError("movement surface interface has no site cell")
        location = graph.locations.get(node_id)
        if location is None or facility.site_cell_id not in location.developed_cell_ids:
            raise ValueError("movement surface interface is outside developed territory")
        return ResolvedMovementEndpoint(
            node_id,
            endpoint.locator_kind,
            endpoint.locator_id,
            facility.site_cell_id,
            facility.site_cell_id,
        )

    if endpoint.access_cell_id is not None:
        location = graph.locations.get(node_id)
        if location is None:
            raise ValueError("movement access cell requires a surface Location")
        cell = graph.surface_cells.get(endpoint.access_cell_id)
        if cell is None:
            raise ValueError(f"unknown movement access cell: {endpoint.access_cell_id}")
        if cell.body_id != location.body_id:
            raise ValueError("movement access cell belongs to another celestial body")
        if endpoint.access_cell_id not in location.developed_cell_ids:
            raise ValueError("movement access cell is not developed by endpoint Location")
        return ResolvedMovementEndpoint(
            node_id,
            endpoint.locator_kind,
            endpoint.locator_id,
            endpoint.access_cell_id,
            endpoint.access_cell_id,
        )

    if node_id not in graph.nodes:
        raise ValueError("non-surface movement interface requires a non-surface operational node")
    return ResolvedMovementEndpoint(
        node_id,
        endpoint.locator_kind,
        endpoint.locator_id,
        endpoint.node_id,
        None,
    )



def movement_geometry(plan: MovementPlan, facilities: FacilityBook) -> MovementGeometrySnapshot:
    graph = facilities.environment.graph
    origin = resolve_movement_endpoint(plan.origin, facilities)
    destination = resolve_movement_endpoint(plan.destination, facilities)
    if origin.surface_cell_id is None or destination.surface_cell_id is None:
        return MovementGeometrySnapshot(origin, destination, False, None)
    origin_cell = graph.surface_cells[origin.surface_cell_id]
    destination_cell = graph.surface_cells[destination.surface_cell_id]
    if origin_cell.body_id != destination_cell.body_id:
        return MovementGeometrySnapshot(origin, destination, False, None)
    body = graph.bodies[origin_cell.body_id]
    return MovementGeometrySnapshot(
        origin,
        destination,
        True,
        great_circle_distance_km(origin_cell.centroid, destination_cell.centroid, body.mean_radius_km),
    )
