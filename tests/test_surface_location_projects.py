from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    DevelopSurfaceCell,
    FoundLocation,
    GetProjects,
    GetSurfaceMap,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import SAVE_SCHEMA_VERSION, load_game, save_game
from space_idle.shared import SpatialNodeId


def test_surface_cell_development_changes_territory_only_after_project_completion():
    app = build_game_application()
    sim = app._simulation
    before = {
        resource_id: sim.inventory.amount(ids.EARTH, resource_id)
        for resource_id in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.CONSTRUCTION_EQUIPMENT)
    }

    result = app.execute(DevelopSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"))
    project_id = result.created_id
    assert project_id is not None
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    app.execute(AdvanceTime(20))
    assert ids.EARTH_CELL_COASTAL in sim.graph.locations[ids.EARTH].developed_cell_ids
    row = next(project for project in app.query(GetProjects()).items if project.id == project_id)
    assert row.target_kind == "surface_cell_development"
    assert row.target_cell_id == str(ids.EARTH_CELL_COASTAL)
    assert row.completed_facility_id is None
    assert row.status.value == "complete"
    for resource_id in before:
        assert sim.inventory.amount(ids.EARTH, resource_id) < before[resource_id]


def test_location_founding_is_a_project_and_allows_a_disconnected_valid_core_cell():
    app = build_game_application()
    sim = app._simulation
    new_location_id = "test.location.earth_coastal"

    result = app.execute(FoundLocation(
        str(ids.EARTH),
        new_location_id,
        "Coastal Industrial Base",
        str(ids.EARTH_BODY),
        str(ids.EARTH_CELL_COASTAL),
        sourcing_policy="import_now",
    ))
    project_id = result.created_id
    assert project_id is not None
    assert SpatialNodeId(new_location_id) not in sim.graph.locations

    app.execute(AdvanceTime(25))
    location = sim.graph.locations[SpatialNodeId(new_location_id)]
    assert location.core_cell_id == ids.EARTH_CELL_COASTAL
    assert location.developed_cell_ids == {ids.EARTH_CELL_COASTAL}
    row = next(project for project in app.query(GetProjects()).items if project.id == project_id)
    assert row.target_kind == "location_founding"
    assert row.target_location_id == new_location_id
    assert row.target_body_id == str(ids.EARTH_BODY)
    assert row.target_cell_id == str(ids.EARTH_CELL_COASTAL)
    assert row.facility_definition_id is None


def test_competing_spatial_projects_cannot_claim_the_same_cell():
    app = build_game_application()
    app.execute(DevelopSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"))

    with pytest.raises(ApplicationError, match="active"):
        app.execute(FoundLocation(
            str(ids.EARTH),
            "test.location.competing",
            "Competing Base",
            str(ids.EARTH_BODY),
            str(ids.EARTH_CELL_COASTAL),
            sourcing_policy="import_now",
        ))


def test_surface_map_exposes_project_costs_blockers_and_active_project():
    app = build_game_application()
    view = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    cell = next(row for row in view.cells if row.id == str(ids.EARTH_CELL_COASTAL))
    dev = next(row for row in cell.development_options if row.location_id == str(ids.EARTH))
    assert dev.construction_required is not None and dev.construction_required > 0
    assert {resource_id for resource_id, _amount in dev.resources} == {
        str(ids.STRUCTURAL_COMPONENTS), str(ids.MACHINERY), str(ids.CONSTRUCTION_EQUIPMENT)
    }
    foundation = next(row for row in cell.foundation_options if row.provider_location_id == str(ids.EARTH))
    assert foundation.construction_required > dev.construction_required
    assert foundation.active_project_id is None

    project_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    )).created_id
    view = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    cell = next(row for row in view.cells if row.id == str(ids.EARTH_CELL_COASTAL))
    dev = next(row for row in cell.development_options if row.location_id == str(ids.EARTH))
    assert dev.active_project_id == project_id
    assert any(code == "active_spatial_project" for code, _detail in dev.blockers)


def test_mid_project_save_load_preserves_geographic_target_and_future_transition(tmp_path):
    assert SAVE_SCHEMA_VERSION == 31
    app = build_game_application()
    project_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    )).created_id
    app.execute(AdvanceTime(4))
    assert project_id is not None
    assert ids.EARTH_CELL_COASTAL not in app._simulation.graph.locations[ids.EARTH].developed_cell_ids

    path = tmp_path / "surface-development.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    loaded_row = next(row for row in loaded.query(GetProjects()).items if row.id == project_id)
    assert loaded_row.target_kind == "surface_cell_development"
    assert loaded_row.target_cell_id == str(ids.EARTH_CELL_COASTAL)

    app.execute(AdvanceTime(20))
    loaded.execute(AdvanceTime(20))
    assert ids.EARTH_CELL_COASTAL in app._simulation.graph.locations[ids.EARTH].developed_cell_ids
    assert ids.EARTH_CELL_COASTAL in loaded._simulation.graph.locations[ids.EARTH].developed_cell_ids
