from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from space_idle import (
    AdvanceTime,
    CreateLogisticsLane,
    CreateTransportAllocation,
    DevelopSurfaceCell,
    GetOperationalNode,
    GetResearch,
    GetWorld,
    PauseBuild,
    PauseFacility,
    PauseLogisticsLane,
    PauseResearch,
    PauseTransportAllocation,
    PlanBuild,
    ProduceVehicle,
    StartResearch,
    StartSurvey,
    build_game_application,
)
from space_idle.content.base_game import (
    EARTH,
    EARTH_RESEARCH_LAB,
    LEO,
    ORBITAL_LOGISTICS_NODE,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    TECH_ORBITAL_OPERATIONS,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.resource_claim import allocate_resource_claims
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import EntityId, CelestialBodyId, DefinitionId
from space_idle.simulation import OfflineProgressPolicy
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService


def _advance_until_research_startable(app, research_id, max_days=2000):
    for _ in range(max_days + 1):
        row = next(item for item in app.query(GetResearch()).items if item.id == str(research_id))
        if row.can_start:
            return
        app.execute(AdvanceTime(1))
    raise AssertionError(f"research never became startable: {research_id}")


def _make_nontrivial_state():
    app = build_game_application()
    _advance_until_research_startable(app, TECH_ORBITAL_OPERATIONS)
    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS), priority=77))
    project_id = app.execute(PlanBuild(
        str(LEO), str(ORBITAL_LOGISTICS_NODE),
        sourcing_policy="import_now", import_source_id=str(EARTH),
    )).created_id
    lane_id = app.execute(CreateLogisticsLane(
        str(EARTH), str(LEO), requested_capacity_t_per_day=1.0
    )).created_id
    allocation_id = app.execute(CreateTransportAllocation(
        str(REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO), target_units=1
    )).created_id
    app.execute(AdvanceTime(1))
    assert project_id is not None and lane_id is not None and allocation_id is not None
    lab_id = next(
        row.id for row in app.query(GetOperationalNode(str(EARTH))).facilities
        if row.definition_id == str(EARTH_RESEARCH_LAB)
    )
    lab_state = next(
        row for row in app._simulation.facilities.facilities.values()
        if str(row.id) == lab_id
    )
    lab_state.level = 2
    app.execute(PauseFacility(lab_id))
    app.execute(PauseResearch(str(TECH_ORBITAL_OPERATIONS)))
    app.execute(PauseBuild(project_id))
    app.execute(PauseLogisticsLane(lane_id))
    app.execute(PauseTransportAllocation(allocation_id))
    app._simulation.research.knowledge_state.add(ids.EXPERIENCE_TRANSPORT_OPERATIONS, 2.5)
    return app



def _transport_service_allocations(sim, day, plan):
    requests = sim.transport.transport_service_capacity_requests(day, plan.planned_usage)
    locations = sim._active_locations() | set(sim.graph.operational_node_ids())
    powers = {
        location_id: sim.power.snapshot(location_id, sim.facilities, day)
        for location_id in locations
    }
    return sim._allocate_tick_services(powers, requests)

def test_save_load_roundtrip_preserves_state_and_future_behavior(tmp_path):
    app = _make_nontrivial_state()
    path = tmp_path / "game.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    loaded, offline = load_game(path, build_game_application)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    assert loaded.query(GetResearch()) == app.query(GetResearch())

    app.execute(AdvanceTime(7))
    loaded.execute(AdvanceTime(7))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)


def test_save_load_preserves_survey_knowledge_campaign_and_future_behavior(tmp_path):
    app = build_game_application()
    sim = app._simulation
    active_key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.WATER)
    target = sim.survey.targets[active_key]

    app.execute(StartSurvey(str(ids.LUNAR_ORBIT), str(active_key[0]), str(active_key[1]), priority=75))
    sim.survey.knowledge_progress[active_key] = target.thresholds[0] / 2.0
    target_level = sim.survey.campaigns[active_key].target_knowledge_level

    path = tmp_path / "survey-knowledge.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert loaded._simulation.survey.knowledge_progress == sim.survey.knowledge_progress
    assert loaded._simulation.survey.campaigns[active_key].target_knowledge_level == target_level
    assert capture_state(loaded._simulation) == capture_state(sim)

    app.execute(AdvanceTime(7))
    loaded.execute(AdvanceTime(7))
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_offline_progress_is_the_normal_simulation_path(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = saved_at + timedelta(hours=3, minutes=17)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=137.0, max_game_days_per_resume=500)
    original = _make_nontrivial_state()
    path = tmp_path / "game.json"
    save_game(original, path, saved_at=saved_at)

    loaded, result = load_game(path, build_game_application, now=now, offline_policy=policy)
    direct, _ = load_game(path, build_game_application)
    expected = direct._simulation.advance_offline((now - saved_at).total_seconds(), policy)
    assert result == expected
    assert capture_state(loaded._simulation) == capture_state(direct._simulation)
    assert loaded.query(GetWorld()).day == direct.query(GetWorld()).day


