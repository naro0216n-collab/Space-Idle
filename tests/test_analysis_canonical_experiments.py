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
from scripts.analysis_variants import apply_content_variant, scenario_variant
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
    transfers = trace.custody_transfers()
    assert len(transfers) == 2
    assert [(row.source_owner, row.destination_owner) for row in transfers] == [
        (f'inventory:{node}', f'staging:{owner}'),
        (f'staging:{owner}', f'inventory:{node}'),
    ]
    assert all(row.quantity_t == pytest.approx(quantity) for row in transfers)
    payload = {'runs': [{'name': 'custody', 'canonical_traces': [trace.to_json_data()]}]}
    assert 'staging:' in to_csv(payload, 'custody_transfers')


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


def test_typed_content_add_remove_recompose_application_and_preserve_accounting(tmp_path):
    """New research/method/resource and deletion share Composition and UI contracts.

    Experiment cases recompose Definitions before Scenario instead of modifying
    a running game or inventing a second supply / tech eligibility evaluator.
    """
    from space_idle.application_commands import (GetCatalog, GetOperationalNode,
        GetResearch, StartResearch, SetResearchPrototypeSite,
        SetFacilityProcess, AdvanceTime, ApplicationError)
    from space_idle.persistence import save_game, load_game
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.validation_support import ConfigurationError

    resource_id = "experiment.resource.raw_mineral"
    research_id = "experiment.research.refining_method"
    process_id = "experiment.process.refining_method"
    changes = (
        {"operation": "add", "kind": "resource", "id": resource_id,
         "definition": {"display_name": "実験原料", "unit": "t", "category": "bulk"}},
        {"operation": "add", "kind": "research", "id": research_id,
         "definition": {"display_name": "代替資源加工", "prerequisites": [], "stage_specs": [
             {"stage_type": "theory", "stage_id": "concept", "research_point_cost": 1.0},
             {"stage_type": "prototype", "stage_id": "bench", "required_work": 1.0,
              "resources": {resource_id: 0.5},
              "site_requirements": {"capabilities": [
                  {"capability_id": "basic_structural_material", "required_state": "ACTIVE"}],
                  "spatial_classifications": [
                  {"classification": "SURFACE", "code": "prototype:surface",
                   "description": "試作には地表の作業場所が必要"}]},
              "execution_requirements": [{"service_type": "research_execution",
                                          "amount_per_execution": 1.0, "scope": "ORGANIZATION"}]},
         ]}},
        {"operation": "add", "kind": "process", "id": process_id,
         "definition": {"display_name": "実験用代替製法",
                        "required_capabilities": ["basic_structural_material"],
                        "inputs_per_day": {resource_id: 0.5},
                        "outputs_per_day": {str(ids.STRUCTURAL_COMPONENTS): 0.25},
                        "prerequisite_technologies": [research_id]}},
    )
    base = build_standard_scenario_definition()
    scenario = scenario_variant(base, {"inventory_stock": [{
        "operational_node_id": str(ids.EARTH), "resource_id": resource_id,
        "amount_t": 20.0,
    }]})

    def factory(scenario=scenario, changes=changes):
        return build_game_application_for_scenario(
            scenario, definition_transform=lambda sim, cat: apply_content_variant(sim, cat, changes),
        )

    app = factory()
    catalog = app.query(GetCatalog())
    assert any(str(row.id) == resource_id for row in catalog.resources)
    assert any(row.id == process_id for row in catalog.processes)
    assert any(row.id == research_id for row in catalog.research)
    assert any(row.id == research_id for row in app.query(GetResearch()).items)
    added_stages = app._simulation.research.definitions[DefinitionId(research_id)].stage_specs
    assert len(added_stages) == 2
    site_requirement = added_stages[1].site_requirements.spatial_classification_requirements[0]
    assert site_requirement.code == "prototype:surface"
    assert site_requirement.description == "試作には地表の作業場所が必要"
    assert added_stages[1].execution_requirements[0].service_type == "research_execution"
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    assert not graph.diagnostics
    stage_node = DependencyNode("research_stage", research_id + "/bench")
    assert any(row.kind == "requires_site_capability" and row.target == stage_node
               and row.condition == "required_state:ACTIVE" for row in graph.relations)
    assert any(row.kind == "requires_site_classification" and row.target == stage_node
               and row.provenance.endswith("prototype:surface") for row in graph.relations)
    assert any(row.kind == "requires_execution_capacity" and row.target == stage_node
               and row.source == DependencyNode("service_capacity", "research_execution")
               and row.condition == "scope:ORGANIZATION" for row in graph.relations)
    assert any(row.kind == "consumes_resource" and row.target == stage_node
               and row.source == DependencyNode("resource", resource_id) for row in graph.relations)
    industry = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                    if any(option.process_id == process_id for option in row.process_options))
    locked = next(option for option in industry.process_options if option.process_id == process_id)
    assert any(f"technology:{research_id}" in constraint.code for constraint in locked.blockers)
    with pytest.raises(ApplicationError):
        app.execute(SetFacilityProcess(industry.facility_id, process_id))
    assert app._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id)) == 20.0

    # The new authored Technology must also be obtainable through the actual
    # Research Stage lifecycle, rather than only a pre-completed Scenario flag.
    # Its typed Site and finite Service constraints are evaluated by Research,
    # not by an experiment-specific approximation.
    researched = factory()
    researched.execute(StartResearch(research_id))
    for _ in range(8):
        research_row = next(item for item in researched.query(GetResearch()).items if item.id == research_id)
        if research_row.current_stage_id == "bench":
            break
        researched.execute(AdvanceTime(1))
    assert research_row.current_stage_id == "bench"
    earth_site = next(site for site in research_row.execution_context_options
                      if site.operational_node_id == str(ids.EARTH))
    assert earth_site.can_select
    orbital_site = next(site for site in research_row.execution_context_options
                        if site.operational_node_id == str(ids.LEO))
    assert not orbital_site.can_select
    assert any(blocker.code == "prototype:surface" for blocker in orbital_site.blockers)
    with pytest.raises(ApplicationError):
        researched.execute(SetResearchPrototypeSite(research_id, "bench", str(ids.LEO)))
    researched.execute(SetResearchPrototypeSite(research_id, "bench", str(ids.EARTH)))
    researched.execute(AdvanceTime(1))
    stage_save = tmp_path / "research-prototype-variant.json"
    save_game(researched, stage_save)
    resumed, _ = load_game(stage_save, lambda: build_game_application_for_load(
        scenario=scenario, definition_transform=lambda sim, cat: apply_content_variant(sim, cat, changes),
    ))
    assert capture_state(resumed._simulation) == capture_state(researched._simulation)
    for _ in range(8):
        if DefinitionId(research_id) in resumed._simulation.technology.completed:
            break
        resumed.execute(AdvanceTime(1))
    assert DefinitionId(research_id) in resumed._simulation.technology.completed
    assert next(option for row in resumed.query(GetOperationalNode(str(ids.EARTH))).industry
                for option in row.process_options if option.process_id == process_id).can_select
    assert next(option for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                for option in row.process_options if option.process_id == process_id).can_select is False

    # Acquisition and existing equipment use different criteria: this research
    # enables an explicit Process choice, not an automatic asset modification.
    with_technology = scenario_variant(scenario, {"completed_technologies": [
        *map(str, base.completed_technologies), research_id,
    ]})
    enabled = factory(with_technology)
    chosen = next(row for row in enabled.query(GetOperationalNode(str(ids.EARTH))).industry
                  if any(option.process_id == process_id for option in row.process_options))
    option = next(option for option in chosen.process_options if option.process_id == process_id)
    assert option.can_select
    enabled.execute(SetFacilityProcess(chosen.facility_id, process_id))
    first = enabled._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id))
    enabled.execute(AdvanceTime(1))
    last = enabled._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id))
    assert last < first
    assert enabled._simulation.facilities.facilities[EntityId(chosen.facility_id)].selected_process_id == DefinitionId(process_id)
    path = tmp_path / "content-variant-state.json"
    save_game(enabled, path)
    restored, _ = load_game(path, lambda: build_game_application_for_load(
        scenario=with_technology,
        definition_transform=lambda sim, cat: apply_content_variant(sim, cat, changes),
    ))
    assert capture_state(restored._simulation) == capture_state(enabled._simulation)

    def policy(app, day):
        if day > 0:
            return ()
        rows = app.query(GetOperationalNode(str(ids.EARTH))).industry
        matches = (row for row in rows if any(option.process_id == process_id for option in row.process_options))
        row = next(matches, None)
        return () if row is None else (SetFacilityProcess(row.facility_id, process_id),)

    cases = (
        ExperimentCase("original", lambda: build_game_application_for_scenario(base), policy),
        ExperimentCase("new-method-locked", factory, policy),
        ExperimentCase("new-method-enabled", lambda: factory(with_technology), policy),
    )
    runs = run_experiments(cases, days=2)
    repeat = run_experiments(cases, days=2)
    assert [run.to_json_data() for run in runs] == [run.to_json_data() for run in repeat]
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[1].content_definitions_sha256 == runs[2].content_definitions_sha256
    assert runs[1].initial_state_sha256 != runs[2].initial_state_sha256
    assert runs[0].definition_graph_sha256 != runs[1].definition_graph_sha256
    assert len(runs[1].rejected_commands) == 1
    assert not runs[2].rejected_commands
    assert all(abs(row["unattributed_delta_t"]) < 1e-7
               for run in runs for row in run.flow_reconciliation)

    # Removing a method changes the actual candidates/Definition Graph; nothing
    # rewrites the Scenario or dependent Technology requirements to conceal it.
    removed_method = changes + ({"operation": "remove", "kind": "process", "id": process_id},)
    no_method = factory(scenario, removed_method)
    assert all(row.id != process_id for row in no_method.query(GetCatalog()).processes)
    assert all(option.process_id != process_id
               for row in no_method.query(GetOperationalNode(str(ids.EARTH))).industry
               for option in row.process_options)

    # Removing referenced definitions must fail closed during Composition;
    # removing an unreferenced Resource still fails when Scenario retains stock.
    with pytest.raises((ConfigurationError, ValueError), match="Resource|catalog|unknown"):
        factory(scenario, changes + ({"operation": "remove", "kind": "resource", "id": resource_id},))
    with pytest.raises((ConfigurationError, ValueError), match="unknown research|technology|prerequisite"):
        factory(scenario, changes + ({"operation": "remove", "kind": "research", "id": research_id},))
    with pytest.raises((ConfigurationError, ValueError), match="Resource|resource definitions"):
        factory(scenario, removed_method + ({"operation": "remove", "kind": "resource", "id": resource_id},))
    # Definitions are isolated from the standard factory and other experiment cases.
    assert all(row.id != process_id for row in build_game_application().query(GetCatalog()).processes)


