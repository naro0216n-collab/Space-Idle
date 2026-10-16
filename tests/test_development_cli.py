"""Development instrumentation must observe the same public Application state."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from space_idle.api.codec import ApiPayloadError, decode_query
from space_idle.app_contracts.operations import AdvanceTime
from space_idle.bootstrap import build_game_application, build_game_application_for_load
from space_idle.dev_cli.experiment import PeriodEvidence, compare_experiments, run_experiment
from space_idle.persistence import load_game, save_game


def _state_json(app, path):
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    return json.loads(path.read_text(encoding="utf-8"))["state"]


def test_query_codec_and_canonical_advance_with_unintrusive_trace(tmp_path):
    app = build_game_application()
    seed = tmp_path / "seed.json"
    _state_json(app, seed)
    control, _ = load_game(seed, build_game_application_for_load)
    script = [
        {"action": "query", "type": "GetResearch"},
        {"action": "advance", "days": 2},
        {"action": "state", "scope": {"nodes": ["base.location.earth_industrial"],
                                      "resources": ["base.resource.water"]}},
    ]
    result = run_experiment(app, script)
    control.execute(AdvanceTime(days=2))
    assert "failed_step" not in result
    assert result["end_day"] == 2
    assert result["steps"][1]["result"]["observed_days"] == 2
    assert result["steps"][0]["result"]
    assert result["steps"][2]["result"]["scope"]["operational_node_ids"] == ["base.location.earth_industrial"]
    assert _state_json(app, tmp_path / "observed.json") == _state_json(control, tmp_path / "control.json")
    with pytest.raises(ApiPayloadError):
        decode_query({"type": "GetResearch", "payload": {"nonexistent": 1}})


def test_checkpoint_and_failure_do_not_grant_assets(tmp_path):
    app = build_game_application()
    original = _state_json(app, tmp_path / "start.json")
    result = run_experiment(app, [
        {"action": "checkpoint", "name": "before"},
        {"action": "command", "type": "NoSuchCommand"},
        {"action": "advance", "days": 1},
    ], checkpoint_root=tmp_path / "checkpoints")
    assert result["failed_step"] == 1
    restored, _ = load_game(tmp_path / "checkpoints/before.json", build_game_application_for_load)
    assert _state_json(restored, tmp_path / "restored.json") == original
    assert app.game_day == 0


def test_comparison_requires_same_origin_and_preserves_units():
    metric = {"kind": "inventory_stock", "subject_id": "water", "context_id": "earth",
              "unit": "t", "provenance": "inventory.stock"}
    a = {"content_id": "v", "world_definition_id": "w", "scenario_id": "s", "start_day": 0,
         "end_day": 1, "origin_state_sha256": "stateA",
         "end_state": {"metrics": [{**metric, "quantity": 2.0}]}}
    b = {**a, "end_day": 2, "end_state": {"metrics": [{**metric, "quantity": 3.0}]}}
    out = compare_experiments(a, b)
    assert out["same_start_state"]
    assert out["state_metric_differences"][0]["difference"] == 1.0
    assert compare_experiments(a, {**b, "origin_state_sha256": "stateB"})["same_start_state"] is False


def test_cli_end_to_end_save_replay_and_trace(tmp_path, capsys):
    from space_idle.dev_cli.__main__ import main

    script = tmp_path / "steps.json"
    script.write_text(json.dumps({
        "format": "space-idle.development-experiment.v1",
        "steps": [
            {"action": "command", "type": "SetTimeControl", "payload": {"speed_multiplier": 2}},
            {"action": "advance", "days": 1},
            {"action": "checkpoint", "name": "day1"},
        ],
    }), encoding="utf-8")
    output = tmp_path / "report.json"
    restored = tmp_path / "result_save.json"
    trace = tmp_path / "detail.ndjson"
    assert main(["run", "--script", str(script), "--output", str(output),
                 "--save-out", str(restored), "--trace-file", str(trace),
                 "--checkpoint-dir", str(tmp_path / "points")]) == 0
    report = json.loads(output.read_text())
    assert report["end_day"] == 1
    assert len(report["origin_state_sha256"]) == 64
    assert "actual_settlements" in report["steps"][0]
    assert [json.loads(line)["kind"] for line in trace.read_text().splitlines()] == ["command", "day"]
    reloaded, _ = load_game(restored, build_game_application_for_load)
    assert reloaded.game_day == 1
    assert _state_json(reloaded, tmp_path / "reload.json") == _state_json(
        load_game(tmp_path / "points/day1.json", build_game_application_for_load)[0],
        tmp_path / "point.json")

    next_run = tmp_path / "next.json"
    assert main(["run", "--script", str(script), "--from-save", str(restored),
                 "--output", str(next_run), "--checkpoint-dir", str(tmp_path / "other")]) == 0
    assert json.loads(next_run.read_text())["start_day"] == 1


def test_scenario_factory_uses_canonical_builder():
    from space_idle.dev_cli.__main__ import _authored_scenario
    app = _authored_scenario("space_idle.content.base_scenario:build_standard_scenario_definition")
    assert app.content_id == build_game_application().content_id
    assert app.game_day == 0
    with pytest.raises(ValueError):
        _authored_scenario("not-a-module")
