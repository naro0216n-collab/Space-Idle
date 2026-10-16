"""Canonical Space Idle development console, with recorded experiments."""
from __future__ import annotations

import argparse
from importlib import import_module
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from ..bootstrap import (build_game_application, build_game_application_for_load,
                         build_game_application_for_scenario)
from ..scenario import ScenarioDefinition
from ..persistence import load_game, save_game
from .experiment import compare_experiments, run_experiment


def _json_dict(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {x}")))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _origin_digest(app):
    """Fingerprint canonical authoritative State, never wall-clock Save metadata."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "origin.json"
        save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        envelope = _json_dict(path)
    payload = {key: envelope[key] for key in ("content_id", "world_definition_id", "scenario_id", "state")}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _authored_scenario(factory_ref: str):
    """Use the existing validated Scenario bootstrap, not a CLI-specific State codec."""
    module, marker, function = factory_ref.partition(":")
    if not marker or not module or not function or "." in function:
        raise ValueError("scenario factory must be module:function")
    provider = getattr(import_module(module), function)
    scenario = provider()
    if not isinstance(scenario, ScenarioDefinition):
        raise TypeError("scenario factory must return ScenarioDefinition")
    return build_game_application_for_scenario(scenario)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Execute and observe the actual GameApplication for design evaluation")
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run", help="run an authored Command/Query/AdvanceTime experiment")
    run.add_argument("--script", type=Path, required=True)
    source = run.add_mutually_exclusive_group()
    source.add_argument("--from-save", type=Path, help="load a normal game Save; defaults to standard new game")
    source.add_argument("--scenario-factory", help="trusted Python module:function returning a ScenarioDefinition")
    run.add_argument("--save-out", type=Path, help="write final normal game Save")
    run.add_argument("--checkpoint-dir", type=Path)
    run.add_argument("--trace-file", type=Path, help="opt-in complete NDJSON day trace")
    run.add_argument("--output", type=Path, help="complete JSON report; summary otherwise printed to stdout")
    cmp = sub.add_parser("compare", help="compare experiment outcomes with baseline identity")
    cmp.add_argument("--left", type=Path, required=True)
    cmp.add_argument("--right", type=Path, required=True)
    cmp.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "compare":
        result = compare_experiments(_json_dict(args.left), _json_dict(args.right))
    else:
        script = _json_dict(args.script)
        if set(script) != {"format", "steps"} or script["format"] != "space-idle.development-experiment.v1":
            parser.error("unsupported experiment format")
        app = (load_game(args.from_save, build_game_application_for_load)[0]
               if args.from_save else (_authored_scenario(args.scenario_factory)
                                       if args.scenario_factory else build_game_application()))
        origin_fingerprint = _origin_digest(app)
        with ExitStack() as stack:
            trace = None
            if args.trace_file:
                args.trace_file.parent.mkdir(parents=True, exist_ok=True)
                trace = stack.enter_context(args.trace_file.open("x", encoding="utf-8"))
            result = run_experiment(app, script["steps"], trace_file=trace,
                                    checkpoint_root=args.checkpoint_dir)
        result["origin_state_sha256"] = origin_fingerprint
        result["origin_kind"] = ("game_save" if args.from_save else
                                 ("authored_scenario" if args.scenario_factory else "standard_scenario"))
        if args.scenario_factory:
            result["scenario_factory"] = args.scenario_factory
        result["script_sha256"] = sha256(args.script.read_bytes()).hexdigest()
        if args.trace_file:
            result["detail_trace_file"] = str(args.trace_file)
        result["end_state"] = app.observe_development_state().to_json_data()
        if args.save_out and "failed_step" not in result:
            args.save_out.parent.mkdir(parents=True, exist_ok=True)
            save_game(app, args.save_out)
            result["saved_game"] = str(args.save_out)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        summary = ({"result_path": str(args.output), "left_day": result["left"]["end_day"],
                    "right_day": result["right"]["end_day"],
                    "same_start_state": result["same_start_state"]}
                   if args.mode == "compare" else
                   {"result_path": str(args.output), "start_day": result["start_day"],
                    "end_day": result["end_day"], "failed_step": result.get("failed_step")})
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if "failed_step" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
