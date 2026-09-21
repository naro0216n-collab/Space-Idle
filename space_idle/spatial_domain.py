from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .shared import CelestialBodyId, DefinitionId, SpatialNodeId, SurfaceCellId
from .spatial import OperationalNodeState, SurfaceLocationState
from .validation_support import ValidationContext, require as _require


def capture(sim: Any) -> dict[str, Any]:
    return {
        "locations": [
            {
                "operational_node_id": str(location.operational_node_id),
                "display_name": location.display_name,
                "body_id": str(location.body_id),
                "core_cell_id": str(location.core_cell_id),
                "developed_cell_ids": [
                    str(cell_id) for cell_id in sorted(location.developed_cell_ids, key=str)
                ],
            }
            for location in sorted(
                sim.graph.locations.values(), key=lambda row: str(row.operational_node_id)
            )
        ],
        "operational_nodes": [
            str(node_id) for node_id in sorted(sim.graph.operational_node_states, key=str)
        ],
        "overlays": sim.environment.capture_overlay_state(),
    }


def restore(sim: Any, data: dict[str, Any]) -> None:
    rows = data["locations"]
    operational_rows = data["operational_nodes"]
    if not isinstance(rows, list):
        raise ValueError("spatial state is missing locations")
    if not isinstance(operational_rows, list):
        raise ValueError("spatial state is missing operational_nodes")
    locations: list[SurfaceLocationState] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("spatial location row must be an object")
        locations.append(
            SurfaceLocationState(
                SpatialNodeId(row["operational_node_id"]),
                row["display_name"],
                CelestialBodyId(row["body_id"]),
                SurfaceCellId(row["core_cell_id"]),
                {SurfaceCellId(str(value)) for value in row["developed_cell_ids"]},
            )
        )
    operational_nodes = tuple(
        OperationalNodeState(SpatialNodeId(str(value))) for value in operational_rows
    )
    sim.graph.replace_dynamic_state(tuple(locations), operational_nodes)
    sim.environment.restore_overlay_state(data["overlays"])


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    _require(sim.environment.graph is sim.graph, "simulation/environment spatial graph mismatch")
    for body_id, body in sim.graph.bodies.items():
        _require(body_id == body.id, f"celestial body key mismatch: {body_id}")
    for node_id, node in sim.graph.nodes.items():
        _require(node_id == node.id, f"spatial node key mismatch: {node_id}")
        _require(
            node.parent_id is None or node.parent_id in sim.graph.nodes,
            f"spatial node has unknown parent: {node_id}",
        )
        _require(
            node.body_id is None or node.body_id in sim.graph.bodies,
            f"spatial node has unknown celestial body: {node_id}",
        )
        sim.graph.lineage(node_id)
        sim.graph.environment_lineage(node_id)

    for cell_id, cell in sim.graph.surface_cells.items():
        _require(cell_id == cell.id, f"surface cell key mismatch: {cell_id}")
        _require(cell.body_id in sim.graph.bodies, f"surface cell has unknown body: {cell_id}")
        _require(cell.area_km2 > 0, f"surface cell has invalid area: {cell_id}")
        _require(cell_id not in cell.neighbor_ids, f"surface cell self adjacency: {cell_id}")
        for neighbor_id in cell.neighbor_ids:
            _require(
                neighbor_id in sim.graph.surface_cells,
                f"surface cell has unknown neighbor: {cell_id}/{neighbor_id}",
            )
            neighbor = sim.graph.surface_cells[neighbor_id]
            _require(
                neighbor.body_id == cell.body_id,
                f"surface cell neighbor crosses celestial body: {cell_id}/{neighbor_id}",
            )
            _require(
                cell_id in neighbor.neighbor_ids,
                f"surface cell adjacency must be symmetric: {cell_id}/{neighbor_id}",
            )
        for resource_id, potential in cell.resource_potential_by_resource.items():
            _require(potential >= 0, f"surface cell has negative resource potential: {cell_id}/{resource_id}")

    for (context_id, facet_type), facet in sim.environment.static.facets.items():
        _require(
            context_id in sim.graph.nodes or context_id in sim.graph.surface_cells,
            f"static environment facet references non-static context: {context_id}",
        )
        sim.environment.static._field_scope(facet_type)
        _require(
            isinstance(facet, facet_type),
            f"environment facet type mismatch: {context_id}/{facet_type.__name__}",
        )
    for (body_id, facet_type), facet in sim.environment.static.body_facets.items():
        _require(body_id in sim.graph.bodies, f"body environment facet references unknown body: {body_id}")
        sim.environment.static._field_scope(facet_type)
        _require(
            isinstance(facet, facet_type),
            f"body environment facet type mismatch: {body_id}/{facet_type.__name__}",
        )
    sim.environment.ordered_overlays()
    validate_runtime(sim)


def validate_runtime(sim: Any) -> None:
    for node_id, state in sim.graph.operational_node_states.items():
        _require(node_id == state.id, f"operational node key mismatch: {node_id}")
        context_count = int(node_id in sim.graph.nodes) + int(node_id in sim.graph.locations)
        _require(
            context_count == 1,
            f"operational node must reference exactly one spatial context: {node_id}",
        )

    seen_cells: set[SurfaceCellId] = set()
    for location_id, location in sim.graph.locations.items():
        _require(location_id == location.operational_node_id, f"location key mismatch: {location_id}")
        _require(location_id not in sim.graph.nodes, f"location collides with non-surface node: {location_id}")
        _require(
            location_id in sim.graph.operational_node_states,
            f"surface location lacks operational node state: {location_id}",
        )
        _require(location.body_id in sim.graph.bodies, f"location has unknown body: {location_id}")
        _require(location.core_cell_id in location.developed_cell_ids, f"location core cell is not developed: {location_id}")
        _require(location.core_cell_id in sim.graph.surface_cells, f"location has unknown core cell: {location_id}")
        for cell_id in location.developed_cell_ids:
            _require(cell_id in sim.graph.surface_cells, f"location has unknown developed cell: {location_id}/{cell_id}")
            _require(
                sim.graph.surface_cells[cell_id].body_id == location.body_id,
                f"location developed cell belongs to another body: {location_id}/{cell_id}",
            )
            _require(cell_id not in seen_cells, f"surface cell belongs to multiple locations: {cell_id}")
            seen_cells.add(cell_id)
        _require(
            sim.graph._cells_connected(location.developed_cell_ids),
            f"location developed territory is not connected: {location_id}",
        )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return {
        resource_id
        for cell in sim.graph.surface_cells.values()
        for resource_id in cell.resource_potential_by_resource
    }


STATE_CODEC = StateCodec("environment", capture, restore)
DOMAIN_EXTENSION = DomainExtension(
    "spatial",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
