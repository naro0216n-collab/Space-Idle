"""Bridge validity is a runtime/state contract, not a balance verdict."""
import json
from datetime import datetime, timezone

import pytest

from balance_evaluation.scenarios import (
    app_from_scenario, read_scenario, scenario_from_save, scenario_to_save,
    stage_scenario, write_scenario,
)
from balance_evaluation.stages import evaluate_scenario
from balance_evaluation.state_evidence import evaluate_state, state_activities
from space_idle import StartResearch, AdvanceTime
from space_idle.bootstrap import build_game_application, build_game_application_for_load
from space_idle.persistence import capture_state, load_game, save_game, SaveFormatError
from content_balance.ledger import quantity_ledger

FIXED = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _save(app, path):
    save_game(app, path, saved_at=FIXED)
    return json.loads(path.read_text())


def test_bidirectional_conversion_uses_game_codec_and_preserves_real_state(tmp_path):
    app = build_game_application()
    app.execute(StartResearch('RP-RESOURCE-CHAIN-01', priority=3))
    app.execute(AdvanceTime(days=2))
    original_path = tmp_path / 'played.json'
    original = _save(app, original_path)
    scenario = scenario_from_save(original_path, stage=2, period_days=2345)
    path = tmp_path / 'evaluation.json'
    write_scenario(scenario, path)
    checked = read_scenario(path)
    exported = tmp_path / 'roundtrip.json'
    scenario_to_save(checked, exported)
    assert json.loads(exported.read_text()) == original
    restored, offline = load_game(exported, build_game_application_for_load)
    assert offline is None
    assert capture_state(restored._simulation) == capture_state(app._simulation)
    assert restored.time_paused == app.time_paused
    assert restored.time_speed_multiplier == app.time_speed_multiplier
    assert evaluate_state(restored, period_days=2345) == evaluate_state(app, period_days=2345)
    assert evaluate_scenario(checked)['snapshot']['game_day'] == 2


def test_builtin_stage_labels_are_not_gifts_and_state_read_is_pure(tmp_path):
    initial = stage_scenario(1)
    progressed = stage_scenario(2)
    one = app_from_scenario(initial)
    two = app_from_scenario(progressed)
    assert one._simulation.day == 0
    assert two._simulation.day > one._simulation.day
    before = capture_state(two._simulation)
    outcome = evaluate_scenario(progressed)
    assert capture_state(two._simulation) == before
    assert outcome['snapshot']['completed_technologies'] == sorted(map(str, two._simulation.technology.completed))
    assert outcome['snapshot']['research_points_stored'] == two._simulation.research.stored_points
    assert sum(r['installed_units'] for r in outcome['snapshot']['installed_facilities']) == sum(
        f.level for f in two._simulation.facilities.facilities.values())
    for case in (initial, progressed):
        output = tmp_path / f'{case.stage}.json'
        scenario_to_save(case, output)
        assert json.loads(output.read_text()) == case.save
    # Changing stage annotations cannot magically build assets.
    annotation = scenario_from_save(output, stage=7, period_days=100)
    assert evaluate_scenario(annotation)['snapshot'] == evaluate_state(two, period_days=100)


def test_save_bridge_rejects_invalid_state_instead_of_manufacturing_assets(tmp_path):
    app = build_game_application()
    path = tmp_path / 'valid.json'
    raw = _save(app, path)
    raw['state']['facilities']['items'][0]['definition_id'] = 'invented.facility.free_rp'
    path.write_text(json.dumps(raw))
    with pytest.raises((SaveFormatError, KeyError, ValueError)):
        scenario_from_save(path, stage=1, period_days=100)
    valid = tmp_path / 'clean.json'
    _save(app, valid)
    scenario = scenario_from_save(valid, stage=1, period_days=100)
    payload = scenario.as_dict()
    payload['period_days'] = float('nan')
    invalid = tmp_path / 'nonfinite.json'
    invalid.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_scenario(invalid)
    invalid.write_text('{"format": "x", "format": "y"}')
    with pytest.raises(ValueError, match='duplicate'):
        read_scenario(invalid)


def test_real_investment_and_level_are_used_in_nominal_evidence():
    app = build_game_application()
    sim = app._simulation
    row = state_activities(sim)[0]
    # Real maintained investment is passed from authoritative FacilityState.
    facility = next(f for f in sim.facilities.facilities.values()
                    if str(f.definition_id) == row['id'] and str(f.operational_node_id) == row['node'])
    assert row['invested_resources'] == {str(k): v for k, v in facility.invested_resources.items()}
    result = quantity_ledger(sim, period_days=10, activities=[row])
    evidence = next(e for e in result['activity_evidence'][0]['evidence']
                    if e['measure'] == 'facility_investment_for_maintenance')
    assert evidence['resources_t'] == row['invested_resources']
    # Level must scale physical Power and Service as in the real owners.
    row['level'] = 2
    stage = quantity_ledger(sim, period_days=10, activities=[row])
    row['level'] = 1
    base = quantity_ledger(sim, period_days=10, activities=[row])
    for metric in ('nominal_generation_mw', 'nominal_active_load_mw'):
        assert stage['power_by_node'][0][metric] == pytest.approx(2 * base['power_by_node'][0][metric])


def test_staged_target_evolution_is_data_only_and_distinct_from_save_state():
    from balance_evaluation.targets import target_profile, evaluate_target
    first = target_profile(1)
    second = target_profile(2)
    assert first['stage'] == 1 and second['stage'] == 2
    # No stage-specific computation; the same registered ledger consumes both.
    sim = app_from_scenario(stage_scenario(1))._simulation
    x = evaluate_target(sim, 1)['research_by_scope'][0]
    y = evaluate_target(sim, 2)['research_by_scope'][0]
    assert x['rp_nominal_per_day'] < y['rp_nominal_per_day']
    assert x['execution_nominal_per_day'] < y['execution_nominal_per_day']
    # These intended future acquisitions must not be smuggled into a saved game.
    assert y['rp_nominal_per_day'] > evaluate_state(
        app_from_scenario(stage_scenario(2)), period_days=28000
    )['nominal_capacity_from_installed_assets']['research'][0]['rp_nominal_per_day']


def test_installed_power_evidence_matches_owner_physical_snapshot():
    for stage in (1, 2):
        app = app_from_scenario(stage_scenario(stage))
        sim = app._simulation
        evidence = evaluate_state(app, period_days=100)['nominal_capacity_from_installed_assets']['power']
        for row in evidence:
            physical = sim.power.physical_snapshot(row['node'], sim.facilities, sim.day)
            assert row['nominal_generation_mw'] == pytest.approx(
                sum(physical.generation_mw_by_facility.values()))
            assert row['nominal_active_load_mw'] == pytest.approx(physical.demand_mw)