def test_independent_definition_membership_connects_assets_providers_acquisition_and_policy():
    """Added Definitions participate in the real Application, not a parallel experiment ruleset."""
    base = build_game_application()
    sim = base._simulation
    source_provider = next(provider for provider in sim.research.providers.values()
                           if provider.source_kind.value == "facility"
                           and any(fid in sim.projects.recipes and fid in sim.power.specs
                                   for fid in sim.research.compatible_facility_definition_ids(provider.id)))
    source_facility = next(fid for fid in sim.research.compatible_facility_definition_ids(source_provider.id)
                           if fid in sim.projects.recipes and fid in sim.power.specs)
    source_vehicle = next(vehicle for vehicle in sim.transport.vehicle_definitions()
                          if vehicle.production.days > 0)
    new_facility = 'experiment.facility.research'
    new_provider = 'experiment.provider.research'
    new_vehicle = 'experiment.vehicle.production'
    additions = [
        {'operation': 'add', 'kind': kind, 'source_id': str(source), 'id': target}
        for kind, source, target in (
            ('facility', source_facility, new_facility),
            ('construction', source_facility, new_facility),
            ('decommission', source_facility, new_facility),
            ('power', source_facility, new_facility),
            ('vehicle', source_vehicle.id, new_vehicle),
            ('research_provider', source_provider.id, new_provider),
        )
    ]
    edits = [
        {'kind': 'facility', 'id': new_facility, 'field': 'capability_supplies',
         'value': ['experiment_research_equipment']},
        {'kind': 'research_provider', 'id': new_provider,
         'field': 'required_source_capabilities', 'value': ['experiment_research_equipment']},
        {'kind': 'vehicle', 'id': new_vehicle, 'field': 'production_days', 'value': 5.0},
        {'kind': 'construction', 'id': new_facility, 'field': 'construction_work', 'value': 5.0},
    ]
    from space_idle.application_commands import GetBuildOptions, GetLogistics, PlanBuild, ProduceVehicle
    from space_idle.composition.analysis_graph import build_definition_dependency_graph

    def factory(additions=additions):
        return build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, additions + edits),
        )

    app = factory()
    options = app.query(GetBuildOptions(str(ids.EARTH)))
    facility_option = next(row for row in options.items
                           if row.facility_definition_id == new_facility)
    vehicle_option = next(row for row in app.query(GetLogistics()).vehicle_production_options
                          if row.vehicle_definition_id == new_vehicle
                          and row.operational_node_id == str(ids.EARTH))
    assert facility_option.can_plan and vehicle_option.can_plan
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    assert not graph.diagnostics
    assert any(row.kind == 'facility' and row.id == new_facility for row in graph.nodes)
    assert any(row.kind == 'vehicle' and row.id == new_vehicle for row in graph.nodes)
    assert any(row.kind == 'research_provider' and row.id == new_provider for row in graph.nodes)

    # Both strategies issue the same Player intent. The baseline rejects unknown
    # authored assets and records the blocker; the modified Content accepts them.
    def policy(_app, day):
        return (PlanBuild(str(ids.EARTH), new_facility),
                ProduceVehicle(new_vehicle, str(ids.EARTH))) if day == 0 else ()

    runs = run_experiments((ExperimentCase('base', build_game_application, policy),
                            ExperimentCase('variant', factory, policy)), days=2)
    assert len(runs[0].rejected_commands) == 2
    assert not runs[1].rejected_commands
    assert len(runs[1].attempted_commands) == 2
    assert all(abs(row['unattributed_delta_t']) < 1e-7
               for run in runs for row in run.flow_reconciliation)
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[0].initial_state_sha256 == runs[1].initial_state_sha256
    assert not compare_experiments(runs)['comparisons'][0]['same_comparison_conditions']
    assert runs[1].to_json_data() == run_experiments(
        (ExperimentCase('variant', factory, policy),), days=2,
    )[0].to_json_data()
    reordered = factory(list(reversed(additions)))
    assert build_definition_dependency_graph(reordered._simulation, reordered._catalog).to_json_data() == graph.to_json_data()

    # Additions never silently invent acquisition recipes. Missing references
    # or competing providers are invalid through normal Composition validation.
    with pytest.raises(ValueError):
        build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, additions + edits + [
                    {'operation': 'remove', 'kind': 'facility', 'id': new_facility},
                ]),
        )
    with pytest.raises(ValueError):
        build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, [additions[-1]]),
        )