def test_offline_progress_matches_normal_ticks_for_active_research(tmp_path):
    app = build_game_application()
    _advance_until_research_startable(app, TECH_ORBITAL_OPERATIONS)
    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS), priority=73))
    path = tmp_path / "active-research.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    direct, _ = load_game(path, build_game_application)
    offline, _ = load_game(path, build_game_application)
    direct._simulation.advance_days(7)
    result = offline._simulation.advance_offline(
        7.0, OfflineProgressPolicy(real_seconds_per_game_day=1.0)
    )

    assert result.advanced_days == 7
    assert capture_state(offline._simulation) == capture_state(direct._simulation)


def test_fractional_offline_time_is_composable():
    app_a = build_game_application()
    app_b = build_game_application()
    policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)
    app_a._simulation.advance_offline(6.0, policy)
    app_a._simulation.advance_offline(6.0, policy)
    app_b._simulation.advance_offline(12.0, policy)
    assert capture_state(app_a._simulation) == capture_state(app_b._simulation)


def test_save_load_preserves_in_flight_cargo_and_rederives_transport_projection(tmp_path):
    app = build_game_application()
    sim = app._simulation
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO), target_units=1
    )).created_id
    lane_id = app.execute(CreateLogisticsLane(
        str(ids.EARTH), str(ids.LEO), 0.5
    )).created_id
    assert allocation_id is not None and lane_id is not None

    sim.inventory.add(ids.EARTH, ids.MACHINERY, 1.0)
    demand = ResourceDemand(
        EntityId("demand.persistence"), "test", EntityId("owner.persistence"),
        ids.LEO, ids.MACHINERY, 0.5, 100, ids.EARTH,
    )
    logistics_plan = sim.logistics.plan_capacity_logistics(sim.day, (demand,))
    funds = sim.external_economy.allocate(logistics_plan.spending_requests, sim.day)
    logistics_plan = sim.logistics.authorize_capacity_logistics(
        logistics_plan, funds, sim.day
    )
    resources = allocate_resource_claims(logistics_plan.claims, sim.inventory)
    services = _transport_service_allocations(sim, sim.day, logistics_plan)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        sim.day, logistics_plan, resources, services
    )
    sim.logistics.advance_capacity_logistics(
        sim.day, logistics_plan, funds, execution,
    )
    assert sim.logistics.cargo_flows

    allocation_entity_id = EntityId(allocation_id)
    before_capacity = sim.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=sim.day
    )
    before_flows = dict(sim.logistics.cargo_flows)

    path = tmp_path / "cargo-flow.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)

    assert loaded._simulation.logistics.cargo_flows == before_flows
    assert loaded._simulation.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=loaded._simulation.day
    ) == before_capacity
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_save_load_preserves_vehicle_production_progress_and_completed_fleet_unit(tmp_path):
    app = build_game_application()
    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = EntityId(result.created_id)
    app.execute(AdvanceTime(1))
    original = app._simulation.transport.vehicle_production_projects[production_id]
    assert original.phase.value == "building"
    assert original.progress_days > 0

    path = tmp_path / "vehicle-production.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    before_units = loaded._simulation.transport.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units
    days = int(app._simulation.transport.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG].production.days)
    app.execute(AdvanceTime(days))
    loaded.execute(AdvanceTime(days))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    state = loaded._simulation.transport.vehicle_production_projects[production_id]
    assert state.phase.value == "complete"
    assert state.completed_units == 1
    assert loaded._simulation.transport.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units == before_units + 1


