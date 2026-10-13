"""Whole-system balance contracts: registered coefficients, activity coupling and conditions.

Neither a static relation nor a nominal negative Stock authorizes an Activity.
Tests use registered Content but never a fixed facility count or balance target.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.analysis_balance import evaluate
from space_idle.bootstrap import build_game_application_for_load
from space_idle.persistence import capture_state


@pytest.fixture(scope="module")
def source():
    return build_game_application_for_load()


def test_network_preserves_node_boundary_and_ledger_quantities(source):
    sim = source._simulation
    fac = next(f for f in sim.facilities.definitions.values() if sim.projects.recipes.get(f.id)
               and sim.projects.recipes[f.id].resources)
    resource = next(iter(sim.projects.recipes[fac.id].resources)).resource_id
    nodes = ("isolated.one", "isolated.two")
    phase = evaluate({"initial_stock": [{"node": nodes[1], "resource": str(resource),
                                           "amount_t": 1_000_000}],
                      "phases": [{"name": "two_nodes", "days": 3, "facilities": [
                          {"node": nodes[0], "facility": str(fac.id), "units": 1}]}]},
                     app=source)["phases"][0]
    actual = {(row["node"], row["resource"]): row for row in phase["resources"]}
    for row in phase["system_network"]["material_balances"]:
        key = row["node"], row["resource"]
        assert row["nominal_closing_stock_t"] == pytest.approx(actual[key]["notional_end_t"])
        contributions = [c for c in phase["resource_contributions"]
                         if (c["node"], c["resource"]) == key]
        assert sum(a["amount_t"] for a in row["activity_demands"]) == pytest.approx(sum(
            max(0, c["amount_t"]) for c in contributions if c["dimension"].endswith("demand_t")))
    shortage = next(e for e in phase["system_network"]["pressure_exposures"]
                    if e["node"] == nodes[0] and e["resource"] == str(resource))
    assert shortage["condition"] == "nominal_shortfall_without_assumed_arrivals"
    assert all(e["node"] != nodes[1] for e in phase["system_network"]["pressure_exposures"])


def test_registered_process_extension_reveals_multistage_resource_exposure():
    """The network follows new Content through multiple processes, not a frozen base-Content chain."""
    from space_idle.production import ProcessSpec
    from space_idle.shared import DefinitionId

    app = build_game_application_for_load()
    sim = app._simulation
    facility, first = next(
        (facility, process)
        for facility in sim.facilities.definitions.values()
        for process in sim.industry.processes.values()
        if process.inputs_per_day and process.outputs_per_day
        and process.required_capabilities <= {c.id for c in facility.capability_supplies}
    )
    raw = next(iter(first.inputs_per_day))
    intermediate = next(iter(first.outputs_per_day))
    final = next(resource for resource in app._catalog.resources
                 if resource not in first.inputs_per_day and resource not in first.outputs_per_day)
    downstream = ProcessSpec(
        id=DefinitionId("test.generated.downstream"),
        display_name="Generated downstream process",
        required_capabilities=first.required_capabilities,
        inputs_per_day={intermediate: 1.0},
        outputs_per_day={final: 1.0},
    )
    sim.industry.processes[downstream.id] = downstream
    node = "shared.industrial.node"
    assets = [
        {"node": node, "facility": str(facility.id), "units": 1, "process": str(first.id)},
        {"node": node, "facility": str(facility.id), "units": 1, "process": str(downstream.id)},
    ]
    before = capture_state(sim)
    phase = evaluate({"initial_facilities": assets, "phases": [
        {"name": "connected_industry", "days": 4, "facilities": assets}]}, app=app)["phases"][0]
    exposure = next(row for row in phase["system_network"]["pressure_exposures"]
                    if row["node"] == node and row["resource"] == str(raw))
    assert str(first.id) in exposure["active_downstream_processes"]
    assert str(intermediate) in exposure["potentially_affected_outputs"]
    assert str(downstream.id) in exposure["active_downstream_processes"]
    assert str(final) in exposure["potentially_affected_outputs"]
    # Nominal quantities remain conditional; no shortage is solved by tracing edges.
    rows = {(row["node"], row["resource"]): row for row in phase["resources"]}
    assert rows[(node, str(intermediate))]["production_t"] > 0
    assert capture_state(sim) == before


def test_inter_node_resource_options_keep_physical_boundaries_and_nonarrival_accounting(source):
    """A remote surplus is neither local stock nor a booked transport capacity."""
    sim = source._simulation
    recipe = next(recipe for recipe in sim.projects.recipes.values()
                  if recipe.resources and recipe.facility_def_id in sim.facilities.definitions)
    resource = str(recipe.resources[0].resource_id)
    facility = str(recipe.facility_def_id)
    origin, destination = "physical.supplier", "physical.consumer"
    candidate = {"initial_stock": [{"node": origin, "resource": resource, "amount_t": 10000}],
                 "phases": [{"name": "resource_distribution", "days": 10,
                             "facilities": [{"node": destination, "facility": facility, "units": 1}]}]}
    phase = evaluate(candidate, app=source)["phases"][0]
    option = next(r for r in phase["system_network"]["inter_node_resource_options"]
                  if (r["origin"], r["destination"], r["resource"]) ==
                  (origin, destination, resource))
    deficit = next(r["shortfall_without_assumed_arrivals_t"] for r in phase["resources"]
                   if r["node"] == destination and r["resource"] == resource)
    assert option["resource_overlap_upper_bound_t"] == pytest.approx(deficit)
    assert option["od_capacity_t_per_day"] is None
    assert option["transport_and_handling_upper_bound_t"] is None
    assert option["blockers"] == ["no_selected_transport_service"]
    assert next(row for row in phase["resources"]
                if row["node"] == destination and row["resource"] == resource)["shortfall_t"] > 0

    # A nominal purchase/source assumption cannot be counted as confirmed
    # exportable production by a different Node.
    conditional = deepcopy(candidate)
    conditional["initial_stock"] = []
    conditional["phases"][0]["external_rates"] = [
        {"node": origin, "resource": resource, "net_t_per_day": 200}]
    phase = evaluate(conditional, app=source)["phases"][0]
    assert not any(o["origin"] == origin and o["resource"] == resource
                   for o in phase["system_network"]["inter_node_resource_options"])


def test_inter_node_shared_freight_bounds_are_independent_and_require_handling(source):
    """Multiple Resource overlap bounds do not mint repeated OD or handling capacity."""
    sim = source._simulation
    facility = next(f for f in sim.facilities.definitions.values()
                    if sim.projects.recipes.get(f.id)
                    and len(sim.projects.recipes[f.id].resources) >= 2)
    inputs = list(sim.projects.recipes[facility.id].resources)[:2]
    origin, destination = "capacity.origin", "capacity.destination"
    plan = {"initial_stock": [{"node": origin, "resource": str(item.resource_id),
                               "amount_t": 10000} for item in inputs],
            "phases": [{"name": "investment", "days": 10,
                        "facilities": [{"node": destination, "facility": str(facility.id),
                                        "units": 1}]}]}
    phase = evaluate(plan, app=source)["phases"][0]
    # A transport capacity preview is an input to this generic diagnostics
    # function. This does not introduce an alternate in-game transport engine.
    phase["transport_services"] = [{"origin": origin, "destination": destination,
                                     "forward_capacity_t_per_day": 3.0,
                                     "reverse_capacity_t_per_day": 0.0,
                                     "reverse_path": [], "blockers": []}]
    phase["service_constraints"] += [
        {"node": node, "service": "cargo_transfer", "nominal_capacity_per_day": capacity,
         "required_per_day": 0.0, "nominal_gap_per_day": 0.0}
        for node, capacity in [(origin, 2.0), (destination, 1.5)]]
    from scripts.analysis_balance_network import trace_material_system
    network = trace_material_system(phase, {})
    options = [option for option in network["inter_node_resource_options"]
               if option["origin"] == origin and option["destination"] == destination
               and option["resource"] in {str(item.resource_id) for item in inputs}]
    assert len(options) == 2
    assert all(option["od_capacity_t_per_day"] == pytest.approx(3) for option in options)
    assert all(option["uncommitted_handling_t_per_day"] == pytest.approx(1.5) for option in options)
    assert all(option["transport_and_handling_upper_bound_t"] == pytest.approx(min(
        option["resource_overlap_upper_bound_t"], 15)) for option in options)
    # Distinct resources cannot each be promised 15t of delivery; there is
    # one shared 15t handling envelope at the receiving Node for this period.
    assert all(option["status"] == "independent_conditional_bound_not_an_allocation"
               for option in options)


def test_node_scoped_research_and_freight_draw_one_registered_service_pool():
    """Research capacity is the installed owner's Service supply, net of competing duty."""
    from dataclasses import replace
    from space_idle.execution_requirements import ServiceCapacityRequirement
    from space_idle.service_capacity import ServiceCapacityScope

    app = build_game_application_for_load()
    sim = app._simulation
    facility = next(f for f in sim.facilities.definitions.values()
                    if any(s.service_type == "cargo_transfer" for s in f.service_capacity_supplies))
    capacity = next(s.nominal_rate for s in facility.service_capacity_supplies
                    if s.service_type == "cargo_transfer")
    technology = next(iter(sim.research.definitions.values()))
    stage = technology.stage_specs[0]
    service = ServiceCapacityRequirement(
        "cargo_transfer", 0.005, scope=ServiceCapacityScope.OPERATIONAL_NODE)
    sim.research.definitions[technology.id] = replace(
        technology, stage_specs=(replace(stage, execution_requirements=(
            *stage.execution_requirements, service)), *technology.stage_specs[1:]))
    node, receiver, days = "research-and-freight", "freight-destination", 8
    resource = str(next(iter(app._catalog.resources)))
    selected = {"node": node, "facility": str(facility.id), "units": 1}
    phase = evaluate({"initial_facilities": [selected],
                      "initial_stock": [{"node": node, "resource": resource, "amount_t": 100}],
                      "phases": [{"name": "shared", "days": days, "facilities": [selected],
                                  "research_stages": [{"node": node,
                                                       "research": str(technology.id),
                                                       "stage": stage.stage_id}],
                                  "transfers": [{"origin": node, "destination": receiver,
                                                 "resource": resource, "t_per_day": 1}]}]},
                     app=app)["phases"][0]
    research = next(row for row in phase["research_service_constraints"]
                    if row["scope"] == f"node:{node}" and row["service"] == "cargo_transfer")
    assert research["nominal_capacity_per_day"] == pytest.approx(capacity)
    assert research["nominal_capacity_remaining_after_other_activities_per_day"] == pytest.approx(capacity - 1)
    assert research["conditional_lower_bound_days_after_other_activities"] == pytest.approx(
        research["total_required"] / (capacity - 1))
    handling = next(row for row in phase["service_constraints"]
                    if row["node"] == node and row["service"] == "cargo_transfer")
    assert handling["nominal_capacity_per_day"] == pytest.approx(capacity)
    assert handling["required_per_day"] == pytest.approx(1 + research["total_required"] / days)


