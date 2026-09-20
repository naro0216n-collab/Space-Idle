from __future__ import annotations

from datetime import datetime, timedelta, timezone

from space_idle import AdvanceTime, GetMovementPlans, GetWorld, SetTimeControl, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import GameRuntime
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy
from space_idle.persistence import capture_state, load_game, save_game


def test_time_control_persists_and_drives_direct_and_runtime_offline_progress(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)

    app = build_game_application()
    app.execute(SetTimeControl(speed_multiplier=2.0))
    path = tmp_path / "running.json"
    save_game(app, path, saved_at=saved_at)
    loaded, result = load_game(
        path,
        build_game_application_for_load,
        now=saved_at + timedelta(seconds=20),
        offline_policy=policy,
    )
    assert loaded.time_paused is False
    assert loaded.time_speed_multiplier == 2.0
    assert result is not None and result.advanced_days == 4
    assert loaded.query(GetWorld()).day == 4

    app.execute(SetTimeControl(paused=True))
    paused_path = tmp_path / "paused.json"
    save_game(app, paused_path, saved_at=saved_at)
    paused, paused_result = load_game(
        paused_path,
        build_game_application_for_load,
        now=saved_at + timedelta(hours=1),
        offline_policy=policy,
    )
    assert paused.time_paused is True
    assert paused.time_speed_multiplier == 2.0
    assert paused_result is None
    assert paused.query(GetWorld()).day == 0

    wall = [saved_at]
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=tmp_path,
        offline_policy=policy,
        clock=lambda: 100.0,
        utcnow=lambda: wall[0],
    )
    runtime.set_time_control(speed_multiplier=2.0)
    runtime.save("slot")
    runtime.set_time_control(paused=True, speed_multiplier=1.0)
    wall[0] += timedelta(seconds=30)
    runtime_result = runtime.load("slot", apply_offline=True)

    session = runtime_result.data["session"]
    assert session["time_paused"] is False
    assert session["time_speed_multiplier"] == 2.0
    assert session["day"] == 6
    assert runtime_result.data["offline_progress"]["advanced_days"] == 6

    # Fractional wall time is accumulated by the same canonical-day policy;
    # splitting resume intervals must not change the resulting simulation state.
    fractional_a = build_game_application()
    fractional_b = build_game_application()
    fractional_a._simulation.advance_offline(6.0, policy)
    fractional_a._simulation.advance_offline(6.0, policy)
    fractional_b._simulation.advance_offline(12.0, policy)
    assert capture_state(fractional_a._simulation) == capture_state(fractional_b._simulation)


def test_runtime_clock_supports_speed_pause_resume_and_nonconflicting_passive_ticks(tmp_path):
    now = [100.0]
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=tmp_path,
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=10.0),
        clock=lambda: now[0],
    )

    assert runtime.metadata()["day"] == 0
    assert runtime.revision == 0

    runtime.set_time_control(speed_multiplier=4.0)
    assert runtime.revision == 1
    now[0] += 5.0
    clock_result = runtime.query(GetWorld())
    assert clock_result.data.day == 2
    assert clock_result.revision == 2
    expected = build_game_application()
    expected.execute(AdvanceTime(2))
    assert capture_state(runtime._app._simulation) == capture_state(expected._simulation)
    assert runtime._app._simulation.boundary_settled_day == runtime._app._simulation.day

    # Revision 1 is stale only because the automatic clock advanced. It remains
    # valid for optimistic command concurrency because no other explicit player
    # mutation occurred in between.
    accepted = runtime.execute(AdvanceTime(0), expected_revision=1)
    assert accepted.revision == 3

    runtime.set_time_control(paused=True)
    paused_revision = runtime.revision
    now[0] += 100.0
    assert runtime.query(GetWorld()).data.day == 2
    assert runtime.revision == paused_revision

    runtime.set_time_control(paused=False, speed_multiplier=1.0)
    resumed_revision = runtime.revision
    now[0] += 10.0
    assert runtime.query(GetWorld()).data.day == 3
    assert runtime.revision == resumed_revision + 1
    expected.execute(AdvanceTime(1))
    assert capture_state(runtime._app._simulation) == capture_state(expected._simulation)
    assert runtime._app._simulation.boundary_settled_day == runtime._app._simulation.day

    runtime.set_time_control(speed_multiplier=4.0)
    query_many = runtime._app.query_many

    def projection_with_elapsed_wall_time(queries):
        result = query_many(queries)
        now[0] += 5.0
        return result

    runtime._app.query_many = projection_with_elapsed_wall_time
    day_before_projection = runtime._app._simulation.day
    first = runtime.snapshot({"world": GetWorld()})
    second = runtime.snapshot({"world": GetWorld()})

    assert first.data["world"].day == day_before_projection
    assert second.data["world"].day == day_before_projection + 2


def test_movement_reachability_depends_on_physical_state_not_technology_completion_state():
    app = build_game_application()
    sim = app._simulation
    plan = min(sim.transport.movement_plan_candidates(ids.LEO, ids.LUNAR_ORBIT), key=lambda row: str(row.id))

    prior_technology_state = set(sim.technology.completed)
    sim.technology.replace(set())
    without_completed_research = sim.transport.movement_plan_failures(plan.id, sim.day)

    sim.technology.replace(set(sim.research.definitions))
    with_all_research_completed = sim.transport.movement_plan_failures(plan.id, sim.day)
    assert with_all_research_completed == without_completed_research

    movement_plan = app.query(GetMovementPlans(movement_plan_id=str(plan.id), include_modes=True)).items[0]
    assert movement_plan.available
    assert movement_plan.service_feasible_now
    assert movement_plan.modes
    assert any(mode.service_feasible for mode in movement_plan.modes)
    sim.technology.replace(prior_technology_state)
