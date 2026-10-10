"""Cross-domain invariants of optional canonical observation and analysis.

Uses the real Application command boundary and Owner Domains, not a second
supply/eligibility implementation or a frozen preferred gameplay sequence.
"""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from scripts.analysis_experiments import (
    ExperimentCase, ParetoObjective, compare_experiments, compare_pareto, run_experiments,
)
from scripts.analysis_projection import project_html, to_csv
from scripts.compare_experiments import parse_cases
from space_idle import build_game_application
from space_idle.analysis_execution import observe_canonical_day
from space_idle.analysis_graph import (
    DependencyFragment, DependencyNode, DependencyRelation, DefinitionGraphRegistry,
)
from space_idle.analysis_observation import observe_state
from space_idle.bootstrap import build_game_application_for_scenario
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.content import base_ids as ids
from space_idle.analysis_variants import apply_content_variant, scenario_variant
from space_idle.application_commands import AdvanceTime
from space_idle.persistence import capture_state
from space_idle.shared import DefinitionId, EntityId


def _idle(_app, _day):
    return ()


def test_optional_canonical_trace_matches_authoritative_stock_and_preserves_save_and_gameplay():
    ordinary = build_game_application()
    observed = build_game_application()
    start = capture_state(observed._simulation)
    assert start == capture_state(ordinary._simulation)
    sim = observed._simulation
    stock = {(str(node), str(rid)): value for (node, rid), value in sim.inventory.stock.items()}
    with observe_canonical_day(sim) as trace:
        observed.execute(AdvanceTime(1))
    ordinary.execute(AdvanceTime(1))
    assert capture_state(sim) == capture_state(ordinary._simulation)
    assert sim.inventory._settlement_observer is None
    assert sim._analysis_decision_observer is None
    assert trace.allocations
    assert trace.movements
    final = {(str(node), str(rid)): value for (node, rid), value in sim.inventory.stock.items()}
    assert all(abs(item['unattributed_delta_t']) < 1e-7 for item in trace.reconcile(stock, final))
    assert any(row.direction == 'inventory_in' for row in trace.movements)
    assert any(row.direction == 'inventory_out' for row in trace.movements)
    assert json.dumps(observe_state(sim).to_json_data(), ensure_ascii=False)
    with pytest.raises(RuntimeError, match='nested'):
        with observe_canonical_day(sim):
            with observe_canonical_day(sim):
                pass
    assert capture_state(sim) == capture_state(ordinary._simulation)


def test_owner_scoped_custody_transfer_is_not_mistaken_for_inventory_or_resource_creation():
    app = build_game_application()
    sim = app._simulation
    node, resource = next((node, rid) for node, rid in sim.inventory.stock
                          if sim.inventory.available(node, rid) >= 1)
    owner = EntityId('test.analytics.project.custody')
    quantity = min(0.25, sim.inventory.available(node, resource))
    before = sim.inventory.amount(node, resource)
    with observe_canonical_day(sim, operational_node_ids=frozenset((node,)),
                               resource_ids=frozenset((resource,))) as trace:
        sim.inventory.stage_allocated(owner, node, resource, quantity)
        assert sim.inventory.amount(node, resource) == pytest.approx(before - quantity)
        assert sim.inventory.staged_for(owner, node, resource) == pytest.approx(quantity)
        sim.inventory.unstage_to_stock(owner, node, resource, quantity)
    assert sim.inventory.amount(node, resource) == pytest.approx(before)
    assert sim.inventory.staged_for(owner, node, resource) == pytest.approx(0)
    assert {row.direction for row in trace.movements} == {
        'inventory_in', 'inventory_out', 'external_storage_in', 'external_storage_out'
    }
    assert trace.inventory_balance(node_id=str(node), resource_id=str(resource)) == pytest.approx(0)


