"""Generic, data-driven acquisition/operation design worksheets.

These *hypotheses* are not game state. They cannot be encoded as Save assets.
Stage evolution uses semantic activity keys to patch the preceding worksheet, interpreted
by the same ledger for every stage. Gameplay snapshots live in ``scenarios``.
"""
from __future__ import annotations

import json
from pathlib import Path

from content_balance.ledger import quantity_ledger

TARGETS = Path(__file__).with_name('target_profiles')


# Stable activity identity is derived from the activity's physical role, not its
# position in a stage profile. `instance` distinguishes genuinely parallel
# activities with otherwise identical identities when necessary.
IDENTITY_FIELDS = (
    'kind', 'node', 'id', 'stage_id', 'portfolio', 'vehicle_id',
    'origin_context_id', 'destination_context_id', 'target_context_id', 'instance',
)


def activity_key(activity: dict) -> str:
    return '|'.join(str(activity.get(field, '')) for field in IDENTITY_FIELDS)


def _indexed(activities: list[dict]) -> dict[str, dict]:
    result = {}
    for activity in activities:
        key = activity_key(activity)
        if key in result:
            raise ValueError(f'duplicate balance activity identity: {key}')
        result[key] = activity
    return result


def available_stages() -> tuple[int, ...]:
    return tuple(sorted(int(p.stem) for p in TARGETS.glob('[0-9]*.json') if p.stem.isdecimal()))


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
        _indexed(data['activities'])
        return data
    if data['parent_stage'] >= stage or data['parent_stage'] < 1:
        raise ValueError('invalid target profile predecessor')
    base = target_profile(data['parent_stage'])
    indexed = _indexed(base['activities'])
    changes = data['changes']
    seen = set()
    for change in changes:
        key = change['key']
        if key in seen or key not in indexed:
            raise ValueError(f'duplicate or unknown activity change: {key}')
        seen.add(key)
        replacement = change['activity']
        if replacement is None:
            del indexed[key]
        else:
            if activity_key(replacement) != key:
                raise ValueError(f'activity identity changed; remove and add instead: {key}')
            indexed[key] = replacement
    for item in data['additions']:
        key = activity_key(item)
        if key in indexed or key in seen:
            raise ValueError(f'activity already present: {key}')
        indexed[key] = item
    return {**{k: v for k, v in base.items() if k != 'activities'},
            **{k: v for k, v in data.items() if k not in ('parent_stage', 'changes', 'additions')},
            'activities': list(indexed.values())}


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
