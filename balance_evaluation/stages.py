"""CLI and shared evaluation entrypoints; stages do not create game assets."""
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
    """One CLI for whole-system overview, focused evidence and real Save state."""
    from .reporting import overview, inspect, impact
    from .targets import available_stages

    parser = argparse.ArgumentParser(description='Content-design evidence, not a balance pass/fail checker.')
    actions = parser.add_subparsers(dest='action', required=True)
    broad = actions.add_parser('overview', help='Compact cross-stage conditional quantities')
    broad.add_argument('--stage', type=int, action='append', help='Stage filter; default all authored profiles')
    focus = actions.add_parser('inspect', help='Drill into stage totals and owned-Definition evidence')
    focus.add_argument('--stage', type=int, required=True)
    focus.add_argument('--kind', choices=('resource', 'service', 'power', 'research', 'activity'), required=True)
    focus.add_argument('--id', help='Resource ID, service type, or research scope')
    focus.add_argument('--node', help='Node or scope filter')
    focus.add_argument('--activity-key', help='Stable activity key (with --kind activity)')
    influence = actions.add_parser('impact', help='Identify direct stage worksheet references to Content ID')
    influence.add_argument('--id', required=True)
    influence.add_argument('--stage', type=int, action='append')
    state = actions.add_parser('state', help='Evaluate a real Save or translate it without granting assets')
    source = state.add_mutually_exclusive_group(required=True)
    source.add_argument('--stage', type=int, help='Bundled real State snapshot label')
    source.add_argument('--scenario', type=Path, help='Read state-backed evaluation scenario')
    source.add_argument('--from-save', type=Path, help='Import genuine game Save as evaluation scenario')
    state.add_argument('--to-save', type=Path, help='Export selected scenario as genuine game Save')
    state.add_argument('--target', action='store_true', help='Include separate hypothetical worksheet')
    state.add_argument('--details', action='store_true', help='Include underlying per-activity evidence')
    state.add_argument('--output', type=Path, help='Write imported scenario to this path')
    state.add_argument('--label-stage', type=int, default=1, help='Stage annotation for --from-save')
    state.add_argument('--period-days', type=float, default=14400, help='Evaluation period for --from-save')
    args = parser.parse_args(argv)
    if args.action == 'impact':
        result = impact(args.id, tuple(args.stage) if args.stage else None)
    elif args.action in ('overview', 'inspect'):
        # Static design quantities rely on real owned Definition and physical
        # rules, not on artificial stage-completed game states.
        app = app_from_scenario(stage_scenario(available_stages()[0]))
        sim = app._simulation
        if args.action == 'overview':
            result = overview(sim, tuple(args.stage) if args.stage else None)
        else:
            if args.activity_key and args.kind != 'activity':
                parser.error('--activity-key requires --kind activity')
            result = inspect(sim, args.stage, args.kind, identifier=args.id,
                             node=args.node, activity=args.activity_key)
    else:
        if args.from_save:
            scenario = scenario_from_save(args.from_save, stage=args.label_stage,
                                          period_days=args.period_days)
            if args.output:
                write_scenario(scenario, args.output)
            elif not args.to_save:
                parser.error('--from-save requires --output or --to-save')
        else:
            if args.output:
                parser.error('--output is only available with --from-save')
            scenario = read_scenario(args.scenario) if args.scenario else stage_scenario(args.stage)
        if args.to_save:
            scenario_to_save(scenario, args.to_save)
        result = evaluate_scenario(scenario, include_target=args.target)
        if not args.details:
            result['snapshot'].pop('asset_evidence', None)
            if args.target:
                result['design_target_worksheet'].pop('activity_evidence', None)
            result['detail_option'] = 'state --details preserves all per-activity evidence'
        if args.output and args.from_save:
            result['written_scenario'] = str(args.output)
        if args.to_save:
            result['written_save'] = str(args.to_save)
    print(json.dumps(result, ensure_ascii=False, default=str, separators=(',', ':')))


if __name__ == '__main__':
    main()
