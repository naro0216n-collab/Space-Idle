from __future__ import annotations

from datetime import datetime, timedelta, timezone

from space_idle import (
    build_game_application,
    AdvanceTime,
    CreateLogisticsRule,
    DispatchVehicle,
    GetLocation,
    GetWorld,
    PauseBuild,
    PauseFacility,
    PauseLogisticsRule,
    PauseResearch,
    PlanBuild,
    ProduceVehicle,
    RefuelVehicle,
    StartResearch,
    SubmitCargo,
)
from space_idle.content.base_game import (
    EARTH,
    EARTH_RESEARCH_LAB,
    LEO,
    ORBITAL_LOGISTICS_NODE,
    PROPELLANT,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    REUSABLE_SURFACE_CARGO_LANDER,
    SOUTH_POLAR_RIDGE,
    MACHINERY,
    TECH_CISLUNAR_LOGISTICS,
    TECH_LUNAR_PROSPECTING,
    TECH_ORBITAL_OPERATIONS,
    WATER,
)
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.simulation import OfflineProgressPolicy
from space_idle.shared import RouteId


def _make_nontrivial_state():
    app = build_game_application()
    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS)))
    project_id = app.execute(PlanBuild(
        str(LEO), str(ORBITAL_LOGISTICS_NODE), sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    rule_id = app.execute(CreateLogisticsRule(
        str(EARTH), str(LEO), str(WATER), target_stock_t=1.0, batch_t=1.0
    )).created_id
    app.execute(AdvanceTime(1))
    assert project_id is not None and rule_id is not None
    lab_id = next(
        row.id for row in app.query(GetLocation(str(EARTH))).facilities
        if row.definition_id == str(EARTH_RESEARCH_LAB)
    )
    app.execute(PauseFacility(lab_id))
    app.execute(PauseResearch(str(TECH_ORBITAL_OPERATIONS)))
    app.execute(PauseBuild(project_id))
    app.execute(PauseLogisticsRule(rule_id))
    tug_state = next(
        state for state in app._simulation.logistics.vehicles.values()
        if state.definition_id == REUSABLE_ORBITAL_CARGO_TUG
    )
    tug_def = app._simulation.logistics.vehicle_defs[tug_state.definition_id]
    # Refueling is an actual infrastructure service in v0.4.2, not a symbolic
    # route permission. Install a provider explicitly for this persistence state.
    app._simulation.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    app._simulation.inventory.add(LEO, PROPELLANT, tug_def.propellant_capacity_t)
    app.execute(RefuelVehicle(str(tug_state.id), tug_def.propellant_capacity_t / 2.0))
    return app


def test_save_load_roundtrip_preserves_state_and_future_behavior(tmp_path):
    app = _make_nontrivial_state()
    path = tmp_path / "game.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    loaded, offline = load_game(path, build_game_application)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    app.execute(AdvanceTime(7))
    loaded.execute(AdvanceTime(7))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)


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


def test_save_load_preserves_active_vehicle_handoff_mission(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.logistics.unlocked_technologies.update(
        {TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS, TECH_LUNAR_PROSPECTING}
    )
    onward_id = sim.logistics.add_vehicle(REUSABLE_SURFACE_CARGO_LANDER, EARTH)
    onward_def = sim.logistics.vehicle_defs[REUSABLE_SURFACE_CARGO_LANDER]
    sim.logistics.vehicles[onward_id].propellant_t = onward_def.propellant_capacity_t

    first = RouteId("base.route.earth_leo")
    second = RouteId("base.route.leo_ridge")
    order_id = app.execute(SubmitCargo(
        str(EARTH), str(SOUTH_POLAR_RIDGE), str(MACHINERY), 1.0, 100,
        (str(first), str(second)),
        ((str(first), str(REUSABLE_LAUNCH_VEHICLE)), (str(second), str(REUSABLE_SURFACE_CARGO_LANDER))),
    )).created_id
    assert order_id is not None
    app.execute(AdvanceTime(1))
    mission = next(iter(sim.logistics.missions.values()))
    assert mission.handoff_vehicle_id == onward_id

    path = tmp_path / "handoff.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(sim)

    app.execute(AdvanceTime(8))
    loaded.execute(AdvanceTime(8))
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_save_load_preserves_vehicle_production_progress(tmp_path):
    app = build_game_application()
    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    vehicle_id = next(vid for vid in app._simulation.logistics.vehicles if str(vid) == result.created_id)
    original = app._simulation.logistics.vehicles[vehicle_id]
    assert original.status == "production"

    path = tmp_path / "vehicle-production.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    # Remaining production time is mutable state. Advancing both simulations
    # through the same normal path must complete the same vehicle on the same day.
    days = max(1, original.available_day - app._simulation.day)
    app.execute(AdvanceTime(days))
    loaded.execute(AdvanceTime(days))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    assert loaded._simulation.logistics.vehicles[vehicle_id].status == "available"


def test_offline_progress_preserves_vehicle_production_state_machine(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=60.0, max_game_days_per_resume=20)
    app = build_game_application()
    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None

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


def test_save_load_and_offline_preserve_maintenance_wait(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=60.0, max_game_days_per_resume=20)
    app = build_game_application()
    sim = app._simulation
    sim.logistics.unlocked_technologies.add(TECH_CISLUNAR_LOGISTICS)
    tug_id = next(
        vid for vid, state in sim.logistics.vehicles.items()
        if state.definition_id == REUSABLE_ORBITAL_CARGO_TUG and state.location_id == LEO
    )
    tug_def = sim.logistics.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG]
    sim.logistics.vehicles[tug_id].propellant_t = tug_def.propellant_capacity_t
    app.execute(DispatchVehicle(str(tug_id), "base.route.leo_lunar_orbit"))
    app.execute(AdvanceTime(5))
    assert sim.logistics.vehicles[tug_id].status == "maintenance_wait"

    path = tmp_path / "maintenance-wait.json"
    save_game(app, path, saved_at=saved_at)
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(sim)

    # Missing servicing infrastructure remains a blocker during offline time;
    # offline progression must not silently complete turnaround.
    offline, _ = load_game(
        path, build_game_application,
        now=saved_at + timedelta(seconds=policy.real_seconds_per_game_day * 3),
        offline_policy=policy,
    )
    direct, _ = load_game(path, build_game_application)
    direct.execute(AdvanceTime(3))
    assert capture_state(offline._simulation) == capture_state(direct._simulation)
    assert offline._simulation.logistics.vehicles[tug_id].status == "maintenance_wait"
