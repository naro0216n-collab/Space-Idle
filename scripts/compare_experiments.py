#!/usr/bin/env python3
"""Run opt-in canonical Simulation comparisons from a JSON Player command plan.

Example plan:
{"days": 2, "cases": [
  {"name": "control", "commands": []},
  {"name": "research", "commands": [
    {"day": 0, "type": "StartResearch", "args": {"research_id": "..."}}
  ]}
]}

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

from space_idle import build_game_application
from scripts.analysis_experiments import (
    ExperimentCase, compare_experiments, run_experiments,
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
    for case in payload["cases"]:
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
            case["name"], build_game_application,
            lambda _app, day, fixed=fixed: fixed.get(day, ()),
        ))
    return days, tuple(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON experiment plan")
    parser.add_argument("--node", action="append", help="Only observe a specified Operational Node")
    parser.add_argument("--resource", action="append", help="Only observe a specified Resource")
    args = parser.parse_args()
    days, cases = parse_cases(json.loads(args.plan.read_text(encoding="utf-8")))
    runs = run_experiments(
        cases, days=days,
        operational_node_ids=(None if args.node is None else frozenset(map(SpatialNodeId, args.node))),
        resource_ids=(None if args.resource is None else frozenset(map(DefinitionId, args.resource))),
    )
    result = {"runs": [run.to_json_data() for run in runs],
              "comparison": compare_experiments(runs)}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    print()


if __name__ == "__main__":
    main()
