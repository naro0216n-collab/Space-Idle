from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    DevelopSurfaceCell,
    FoundLocation,
    GetBuildOptions,
    GetProjects,
    GetSurfaceMap,
    StartSurvey,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import SAVE_SCHEMA_VERSION, load_game, save_game
from space_idle.shared import SpatialNodeId


def _prime_lunar_founding(app, target_cell, *, survey: bool = True, fleet_units: int = 1):
    sim = app._simulation
    if survey:
        sim.survey.initialize_known(target_cell, ids.WATER)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.logistics.add_fleet_units(
        ids.REUSABLE_SURFACE_CARGO_LANDER, fleet_units, ids.LUNAR_ORBIT, day=sim.day
    )
    for resource_id, required_t in sim.founding.deployment_resource_requirements(
        ids.LUNAR_ROBOTIC_FOUNDING_PACKAGE, ids.REUSABLE_SURFACE_CARGO_LANDER
    ):
        sim.inventory.add(ids.LUNAR_ORBIT, resource_id, required_t + 1.0)
    sim.refresh_resource_claims()
    return sim


def _start_lunar_founding(app, target_cell, name="Farside Robotic Base"):
    return app.execute(FoundLocation(
        str(ids.LUNAR_ROBOTIC_FOUNDING_PACKAGE),
        str(ids.LUNAR_ORBIT),
        str(target_cell),
        name,
        str(ids.REUSABLE_SURFACE_CARGO_LANDER),
    )).created_id


def test_surface_cell_development_changes_territory_only_after_project_completion():
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
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


def test_location_founding_is_a_deployment_and_creates_first_surface_location():
    app = build_game_application()
    sim = _prime_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    assert not [location for location in sim.graph.locations.values() if location.body_id == ids.MOON]

    project_id = _start_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    assert project_id is not None
    planned = next(project for project in app.query(GetProjects()).items if project.id == project_id)
    new_location_id = planned.target_location_id
    assert planned.target_kind == "location_founding_deployment"
    assert planned.location_id == str(ids.LUNAR_ORBIT)
    assert planned.founding_package_id == str(ids.LUNAR_ROBOTIC_FOUNDING_PACKAGE)
    assert planned.founding_vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    assert new_location_id is not None and new_location_id.startswith("player.location.")
    assert SpatialNodeId(new_location_id) not in sim.graph.locations

    app.execute(AdvanceTime(5))
    location_id = SpatialNodeId(new_location_id)
    location = sim.graph.locations[location_id]
    assert location.core_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert location.developed_cell_ids == {ids.MOON_CELL_FARSIDE_HIGHLANDS}
    row = next(project for project in app.query(GetProjects()).items if project.id == project_id)
    assert row.status.value == "complete"
    assert any(route.origin.location_id == ids.LUNAR_ORBIT and route.destination.location_id == location_id for route in sim.logistics.routes.values())
    assert any(route.origin.location_id == location_id and route.destination.location_id == ids.LUNAR_ORBIT for route in sim.logistics.routes.values())
    deployed_defs = {sim.facilities.facilities[fid].definition_id for fid in sim.founding.projects[next(iter(sim.founding.projects))].completed_facility_ids}
    assert {ids.ROBOTIC_SURVEY_PACKAGE, ids.CARGO_WAREHOUSE, ids.SURFACE_DISTRIBUTION_HUB, ids.CRYOGENIC_STORAGE} <= deployed_defs


def test_competing_founding_projects_cannot_claim_the_same_cell():
    app = build_game_application()
    _prime_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS, fleet_units=2)
    first = _start_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS, "First Base")
    assert first is not None
    with pytest.raises(ApplicationError, match="active_founding_project"):
        _start_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS, "Competing Base")


