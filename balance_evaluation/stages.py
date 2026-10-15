"""Evaluate a common game-state snapshot; stage is metadata, not a code path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scenarios import (
    app_from_scenario, read_scenario, scenario_from_save, scenario_to_save,
    stage_scenario, write_scenario,
)
from .state_evidence import evaluate_state
from .targets import evaluate_target


def evaluate_scenario(scenario, *, include_target: bool = False) -> dict:
    app = app_from_scenario(scenario)
    result = {
        'stage_label': scenario.stage,
        'sample_window_days': scenario.period_days,
        'questions': scenario.questions,
        'snapshot': evaluate_state(app, period_days=scenario.period_days),
        'scope': ('A stage label does not imply completion or provide unbuilt assets. '
                  'This reports only the imported, game-valid State; proposed acquisitions '
                  'must be performed in the real game before appearing in this snapshot.'),
    }
    if include_target:
        # Authored design hypotheses remain separate from authoritative game state.
        result['design_target_worksheet'] = evaluate_target(app._simulation, scenario.stage)
        result['target_scope'] = ('Hypothetical coefficients only; no Facility, Fleet, '
                                  'Resource or Technology is granted to the saved game State.')
    return result


def evaluate_stage(stage: int) -> dict:
    return evaluate_scenario(stage_scenario(stage), include_target=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Inspect actual game-save state; no stage-specific simulation.')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--stage', type=int, action='append', help='Bundled snapshot label; repeatable')
    selection.add_argument('--scenario', type=Path, help='Read a state-backed evaluation scenario')
    selection.add_argument('--from-save', type=Path, help='Import a genuine game Save as a scenario')
    parser.add_argument('--to-save', type=Path, help='Export selected evaluation scenario to a genuine game Save')
    parser.add_argument('--target', action='store_true', help='Include separate, hypothetical design worksheet')
    parser.add_argument('--output', type=Path, help='Write imported evaluation scenario')
    parser.add_argument('--label-stage', type=int, help='Stage annotation for --from-save (default: 1)')
    parser.add_argument('--period-days', type=float, default=14400,
                        help='Evaluation window annotation for --from-save')
    args = parser.parse_args(argv)
    if args.from_save:
        scenario = scenario_from_save(args.from_save, stage=args.label_stage or 1,
                                      period_days=args.period_days)
        if args.output:
            write_scenario(scenario, args.output)
        elif not args.to_save:
            parser.error('--from-save requires --output or --to-save')
        scenarios = [scenario]
    elif args.scenario:
        scenarios = [read_scenario(args.scenario)]
    else:
        stages = args.stage or [1, 2]
        scenarios = [stage_scenario(stage) for stage in stages]
    if args.to_save:
        if len(scenarios) != 1:
            parser.error('--to-save requires exactly one evaluation scenario')
        scenario_to_save(scenarios[0], args.to_save)
    if not args.output or not args.from_save:
        for scenario in scenarios:
            print(json.dumps(evaluate_scenario(scenario, include_target=args.target or not (args.from_save or args.scenario)),
                             ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
