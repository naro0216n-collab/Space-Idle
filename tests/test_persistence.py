from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from space_idle import (
    AdvanceTime,
    AssignExplorationFleet,
    CreateLogisticsLane,
    CreateTransportAllocation,
    GetLocation,
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
    StartScientificExploration,
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
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import EntityId
from space_idle.simulation import OfflineProgressPolicy


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
    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS)))
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
        row.id for row in app.query(GetLocation(str(EARTH))).facilities
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
    return app


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


def test_save_load_preserves_survey_knowledge_separately_from_active_campaign(tmp_path):
    app = build_game_application()
    sim = app._simulation
    active_key = (ids.SOUTH_POLAR_RIDGE, ids.WATER)
    known_key = (ids.EARTH, ids.WATER)
    target = sim.survey.targets[active_key]

    app.execute(StartSurvey(str(active_key[0]), str(active_key[1]), allocation_weight=0.75))
    sim.survey.knowledge_progress[active_key] = target.thresholds[0] / 2.0
    assert known_key not in sim.survey.campaigns

    path = tmp_path / "survey-knowledge.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert loaded._simulation.survey.knowledge_progress == sim.survey.knowledge_progress
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


def test_fractional_offline_time_is_composable():
    app_a = build_game_application()
    app_b = build_game_application()
    policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)
    app_a._simulation.advance_offline(6.0, policy)
    app_a._simulation.advance_offline(6.0, policy)
    app_b._simulation.advance_offline(12.0, policy)
    assert capture_state(app_a._simulation) == capture_state(app_b._simulation)


def test_fleet_allocation_exploration_relocation_and_cargo_flow_roundtrip(tmp_path):
    app = build_game_application()
    sim = app._simulation
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO), target_units=1
    )).created_id
    lane_id = app.execute(CreateLogisticsLane(
        str(ids.EARTH), str(ids.LEO), 0.5
    )).created_id
    assert allocation_id is not None and lane_id is not None

    # Create a real ordinary Cargo Flow through the sustained-capacity path.
    sim.inventory.add(ids.EARTH, ids.MACHINERY, 1.0)
    demand = ResourceDemand(
        EntityId("demand.persistence"), "test", EntityId("owner.persistence"),
        ids.LEO, ids.MACHINERY, 0.5, 100, ids.EARTH, 0.0,
    )
    sim.logistics.advance_capacity_logistics(sim.day, (demand,))
    assert sim.logistics.cargo_flows

    # Exploration reservation uses another LEO Fleet pool while cargo remains in flight.
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 10.0)
    relocation_id = sim.logistics.relocate_fleet(
        ids.REUSABLE_SURFACE_CARGO_LANDER, 1, ids.LEO, ids.LUNAR_ORBIT, day=sim.day
    )
    allocation_entity_id = EntityId(allocation_id)
    lane_entity_id = EntityId(lane_id)
    before_plan = sim.logistics.derive_transport_service_plan(allocation_entity_id, sim.day)
    before_capacity = sim.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=sim.day
    )
    before_lane = next(
        row
        for row in sim.logistics.lane_snapshot((demand,), day=sim.day).lanes
        if row.lane_id == lane_entity_id
    )
    assert before_capacity.used.forward_t_per_day == 0.5
    assert before_lane.used_t == 0.5

    path = tmp_path / "fleet-state.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    payload = json.loads(path.read_text(encoding="utf-8"))
    logistics = payload["state"]["logistics"]
    assert "service_plans" not in logistics
    assert "transport_capacity" not in logistics
    assert "vehicles" not in logistics

    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert relocation_id in loaded._simulation.logistics.fleet_relocations
    after_plan = loaded._simulation.logistics.derive_transport_service_plan(
        allocation_entity_id, loaded._simulation.day
    )
    after_capacity = loaded._simulation.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=loaded._simulation.day
    )
    after_lane = next(
        row
        for row in loaded._simulation.logistics.lane_snapshot(
            (demand,), day=loaded._simulation.day
        ).lanes
        if row.lane_id == lane_entity_id
    )
    assert after_plan == before_plan
    assert after_capacity == before_capacity
    assert after_lane == before_lane


def test_save_load_preserves_vehicle_production_progress_and_completed_fleet_unit(tmp_path):
    app = build_game_application()
    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = EntityId(result.created_id)
    app.execute(AdvanceTime(1))
    original = app._simulation.logistics.vehicle_production_projects[production_id]
    assert original.phase.value == "building"
    assert original.progress_days > 0

    path = tmp_path / "vehicle-production.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    before_units = loaded._simulation.logistics.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units
    days = int(app._simulation.logistics.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG].production.days)
    app.execute(AdvanceTime(days))
    loaded.execute(AdvanceTime(days))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    state = loaded._simulation.logistics.vehicle_production_projects[production_id]
    assert state.phase.value == "complete"
    assert state.completed_units == 1
    assert loaded._simulation.logistics.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units == before_units + 1


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


def test_resource_demand_reservations_are_derived_and_rebuilt_after_load(tmp_path):
    app = build_game_application()
    app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim = app._simulation
    assert sim.inventory.reserved
    expected_reservations = dict(sim.inventory.reserved)
    captured = capture_state(sim)
    assert "reserved" not in captured["inventory"]

    path = tmp_path / "derived-reservations.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert loaded._simulation.inventory.reserved == expected_reservations
    assert capture_state(loaded._simulation) == captured