def test_surface_map_exposes_founding_package_staging_vehicle_and_blockers():
    app = build_game_application()
    view = app.query(GetSurfaceMap(str(ids.MOON)))
    assert view.locations == ()
    cell = next(row for row in view.cells if row.id == str(ids.MOON_CELL_FARSIDE_HIGHLANDS))
    foundation = next(
        row for row in cell.foundation_options
        if row.package_id == str(ids.LUNAR_ROBOTIC_FOUNDING_PACKAGE)
        and row.staging_location_id == str(ids.LUNAR_ORBIT)
        and row.vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert foundation.deployment_days > 0
    assert foundation.payload_t > 0
    assert {resource_id for resource_id, _amount in foundation.resources} >= {
        str(ids.STRUCTURAL_COMPONENTS), str(ids.MACHINERY), str(ids.PRECISION_ELECTRONICS), str(ids.PROPELLANT)
    }
    assert any(code == "survey_knowledge" for code, _detail in foundation.blockers)
    # Generic Core does not silently hide cross-body staging candidates; the
    # lunar package itself declares that it requires same-body staging.
    earth_option = next(
        row for row in cell.foundation_options
        if row.package_id == str(ids.LUNAR_ROBOTIC_FOUNDING_PACKAGE)
        and row.staging_location_id == str(ids.EARTH)
        and row.vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert any(code == "staging_relation" for code, _detail in earth_option.blockers)


def test_mid_project_save_load_preserves_geographic_target_and_future_transition(tmp_path):
    assert SAVE_SCHEMA_VERSION == 32
    app = build_game_application()
    app._simulation.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
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


def test_mid_project_save_load_preserves_founding_identity_reservation_and_route(tmp_path):
    app = build_game_application()
    sim = _prime_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    project_id = _start_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS, "Persisted Farside Base")
    assert project_id is not None
    planned = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    generated_location_id = planned.target_location_id
    assert generated_location_id is not None

    app.execute(AdvanceTime(1))
    path = tmp_path / "location-founding.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    loaded_row = next(row for row in loaded.query(GetProjects()).items if row.id == project_id)
    assert loaded_row.target_location_id == generated_location_id
    assert loaded._simulation.logistics.fleet_reservation_snapshot(
        loaded._simulation.founding._reservation_id(next(iter(loaded._simulation.founding.projects)))
    ) is not None

    app.execute(AdvanceTime(5))
    loaded.execute(AdvanceTime(5))
    location_id = SpatialNodeId(generated_location_id)
    for current in (app, loaded):
        assert location_id in current._simulation.graph.locations
        assert current._simulation.graph.locations[location_id].core_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
        assert any(route.origin.location_id == ids.LUNAR_ORBIT and route.destination.location_id == location_id for route in current._simulation.logistics.routes.values())


def test_surface_development_requires_survey_knowledge_on_runtime_location():
    app = build_game_application()
    sim = app._simulation
    location_id = SpatialNodeId("test.location.lunar_south")
    sim.graph.found_location(location_id, "Test South", ids.MOON, ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    sim.facilities.install(ids.ROBOTIC_SURVEY_PACKAGE, location_id)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, location_id)
    view = app.query(GetSurfaceMap(str(ids.MOON)))
    cell = next(row for row in view.cells if row.id == str(ids.MOON_CELL_SOUTH_POLAR_PLAIN))
    dev = next(row for row in cell.development_options if row.location_id == str(location_id))
    assert ("survey_knowledge", "level=0/1") in dev.blockers
    with pytest.raises(ApplicationError, match="survey_knowledge: level=0/1"):
        app.execute(DevelopSurfaceCell(str(location_id), str(ids.MOON_CELL_SOUTH_POLAR_PLAIN), sourcing_policy="import_now"))

    sim.survey.initialize_known(ids.MOON_CELL_SOUTH_POLAR_PLAIN, ids.WATER)
    view = app.query(GetSurfaceMap(str(ids.MOON)))
    cell = next(row for row in view.cells if row.id == str(ids.MOON_CELL_SOUTH_POLAR_PLAIN))
    dev = next(row for row in cell.development_options if row.location_id == str(location_id))
    assert not any(code == "survey_knowledge" for code, _detail in dev.blockers)
    assert app.execute(DevelopSurfaceCell(
        str(location_id), str(ids.MOON_CELL_SOUTH_POLAR_PLAIN), sourcing_policy="import_now"
    )).created_id is not None


def test_orbital_survey_enables_first_surface_founding_without_preexisting_location():
    app = build_game_application()
    sim = app._simulation
    target_cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert not [location for location in sim.graph.locations.values() if location.body_id == ids.MOON]
    assert sim.survey.knowledge_level(target_cell, ids.WATER) == 0

    app.execute(StartSurvey(str(ids.LUNAR_ORBIT), str(target_cell), str(ids.WATER)))
    app.execute(AdvanceTime(3))
    assert sim.survey.knowledge_level(target_cell, ids.WATER) >= 1

    # Founding infrastructure and vehicle are ordinary staging assets.  Seeding
    # them here isolates the transition under test from their own build/relocation chains.
    _prime_lunar_founding(app, target_cell, survey=False)
    project_id = _start_lunar_founding(app, target_cell, "Survey-selected Farside Base")
    assert project_id is not None
    assert not [location for location in sim.graph.locations.values() if location.body_id == ids.MOON]

    app.execute(AdvanceTime(5))
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project.status.value == "complete"
    assert SpatialNodeId(project.target_location_id) in sim.graph.locations


def test_location_founding_requires_survey_knowledge_without_preexisting_surface_base():
    app = build_game_application()
    sim = _prime_lunar_founding(app, ids.MOON_CELL_FARSIDE_HIGHLANDS, survey=False)
    target_cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    view = app.query(GetSurfaceMap(str(ids.MOON)))
    cell = next(row for row in view.cells if row.id == str(target_cell))
    foundation = next(
        row for row in cell.foundation_options
        if row.staging_location_id == str(ids.LUNAR_ORBIT)
        and row.vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert ("survey_knowledge", "level=0/1") in foundation.blockers
    with pytest.raises(ApplicationError, match="survey_knowledge"):
        _start_lunar_founding(app, target_cell, "Unsurveyed Farside Base")

    sim.survey.initialize_known(target_cell, ids.WATER)
    view = app.query(GetSurfaceMap(str(ids.MOON)))
    cell = next(row for row in view.cells if row.id == str(target_cell))
    foundation = next(
        row for row in cell.foundation_options
        if row.staging_location_id == str(ids.LUNAR_ORBIT)
        and row.vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert not any(code == "survey_knowledge" for code, _detail in foundation.blockers)
    assert _start_lunar_founding(app, target_cell, "Surveyed Farside Base") is not None
