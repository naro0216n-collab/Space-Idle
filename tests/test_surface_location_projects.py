from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CancelFounding,
    CreateExternalServicePolicy,
    CreateLogisticsLane,
    DevelopSurfaceCell,
    FoundLocation,
    GetProjects,
    GetSurfaceMap,
    StartSurvey,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import SAVE_SCHEMA_VERSION, capture_state, load_game, save_game
from space_idle.simulation import OfflineProgressPolicy
from space_idle.founding import FoundingResourceRequirement
from space_idle.shared import DefinitionId, SpatialNodeId
from space_idle.transport.surface_routes import DERIVED_SURFACE_ORBIT_ROUTE_PREFIX


def _survey_cell_to_l2(sim, cell_id):
    target = next(target for key, target in sim.survey.targets.items() if key[0] == cell_id)
    sim.survey.knowledge_progress[(target.cell_id, target.resource_id)] = target.thresholds[1]
    assert sim.survey.cell_knowledge_level(cell_id) >= 2


def _stage_founding_resources(sim):
    package = sim.founding.packages[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    for req in package.payload_resources:
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



def test_founding_package_payload_is_derived_from_deployment_investment_and_initial_inventory():
    app = build_game_application()
    package = app._simulation.founding.packages[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    expected = package.investment_totals()
    for resource_id, amount_t in package.initial_inventory_totals().items():
        expected[resource_id] = expected.get(resource_id, 0.0) + amount_t
    assert {row.resource_id: row.amount_t for row in package.payload_resources} == expected
    assert package.payload_t == pytest.approx(sum(expected.values()))


def test_founding_transport_path_and_site_requirements_follow_staging_and_target_contexts():
    app = build_game_application()
    sim = app._simulation
    package = sim.founding.packages[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)

    same_body = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, ids.MOON, cell, package.id, ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day
    )
    assert not any(row.code.startswith("deployment_vehicle") and "deployment_path:" in row.detail for row in same_body)
    assert not any(row.code.startswith("staging:") for row in same_body)
    assert not any(row.code.startswith("target:") for row in same_body)

    cross_body = sim.founding.planning_failures(
        ids.LEO, ids.MOON, cell, package.id, ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day
    )
    assert any(
        row.code == "deployment_vehicle" and row.detail == "deployment_path:spaceflight_required"
        for row in cross_body
    )

    earth_target = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, ids.EARTH_BODY, ids.EARTH_CELL_COASTAL, package.id, ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day
    )
    assert any(row.code == "target:environment:low_pressure" for row in earth_target)


