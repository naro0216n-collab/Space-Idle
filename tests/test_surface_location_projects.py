from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CancelFounding,
    DevelopSurfaceCell,
    FoundLocation,
    GetProjects,
    GetSurfaceMap,
    StartSurvey,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import SAVE_SCHEMA_VERSION, capture_state, load_game, save_game
from space_idle.shared import SpatialNodeId
from space_idle.transport.surface_routes import DERIVED_SURFACE_ORBIT_ROUTE_PREFIX


def _survey_cell_to_l2(sim, cell_id):
    target = next(target for key, target in sim.survey.targets.items() if key[0] == cell_id)
    sim.survey.knowledge_progress[(target.cell_id, target.resource_id)] = target.thresholds[1]
    assert sim.survey.cell_knowledge_level(cell_id) >= 2


def _stage_founding_resources(sim):
    package = sim.founding.packages[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    for req in package.resources:
        sim.inventory.add(ids.LUNAR_ORBIT, req.resource_id, req.amount_t + 1.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 10.0)
    return package


def _found_command(name: str, cell_id):
    return FoundLocation(
        staging_node_id=str(ids.LUNAR_ORBIT),
        display_name=name,
        body_id=str(ids.MOON),
        core_cell_id=str(cell_id),
        founding_package_id=str(ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE),
        vehicle_definition_id=str(ids.REUSABLE_SURFACE_CARGO_LANDER),
    )


def test_baseline_has_no_player_lunar_location_and_orbital_survey_is_available():
    app = build_game_application()
    sim = app._simulation
    assert [loc for loc in sim.graph.locations.values() if loc.body_id == ids.MOON] == []

    target_cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    target = next(target for key, target in sim.survey.targets.items() if key[0] == target_cell)
    app.execute(StartSurvey(str(ids.LUNAR_ORBIT), str(target_cell), str(target.resource_id)))
    app.execute(AdvanceTime(8))
    assert sim.survey.cell_knowledge_level(target_cell) >= 2


def test_surface_cell_development_changes_territory_only_after_project_completion():
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    result = app.execute(DevelopSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"))
    assert result.created_id is not None
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids
    app.execute(AdvanceTime(20))
    assert ids.EARTH_CELL_COASTAL in sim.graph.locations[ids.EARTH].developed_cell_ids


def test_founding_requires_orbital_survey_and_does_not_create_target_inventory_before_arrival():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    with pytest.raises(ApplicationError, match="survey_knowledge"):
        app.execute(_found_command("Farside", cell))

    _survey_cell_to_l2(sim, cell)
    _stage_founding_resources(sim)
    result = app.execute(_found_command("Farside", cell))
    assert result.created_id is not None
    project = sim.founding.projects[next(iter(sim.founding.projects))]
    assert project.new_location_id not in sim.graph.locations
    assert all(location_id != project.new_location_id for location_id, _resource in sim.inventory.stock)
    assert not any(
        project.new_location_id in {route.origin_id, route.destination_id}
        for route in sim.logistics.routes.values()
    )


def test_founding_completion_creates_location_bootstrap_and_dynamic_orbit_routes_once():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    package = _stage_founding_resources(sim)
    project_id = app.execute(_found_command("Farside", cell)).created_id
    assert project_id is not None
    app.execute(AdvanceTime(8))

    project = next(p for p in sim.founding.projects.values() if str(p.id) == project_id)
    assert project.status.value == "complete"
    location = sim.graph.locations[project.new_location_id]
    assert location.core_cell_id == cell
    deployed_defs = {f.definition_id for f in sim.facilities.all_at(project.new_location_id)}
    assert {d.facility_def_id for d in package.deployed_facilities} <= deployed_defs
    orbit_routes = [
        route for route_id, route in sim.logistics.routes.items()
        if str(route_id).startswith(DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
        and project.new_location_id in {route.origin_id, route.destination_id}
    ]
    assert len(orbit_routes) == 2
    assert sim.logistics.fleet_pool(ids.REUSABLE_SURFACE_CARGO_LANDER, project.new_location_id).total_units == 1


def test_founding_and_surface_development_claims_are_mutually_exclusive():
    app = build_game_application()
    sim = app._simulation
    # Existing Earth location starts a development claim.
    dev_id = app.execute(DevelopSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now")).created_id
    assert dev_id
    # A Founding service must see that same cell as claimed even if other package
    # prerequisites would also fail.
    package = sim.founding.packages[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    failures = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, ids.EARTH_BODY, ids.EARTH_CELL_COASTAL,
        package.id, ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day,
    )
    assert any(row.code == "cell_claimed" for row in failures)


def test_cancelled_founding_does_not_consume_generated_location_identity():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    _stage_founding_resources(sim)
    first = app.execute(_found_command("First", cell)).created_id
    project = next(p for p in sim.founding.projects.values() if str(p.id) == first)
    generated = project.new_location_id
    app.execute(CancelFounding(first))
    second = app.execute(_found_command("Second", cell)).created_id
    project2 = next(p for p in sim.founding.projects.values() if str(p.id) == second)
    assert project2.new_location_id == generated


def test_surface_map_exposes_founding_package_vehicle_and_blockers():
    app = build_game_application()
    cell_id = ids.MOON_CELL_FARSIDE_HIGHLANDS
    cell = next(row for row in app.query(GetSurfaceMap(str(ids.MOON))).cells if row.id == str(cell_id))
    option = next(
        row for row in cell.foundation_options
        if row.staging_node_id == str(ids.LUNAR_ORBIT)
        and row.founding_package_id == str(ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE)
        and row.vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert option.payload_t > 0
    assert option.payload_t_per_unit <= 6.0
    assert option.required_units == 1
    assert any(code == "survey_knowledge" for code, _detail in option.blockers)


def test_active_founding_save_load_preserves_identity_and_future_transition(tmp_path):
    assert SAVE_SCHEMA_VERSION == 32
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    _stage_founding_resources(sim)
    project_id = app.execute(_found_command("Persisted", cell)).created_id
    assert project_id is not None
    app.execute(AdvanceTime(2))
    project = next(p for p in sim.founding.projects.values() if str(p.id) == project_id)
    generated = project.new_location_id

    path = tmp_path / "founding.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    loaded_project = loaded._simulation.founding.projects[project.id]
    assert loaded_project.new_location_id == generated
    assert capture_state(loaded._simulation) == capture_state(sim)

    app.execute(AdvanceTime(8))
    loaded.execute(AdvanceTime(8))
    assert generated in app._simulation.graph.locations
    assert generated in loaded._simulation.graph.locations
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
