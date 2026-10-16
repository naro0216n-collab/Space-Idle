"""Balance-design console: Content totals, authored scale evaluation, contributor drilldown.

Not an interactive Command/Query runner, replay harness, or second Simulation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ..bootstrap import build_game_application, build_game_application_for_load
from ..persistence import load_game
from ..app_contracts.queries import GetTransportAllocationPreview
from ..balance.analysis import overview, evaluate, inspect


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=lambda item: (_ for _ in ()).throw(ValueError(f"invalid JSON number: {item}")))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _app(source: Path | None):
    return load_game(source, build_game_application_for_load)[0] if source else build_game_application()


def _transport_preview(app):
    def preview(vehicle, origin, destination, tonnes_per_day):
        row = app.query(GetTransportAllocationPreview(
            vehicle_definition_id=vehicle, source_id=origin, destination_id=destination,
            target_forward_t_per_day=tonnes_per_day, target_reverse_t_per_day=0.0))
        return asdict(row)
    return preview


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Space Idle cross-domain Content balance analysis")
    sub = parser.add_subparsers(dest="mode", required=True)
    show = sub.add_parser("overview", help="All registered Content quantities across research generations")
    show.add_argument("--from-save", type=Path, help="optional canonical Save (default: standard scenario)")
    show.add_argument("--output", type=Path, help="complete JSON report (stdout prints summary)")
    evaluation = sub.add_parser("evaluate", help="Capital and daily quantities for authored development scales")
    evaluation.add_argument("--assessment", type=Path, required=True, help="JSON scale hypothesis, not a Command script")
    evaluation.add_argument("--from-save", type=Path, help="optional canonical Save as base asset state")
    evaluation.add_argument("--output", type=Path, help="complete JSON report (stdout prints summary)")
    drilldown = sub.add_parser("inspect", help="Show contributors from an existing balance report")
    drilldown.add_argument("--report", type=Path, required=True)
    for name in ("resource", "facility", "vehicle", "research", "node", "period"):
        drilldown.add_argument("--" + name)
    drilldown.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "inspect":
        result = inspect(_load(args.report), **{
            name: getattr(args, name) for name in ("resource", "facility", "vehicle", "research", "node", "period")
        })
    else:
        app = _app(args.from_save)
        definitions = app.balance_definitions()
        if args.mode == "overview":
            result = overview(definitions)
        else:
            result = evaluate(definitions, _load(args.assessment), current=app.balance_current(),
                              transport_preview=_transport_preview(app), power_site=app.balance_site_power)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        summary = {"kind": result["kind"], "report": str(args.output)}
        if args.mode == "overview":
            summary["counts"] = result["counts"]
            summary["research_stage_costs"] = {k: {"research_count": row["count"],
                "theory_rp": row["theory_rp"], "prototype_work": row["prototype_work"],
                "demonstration_work": row["demonstration_work"]}
                for k, row in result["research_by_stage"].items()}
        if args.mode == "evaluate":
            summary["periods"] = [{"name": row["name"], "period_days": row["period_days"],
                "selected_research_theory_rp": row["research"]["theory_rp_total"],
                "investments": row["investment_by_resource"],
                "nominal_local_gaps": sorted(
                    (item for item in row["partial_local_nominal_balance"] if item["local_nominal_gap_t_per_day"] > 0),
                    key=lambda item: -item["local_nominal_gap_t_per_day"])[:12],
                "unresolved_conditions": len(row["caveats"])} for row in result["periods"]]
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    else:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