def test_save_load_preserves_partial_vehicle_production_staging(tmp_path):
    app = build_game_application()
    sim = app._simulation
    definition = sim.transport.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG]
    for resource_id, _required_t in definition.production.resources:
        sim.inventory.stock[(EARTH, resource_id)] = 0.0
    sim.inventory.stock[(EARTH, ids.STRUCTURAL_COMPONENTS)] = 1.0

    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = EntityId(result.created_id)
    app.execute(AdvanceTime(1))
    state = sim.transport.vehicle_production_projects[production_id]
    staged = sim.transport._vehicle_production_staged_t(
        state, ids.STRUCTURAL_COMPONENTS
    )
    assert state.phase.value == "awaiting_inputs"
    assert staged > 0.0

    path = tmp_path / "vehicle-production-partial.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)

    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded_state = loaded._simulation.transport.vehicle_production_projects[production_id]
    assert loaded._simulation.transport._vehicle_production_staged_t(
        loaded_state, ids.STRUCTURAL_COMPONENTS
    ) == staged


def test_offline_progress_preserves_vehicle_production_state_machine(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=60.0, max_game_days_per_resume=20)
    app = build_game_application()
    app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    path = tmp_path / "vehicle-production-offline.json"
    save_game(app, path, saved_at=saved_at)
    elapsed_days = 2
    loaded, _ = load_game(
        path, build_game_application,
        now=saved_at + timedelta(seconds=policy.real_seconds_per_game_day * elapsed_days),
        offline_policy=policy,
    )
    direct, _ = load_game(path, build_game_application)
    direct.execute(AdvanceTime(elapsed_days))
    assert capture_state(loaded._simulation) == capture_state(direct._simulation)


def test_transient_resource_allocations_are_not_saved_or_rebuilt_after_load(tmp_path):
    from space_idle.resource_claim import allocate_resource_claims

    app = build_game_application()
    app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim = app._simulation
    before = capture_state(sim)
    claims = sim._resource_claims()
    allocate_resource_claims(claims, sim.inventory)
    assert capture_state(sim) == before

    path = tmp_path / "transient-resource-allocation.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == before


def test_durable_inventory_reservation_roundtrips(tmp_path):
    app = build_game_application()
    sim = app._simulation
    owner = EntityId("test.durable-reservation")
    resource_id = ids.STRUCTURAL_COMPONENTS
    amount = min(1.0, sim.inventory.available(EARTH, resource_id))
    assert amount > 0.0
    assert sim.inventory.reserve(owner, EARTH, resource_id, amount) == pytest.approx(amount)

    path = tmp_path / "durable-reservation.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)

    assert loaded._simulation.inventory.reserved_for(owner, EARTH, resource_id) == pytest.approx(amount)
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_offline_progress_preserves_surface_cell_development_state_machine(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=60.0, max_game_days_per_resume=30)
    app = build_game_application()
    app._simulation.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    result = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    ))
    assert result.created_id is not None

    path = tmp_path / "surface-development-offline.json"
    save_game(app, path, saved_at=saved_at)
    elapsed_days = 20
    loaded, _ = load_game(
        path, build_game_application,
        now=saved_at + timedelta(seconds=policy.real_seconds_per_game_day * elapsed_days),
        offline_policy=policy,
    )
    direct, _ = load_game(path, build_game_application)
    direct.execute(AdvanceTime(elapsed_days))

    assert capture_state(loaded._simulation) == capture_state(direct._simulation)
    assert ids.EARTH_CELL_COASTAL in loaded._simulation.graph.locations[ids.EARTH].developed_cell_ids


def test_dynamic_environment_overlay_roundtrips_through_game_save(tmp_path):
    body_id = CelestialBodyId(str(ids.EARTH_BODY))
    species = DefinitionId("test.atmosphere.n2")

    def factory():
        app = build_game_application()
        service = TerraformingService({
            body_id: PlanetaryClimateState(body_id, 101325.0, 1.225, 288.0, {species: 1.0})
        })
        app._simulation.environment.overlays.append(TerraformingEnvironmentOverlay(service))
        return app

    app = factory()
    overlay = app._simulation.environment.overlays[-1]
    overlay.service.add_atmosphere(body_id, 250.0, 0.01, species, 0.0, 3.5)
    before = app._simulation.environment.capture_overlay_state()

    path = tmp_path / "dynamic-environment.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, factory)

    assert loaded._simulation.environment.capture_overlay_state() == before
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
