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
    # Capacity headroom is unused supply, never an unmet Activity request.
    capacities = [row for row in trace.allocations if row.kind == "finite_constraint"]
    assert capacities
    assert all(row.requested is None and row.allocated is None and row.unmet is None
               and row.capacity is not None and row.used is not None and row.remaining is not None
               and row.capacity >= row.used - 1e-9 for row in capacities)
    assert any(row.remaining > 0 for row in capacities)
    assert all(row.capacity is None and row.used is None and row.remaining is None
               for row in trace.allocations if row.kind != "finite_constraint")
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


def test_scoped_canonical_allocation_preserves_node_constraint_and_resource_identity():
    app = build_game_application()
    sim = app._simulation
    node, resource = next((node, resource) for (node, resource), stock in sim.inventory.stock.items()
                          if stock > 0)
    with observe_canonical_day(sim, operational_node_ids=frozenset((node,)),
                               resource_ids=frozenset((resource,))) as trace:
        app.execute(AdvanceTime(1))
    constraints = [row for row in trace.allocations if row.kind == "finite_constraint"]
    assert any(row.provenance == "allocation:resource" and row.subject_id == str(resource)
               and row.context_id == f"node:{node}" for row in constraints)
    assert all(row.subject_id == str(resource) for row in constraints
               if row.provenance == "allocation:resource")
    assert all(row.context_id in (str(node), f"node:{node}", "organization")
               for row in trace.allocations)
    assert all(row.subject_id == str(resource) for row in trace.allocations
               if row.kind == "resource_request")
    assert all(row.unmet is None and row.remaining is not None for row in constraints)


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


def test_initial_facility_scenario_variants_use_regular_site_and_power_contracts():
    from space_idle.content.base_scenario import build_standard_scenario_definition

    scenario = build_standard_scenario_definition()
    # A complete typed asset list retains multiplicity and actual investment.
    replacement = [
        {
            "definition_id": str(row.definition_id),
            "operational_node_id": str(row.operational_node_id),
            "site_cell_id": None if row.site_cell_id is None else str(row.site_cell_id),
            "invested_resources": [[str(resource), amount] for resource, amount in row.invested_resources],
        }
        for row in scenario.facilities
        if row.definition_id != ids.GRID_POWER_SUPPLY
    ]
    without_grid = scenario_variant(scenario, {"facilities": replacement})
    assert len(without_grid.facilities) == len(scenario.facilities) - 1
    assert len(scenario.facilities) == len(build_standard_scenario_definition().facilities)

    original = build_game_application_for_scenario(scenario)
    variant = build_game_application_for_scenario(without_grid)
    node = ids.EARTH
    original_power = original._simulation.power.snapshot(node, original._simulation.facilities, 0)
    variant_power = variant._simulation.power.snapshot(node, variant._simulation.facilities, 0)
    assert original_power.generation_mw > variant_power.generation_mw
    assert all(row.definition_id != ids.GRID_POWER_SUPPLY for row in variant._simulation.facilities.all_at(node))
    assert variant._simulation.projects.recipes[ids.GRID_POWER_SUPPLY] == original._simulation.projects.recipes[ids.GRID_POWER_SUPPLY]
    with pytest.raises(ValueError, match="nonnegative"):
        scenario_variant(scenario, {"facilities": [{"definition_id": str(ids.FOOD_FARM),
            "operational_node_id": str(node), "invested_resources": [[str(ids.WATER), -1.0]]}]})


def test_comparative_canonical_policy_connects_market_construction_power_and_multiple_nodes():
    """Different authored conditions remain distinct from policy and observed stock flow.

    An adaptive policy reads actual Application options, not guessed recipe IDs
    or a fixture-specific preferred build order. All cases use the same Command
    policy; each case composes its own State and typed Content before executing.
    """
    from space_idle.application_commands import CreateTradeOrder, GetBuildOptions, GetMarket, PlanBuild
    from space_idle.content import base_ids as ids
    from space_idle.content.base_scenario import build_standard_scenario_definition

    original = build_standard_scenario_definition()
    candidate_stock = next(row for row in original.inventory_stock
                           if row.operational_node_id == ids.EARTH
                           and row.resource_id == ids.STRUCTURAL_COMPONENTS)
    extra_stock = scenario_variant(original, {'inventory_stock': [{
        'operational_node_id': str(candidate_stock.operational_node_id),
        'resource_id': str(candidate_stock.resource_id),
        'amount_t': candidate_stock.amount_t + 50.0,
    }]})

    def make_case(name, scenario, edits=()):
        def factory():
            return build_game_application_for_scenario(
                scenario,
                definition_transform=(
                    (lambda sim, catalog: apply_content_variant(sim, catalog, edits)) if edits else None
                ),
            )

        def policy(app, offset):
            if offset != 0:
                return ()
            options = app.query(GetBuildOptions(str(ids.EARTH)))
            feasible = [row for row in options.items if row.can_plan and not row.blockers
                        and row.construction_required > 0]
            assert feasible
            selected = min(feasible, key=lambda row: (row.construction_required,
                                                       row.facility_definition_id))
            interface = next(row for row in app.query(GetMarket()).interfaces
                             if row.operational_node_id == str(ids.EARTH) and row.enabled)
            offer = next(row for row in interface.offers if row.buy_price_musd_per_t is not None)
            return (CreateTradeOrder('buy', offer.resource_id, interface.id,
                                     quantity_target_t=1.25),
                    PlanBuild(str(ids.EARTH), selected.facility_definition_id))

        return ExperimentCase(name, factory, policy)

    runs = run_experiments((
        make_case('baseline', original),
        make_case('reduced-power', original, ({'kind': 'power', 'id': str(ids.GRID_POWER_SUPPLY),
                                              'field': 'generation_mw', 'value': 0.1},)),
        make_case('additional-stock', extra_stock),
    ), days=4, operational_node_ids=frozenset((ids.EARTH, ids.LEO)))
    assert all(len(run.attempted_commands) == 2 and not run.rejected_commands for run in runs)
    assert all(len(run.canonical_traces) == 4 and len(run.observations) == 5 for run in runs)
    assert all(abs(row['unattributed_delta_t']) < 1e-7
               for run in runs for row in run.flow_reconciliation)
    assert all({move.operation for trace in run.canonical_traces for move in trace.movements}
               for run in runs)
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[0].initial_state_sha256 == runs[1].initial_state_sha256
    assert runs[0].content_definitions_sha256 == runs[2].content_definitions_sha256
    assert runs[0].initial_state_sha256 != runs[2].initial_state_sha256
    comparison = compare_experiments(runs)
    assert len(comparison['comparisons']) == 2
    assert all(not row['same_comparison_conditions'] for row in comparison['comparisons'])
    assert all((metric.context_id in (str(ids.EARTH), str(ids.LEO), 'organization')
                or metric.kind.startswith('external_market_'))
               for run in runs for observation in run.observations for metric in observation.metrics)
    again = run_experiments((make_case('baseline', original),), days=4,
                            operational_node_ids=frozenset((ids.EARTH, ids.LEO)))
    assert again[0].to_json_data() == runs[0].to_json_data()
