"""CLI projection checks: references and numbers, not balancing outcomes."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from balance_evaluation.reporting import overview, inspect, impact
from balance_evaluation.scenarios import stage_scenario, app_from_scenario
from balance_evaluation.targets import activity_key, evaluate_target, target_profile
from space_idle.persistence import capture_state


def _sim():
    return app_from_scenario(stage_scenario(1))._simulation


def test_keyed_profile_changes_survive_parent_reordering(monkeypatch):
    import balance_evaluation.targets as targets
    original = targets.target_profile
    baseline = original(2)
    parent = original(1)

    # The second profile must not depend on source-list positions.
    def reordered(stage):
        if stage == 1:
            return {**parent, 'activities': list(reversed(parent['activities']))}
        return original(stage)

    monkeypatch.setattr(targets, 'target_profile', reordered)
    changed = targets.target_profile(2)
    assert {activity_key(a): a for a in baseline['activities']} == {
        activity_key(a): a for a in changed['activities']
    }
    assert len(set(activity_key(a) for a in changed['activities'])) == len(changed['activities'])


def test_stage_delta_rejects_unknown_key_or_mutated_identity(monkeypatch, tmp_path):
    import balance_evaluation.targets as targets
    raw = json.loads((targets.TARGETS / '2.json').read_text())
    raw['changes'][0]['key'] = 'not-an-existing-activity'
    (tmp_path / '2.json').write_text(json.dumps(raw))
    (tmp_path / '1.json').write_text((targets.TARGETS / '1.json').read_text())
    monkeypatch.setattr(targets, 'TARGETS', tmp_path)
    with pytest.raises(ValueError, match='unknown activity'):
        target_profile(2)


def test_overview_matches_real_owned_ledger_and_does_not_mutate_state():
    sim = _sim()
    before = capture_state(sim)
    result = overview(sim)
    assert result['configured_stages'] == [1, 2]
    for row in result['stages']:
        physical = evaluate_target(sim, row['stage'])
        assert row['research_by_scope'][0]['rp_nominal_per_day'] == physical['research_by_scope'][0]['rp_nominal_per_day']
        assert row['research_by_scope'][0]['execution_nominal_per_day'] == physical['research_by_scope'][0]['execution_nominal_per_day']
        assert row['resource_observation']['node_resource_pairs'] == len(physical['resource_by_node'])
        assert row['service_observation']['scope_service_pairs'] == len(physical['service_by_scope'])
    assert capture_state(sim) == before


def test_inspect_resource_and_power_retain_matching_provenance():
    sim = _sim()
    resource = 'base.resource.chemical_propellant'
    result = inspect(sim, 2, 'resource', identifier=resource)
    assert result['totals'] and result['contributors']
    for contributor in result['contributors']:
        assert all(e['resource_id'] == resource for e in contributor['evidence'])
    for total in result['totals']:
        contribution = [e for row in result['contributors'] for e in row['evidence']
                        if e['node'] == total['node']]
        assert sum(e['mean_t_per_day'] for e in contribution if e['direction'] == 'supply') == pytest.approx(total['supply_t_per_day'])
        assert sum(e['mean_t_per_day'] for e in contribution if e['direction'] == 'demand') == pytest.approx(total['demand_t_per_day'])
    node = 'base.node.low_earth_orbit'
    power = inspect(sim, 2, 'power', node=node)
    assert power['totals'] and power['contributors']
    assert all(row['node'] == node for row in power['contributors'])


def test_impact_counts_direct_references_only():
    label = 'base.facility.research_laboratory'
    result = impact(label)
    assert result['stage_references']
    for row in result['stage_references']:
        keys = {activity_key(a) for a in target_profile(row['stage'])['activities']}
        assert all(r['activity_key'] in keys for r in row['direct_references'])
    assert impact('does-not-exist')['stage_references'] == []


def test_cli_operates_as_a_scoped_evidence_interface():
    root = Path(__file__).resolve().parents[2]
    for command in [
        ['overview'],
        ['inspect', '--stage', '1', '--kind', 'research'],
        ['impact', '--id', 'base.facility.research_laboratory'],
        ['state', '--stage', '1'],
    ]:
        result = subprocess.run([sys.executable, '-m', 'balance_evaluation', *command],
                                cwd=root, capture_output=True, text=True, check=True)
        assert isinstance(json.loads(result.stdout), dict)
