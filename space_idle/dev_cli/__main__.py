"""Top-down real-play-time Content tuning; no local diagnostic subcommands."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ..bootstrap import build_game_application, build_game_application_for_load
from ..persistence import load_game
from ..app_contracts.queries import GetTransportAllocationPreview
from ..balance.pacing import tune


def _load(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"),
                        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(f"invalid number: {v}")))
    if not isinstance(result, dict):
        raise ValueError("targets must be a JSON object")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Time-first, whole-game Content tuning")
    parser.add_argument("--targets", type=Path, required=True, help="cumulative play-hour milestones and desired outcomes")
    parser.add_argument("--from-save", type=Path, help="optional canonical Save as the initial assets and completed research")
    parser.add_argument("--output", type=Path, help="write complete integrated JSON evaluation")
    args = parser.parse_args(argv)
    app = (load_game(args.from_save, build_game_application_for_load)[0]
           if args.from_save else build_game_application())

    def transport_preview(vehicle, origin, destination, rate):
        return asdict(app.query(GetTransportAllocationPreview(
            vehicle_definition_id=vehicle, source_id=origin, destination_id=destination,
            target_forward_t_per_day=rate, target_reverse_t_per_day=0.0)))

    report = tune(app.balance_definitions(), _load(args.targets), transport_preview=transport_preview)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    summary = {"kind": report["kind"], "report": str(args.output) if args.output else None,
               "milestones": [{"name": stage["name"], "cumulative_hours": stage["target_cumulative_hours"],
                               "required_rp_per_day": stage["research"]["required_generation_and_execution_rp_per_day"],
                               "rp_cost_scale_to_fit_budget": stage["research"]["theory_rp_cost_scale_to_fit_budget"],
                               "generation_capacity_scale_to_meet_time": stage["research"]["generation_capacity_scale_to_meet_time"],
                               "execution_capacity_scale_to_meet_time": stage["research"]["execution_capacity_scale_to_meet_time"],
                               "capital_resources_t": stage["capital_resources_t"],
                               "resource_budget_pressure": [r for r in stage["resource_time_budget"]
                                    if r["authored_available_average_t_per_day"] is not None],
                               "work_per_day_needed": stage["required_average_work_per_day_by_service"],
                               "transport_targets": len(stage["transport_targets"]),
                               "population_targets": stage["population_targets"],
                               "production_targets": [{"resource": p["resource"], "target_t_per_day": p["target_t_per_day"],
                                                       "selected": p["selected"], "alternatives": len(p["options"])}
                                                      for p in stage["production_targets"]],
                               "unresolved_assumptions": stage["unresolved_assumptions"]}
                              for stage in report["milestones"]]}
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