def test_independent_survey_definition_requires_a_real_compatible_vehicle(tmp_path):
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    base = build_game_application()
    sim = base._simulation
    source = next(provider for provider in sim.survey.providers.values()
                  if provider.source_kind.value == 'fleet')
    craft = next(vehicle for vehicle in sim.transport.vehicle_definitions()
                 if source.required_source_capabilities.issubset(vehicle.generic_capabilities))
    added_vehicle = 'experiment.vehicle.survey'
    added_provider = 'experiment.provider.survey'
    edits = [
        {'operation': 'add', 'kind': 'vehicle', 'id': added_vehicle, 'source_id': str(craft.id)},
        {'kind': 'vehicle', 'id': added_vehicle, 'field': 'generic_capabilities',
         'value': sorted(set(craft.generic_capabilities) | {'experiment_survey_sensor'})},
        {'operation': 'add', 'kind': 'survey_provider', 'id': added_provider,
         'source_id': str(source.id)},
        {'kind': 'survey_provider', 'id': added_provider,
         'field': 'required_source_capabilities', 'value': ['experiment_survey_sensor']},
        {'kind': 'survey_provider', 'id': added_provider,
         'field': 'capacity_units_per_source_per_day', 'value': 2.0},
    ]
    def factory(changes):
        return build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, changes),
        )
    modified = factory(edits)
    assert not build_definition_dependency_graph(modified._simulation, modified._catalog).diagnostics
    assert modified._simulation.survey.compatible_source_definition_ids(
        modified._simulation.survey.providers[DefinitionId(added_provider)]
    )
    # The copied Fleet is a real physical asset in an independent Scenario.
    # Application candidates, exclusive commitment, Save/Load and progression
    # all use the ordinary Survey and Transport Domains.
    from datetime import datetime, timezone
    from space_idle.application_commands import GetSurveys, SetSurveyProviderFleetQuantity, AdvanceTime
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.persistence import save_game, load_game
    node_id = ids.LUNAR_ORBIT
    variant_scenario = scenario_variant(build_standard_scenario_definition(), {
        'fleet': [{'operational_node_id': str(node_id),
                   'vehicle_definition_id': added_vehicle, 'units': 1}],
    })
    variant = build_game_application_for_scenario(
        variant_scenario,
        definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, edits),
    )
    def candidate(app):
        return next(row for row in app.query(GetSurveys(str(node_id))).provider_fleet
                    if row.provider_definition_id == added_provider
                    and row.vehicle_definition_id == added_vehicle)
    assert candidate(variant).free_units == 1 and candidate(variant).can_set_quantity
    assignment = variant.execute(SetSurveyProviderFleetQuantity(
        added_provider, str(node_id), added_vehicle, 1,
    )).created_id
    assert assignment is not None
    assert candidate(variant).committed_units == 1
    assert variant._simulation.transport.fleet_free_units(DefinitionId(added_vehicle), node_id) == 0
    path = tmp_path / 'independent-content-survey.json'
    save_game(variant, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, lambda: build_game_application_for_load(
        scenario=variant_scenario,
        definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, edits),
    ))
    assert capture_state(loaded._simulation) == capture_state(variant._simulation)
    variant.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(variant._simulation)
    assert candidate(loaded).committed_units == 1
    with pytest.raises(ValueError):
        factory(edits[2:])  # No compatible physical source for the new provider.