def test_founding_package_initial_inventory_is_delivered_only_on_completion():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    base = sim.founding.packages[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    cargo_deployment = next(
        deployment for deployment in base.deployed_facilities
        if deployment.facility_def_id == ids.CARGO_WAREHOUSE
    )
    package_id = DefinitionId("test.founding.initial_inventory")
    package = replace(
        base,
        id=package_id,
        deployed_facilities=(cargo_deployment,),
        initial_inventory=(FoundingResourceRequirement(ids.STRUCTURAL_COMPONENTS, 0.4),),
    )
    sim.founding.packages[package_id] = package
    for req in package.payload_resources:
        sim.inventory.add(ids.LUNAR_ORBIT, req.resource_id, req.amount_t + 1.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 10.0)

    project_id = app.execute(FoundLocation(
        staging_node_id=str(ids.LUNAR_ORBIT),
        display_name="Bootstrap Inventory",
        body_id=str(ids.MOON),
        core_cell_id=str(cell),
        founding_package_id=str(package_id),
        vehicle_definition_id=str(ids.REUSABLE_SURFACE_CARGO_LANDER),
    )).created_id
    assert project_id is not None
    project = next(row for row in sim.founding.projects.values() if str(row.id) == project_id)
    assert sim.inventory.amount(project.new_location_id, ids.STRUCTURAL_COMPONENTS) == 0.0

    app.execute(AdvanceTime(8))
    assert sim.inventory.amount(project.new_location_id, ids.STRUCTURAL_COMPONENTS) == pytest.approx(0.4)


def test_baseline_has_no_player_lunar_location_and_orbital_survey_is_available():
    app = build_game_application()
    sim = app._simulation
    assert [loc for loc in sim.graph.locations.values() if loc.body_id == ids.MOON] == []

    target_cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    target = next(target for key, target in sim.survey.targets.items() if key[0] == target_cell)
    app.execute(StartSurvey(str(ids.LUNAR_ORBIT), str(target_cell), str(target.resource_id)))
    app.execute(AdvanceTime(8))
    assert sim.survey.cell_knowledge_level(target_cell) >= 2


def test_orbital_survey_player_logistics_and_founding_create_first_surface_location():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert not [location for location in sim.graph.locations.values() if location.body_id == ids.MOON]

    target = next(target for key, target in sim.survey.targets.items() if key[0] == cell)
    app.execute(StartSurvey(str(ids.LUNAR_ORBIT), str(cell), str(target.resource_id)))
    app.execute(AdvanceTime(8))
    assert sim.survey.cell_knowledge_level(cell) >= 2

    app.execute(CreateExternalServicePolicy(
        enabled=True,
        allowed_service_ids=tuple(map(str, sim.transport.external_services)),
    ))
    lane_id = app.execute(CreateLogisticsLane(
        str(ids.EARTH), str(ids.LUNAR_ORBIT), 0.25, priority=70
    )).created_id
    assert lane_id is not None
    project_id = app.execute(_found_command("Farside First Base", cell)).created_id
    assert project_id is not None

    app.execute(AdvanceTime(40))

    project = next(
        project for project in sim.founding.projects.values()
        if str(project.id) == project_id
    )
    assert project.status.value == "complete"
    lunar_locations = [
        location for location in sim.graph.locations.values()
        if location.body_id == ids.MOON
    ]
    assert len(lunar_locations) == 1
    assert lunar_locations[0].operational_node_id == project.new_location_id
    assert lunar_locations[0].core_cell_id == cell
    assert sim.graph.owner_of_cell(cell) == project.new_location_id
    assert sim.graph.has_operational_node(project.new_location_id)


def test_surface_cell_development_changes_territory_only_after_project_completion():
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    result = app.execute(DevelopSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"))
    assert result.created_id is not None
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids
    app.execute(AdvanceTime(20))
    assert ids.EARTH_CELL_COASTAL in sim.graph.locations[ids.EARTH].developed_cell_ids


def test_founding_resource_shortage_reports_logistics_lane_blocker():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    project_id = app.execute(_found_command("No Supply Lane", cell)).created_id
    assert project_id is not None

    row = next(
        item for item in app.query(GetProjects(str(ids.LUNAR_ORBIT))).items
        if item.id == project_id
    )
    assert any(code == "import_lane" for code, _detail in row.blockers)
    assert any(code == "resource_shortage" for code, _detail in row.blockers)


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
    assert not sim.graph.has_operational_node(project.new_location_id)
    assert all(location_id != project.new_location_id for location_id, _resource in sim.inventory.stock)
    assert not any(
        project.new_location_id in {route.origin_id, route.destination_id}
        for route in sim.transport.routes.values()
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
        route for route_id, route in sim.transport.routes.items()
        if str(route_id).startswith(DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
        and project.new_location_id in {route.origin_id, route.destination_id}
    ]
    assert orbit_routes
    assert sim.transport.fleet_pool(ids.REUSABLE_SURFACE_CARGO_LANDER, project.new_location_id).total_units == 1


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



def test_cancelling_prepared_founding_returns_staged_payload_to_inventory():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    _stage_founding_resources(sim)
    project_id = app.execute(_found_command("Cancelled Prepared", cell)).created_id
    assert project_id is not None
    app.execute(AdvanceTime(1))
    project = next(row for row in sim.founding.projects.values() if str(row.id) == project_id)
    assert project.status.value == "preparing"
    assert project.inputs_consumed
    payload_owner = sim.founding.payload_owner_id(project.id)
    staged = {
        resource_id: amount
        for (owner, location_id, resource_id), amount in sim.inventory.external_occupancy.items()
        if owner == payload_owner and location_id == ids.LUNAR_ORBIT
    }
    assert staged
    stock_before_cancel = {
        resource_id: sim.inventory.amount(ids.LUNAR_ORBIT, resource_id)
        for resource_id in staged
    }

    app.execute(CancelFounding(project_id))
    assert project.status.value == "cancelled"
    assert not project.inputs_consumed
    assert not any(owner == payload_owner for owner, _location, _resource in sim.inventory.external_occupancy)
    for resource_id, amount in staged.items():
        assert sim.inventory.amount(ids.LUNAR_ORBIT, resource_id) == pytest.approx(
            stock_before_cancel[resource_id] + amount
        )



def test_partial_founding_procurement_becomes_durable_staged_payload_and_cancel_restores_it():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    available = sim.inventory.available(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT)
    if available > 1e-12:
        sim.inventory.consume_allocated(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT, available)
    partial = 0.25
    sim.inventory.add(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT, partial)

    project_id = app.execute(_found_command("Partial Procurement", cell)).created_id
    assert project_id is not None
    app.execute(AdvanceTime(1))
    project = next(row for row in sim.founding.projects.values() if str(row.id) == project_id)
    staged = sim.founding.staged_payload_t(project.id, ids.CONSTRUCTION_EQUIPMENT)
    assert staged == pytest.approx(partial)
    assert not project.inputs_consumed

    project_row = next(
        row for row in app.query(GetProjects(str(ids.LUNAR_ORBIT))).items
        if row.id == project_id
    )
    resource_row = next(
        row for row in project_row.resources
        if row.resource_id == str(ids.CONSTRUCTION_EQUIPMENT)
    )
    requirement = next(
        row for row in sim.founding.project_resource_requirements(project.id)
        if row.resource_id == ids.CONSTRUCTION_EQUIPMENT
    )
    assert resource_row.committed_t == pytest.approx(partial)
    assert resource_row.shortage_t == pytest.approx(requirement.amount_t - partial)

    app.execute(AdvanceTime(3))
    assert sim.founding.staged_payload_t(project.id, ids.CONSTRUCTION_EQUIPMENT) == pytest.approx(staged)
    stock_before_cancel = sim.inventory.amount(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT)
    app.execute(CancelFounding(project_id))
    assert sim.inventory.amount(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT) == pytest.approx(
        stock_before_cancel + staged
    )

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
    displayed_resources = dict(option.resources)
    expected_resources = {
        str(row.resource_id): row.amount_t
        for row in app._simulation.founding.resource_requirements_for(
            ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE,
            ids.REUSABLE_SURFACE_CARGO_LANDER,
        )
    }
    assert displayed_resources == expected_resources
    assert str(ids.PROPELLANT) in displayed_resources
    assert any(code == "survey_knowledge" for code, _detail in option.blockers)


def test_active_founding_save_load_preserves_identity_and_future_transition(tmp_path):
    assert SAVE_SCHEMA_VERSION == 42
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

    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    path = tmp_path / "founding.json"
    save_game(app, path, saved_at=saved_at)
    loaded, _ = load_game(path, build_game_application)
    loaded_project = loaded._simulation.founding.projects[project.id]
    assert loaded_project.new_location_id == generated
    assert capture_state(loaded._simulation) == capture_state(sim)

    elapsed_days = 8
    policy = OfflineProgressPolicy(real_seconds_per_game_day=60.0)
    offline_loaded, offline = load_game(
        path,
        build_game_application,
        now=saved_at + timedelta(seconds=policy.real_seconds_per_game_day * elapsed_days),
        offline_policy=policy,
    )
    app.execute(AdvanceTime(elapsed_days))
    assert offline is not None
    assert offline.advanced_days == elapsed_days
    assert generated in app._simulation.graph.locations
    assert generated in offline_loaded._simulation.graph.locations
    assert capture_state(offline_loaded._simulation) == capture_state(app._simulation)


def test_deploying_founding_save_load_completes_exactly_once(tmp_path):
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    package = _stage_founding_resources(sim)
    project_id = app.execute(_found_command("Persisted Deployment", cell)).created_id
    assert project_id is not None

    app.execute(AdvanceTime(3))
    project = next(p for p in sim.founding.projects.values() if str(p.id) == project_id)
    assert project.status.value == "deploying"
    assert project.new_location_id not in sim.graph.locations
    project_row = next(
        row for row in app.query(GetProjects(str(ids.LUNAR_ORBIT))).items
        if row.id == project_id
    )
    assert project_row.resources
    assert all(row.shortage_t == pytest.approx(0.0) for row in project_row.resources)
    assert all(row.committed_t == pytest.approx(row.required_t) for row in project_row.resources)

    path = tmp_path / "deploying-founding.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    loaded_sim = loaded._simulation
    loaded_project = loaded_sim.founding.projects[project.id]
    assert loaded_project.status.value == "deploying"
    assert loaded_project.new_location_id not in loaded_sim.graph.locations

    loaded.execute(AdvanceTime(3))
    assert loaded_project.status.value == "complete"
    location_id = loaded_project.new_location_id
    assert location_id in loaded_sim.graph.locations
    facilities = loaded_sim.facilities.all_at(location_id)
    assert len(facilities) == len(package.deployed_facilities)
    assert {row.definition_id for row in facilities} == {
        row.facility_def_id for row in package.deployed_facilities
    }
    orbit_routes = [
        route for route_id, route in loaded_sim.transport.routes.items()
        if str(route_id).startswith(DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
        and location_id in {route.origin_id, route.destination_id}
    ]
    assert orbit_routes
    route_ids = {route.id for route in orbit_routes}

    loaded.execute(AdvanceTime(10))
    assert loaded_project.status.value == "complete"
    assert len(loaded_sim.facilities.all_at(location_id)) == len(package.deployed_facilities)
    assert {
        route.id for route_id, route in loaded_sim.transport.routes.items()
        if str(route_id).startswith(DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
        and location_id in {route.origin_id, route.destination_id}
    } == route_ids
