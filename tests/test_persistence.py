from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from space_idle import (
    AdvanceTime,
    CreateTransportAllocation,
    DevelopSurfaceCell,
    GetOperationalNode,
    GetResearch,
    GetWorld,
    PauseBuild,
    PauseFacility,
    PauseResearch,
    PauseTransportAllocation,
    ResumeBuild,
    ResumeFacility,
    ResumeResearch,
    ResumeTransportAllocation,
    PlanBuild,
    ProduceVehicle,
    StartResearch,
    StartSurvey,
    SetSupplyPolicy,
    SetTargetStock,
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
from space_idle.supply import SupplyRequirement
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
    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS), priority=4))
    project_id = app.execute(PlanBuild(
        str(LEO), str(ORBITAL_LOGISTICS_NODE),
        sourcing_policy="import_now", import_source_id=str(EARTH),
    )).created_id
    app.execute(SetSupplyPolicy(
        str(LEO), str(ids.MACHINERY), preferred_source_id=str(EARTH),
    ))
    app.execute(SetTargetStock(str(LEO), str(ids.MACHINERY), 1.0, priority=4))
    allocation_id = app.execute(CreateTransportAllocation(
        str(REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO), target_units=1
    )).created_id
    app.execute(AdvanceTime(1))
    assert project_id is not None and allocation_id is not None
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

    app.execute(StartSurvey(str(ids.LUNAR_ORBIT), str(active_key[0]), str(active_key[1]), priority=4))
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


def test_offline_progress_uses_the_same_active_simulation_path_as_normal_time(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    elapsed_days = 3
    policy = OfflineProgressPolicy(real_seconds_per_game_day=1.0, max_game_days_per_resume=20)
    original = _make_nontrivial_state()
    sim = original._simulation

    # Exercise several active domains at once instead of preserving one offline
    # regression test per feature that happened to be added over time.
    for facility in sim.facilities.facilities.values():
        if facility.paused:
            original.execute(ResumeFacility(str(facility.id)))
    for research_id, project in tuple(sim.research.active.items()):
        if project.paused:
            original.execute(ResumeResearch(str(research_id)))
    for project in tuple(sim.projects.projects.values()):
        if project.paused:
            original.execute(ResumeBuild(str(project.id)))
    for allocation in tuple(sim.transport.transport_allocations.values()):
        if allocation.paused:
            original.execute(ResumeTransportAllocation(str(allocation.id)))
    original.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    original.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    ))

    path = tmp_path / "offline-active-domains.json"
    save_game(original, path, saved_at=saved_at)

    offline, result = load_game(
        path, build_game_application,
        now=saved_at + timedelta(seconds=elapsed_days),
        offline_policy=policy,
    )
    direct, _ = load_game(path, build_game_application)
    direct.execute(AdvanceTime(elapsed_days))

    assert result is not None and result.advanced_days == elapsed_days
    assert capture_state(offline._simulation) == capture_state(direct._simulation)
    assert offline.query(GetWorld()).day == direct.query(GetWorld()).day
    assert offline._simulation.boundary_settled_day == offline._simulation.day
    assert direct._simulation.boundary_settled_day == direct._simulation.day


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
    assert allocation_id is not None

    sim.inventory.add(ids.EARTH, ids.MACHINERY, 1.0)
    demand = SupplyRequirement(
        EntityId("demand.persistence"), "test", EntityId("owner.persistence"),
        ids.LEO, ids.MACHINERY, 0.5, 5, ids.EARTH,
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
    partial_resource, required_t = next(
        (resource_id, required_t)
        for resource_id, required_t in definition.production.resources
        if required_t > 0.0
    )
    partial_stock = required_t * 0.5
    sim.inventory.stock[(EARTH, partial_resource)] = partial_stock

    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = EntityId(result.created_id)
    app.execute(AdvanceTime(1))
    state = sim.transport.vehicle_production_projects[production_id]
    remaining_on_hand = sim.inventory.amount(EARTH, partial_resource)
    staged_t = partial_stock - remaining_on_hand
    assert state.phase.value == "awaiting_inputs"
    assert staged_t > 0.0

    path = tmp_path / "vehicle-production-partial.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)

    assert capture_state(loaded._simulation) == capture_state(sim)
    assert loaded._simulation.inventory.amount(
        EARTH, partial_resource
    ) == pytest.approx(remaining_on_hand)


def test_transient_allocation_projection_is_not_persisted_as_authoritative_state(tmp_path):
    app = build_game_application()
    app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim = app._simulation
    before = capture_state(sim)

    decision = sim.tick_decision_projection()
    assert decision.allocations.resources.allocations
    assert capture_state(sim) == before

    path = tmp_path / "transient-allocation.json"
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
