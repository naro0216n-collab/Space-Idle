from __future__ import annotations

from dataclasses import replace

from space_idle import AdvanceTime, GetMovementPlans, GetWorld, build_game_application
from space_idle.api import GameRuntime
from space_idle.content import base_ids as ids
from space_idle.content.base_game import (
    TECH_CISLUNAR_LOGISTICS,
    TECH_LUNAR_PROSPECTING,
    REUSABLE_ORBITAL_CARGO_TUG,
)
from space_idle.simulation import OfflineProgressPolicy
from space_idle.persistence import capture_state


def test_runtime_clock_supports_speed_pause_resume_and_nonconflicting_passive_ticks(tmp_path):
    now = [100.0]
    runtime = GameRuntime(
        factory=build_game_application,
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


def test_runtime_does_not_recredit_runtime_processing_time_as_game_time(tmp_path):
    now = [100.0]
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=tmp_path,
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=10.0),
        clock=lambda: now[0],
    )
    runtime.set_time_control(speed_multiplier=4.0)

    query_many = runtime._app.query_many

    def expensive_projection(queries):
        result = query_many(queries)
        now[0] += 5.0
        return result

    runtime._app.query_many = expensive_projection

    first = runtime.snapshot({"world": GetWorld()})
    second = runtime.snapshot({"world": GetWorld()})

    assert first.data["world"].day == 0
    assert second.data["world"].day == 0

    now[0] += 2.5
    advanced = runtime.snapshot({"world": GetWorld()})
    assert advanced.data["world"].day == 1


def test_positive_transport_duration_rounds_up_to_canonical_day_boundary():
    sim = build_game_application()._simulation
    plan = sim.transport.movement_plan_candidates(ids.LEO, ids.LUNAR_ORBIT)[0]
    base = sim.transport.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG].performance
    performance = replace(base, transit_time_multiplier=0.7)

    assert plan.transit_days * performance.transit_time_multiplier == 3.5
    assert sim.transport.performance_movement_transit_days(plan, performance) == 4


def test_movement_reachability_is_not_directly_gated_by_research_completion():
    app = build_game_application()
    sim = app._simulation
    plan = sim.transport.movement_plan_candidates(ids.LEO, ids.LUNAR_ORBIT)[0]

    before = sim.transport.movement_plan_failures(plan.id, sim.day)
    assert not any(failure.startswith("technology:") for failure in before)

    sim.technology.completed.update({TECH_CISLUNAR_LOGISTICS, TECH_LUNAR_PROSPECTING})
    after = sim.transport.movement_plan_failures(plan.id, sim.day)
    assert after == before

    movement_plan = app.query(GetMovementPlans(movement_plan_id=str(plan.id), include_modes=True)).items[0]
    assert movement_plan.available
    assert movement_plan.service_feasible_now
    assert movement_plan.modes
    assert any(mode.service_feasible for mode in movement_plan.modes)