def test_typed_independent_scenario_and_content_variants_do_not_mutate_base_or_initialization():
    base = build_standard_scenario_definition()
    original = base.inventory_stock[0]
    variation = scenario_variant(base, {'inventory_stock': [{
        'operational_node_id': str(original.operational_node_id),
        'resource_id': str(original.resource_id),
        'amount_t': original.amount_t + 2,
    }]})
    assert base.inventory_stock[0] == original
    assert variation != base
    control = build_game_application_for_scenario(base)
    variant = build_game_application_for_scenario(variation)
    assert capture_state(control._simulation) != capture_state(variant._simulation)
    process = next(p for p in control._simulation.industry.processes.values() if p.outputs_per_day)
    rid = next(iter(process.outputs_per_day))
    value = process.outputs_per_day[rid] + 0.25
    def edit(sim, catalog):
        apply_content_variant(sim, catalog, ({'kind': 'process', 'id': str(process.id),
                                              'field': 'outputs_per_day', 'resource_id': str(rid),
                                              'value': value},))
    modified = build_game_application_for_scenario(base, definition_transform=edit)
    assert modified._simulation.industry.processes[process.id].outputs_per_day[rid] == pytest.approx(value)
    assert control._simulation.industry.processes[process.id].outputs_per_day[rid] != value
    assert capture_state(control._simulation) == capture_state(modified._simulation)
    with pytest.raises(ValueError, match='unknown Scenario variant'):
        scenario_variant(base, {'impossible_initial_state': []})
    with pytest.raises(ValueError, match='unsupported typed Content'):
        edit_that_does_not_exist = ({'kind': 'planet', 'id': 'X', 'field': 'gravity', 'value': 9},)
        apply_content_variant(modified._simulation, modified._catalog, edit_that_does_not_exist)


def test_case_execution_reproducibility_projection_and_missing_observation_pareto():
    app = build_game_application()
    resource, node = next((str(rid), str(node)) for (node, rid), value in app._simulation.inventory.stock.items()
                          if value > 0)
    plan = {'days': 1, 'cases': [
        {'name': 'baseline', 'commands': []},
        {'name': 'inventory-change', 'commands': [], 'scenario_variant': {
            'inventory_stock': [{'resource_id': resource, 'operational_node_id': node, 'amount_t': 777.0}],
        }},
    ]}
    days, cases = parse_cases(plan)
    runs = run_experiments(cases, days=days)
    again = run_experiments(cases, days=days)
    assert [row.to_json_data() for row in runs] == [row.to_json_data() for row in again]
    assert not compare_experiments(runs)['comparisons'][0]['same_comparison_conditions']
    assert runs[0].content_definitions_sha256 == runs[1].content_definitions_sha256
    assert runs[0].initial_state_sha256 != runs[1].initial_state_sha256
    assert all(abs(row['unattributed_delta_t']) < 1e-7 for run in runs for row in run.flow_reconciliation)
    payload = {'runs': [run.to_json_data() for run in runs]}
    assert 'inventory_in' in to_csv(payload, 'inventory_movements')
    assert 'provenance' in to_csv(payload, 'state_metrics')
    assert '<svg' in project_html(payload) and '確定入出庫' in project_html(payload)
    metric = next(row for row in runs[0].observations[-1].metrics if row.kind == 'inventory_stock')
    objective = ParetoObjective(metric.kind, metric.subject_id, metric.context_id,
                                metric.unit, metric.provenance, 'maximize')
    result = compare_pareto(runs, [objective])
    assert len(result['cases']) == 2
    missing = replace(objective, subject_id='nonexistent.Resource')
    assert all(row['values'] is None and not row['comparable']
               for row in compare_pareto(runs, [missing])['cases'])


def test_graph_reports_registered_definition_omissions_duplicate_relations_and_time_basis():
    node = DependencyNode('test_method', 'generic')
    resource = DependencyNode('resource', 'R')
    extra = DependencyNode('test_method', 'expected')
    relation = DependencyRelation('consumes_resource', resource, node, 'test:recipe', 2.0, 't')
    registry = DefinitionGraphRegistry()
    registry.register('method', lambda: DependencyFragment((node, resource), (relation, relation)),
                      expected_definitions=lambda: (node, extra), relation_kinds={'consumes_resource'})
    diagnostic = {row.code for row in registry.build().diagnostics}
    assert {'duplicate_relation', 'quantitative_relation_without_time_basis',
            'unrepresented_registered_definition'} <= diagnostic
