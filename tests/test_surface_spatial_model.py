from __future__ import annotations

from pathlib import Path

import pytest

from space_idle import GetSurfaceMap, build_game_application
from space_idle.content import base_ids as ids
from space_idle.persistence import load_game, save_game
from space_idle.shared import CelestialBodyId, SpatialNodeId, SurfaceCellId
from space_idle.spatial import (
    CelestialBodyDef,
    LocationState,
    SpatialGraph,
    SurfaceCellDef,
    SurfaceField,
    SurfacePoint,
)
from space_idle.validation import validate_runtime_state


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
    graph.add_body(CelestialBodyDef(body_a, "A", 1000.0))
    graph.add_body(CelestialBodyDef(body_b, "B", 1000.0))
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
    graph.add_body(CelestialBodyDef(body, "Body", 1000.0))
    graph.add_surface_cell(_cell("c1", body, ("c2",)))
    graph.add_surface_cell(_cell("c2", body, ("c1", "c3")))
    graph.add_surface_cell(_cell("c3", body, ("c2",)))
    location = SpatialNodeId("location.one")
    graph.add_location(LocationState(location, "One", body, SurfaceCellId("c1")))

    assert graph.surface_cell_development_failures(location, SurfaceCellId("c3"))[0][0] == "not_adjacent"
    graph.develop_surface_cell(location, SurfaceCellId("c2"))
    graph.develop_surface_cell(location, SurfaceCellId("c3"))
    assert graph.locations[location].developed_cell_ids == {
        SurfaceCellId("c1"), SurfaceCellId("c2"), SurfaceCellId("c3")
    }

    with pytest.raises(ValueError, match="already belongs"):
        graph.add_location(LocationState(SpatialNodeId("location.two"), "Two", body, SurfaceCellId("c2")))


def test_base_surface_map_exposes_affiliation_without_creating_cell_inventory_nodes():
    app = build_game_application()
    sim = app._simulation
    before_inventory_locations = {location_id for location_id, _resource_id in sim.inventory.stock}
    view = app.query(GetSurfaceMap(str(ids.MOON)))

    assert len(view.cells) == 6
    assert len(view.locations) == 3
    assert any(not cell.developed for cell in view.cells)
    assert all(cell.environment for cell in view.cells)
    assert all(cell.display_name for cell in view.cells)
    assert {cell.display_name for cell in view.cells} >= {"南極高地縁辺", "極域永久影クレーター", "表側海地域"}
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
