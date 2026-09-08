from __future__ import annotations

from space_idle import AdvanceTime, GetRoutes, GetWorld, build_game_application
from space_idle.api import GameRuntime
from space_idle.content.base_game import (
    TECH_CISLUNAR_LOGISTICS,
    TECH_LUNAR_PROSPECTING,
)
from space_idle.shared import RouteId
from space_idle.simulation import OfflineProgressPolicy


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


def test_route_reachability_is_not_directly_gated_by_research_completion():
    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.leo_lunar_orbit")

    before = sim.logistics.route_failures(route_id, sim.day)
    assert not any(failure.startswith("technology:") for failure in before)

    sim.technology.completed.update({TECH_CISLUNAR_LOGISTICS, TECH_LUNAR_PROSPECTING})
    after = sim.logistics.route_failures(route_id, sim.day)
    assert after == before

    route = app.query(GetRoutes(route_id=str(route_id), include_modes=True)).items[0]
    assert route.available
    assert route.usable_now
    assert route.modes
    assert any(mode.usable_now for mode in route.modes)
