from __future__ import annotations

from typing import Any
from copy import deepcopy
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from collections.abc import Mapping

from .domain import DomainExtension, StateCodec, decode_list, decode_str, require_fields
from .shared import CelestialBodyId, DefinitionId, SpatialNodeId, SurfaceCellId
from .spatial import AtmosphereField, OperationalNodeState, PhysicalSurface, SurfaceLocationState
from .surface_partition import validate_surface_partitions
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
        "engineered_terrain": [
            {"cell_id": str(cell), "profile_id": profile}
            for cell, profile in sorted(sim.graph.engineered_terrain.items(), key=lambda row: str(row[0]))
        ],
    }


def restore(sim: Any, data: dict[str, Any]) -> None:
    rows = decode_list(data["locations"], "spatial locations")
    operational_rows = decode_list(data["operational_nodes"], "spatial operational_nodes")
    location_fields = {
        "operational_node_id", "display_name", "body_id", "core_cell_id",
        "developed_cell_ids",
    }
    locations: list[SurfaceLocationState] = []
    location_ids: set[SpatialNodeId] = set()
    for index, raw in enumerate(rows):
        row = require_fields(raw, location_fields, f"spatial location[{index}]")
        operational_node_id = SpatialNodeId(
            decode_str(row["operational_node_id"], "spatial operational_node_id")
        )
        if operational_node_id in location_ids:
            raise ValueError(f"duplicate spatial location: {operational_node_id}")
        location_ids.add(operational_node_id)
        developed = tuple(
            SurfaceCellId(decode_str(value, "spatial developed_cell_id"))
            for value in decode_list(row["developed_cell_ids"], "spatial developed_cell_ids")
        )
        if len(developed) != len(set(developed)):
            raise ValueError(f"duplicate developed surface cell: {operational_node_id}")
        locations.append(
            SurfaceLocationState(
                operational_node_id,
                decode_str(row["display_name"], "spatial display_name"),
                CelestialBodyId(decode_str(row["body_id"], "spatial body_id")),
                SurfaceCellId(decode_str(row["core_cell_id"], "spatial core_cell_id")),
                set(developed),
            )
        )
    operational_node_ids = tuple(
        SpatialNodeId(decode_str(value, "spatial operational_node"))
        for value in operational_rows
    )
    if len(operational_node_ids) != len(set(operational_node_ids)):
        raise ValueError("duplicate spatial operational node")
    operational_nodes = tuple(OperationalNodeState(node_id) for node_id in operational_node_ids)
    sim.graph.replace_dynamic_state(tuple(locations), operational_nodes)
    improvements = {}
    for index, raw in enumerate(decode_list(data["engineered_terrain"], "engineered terrain")):
        row = require_fields(raw, {"cell_id", "profile_id"}, f"engineered terrain[{index}]")
        cell_id = SurfaceCellId(decode_str(row["cell_id"], "engineered terrain cell_id"))
        profile_id = decode_str(row["profile_id"], "engineered terrain profile_id")
        if cell_id in improvements:
            raise ValueError(f"duplicate engineered terrain: {cell_id}")
        if cell_id not in sim.graph.surface_cells or profile_id not in sim.graph.terrain_profiles:
            raise ValueError(f"invalid engineered terrain: {cell_id}/{profile_id}")
        owner = sim.graph.owner_of_cell(cell_id)
        if owner is None or profile_id == sim.graph.surface_cells[cell_id].terrain.profile_id:
            raise ValueError(f"unowned/redundant terrain change: {cell_id}")
        improvements[cell_id] = profile_id
    sim.graph.engineered_terrain = improvements
    sim.environment.restore_overlay_state(
        decode_list(data["overlays"], "environment overlays")
    )


def validate_static_world(graph: Any, environment: Any) -> None:
    """Fully verify authored static spatial and Environment definitions."""
    for body_id, body in graph.bodies.items():
        _require(body_id == body.id, f"celestial body key mismatch: {body_id}")
        _require(body.star_system_id in graph.star_systems, f"celestial body has unknown system: {body_id}")
        if body.parent_body_id is not None:
            _require(body.parent_body_id in graph.bodies, f"celestial body has unknown parent: {body_id}")
            _require(
                graph.bodies[body.parent_body_id].star_system_id == body.star_system_id,
                f"celestial body parent belongs to another system: {body_id}",
            )
        graph.body_lineage(body_id)
    for node_id, node in graph.nodes.items():
        _require(node_id == node.id, f"spatial node key mismatch: {node_id}")
        _require(
            node.parent_id is None or node.parent_id in graph.nodes,
            f"spatial node has unknown parent: {node_id}",
        )
        _require(
            node.body_id is None or node.body_id in graph.bodies,
            f"spatial node has unknown celestial body: {node_id}",
        )
        graph.lineage(node_id)
        graph.environment_lineage(node_id)

    for profile_id, profile in graph.terrain_profiles.items():
        _require(profile.id == profile_id, f"terrain profile key mismatch: {profile_id}")

    for cell_id, cell in graph.surface_cells.items():
        _require(cell_id == cell.id, f"surface cell key mismatch: {cell_id}")
        _require(cell.body_id in graph.bodies, f"surface cell has unknown body: {cell_id}")
        _require(
            graph.bodies[cell.body_id].physical_surface is PhysicalSurface.SOLID,
            f"surface cell on body without solid surface: {cell_id}",
        )
        _require(cell.terrain.profile_id in graph.terrain_profiles, f"unknown terrain profile: {cell_id}")
        _require(cell.area_km2 > 0, f"surface cell has invalid area: {cell_id}")
        _require(cell_id not in cell.neighbor_ids, f"surface cell self adjacency: {cell_id}")
        for neighbor_id in cell.neighbor_ids:
            _require(
                neighbor_id in graph.surface_cells,
                f"surface cell has unknown neighbor: {cell_id}/{neighbor_id}",
            )
            neighbor = graph.surface_cells[neighbor_id]
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

    validate_surface_partitions(graph)

    for (context_id, facet_type), facet in environment.static.facets.items():
        _require(
            context_id in graph.nodes or context_id in graph.surface_cells,
            f"static environment facet references non-static context: {context_id}",
        )
        environment.static._field_scope(facet_type)
        _require(
            isinstance(facet, facet_type),
            f"environment facet type mismatch: {context_id}/{facet_type.__name__}",
        )
    for (body_id, facet_type), facet in environment.static.body_facets.items():
        _require(body_id in graph.bodies, f"body environment facet references unknown body: {body_id}")
        environment.static._field_scope(facet_type)
        _require(
            isinstance(facet, facet_type),
            f"body environment facet type mismatch: {body_id}/{facet_type.__name__}",
        )


