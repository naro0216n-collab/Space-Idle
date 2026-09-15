from __future__ import annotations

from pathlib import Path

import pytest

from space_idle import GetSurfaceMap, build_game_application
from space_idle.content import base_ids as ids
from space_idle.persistence import load_game, save_game
from space_idle.shared import CelestialBodyId, DefinitionId, SpatialNodeId, StarSystemId, SurfaceCellId
from space_idle.spatial import (
    CelestialBodyDef,
    CharacteristicTransportGeometry,
    SpatialGraph,
    SpatialNodeDef,
    SpatialNodeKind,
    StarSystemDef,
    SurfaceCellDef,
    SurfaceField,
    SurfacePoint,
)
from space_idle.validation import validate_runtime_state
from space_idle.facilities import FacilityDef


def _add_system(graph: SpatialGraph, system_id: str = "test.system") -> StarSystemId:
    value = StarSystemId(system_id)
    graph.add_star_system(StarSystemDef(
        value, system_id, CharacteristicTransportGeometry((0.0,), (0.0,))
    ))
    return value


def _body(
    graph: SpatialGraph, body_id: CelestialBodyId, display_name: str,
    system_id: StarSystemId, coordinate: float = 0.0,
) -> None:
    graph.add_body(CelestialBodyDef(
        body_id, display_name, 1000.0, system_id,
        CharacteristicTransportGeometry((coordinate,), (coordinate,)),
    ))


def _cell(cell_id: str, body_id: CelestialBodyId, neighbors: tuple[str, ...]) -> SurfaceCellDef:
    return SurfaceCellDef(
        SurfaceCellId(cell_id),
        body_id,
        100.0,
        SurfacePoint(0.0, 0.0),
        frozenset(SurfaceCellId(value) for value in neighbors),
        SurfaceField(),
        display_name=cell_id,
    )


def test_surface_topology_supports_variable_cell_counts_and_non_hex_neighbors():
    graph = SpatialGraph()
    body_a = CelestialBodyId("body.a")
    body_b = CelestialBodyId("body.b")
    system = _add_system(graph)
    _body(graph, body_a, "A", system, 0.0)
    _body(graph, body_b, "B", system, 10.0)
    graph.add_surface_cell(_cell("a.1", body_a, ("a.2",)))
    graph.add_surface_cell(_cell("a.2", body_a, ("a.1",)))
    graph.add_surface_cell(_cell("b.1", body_b, ("b.2", "b.3")))
    graph.add_surface_cell(_cell("b.2", body_b, ("b.1",)))
    graph.add_surface_cell(_cell("b.3", body_b, ("b.1",)))

    assert len(graph.cells_for_body(body_a)) == 2
    assert len(graph.cells_for_body(body_b)) == 3
    assert max(len(cell.neighbor_ids) for cell in graph.cells_for_body(body_b)) == 2


def test_location_territory_owns_cells_once_and_expands_only_to_adjacent_cells():
    graph = SpatialGraph()
    body = CelestialBodyId("body")
    system = _add_system(graph)
    _body(graph, body, "Body", system)
    graph.add_surface_cell(_cell("c1", body, ("c2",)))
    graph.add_surface_cell(_cell("c2", body, ("c1", "c3")))
    graph.add_surface_cell(_cell("c3", body, ("c2",)))
    location = SpatialNodeId("location.one")
    graph.found_location(location, "One", body, SurfaceCellId("c1"))

    assert graph.surface_cell_development_failures(location, SurfaceCellId("c3"))[0][0] == "not_adjacent"
    graph.develop_surface_cell(location, SurfaceCellId("c2"))
    graph.develop_surface_cell(location, SurfaceCellId("c3"))
    assert graph.locations[location].developed_cell_ids == {
        SurfaceCellId("c1"), SurfaceCellId("c2"), SurfaceCellId("c3")
    }

    with pytest.raises(ValueError, match="already belongs"):
        graph.found_location(SpatialNodeId("location.two"), "Two", body, SurfaceCellId("c2"))


def test_base_surface_map_exposes_affiliation_without_creating_cell_inventory_nodes():
    app = build_game_application()
    sim = app._simulation
    before_inventory_locations = {location_id for location_id, _resource_id in sim.inventory.stock}
    view = app.query(GetSurfaceMap(str(ids.MOON)))

    assert view.cells
    assert not view.locations
    assert any(not cell.developed for cell in view.cells)
    assert all(cell.environment for cell in view.cells)
    assert all(cell.display_name for cell in view.cells)
    assert all(cell.id not in {str(value) for value in sim.graph.operational_node_ids()} for cell in sim.graph.surface_cells.values())
    assert {location_id for location_id, _resource_id in sim.inventory.stock} == before_inventory_locations


