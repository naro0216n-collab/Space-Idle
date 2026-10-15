"""Scope-controlled views of the same conditional ledger, not balance verdicts.

No allocation, simulated acquisition, global score or inferred Cargo delivery is
performed here. Each view retains the ledger's period, source, units and scope.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .targets import activity_key, available_stages, evaluate_target, target_profile


def _research(ledger: dict) -> list[dict]:
    return [
        {**row, 'sustained_theory_upper_bound_per_day': min(
            row.get('rp_nominal_per_day', 0), row.get('execution_nominal_per_day', 0)
        )}
        for row in ledger['research_by_scope']
    ]


def overview(sim, stages: tuple[int, ...] | None = None) -> dict:
    """Stage-wide context, without manufacturing a comprehensive pass/fail score."""
    selected = stages if stages is not None else available_stages()
    results = []
    for stage in selected:
        profile = target_profile(stage)
        ledger = evaluate_target(sim, stage)
        resources = ledger['resource_by_node']
        services = ledger['service_by_scope']
        results.append({
            'stage': stage,
            'evaluation_period_days': ledger['period_days'],
            'cumulative_pacing_target_hours': profile.get('cumulative_target_hours'),
            'questions': profile.get('questions', []),
            'research_by_scope': _research(ledger),
            'power_by_node': [
                {**row, 'conditional_margin_mw': row.get('nominal_generation_mw', 0)
                 - row.get('nominal_active_load_mw', 0)}
                for row in ledger['power_by_node']
            ],
            'resource_observation': {
                'node_resource_pairs': len(resources),
                'conditional_negative_pairs': sum(row['conditional_difference_t_per_day'] < 0 for row in resources),
                'nodes': sorted(set(row['node'] for row in resources)),
            },
            'service_observation': {
                'scope_service_pairs': len(services),
                'conditional_demand_exceeds_nominal_supply': sum(
                    row['demand_per_day'] > row['nominal_supply_per_day'] for row in services
                ),
            },
            'activity_roles': dict(sorted(Counter(
                row['kind'] for row in profile['activities']).items()
            )),
        })
    return {
        'configured_stages': list(available_stages()),
        'stages': results,
        'interpretation': 'Hypothetical registered-Content coefficients and conditional arithmetic, '
                          'not acquired assets, actual allocation, delivery, timing proof or a balance score. '
                          'Different evaluation windows do not make RP demand/day directly comparable.',
    }


def _matches_measure(measure: dict, category: str, identifier: str | None, node: str | None, source_node: str) -> bool:
    if category == 'resource':
        return (measure.get('measure') == 'resource'
                and (identifier is None or measure.get('resource_id') == identifier)
                and (node is None or measure.get('node') == node))
    if category == 'service':
        return (measure.get('measure') == 'service'
                and (identifier is None or measure.get('service_type') == identifier)
                and (node is None or measure.get('node_or_scope') == node))
    if category == 'power':
        return measure.get('measure') == 'power' and (node is None or source_node == node)
    if category == 'research':
        return measure.get('measure') in (
            'research_provider', 'fleet_research_provider', 'research_stage_work_or_rp'
        )
    raise ValueError('unsupported category')


def inspect(sim, stage: int, category: str, *, identifier: str | None = None,
            node: str | None = None, activity: str | None = None) -> dict:
    """Show the requested totals and the physical contributors to those totals."""
    profile = target_profile(stage)
    ledger = evaluate_target(sim, stage)
    category_rows = {
        'resource': ledger['resource_by_node'],
        'service': ledger['service_by_scope'],
        'research': _research(ledger),
        'power': ledger['power_by_node'],
        'activity': ledger['activity_evidence'],
    }
    if category not in category_rows:
        raise ValueError(f'unsupported inspect category: {category}')
    if category == 'activity':
        matching = [(activity_key(spec), detail) for spec, detail in
                    zip(profile['activities'], ledger['activity_evidence'])
                    if activity is None or activity_key(spec) == activity]
        rows = []
        contributions = [{'activity_key': key, **detail} for key, detail in matching]
    else:
        id_field = {'resource': 'resource_id', 'service': 'service_type',
                    'research': 'scope', 'power': 'node'}[category]
        node_field = {'resource': 'node', 'service': 'node_or_scope',
                      'research': 'scope', 'power': 'node'}[category]
        rows = [row for row in category_rows[category]
                if (identifier is None or str(row[id_field]) == identifier)
                and (node is None or str(row[node_field]) == node)]
        contributions = []
        for spec, detail in zip(profile['activities'], ledger['activity_evidence']):
            evidence = [e for e in detail['evidence']
                        if _matches_measure(e, category, identifier, node, detail['node'])]
            if evidence:
                contributions.append({'activity_key': activity_key(spec),
                                      'source': detail['source'], 'node': detail['node'],
                                      'evidence': evidence})
    return {'stage': stage, 'period_days': ledger['period_days'], 'category': category,
            'identifier': identifier, 'node': node, 'totals': rows, 'contributors': contributions,
            'limits': ledger['limits']}


def _contains_reference(value: Any, identifier: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_reference(v, identifier) or k == identifier for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_reference(v, identifier) for v in value)
    return isinstance(value, str) and value == identifier


def impact(identifier: str, stages: tuple[int, ...] | None = None) -> dict:
    """Locate direct worksheet references; never claim indirect supply-chain effects."""
    chosen = stages if stages is not None else available_stages()
    matches = []
    for stage in chosen:
        profile = target_profile(stage)
        relevant = [{'activity_key': activity_key(row), 'kind': row['kind'],
                     'node': row['node'], 'definition_id': row.get('id')}
                    for row in profile['activities'] if _contains_reference(row, identifier)]
        if relevant:
            matches.append({'stage': stage, 'direct_references': relevant})
    return {'definition_or_resource_id': identifier, 'stage_references': matches,
            'limits': 'Direct authored worksheet references only. This is not a dependency graph, '
                      'proof of indirect effects, optimizer or exhaustive change-impact analysis. '
                      'Re-evaluate shared consumers and adjacent stages when editing Content.'}