@dataclass(frozen=True)
class ValidatedStaticWorld:
    """Validated registration snapshot, not a mutable authoritative World.

    A standard Application receives independent mappings. Equality against the
    complete static input must hold before reusing the geometric/facet proof;
    altered or extended definitions always run the full generic validator.
    """

    graph_kind: type = field(repr=False)
    environment_kind: type = field(repr=False)
    static_store_kind: type = field(repr=False)
    stars: Mapping = field(repr=False)
    bodies: Mapping = field(repr=False)
    nodes: Mapping = field(repr=False)
    cells: Mapping = field(repr=False)
    facets: Mapping = field(repr=False)
    body_facets: Mapping = field(repr=False)
    geology_keys: frozenset[str] = field(repr=False)
    terrain_types: frozenset[type] = field(repr=False)
    terrain_profiles: Mapping = field(repr=False)

    def matches(self, graph: Any, environment: Any) -> bool:
        return (type(graph) is self.graph_kind
                and type(environment) is self.environment_kind
                and type(environment.static) is self.static_store_kind
                and graph.star_systems == self.stars
                and graph.bodies == self.bodies
                and graph.nodes == self.nodes
                and graph.surface_cells == self.cells
                and graph.terrain_profiles == self.terrain_profiles
                and environment.static.facets == self.facets
                and environment.static.body_facets == self.body_facets)

    def __deepcopy__(self, memo):
        # A proof has no player-owned State and is safe to share with forecasts.
        return self


def certify_static_world(graph: Any, environment: Any) -> ValidatedStaticWorld:
    """Register the full verification evidence once, before any Game State."""
    _require(environment.graph is graph, "simulation/environment spatial graph mismatch")
    validate_static_world(graph, environment)
    # Freeze both the top-level registries and nested mutable Content maps.
    # A caller cannot rewrite the evidence that licensed the fast path.
    cells = {
        cell_id: replace(
            cell,
            static_geology=MappingProxyType(dict(cell.static_geology)),
            resource_potential_by_resource=MappingProxyType(dict(cell.resource_potential_by_resource)),
        )
        for cell_id, cell in graph.surface_cells.items()
    }

    def static_facets(rows):
        return MappingProxyType({
            key: replace(value, composition=MappingProxyType(dict(value.composition)))
            if isinstance(value, AtmosphereField) else deepcopy(value)
            for key, value in rows.items()
        })

    return ValidatedStaticWorld(
        type(graph), type(environment), type(environment.static),
        MappingProxyType(deepcopy(graph.star_systems)),
        MappingProxyType(deepcopy(graph.bodies)),
        MappingProxyType(deepcopy(graph.nodes)),
        MappingProxyType(cells),
        static_facets(environment.static.facets),
        static_facets(environment.static.body_facets),
        frozenset(key for cell in graph.surface_cells.values() for key in cell.static_geology),
        frozenset(type(cell.terrain) for cell in graph.surface_cells.values()),
        MappingProxyType(deepcopy(graph.terrain_profiles)),
    )


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    _require(sim.environment.graph is sim.graph, "simulation/environment spatial graph mismatch")
    if not ctx.static_world_proof_matches:
        validate_static_world(sim.graph, sim.environment)
    # Overlays can change at runtime and must never inherit a static proof.
    sim.environment.ordered_overlays()
    # Surface Location ownership and physical overlays are authoritative
    # runtime State, even when the entire static input is unchanged.
    validate_runtime(sim)


def validate_runtime(sim: Any) -> None:
    for cell_id, profile_id in sim.graph.engineered_terrain.items():
        _require(cell_id in sim.graph.surface_cells, f"engineered terrain unknown Cell: {cell_id}")
        _require(profile_id in sim.graph.terrain_profiles, f"engineered terrain unknown profile: {cell_id}")
        _require(sim.graph.owner_of_cell(cell_id) is not None, f"engineered terrain lacks owner: {cell_id}")
        _require(profile_id != sim.graph.surface_cells[cell_id].terrain.profile_id,
                 f"redundant engineered terrain: {cell_id}")
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
        _require(
            sim.graph.bodies[location.body_id].physical_surface is PhysicalSurface.SOLID,
            f"surface location on body without solid surface: {location_id}",
        )
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