def test_registered_research_generations_link_time_capital_upkeep_and_maturity_without_state_mutation(source):
    """Across the entire catalog, days are conditional quantities, not a prescribed research route."""
    from scripts.analysis_balance_research import evaluate_research_generations
    from math import isfinite
    from space_idle.shared import DefinitionId

    sim = source._simulation
    before = deepcopy(capture_state(sim))
    study = evaluate_research_generations(app=source, horizon_days=(15, 150))
    stages = {definition.progression_stage for definition in sim.research.definitions.values()
              if definition.progression_stage is not None}
    assert {entry['goal']['progression_stage'] for entry in study['generations']} == stages
    for generation in study['generations']:
        goal = generation['goal']
        assert goal['theory_research_point_demand'] == pytest.approx(sum(
            getattr(spec, 'research_point_cost', 0)
            for identifier in goal['research_ids']
            for spec in sim.research.definitions[DefinitionId(identifier)].stage_specs))
        demands = {(row['scope'], row['service']): row['total_work']
                   for row in goal['research_stage_service_work']}
        execution_demand = demands.get(('ORGANIZATION', 'research_execution'), 0)
        for choice in generation['provider_choices']:
            if choice['rp_generation_per_day'] > 0:
                assert choice['rp_generation_lower_bound_days'] == pytest.approx(
                    goal['theory_research_point_demand'] / choice['rp_generation_per_day'])
            if choice['research_execution_capacity_per_day'] > 0:
                assert choice['research_execution_lower_bound_days'] == pytest.approx(
                    execution_demand / choice['research_execution_capacity_per_day'])
            days = choice['operating_lower_bound_days_excluding_unassessed_dependencies']
            if days is not None and choice['source_maintenance_resource_per_day_t'] is not None:
                assert days >= choice['rp_generation_lower_bound_days']
                assert days >= choice['research_execution_lower_bound_days']
                for resource, rate in choice['source_maintenance_resource_per_day_t'].items():
                    assert choice['maintenance_for_goal_rp_generation_t'][resource] == pytest.approx(rate * days)
            for h in choice['horizon_sensitivity']:
                assert h['days'] in (15, 150)
                if h['minimum_provider_units_capacity_only'] is not None:
                    count = h['minimum_provider_units_capacity_only']
                    assert count * h['days'] * choice['rp_generation_per_day'] / choice['source_units'] >= (
                        goal['theory_research_point_demand'] - 1e-6)
                    assert count * h['days'] * choice['research_execution_capacity_per_day'] / choice['source_units'] >= (
                        execution_demand - 1e-6)
            assert all(isfinite(v) for v in choice['construction_resource_t'].values())
    assert capture_state(sim) == before


