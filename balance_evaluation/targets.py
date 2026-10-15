"""Generic, data-driven acquisition/operation design worksheets.

These *hypotheses* are not game state. They cannot be encoded as Save assets.
Stage evolution is an ordered delta to the preceding worksheet, interpreted
by the same ledger for every stage. Gameplay snapshots live in ``scenarios``.
"""
from __future__ import annotations

import json
from pathlib import Path

from content_balance.ledger import quantity_ledger

TARGETS = Path(__file__).with_name('target_profiles')


def target_profile(stage: int) -> dict:
    if type(stage) is not int or stage < 1:
        raise ValueError('invalid target stage')
    path = TARGETS / f'{stage}.json'
    if not path.exists():
        raise ValueError(f'no design target profile for stage {stage}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['stage'] != stage:
        raise ValueError('mismatched target profile stage')
    if 'parent_stage' not in data:
        if stage != 1:
            raise ValueError('noninitial target profile requires a parent')
        return data
    if data['parent_stage'] >= stage or data['parent_stage'] < 1:
        raise ValueError('invalid target profile predecessor')
    base = target_profile(data['parent_stage'])
    activities = base['activities'].copy()
    # Edit offsets always refer to the previous stage and are applied in reverse.
    last_start = len(activities)
    for op in sorted(data['edits'], key=lambda row: row['start'], reverse=True):
        start, count = op['start'], op['delete']
        if not (0 <= start <= len(activities) and 0 <= count <= len(activities) - start):
            raise ValueError('invalid target profile splice')
        if start + count > last_start:
            raise ValueError('overlapping target edits')
        activities[start:start + count] = op['insert']
        last_start = start
    return {**{k: v for k, v in base.items() if k != 'activities'},
            **{k: v for k, v in data.items() if k not in ('parent_stage', 'edits')},
            'activities': activities}


def _resolved_plans(sim, activities):
    """Re-derive candidate plan references from real Movement rules, not stale IDs."""
    result = []
    resolver = sim.transport.movement_resolver()
    for item in activities:
        activity = dict(item)
        if activity['kind'] in ('movement', 'transport_cycle'):
            origin, destination = activity['origin_context_id'], activity['destination_context_id']
            fwd = resolver.physical_context_plans(origin, destination)
            if not fwd:
                raise ValueError(f'no Movement Plan: {origin} -> {destination}')
            if activity['kind'] == 'movement':
                activity['movement_plan_id'] = str(fwd[0].id)
            else:
                activity['forward_plan_id'] = str(fwd[0].id)
                if sim.transport.vehicle_defs[activity['id']].movement_asset_disposition(fwd[0]).value == 'destination':
                    reverse = resolver.physical_context_plans(destination, origin)
                    if not reverse:
                        raise ValueError(f'no return Movement Plan: {destination} -> {origin}')
                    activity['reverse_plan_id'] = str(reverse[0].id)
        result.append(activity)
    return result


def evaluate_target(sim, stage: int) -> dict:
    case = target_profile(stage)
    activities = _resolved_plans(sim, case['activities'])
    return quantity_ledger(sim, period_days=case['period_days'], activities=activities)