def test_developed_territory_persists_without_saving_derived_cell_owner(tmp_path: Path):
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    validate_runtime_state(sim)

    path = tmp_path / "save.json"
    save_game(app, path)
    raw = path.read_text(encoding="utf-8")
    assert "developed_cell_ids" in raw
    assert "owner_location_id" not in raw

    loaded, _ = load_game(path, build_game_application)
    assert loaded._simulation.graph.locations[ids.EARTH].developed_cell_ids == {
        ids.EARTH_CELL_INDUSTRIAL,
        ids.EARTH_CELL_COASTAL,
    }
    assert loaded._simulation.graph.owner_of_cell(ids.EARTH_CELL_COASTAL) == ids.EARTH


def test_non_surface_spatial_context_is_not_operational_until_explicitly_promoted():
    graph = SpatialGraph()
    body = CelestialBodyId("body.context")
    node_id = SpatialNodeId("node.context.only")
    system = _add_system(graph)
    geometry = CharacteristicTransportGeometry((0.0,), (0.0,))
    graph.add_body(CelestialBodyDef(body, "Body", 1000.0, system, geometry))
    graph.add(
        SpatialNodeDef(
            node_id,
            "Context only",
            system,
            geometry,
            body_id=body,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )

    assert node_id in graph.nodes
    assert not graph.has_operational_node(node_id)
    assert node_id not in graph.operational_node_ids()


def test_non_operational_spatial_context_cannot_own_facility_lane_or_inventory_state():
    app = build_game_application()
    sim = app._simulation
    dormant = SpatialNodeId("test.node.dormant")
    sim.graph.add(
        SpatialNodeDef(
            dormant,
            "Dormant orbit",
            ids.SOL_SYSTEM,
            sim.graph.bodies[ids.MOON].system_local_transport_geometry,
            body_id=ids.MOON,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )
    assert not sim.graph.has_operational_node(dormant)

    facility_definition_id = next(iter(sim.facilities.definitions))
    with pytest.raises(KeyError):
        sim.facilities.install(facility_definition_id, dormant)
    with pytest.raises(KeyError):
        sim.logistics.create_lane(ids.EARTH, dormant, 1.0, 3)

    sim.inventory.stock[(dormant, ids.WATER)] = 1.0
    with pytest.raises(ValueError, match="inventory references unknown location"):
        validate_runtime_state(sim)


def test_save_load_preserves_operational_node_existence_separately_from_surface_territory(tmp_path: Path):
    app = build_game_application()
    sim = app._simulation
    dormant = SpatialNodeId("test.node.context_only")
    sim.graph.add(
        SpatialNodeDef(
            dormant,
            "Context only",
            ids.SOL_SYSTEM,
            sim.graph.bodies[ids.MOON].system_local_transport_geometry,
            body_id=ids.MOON,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )
    before_operational = set(sim.graph.operational_node_ids())
    assert dormant not in before_operational

    path = tmp_path / "operational-node-state.json"
    save_game(app, path)
    loaded, _ = load_game(path, build_game_application)

    assert set(loaded._simulation.graph.operational_node_ids()) == before_operational
    assert dormant not in loaded._simulation.graph.nodes  # static Content is rebuilt, not Save state
    assert set(loaded._simulation.graph.locations) == set(sim.graph.locations)


def test_surface_and_non_surface_operational_nodes_share_owner_contracts():
    app = build_game_application()
    sim = app._simulation
    generic_facility = DefinitionId("test.facility.operational_node")
    generic_resource = DefinitionId("test.resource.unbounded")
    sim.facilities.definitions[generic_facility] = FacilityDef(generic_facility, "Generic")

    earth_facility = sim.facilities.install(generic_facility, ids.EARTH)
    orbit_facility = sim.facilities.install(generic_facility, ids.LEO)
    assert sim.facilities.facilities[earth_facility].operational_node_id == ids.EARTH
    assert sim.facilities.facilities[orbit_facility].operational_node_id == ids.LEO

    sim.inventory.add(ids.EARTH, generic_resource, 1.0)
    sim.inventory.add(ids.LEO, generic_resource, 1.0)
    assert sim.inventory.amount(ids.EARTH, generic_resource) == pytest.approx(1.0)
    assert sim.inventory.amount(ids.LEO, generic_resource) == pytest.approx(1.0)

    vehicle_definition = next(iter(sim.transport.vehicle_defs))
    before_earth = sim.transport.fleet_pool(vehicle_definition, ids.EARTH).total_units
    before_orbit = sim.transport.fleet_pool(vehicle_definition, ids.LEO).total_units
    sim.transport.add_fleet_units(vehicle_definition, 1, ids.EARTH, day=sim.day)
    sim.transport.add_fleet_units(vehicle_definition, 1, ids.LEO, day=sim.day)
    assert sim.transport.fleet_pool(vehicle_definition, ids.EARTH).total_units == before_earth + 1
    assert sim.transport.fleet_pool(vehicle_definition, ids.LEO).total_units == before_orbit + 1