def test_finite_science_rp_can_replace_nominal_provider_demand_only_conditionally(source):
    from scripts.analysis_balance_research import analyze_research_goal
    sim = source._simulation
    stage = min(d.progression_stage for d in sim.research.definitions.values()
                if d.progression_stage is not None)
    campaign = next(iter(sim.scientific_exploration.definitions.values()))
    before = analyze_research_goal(progression_stage=stage, app=source)
    science = analyze_research_goal(progression_stage=stage,
                                    selected_science_campaigns=(str(campaign.id),), app=source)
    assert science['goal']['theory_research_point_demand'] == before['goal']['theory_research_point_demand']
    assert science['goal']['conditionally_credited_science_rp'] == pytest.approx(campaign.research_points_total)
    assert science['goal']['remaining_nominal_rp_from_provider_if_science_settles'] == pytest.approx(
        max(0, before['goal']['theory_research_point_demand'] - campaign.research_points_total))
    for original, changed in zip(before['provider_choices'], science['provider_choices']):
        assert original['provider'] == changed['provider']
        if changed['rp_generation_lower_bound_days'] is not None and original['rp_generation_lower_bound_days'] is not None:
            assert changed['rp_generation_lower_bound_days'] <= original['rp_generation_lower_bound_days']
        else:
            assert changed['rp_generation_lower_bound_days'] is None or original['rp_generation_lower_bound_days'] is None
        assert changed['research_execution_lower_bound_days'] == original['research_execution_lower_bound_days']
    assert any('movement' in note for note in science['model_limitations'])


