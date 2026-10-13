"""Whole-system balance contracts: registered coefficients, activity coupling and conditions.

Neither a static relation nor a nominal negative Stock authorizes an Activity.
Tests use registered Content but never a fixed facility count or balance target.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

import pytest

from scripts.analysis_balance import evaluate, evaluate_portfolio, summarize_portfolio
from scripts.analysis_balance_network import registered_activity_coefficients, registered_material_links
from space_idle.bootstrap import build_game_application_for_load
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.persistence import capture_state


@pytest.fixture(scope="module")
def source():
    return build_game_application_for_load()


def test_catalog_wide_coefficients_are_typed_definition_values_without_assumed_activity(source):
    sim = source._simulation
    graph = build_definition_dependency_graph(sim, source._catalog)
    matrix = {(row["method_kind"], row["method_definition"]): row
              for row in registered_activity_coefficients(graph)}
    links = registered_material_links(graph)
    for process in sim.industry.processes.values():
        entry = matrix[("process", str(process.id))]
        inputs = {row["other_id"]: row["quantity"] for row in entry["resource_inputs"]
                  if row["relation"] == "consumes_resource"}
        outputs = {row["other_id"]: row["quantity"] for row in entry["resource_outputs"]
                   if row["relation"] == "produces_resource"}
        assert inputs == {str(k): v for k, v in process.inputs_per_day.items()}
        assert outputs == {str(k): v for k, v in process.outputs_per_day.items()}
        assert all(r["time_basis"] == "per_execution_day" for r in entry["resource_outputs"])
    for method in sim.extraction.specs.values():
        output = str(method.output_resource_id)
        assert any(row["kind"] == "extraction_method" and row["definition"] == str(method.id)
                   for row in links[output]["potential_producers"])
    for tech in sim.research.definitions.values():
        for stage in tech.stage_specs:
            key = ("research_stage", f"{tech.id}/{stage.stage_id}")
            if hasattr(stage, "research_point_cost"):
                assert any(row["relation"] == "research_point_cost" and
                           row["quantity"] == pytest.approx(stage.research_point_cost)
                           for row in matrix[key]["other_typed_coefficients"])


def test_network_exposes_industrial_input_shortages_to_downstream_without_creating_flow(source):
    sim = source._simulation
    pairs = [(fac, process) for fac in sim.facilities.definitions.values()
             for process in sim.industry.processes.values()
             if process.inputs_per_day and process.outputs_per_day and
             process.required_capabilities <= {cap.id for cap in fac.capability_supplies}]
    fac, process = pairs[0]
    node = "comparison.node"
    row = {"node": node, "facility": str(fac.id), "units": 1,
           "process": str(process.id)}
    before = capture_state(sim)
    phase = evaluate({"initial_facilities": [row], "phases": [
        {"name": "selected_activity", "days": 5, "facilities": [row]}]}, app=source)["phases"][0]
    expected_outputs = {str(res) for res in process.outputs_per_day}
    for input_resource in process.inputs_per_day:
        relevant = next(value for value in phase["system_network"]["pressure_exposures"]
                        if value["node"] == node and value["resource"] == str(input_resource))
        assert str(process.id) in relevant["active_downstream_processes"]
        assert expected_outputs <= set(relevant["potentially_affected_outputs"])
        assert relevant["status"] == "possible_exposure_not_allocated_lost_output"
        # The operation's nominal production remains counted as notional, NOT
        # "achieved" output when an input is missing.
        assert all(v["production_t"] >= 0 for v in phase["resources"])
    assert capture_state(sim) == before


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


def test_portfolio_keeps_different_duration_compositions_independent(source):
    sim = source._simulation
    before = deepcopy(capture_state(sim))
    fac = next(f for f in sim.facilities.definitions.values() if sim.projects.recipes.get(f.id)
               and sim.projects.recipes[f.id].resources)
    node = "scenario.node"
    def selected(days):
        return {"phases": [{"name": "investment", "days": days,
                            "facilities": [{"node": node, "facility": str(fac.id), "units": 1}]}]}
    portfolio = evaluate_portfolio({"short": selected(3), "long": selected(30)}, app=source)
    assert [r["plan"] for r in portfolio["evaluations"]] == ["long", "short"]
    summary = summarize_portfolio(portfolio)
    assert len(summary["scenarios"]) == 2
    baseline_phase = summary["scenarios"][0]["cases"][0]["phases"][0]
    assert all("shortfall_without_assumed_arrivals_t" in item and
               "recurring_net_t_per_day" in item
               for item in baseline_phase["resource_pressures"])
    assert "od_transport" in baseline_phase
    assert [s["cases"][0]["phases"][0]["days"] for s in summary["scenarios"]] == [30, 3]
    assert "not_gameplay" in portfolio["portfolio_conditions"]
    assert portfolio["registered_activity_coefficients"]
    assert all(e["status"] == "possible_exposure_not_allocated_lost_output"
               for r in portfolio["pressure_exposure_index"] for e in r["conditions"])
    assert capture_state(sim) == before


def test_selected_process_chain_reveals_multistage_resource_exposure(source):
    """Output of a vulnerable process may itself supply further selected work."""
    sim = source._simulation
    pairs = [(fac, proc) for fac in sim.facilities.definitions.values()
             for proc in sim.industry.processes.values()
             if proc.inputs_per_day and proc.outputs_per_day and
             proc.required_capabilities <= {cap.id for cap in fac.capability_supplies}]
    chain = next(((fa, first, fb, second, overlap)
                  for fa, first in pairs for fb, second in pairs
                  if first.id != second.id
                  for overlap in first.outputs_per_day if overlap in second.inputs_per_day), None)
    assert chain is not None, "registered industrial Content must contain a connected Process chain"
    fa, first, fb, second, intermediate = chain
    node = "shared.industrial.node"
    assets = [{"node": node, "facility": str(fa.id), "units": 1, "process": str(first.id)},
              {"node": node, "facility": str(fb.id), "units": 1, "process": str(second.id)}]
    # If source facility is identical, two blocks represent selected dedicated
    # capacity, not two simultaneous Processes on one Facility unit.
    phase = evaluate({"initial_facilities": assets, "phases": [
        {"name": "connected_industry", "days": 4, "facilities": assets}]}, app=source)["phases"][0]
    raw = next(iter(first.inputs_per_day))
    exposure = next(row for row in phase["system_network"]["pressure_exposures"]
                    if row["node"] == node and row["resource"] == str(raw))
    assert str(first.id) in exposure["active_downstream_processes"]
    assert str(intermediate) in exposure["potentially_affected_outputs"]
    assert str(second.id) in exposure["active_downstream_processes"]
    assert {str(r) for r in second.outputs_per_day} <= set(exposure["potentially_affected_outputs"])
    # The output is a *possible* exposure, never subtracted from the sole
    # authoritative nominal ledger or credited as a guaranteed result.
    rows = {(row["node"], row["resource"]): row for row in phase["resources"]}
    assert rows[(node, str(intermediate))]["production_t"] > 0


def test_unconfirmed_arrival_does_not_make_downstream_input_assured(source):
    sim = source._simulation
    fac = next(f for f in sim.facilities.definitions.values()
               if sim.projects.recipes.get(f.id) and sim.projects.recipes[f.id].resources)
    resource = str(sim.projects.recipes[fac.id].resources[0].resource_id)
    receiver, sender = "receiver.node", "sender.node"
    planned = {"phases": [{"name": "unsettled_shipping", "days": 3,
                           "facilities": [{"node": receiver, "facility": str(fac.id), "units": 1}],
                           "transfers": [{"origin": sender, "destination": receiver,
                                          "resource": resource, "t_per_day": 1_000_000}]}]}
    phase = evaluate(planned, app=source)["phases"][0]
    row = next(row for row in phase["resources"]
               if row["node"] == receiver and row["resource"] == resource)
    assert row["notional_end_t"] > 0
    assert row["shortfall_without_assumed_arrivals_t"] > 0
    exposed = next(row for row in phase["system_network"]["pressure_exposures"]
                   if row["node"] == receiver and row["resource"] == resource)
    assert exposed["condition"] == "nominal_shortfall_without_assumed_arrivals"
    assert exposed["status"] == "possible_exposure_not_allocated_lost_output"
    assert phase["system_network"]["unresolved_transport_od"]


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
