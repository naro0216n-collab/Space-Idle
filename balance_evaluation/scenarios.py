"""State-backed balance scenarios and lossless *game-state* conversion.

A balance scenario's only physical state is the canonical game Save envelope.
The stage label and questions are analyst annotations, not unlocks or assets.
All mutations of physical state belong to GameApplication/owner Domains.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import tempfile
from typing import Any

from space_idle.bootstrap import build_game_application_for_load
from space_idle.persistence import load_game, save_game

FORMAT = "space-idle.balance-evaluation-state.v1"
STAGES = Path(__file__).with_name("stage_snapshots")


@dataclass(frozen=True)
class EvaluationScenario:
    stage: int
    period_days: float
    questions: tuple[str, ...]
    save: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"format": FORMAT, "stage": self.stage,
                "period_days": self.period_days, "questions": list(self.questions),
                "save": self.save}


def _json_load(path: str | Path) -> dict[str, Any]:
    def no_duplicate(pairs):
        row = {}
        for key, value in pairs:
            if key in row:
                raise ValueError(f"duplicate JSON field: {key}")
            row[key] = value
        return row

    def no_nonfinite(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    payload = json.loads(Path(path).read_text(encoding="utf-8"),
                         object_pairs_hook=no_duplicate, parse_constant=no_nonfinite)
    if not isinstance(payload, dict):
        raise ValueError("scenario/save root must be a JSON object")
    return payload


def read_scenario(path: str | Path) -> EvaluationScenario:
    data = _json_load(path)
    if set(data) != {"format", "stage", "period_days", "questions", "save"} or data["format"] != FORMAT:
        raise ValueError("not a supported state-backed balance scenario")
    if type(data["stage"]) is not int or data["stage"] < 1:
        raise ValueError("stage must be a positive integer annotation")
    from math import isfinite
    if type(data["period_days"]) not in (int, float) or not isfinite(data["period_days"]) or data["period_days"] <= 0:
        raise ValueError("period_days must be positive and finite")
    if not isinstance(data["questions"], list) or any(type(q) is not str for q in data["questions"]):
        raise ValueError("questions must be strings")
    if not isinstance(data["save"], dict):
        raise ValueError("scenario save must be an object")
    return EvaluationScenario(data["stage"], data["period_days"], tuple(data["questions"]), data["save"])


def _load_save(path: str | Path):
    # Do not advance offline time when opening an evaluation snapshot.
    app, _ = load_game(path, build_game_application_for_load)
    return app


def _load_payload(payload: dict[str, Any]):
    # Pass through the exact game Save loader. No parallel codecs, no relaxed
    # snapshot validators, and no direct mutation of another Domain's State.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "state.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        app = _load_save(path)
    return app


def app_from_scenario(scenario: EvaluationScenario):
    return _load_payload(scenario.save)


def scenario_from_save(path: str | Path, *, stage: int, period_days: float,
                       questions: tuple[str, ...] = ()) -> EvaluationScenario:
    app = _load_save(path)
    # Canonicalize using the actual Save writer before embedding.
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "canonical.json"
        saved = _json_load(path)["saved_at"]
        save_game(app, target, saved_at=datetime.fromisoformat(saved))
        envelope = _json_load(target)
    scenario = EvaluationScenario(stage, period_days, questions, envelope)
    # Reuse the scenario's regular validation path, including numeric checks.
    with tempfile.TemporaryDirectory() as folder:
        candidate = Path(folder) / "scenario.json"
        candidate.write_text(json.dumps(scenario.as_dict(), allow_nan=False), encoding="utf-8")
        return read_scenario(candidate)


def write_scenario(scenario: EvaluationScenario, path: str | Path) -> None:
    # Validate actual world, Content and state before advertising a scenario.
    app_from_scenario(scenario)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(scenario.as_dict(), ensure_ascii=False, indent=2,
                                 allow_nan=False) + "\n", encoding="utf-8")


def scenario_to_save(scenario: EvaluationScenario, path: str | Path) -> None:
    app = app_from_scenario(scenario)
    timestamp = datetime.fromisoformat(scenario.save["saved_at"])
    save_game(app, path, saved_at=timestamp)
    # An evaluation format must never silently drop or manufacture game state.
    if _json_load(path) != scenario.save:
        Path(path).unlink(missing_ok=True)
        raise ValueError("evaluation snapshot cannot round-trip to canonical game Save")


def stage_scenario(stage: int) -> EvaluationScenario:
    file = STAGES / f"{stage}.json"
    if not file.exists():
        raise ValueError(f"No state snapshot for stage {stage}; import a played Save")
    return read_scenario(file)