def test_research_branch_pacing_uses_real_prerequisite_closure_and_parallel_site_work(source):
    """Multiple projects' independent demonstration work cannot be added as elapsed days."""
    from dataclasses import replace
    from scripts.analysis_balance_research import analyze_research_goal
    sim = source._simulation
    independent = [d for d in sim.research.definitions.values() if not d.prerequisites]
    sample = next(s for d in sim.research.definitions.values()
                  for s in d.stage_specs if s.stage_type.value == 'prototype')
    assert len(independent) >= 2
    chosen = independent[:2]
    for i, definition in enumerate(chosen):
        existing = definition.stage_specs[0]
        assert existing.stage_type.value == 'theory'
        theory = replace(existing, research_point_cost=1.0)
        proto = replace(sample, stage_id='synthetic_parallel_prototype', required_work=8 + i * 6)
        sim.research.definitions[definition.id] = replace(definition, stage_specs=(theory, proto))
    analysis = analyze_research_goal(research_ids=[str(d.id) for d in chosen], app=source)
    assert analysis['goal']['serial_site_stage_work'] == pytest.approx(22)
    viable = 0
    for option in analysis['provider_choices']:
        if option['rp_generation_lower_bound_days'] is None or option['research_execution_capacity_per_day'] <= 0:
            assert option['operating_lower_bound_days_excluding_unassessed_dependencies'] is None
            continue
        viable += 1
        expected_serial = 14 + 1 / option['research_execution_capacity_per_day']
        assert option['selected_project_serial_stage_lower_bound_days'] == pytest.approx(expected_serial)
        assert option['operating_lower_bound_days_excluding_unassessed_dependencies'] == pytest.approx(
            max(expected_serial, option['rp_generation_lower_bound_days'],
                option['research_execution_lower_bound_days']))
    assert viable > 0


def test_cyclic_selected_material_chain_exposes_one_shared_symbolic_run_per_process():
    """Cyclic material accounting is a constrained system, never recursive free supply."""
    from types import SimpleNamespace
    from scripts.analysis_balance_network import conditional_material_paths
    from space_idle.shared import DefinitionId
    a, b = DefinitionId("test.cycle.a"), DefinitionId("test.cycle.b")
    first, second = DefinitionId("test.cycle.first"), DefinitionId("test.cycle.second")
    process_a = SimpleNamespace(id=first, inputs_per_day={b: .25}, outputs_per_day={a: 1.0})
    process_b = SimpleNamespace(id=second, inputs_per_day={a: .4}, outputs_per_day={b: 1.0})
    sim = SimpleNamespace(industry=SimpleNamespace(processes={first: process_a, second: process_b}))
    report = conditional_material_paths({str(a): 3}, sim,
        {str(a): [(process_a, 1.0, ())], str(b): [(process_b, 1.0, ())]}, {},
        {str(a): str(first), str(b): str(second)})
    assert not report["material_bill_complete"]
    assert len(report["selected_processes"]) == 2
    assert report["cyclic_selected_resource_paths"]
    assert len(report["conditional_simultaneous_resource_constraints"]) == 2
    assert report["gross_resource_requirements_t"] == {str(a): 3}
    assert all(r["external_supply"] == "requires_explicit_stock_extraction_process_or_OD_choice"
               for r in report["conditional_simultaneous_resource_constraints"])
