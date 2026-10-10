#!/usr/bin/env python3
"""Run opt-in canonical Simulation comparisons from a JSON Player command plan.

Example plan:
{"days": 2, "cases": [
  {"name": "control", "commands": []},
  {"name": "research", "commands": [
    {"day": 0, "type": "StartResearch", "args": {"research_id": "..."}}
  ]}
]}

Use ``content_variant`` operations (edit/add/remove) to compare independent
authored Definition sets. Broken references fail during normal Composition.
Commands with primitive JSON parameters work directly. For dynamically adapting
Player policies or advanced typed Command arguments, use the Python experiment
API rather than introducing a separate script-side eligibility engine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from space_idle.bootstrap import build_game_application_for_scenario
from space_idle.content.base_scenario import build_standard_scenario_definition
from scripts.analysis_variants import scenario_variant, apply_content_variant
from scripts.analysis_experiments import (
    ExperimentCase, ParetoObjective, compare_pareto, compare_experiments, run_experiments,
)
from space_idle.application_commands import AdvanceTime, Command
from space_idle.shared import DefinitionId, SpatialNodeId

COMMAND_TYPES = {
    command.__name__: command
    for command in get_args(Command)
    if command is not AdvanceTime
}


def parse_cases(payload: dict) -> tuple[int, tuple[ExperimentCase, ...]]:
    days = payload["days"]
    if type(days) is not int or days < 0:
        raise ValueError("days must be a nonnegative integer")
    cases = []
    base_scenario = build_standard_scenario_definition()
    for case in payload["cases"]:
        scenario = scenario_variant(base_scenario, case.get("scenario_variant", {}))
        edits = tuple(case.get("content_variant", ()))
        if not isinstance(edits, tuple) or any(not isinstance(row, dict) for row in edits):
            raise ValueError("content_variant must be a list of typed Definition edits")

        def compose_case(scenario=scenario, edits=edits):
            return build_game_application_for_scenario(
                scenario, definition_transform=(
                    (lambda simulation, catalog: apply_content_variant(simulation, catalog, edits))
                    if edits else None
                ),
            )
        day_commands: dict[int, list[Command]] = {}
        for row in case["commands"]:
            day = row["day"]
            if type(day) is not int or not 0 <= day < days:
                raise ValueError("command day outside experiment horizon")
            command_type = COMMAND_TYPES.get(row["type"])
            if command_type is None:
                raise ValueError(f"unknown or unsupported Player Command: {row['type']}")
            arguments = row.get("args", {})
            if not isinstance(arguments, dict) or any(not isinstance(value, (str, float, int, bool, type(None)))
                                                      for value in arguments.values()):
                raise ValueError("CLI command arguments must be primitive JSON values; use Python for typed arguments")
            day_commands.setdefault(day, []).append(command_type(**arguments))
        fixed = {day: tuple(commands) for day, commands in day_commands.items()}
        cases.append(ExperimentCase(
            case["name"], compose_case,
            lambda _app, day, fixed=fixed: fixed.get(day, ()),
        ))
    return days, tuple(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON experiment plan")
    parser.add_argument("--node", action="append", help="Only observe a specified Operational Node")
    parser.add_argument("--resource", action="append", help="Only observe a specified Resource")
    parser.add_argument("--decisions", action="store_true",
                        help="Opt-in snapshots of Application eligibility at each observed day")
    parser.add_argument("--founding-target", action="append", metavar="BODY:CONTEXT",
                        help="With --decisions: query a specific non-surface Founding context")
    parser.add_argument("--surface-cell", action="append", metavar="BODY:CELL",
                        help="With --decisions: query a specific Surface founding/development Cell")
    parser.add_argument("--transport-pair", action="append", metavar="ORIGIN:DESTINATION",
                        help="With --decisions: query a Transport Allocation OD")
    args = parser.parse_args()
    if not args.decisions and (args.founding_target or args.surface_cell or args.transport_pair):
        parser.error("--founding-target, --surface-cell and --transport-pair require --decisions")
    def pairs(values, flag):
        rows = []
        for value in values or ():
            lhs, delimiter, rhs = value.partition(":")
            if not delimiter or not lhs or not rhs:
                parser.error(f"{flag} needs two IDs separated by :")
            rows.append((lhs, rhs))
        return tuple(rows)
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    days, cases = parse_cases(payload)
    runs = run_experiments(
        cases, days=days,
        operational_node_ids=(None if args.node is None else frozenset(map(SpatialNodeId, args.node))),
        resource_ids=(None if args.resource is None else frozenset(map(DefinitionId, args.resource))),
        observe_decisions=args.decisions,
        founding_targets=pairs(args.founding_target, "--founding-target"),
        surface_cells=pairs(args.surface_cell, "--surface-cell"),
        transport_pairs=pairs(args.transport_pair, "--transport-pair"),
    )
    result = {"runs": [run.to_json_data() for run in runs],
              "comparison": compare_experiments(runs)}
    if "objectives" in payload:
        result["pareto"] = compare_pareto(
            runs, tuple(ParetoObjective(**row) for row in payload["objectives"]),
        )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    print()


if __name__ == "__main__":
    main()
