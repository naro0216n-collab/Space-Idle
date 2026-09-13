from __future__ import annotations

from datetime import datetime, timedelta, timezone

from space_idle import GetWorld, SetTimeControl, build_game_application
from space_idle.api import GameRuntime
from space_idle.persistence import load_game, save_game
from space_idle.simulation import OfflineProgressPolicy


def test_application_time_control_is_saved_and_controls_offline_progress(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)

    app = build_game_application()
    app.execute(SetTimeControl(speed_multiplier=2.0))
    path = tmp_path / "running.json"
    save_game(app, path, saved_at=saved_at)

    loaded, result = load_game(
        path,
        build_game_application,
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
        build_game_application,
        now=saved_at + timedelta(hours=1),
        offline_policy=policy,
    )
    assert paused.time_paused is True
    assert paused.time_speed_multiplier == 2.0
    assert paused_result is None
    assert paused.query(GetWorld()).day == 0


def test_runtime_load_uses_saved_timestamp_and_saved_application_time_control(tmp_path):
    wall = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monotonic_clock = [100.0]
    policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=tmp_path,
        offline_policy=policy,
        clock=lambda: monotonic_clock[0],
        utcnow=lambda: wall[0],
    )

    runtime.set_time_control(speed_multiplier=2.0)
    runtime.save("slot")
    runtime.set_time_control(paused=True, speed_multiplier=1.0)

    wall[0] += timedelta(seconds=30)
    result = runtime.load("slot", apply_offline=True)

    session = result.data["session"]
    assert session["time_paused"] is False
    assert session["time_speed_multiplier"] == 2.0
    assert session["day"] == 6
    assert result.data["offline_progress"]["advanced_days"] == 6
