"""Generic quantitative projection contracts; no Content strategy is a test oracle.

These tests check dimensional accounting from registered Definitions, not the
relative desirability of particular Facilities, generations or build orders.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

import pytest

from scripts.analysis_balance import (compare_cases, evaluate, evaluate_world_context_sweep,
                                      _bind_world_context, summarize_world_context_sweep)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.persistence import capture_state
from space_idle.shared import SurfaceCellId


@pytest.fixture(scope="module")
def definitions():
    return build_game_application_for_load()


def _rows(phase):
    return {(row["node"], row["resource"]): row for row in phase["resources"]}


def _compatible_processes(sim):
    for facility in sorted(sim.facilities.definitions.values(), key=lambda d: str(d.id)):
        capabilities = {s.id for s in facility.capability_supplies}
        for process in sorted(sim.industry.processes.values(), key=lambda d: str(d.id)):
            if process.required_capabilities <= capabilities:
                yield facility, process


def test_multiphase_resource_balance_and_transfer_do_not_perform_hidden_settlement(definitions):
    """All Resource kinds use the same accounting across phases and nodes."""
    facility, process = next((f, p) for f, p in _compatible_processes(definitions._simulation)
                             if p.inputs_per_day and p.outputs_per_day)
    # Transfers, including resources with finite special pools, never imply
    # actual Cargo settlement or automatic Facility investment.
    resources = sorted(str(key) for key in definitions._catalog.resources)
    a, b = "projection.origin", "projection.destination"
    asset = {"node": a, "facility": str(facility.id), "units": 1,
             "process": str(process.id)}
    plan = {"initial_facilities": [asset],
            "initial_stock": [{"node": a, "resource": resource, "amount_t": .1}
                              for resource in resources],
            "phases": [
                {"name": "existing", "days": 2, "facilities": [asset],
                 "facility_investments": [{"node": a, "facility": str(facility.id), "units": 1}],
                 "transfers": [{"origin": a, "destination": b, "resource": resource, "t_per_day": 4}
                               for resource in resources]},
                {"name": "expansion", "days": 5,
                 "facilities": [{**asset, "units": 2}],
                 "transfers": [{"origin": b, "destination": a, "resource": resource, "t_per_day": 1}
                               for resource in resources],
                 "external_rates": [{"node": b, "resource": resource, "net_t_per_day": -2}
                                    for resource in resources]},
            ]}
    result = evaluate(plan, app=definitions)
    prior_stock = defaultdict(float, {(a, resource): .1 for resource in resources})
    outstanding_receipts = defaultdict(float)
    assert "not settled Game flow" in " ".join(result["assumptions"])
    assert any(row["shortfall_t"] > 0 for phase in result["phases"] for row in phase["resources"])
    for phase in result["phases"]:
        current = _rows(phase)
        shipped = defaultdict(float)
        received = defaultdict(float)
        for key, row in current.items():
            assert row["start_t"] == pytest.approx(prior_stock[key])
            sources = (row["production_t"] + row["external_net_t"] + row["received_t"])
            needs = sum(row[field] for field in (
                "process_demand_t", "construction_demand_t", "maintenance_demand_t",
                "vehicle_build_demand_t", "research_material_demand_t", "life_support_demand_t",
                "shipped_t"))
            assert row["net_t"] == pytest.approx(sources - needs)
            assert row["notional_end_t"] == pytest.approx(row["start_t"] + row["net_t"])
            assert row["shortfall_t"] == pytest.approx(max(0, -row["notional_end_t"]))
            outstanding_receipts[key] += row["received_t"]
            assert row["cumulative_unverified_incoming_cargo_t"] == pytest.approx(outstanding_receipts[key])
            assert row["shortfall_without_assumed_arrivals_t"] == pytest.approx(max(
                0, outstanding_receipts[key] - row["notional_end_t"]))
            shipped[key[1]] += row["shipped_t"]
            received[key[1]] += row["received_t"]
        assert shipped == pytest.approx(received)
        prior_stock = defaultdict(float, {key: row["notional_end_t"] for key, row in current.items()})
    # Investment is debited in the earlier Phase; its Facility starts
    # contributing only after that Phase boundary.
    assert any(row["construction_demand_t"] > 0 for row in result["phases"][0]["resources"])
    assert all(row["construction_demand_t"] == 0 for row in result["phases"][1]["resources"])



def test_case_comparison_preserves_resource_deltas_without_fixed_targets(definitions):
    facility, process = next((f, p) for f, p in _compatible_processes(definitions._simulation)
                             if p.outputs_per_day)
    node = "comparison.node"
    def plan(units):
        asset = {"node": node, "facility": str(facility.id), "units": units,
                 "process": str(process.id)}
        return {"initial_facilities": [asset], "phases": [
            {"name": "period", "days": 5, "facilities": [asset]}]}
    base, increased = plan(1), plan(3)
    comparison = compare_cases({"cases": [{"name": "base", "plan": base},
                                          {"name": "different", "plan": increased}]}, app=definitions)
    assert comparison["baseline_case"] == "base"
    assert {c["name"] for c in comparison["cases"]} == {"base", "different"}
    first, second = (x["projection"]["phases"][0] for x in comparison["cases"])
    for resource, amount in process.outputs_per_day.items():
        delta = (_rows(second)[(node, str(resource))]["production_t"]
                 - _rows(first)[(node, str(resource))]["production_t"])
        assert delta == pytest.approx(2 * 5 * facility.process_throughput_per_day * amount)
        assert any(row["section"] == "resources"
                   and row["identity"] == {"node": node, "resource": str(resource)}
                   and row["delta_from_baseline"].get("production_t") == pytest.approx(delta)
                   for row in comparison["differences"])
    assert all(row["section"] != "aggregate_score" for row in comparison["differences"])
    assert compare_cases({"cases": [{"name": "a", "plan": base},
                                    {"name": "b", "plan": base}]}, app=definitions)["differences"] == []


def test_world_cell_extraction_scales_with_shared_opportunity_without_fake_site_state(definitions):
    """Selected real World cells change a pure physical bound, not actual Simulation state."""
    sim = definitions._simulation
    graph = sim.extraction.graph
    candidates = []
    for facility in sim.facilities.definitions.values():
        if not facility.extraction_capacity_t_per_day:
            continue
        for method in sim.extraction.compatible_methods(facility.id):
            for cell in graph.surface_cells.values():
                if cell.resource_potential_by_resource.get(method.resource_id, 0) > 0:
                    candidates.append((facility, method, cell))
    facility, method, cell = next((f, m, c) for f, m, c in candidates
                                   if sim.extraction.opportunity_for_cells(
                                       m.resource_id, (m,), (c.id,), 0,
                                       eligible=lambda _m, _c: True) > 0)
    node = "scenario.surface"
    initial = [{"node": node, "facility": str(facility.id), "units": 1,
                "extraction": str(method.id)}]
    knowledge = [{"cell": str(cell.id), "resource": str(method.resource_id), "level": 3}]
    def projection(units, with_knowledge):
        asset = {**initial[0], "units": units}
        return evaluate({"initial_facilities": [asset], "phases": [
            {"name": "physical", "days": 3, "facilities": [asset],
             "extraction_sites": [{"node": node, "developed_cells": [str(cell.id)],
                                   "knowledge": knowledge if with_knowledge else []}]}]},
                        app=definitions)["phases"][0]
    before = deepcopy(capture_state(sim))
    one = projection(1, True)
    two = projection(2, True)
    no_knowledge = projection(1, False)
    def produced(report):
        return _rows(report)[node, str(method.output_resource_id)]["production_t"]
    if method.minimum_knowledge_level is not None:
        assert produced(no_knowledge) == 0
    assert produced(two) > produced(one) > 0
    assert produced(two) < 2 * produced(one)
    assert two["extraction_world_context"][0]["world_cells"] == [str(cell.id)]
    assert "extraction_site_technology_service_and_stock_allocation" in two["unassessed_constraints"]
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match="non-surface World node"):
        evaluate({"phases": [{"name": "illegal", "days": 1, "facilities": [],
                  "extraction_sites": [{"node": str(next(iter(graph.nodes))),
                                        "developed_cells": [str(cell.id)]}]}]}, app=definitions)


def test_graph_provenance_is_attached_without_reinterpreting_relations_as_flow(definitions):
    sim = definitions._simulation
    facility, process = next((facility, process) for facility, process in _compatible_processes(sim)
                             if process.inputs_per_day)
    node = "graph.comparison"
    asset = {"node": node, "facility": str(facility.id), "units": 1,
             "process": str(process.id)}
    phase = evaluate({"initial_facilities": [asset], "phases": [
        {"name": "registered", "days": 1, "facilities": [asset]}]}, app=definitions)["phases"][0]
    evidence = phase["activity_sources"][0]["graph_evidence"]
    assert {root["kind"] for root in evidence["roots"]} == {"facility", "process"}
    assert any(r["kind"] == "consumes_resource" and r["provenance"] and r["unit"]
               for r in evidence["relations"])
    assert evidence["status"] == "typed_definition_dependencies_not_executed"
    assert "resources" in phase and "process_demand_t" in phase["resources"][0]


def test_fleet_research_provider_competes_for_held_units_and_uses_registered_levels(definitions):
    """A Fleet-backed research source is not also free Transport or Survey capacity."""
    sim = definitions._simulation
    fleet_providers = [p for p in sim.research.providers.values() if p.source_kind.value == "fleet"]
    for provider in fleet_providers:
        for vehicle in sim.research.compatible_vehicle_definitions(provider.id):
            node = "research.fleet.node"
            destination = "research.fleet.destination"
            level = provider.levels[0]
            allocation = {"node": node, "provider": str(provider.id),
                          "source_vehicle": str(vehicle.id), "units": 2, "level": level.level,
                          "duty": 0.6}
            base = {"initial_fleet": [{"node": node, "vehicle": str(vehicle.id), "units": 3}],
                    "phases": [{"name": "comparison", "days": 5, "facilities": [],
                                "research_provider_allocations": [allocation]}]}
            rp = evaluate(base, app=definitions)["phases"][0]["research_point_balance"]
            assert rp["nominal_generation_points"] == pytest.approx(2 * .6 * level.generation_points_per_day * 5)
            assert rp["nominal_storage_capacity_points"] == pytest.approx(2 * level.storage_capacity_points)
            assert rp["nominal_execution_per_day"] == pytest.approx(2 * .6 * level.research_execution_per_day)
            conflicting = deepcopy(base)
            conflicting["phases"][0]["transport_allocations"] = [{
                "origin": node, "destination": destination,
                "vehicle": str(vehicle.id), "units": 2}]
            with pytest.raises(ValueError, match="reuse Fleet holdings"):
                evaluate(conflicting, app=definitions)
            conflicting = deepcopy(base)
            conflicting["phases"][0]["research_provider_allocations"][0]["source_facility"] = str(vehicle.id)
            with pytest.raises(ValueError, match="exactly one typed source"):
                evaluate(conflicting, app=definitions)
            conflicting = deepcopy(base)
            conflicting["phases"][0]["fleet"] = [{
                "node": node, "vehicle": str(vehicle.id), "units": 3,
                "turnarounds_per_unit_per_day": .5}]
            with pytest.raises(ValueError, match="overlaps authored turnarounds"):
                evaluate(conflicting, app=definitions)


def test_one_fleet_budget_covers_science_survey_founding_passenger_and_cargo(definitions):
    """Selected Fleet turnarounds cannot be reused by any other owner-specific activity."""
    sim = definitions._simulation
    vehicles = list(sim.transport.vehicle_definitions())
    cell, resource = next(iter(sim.survey.targets))
    scenarios = []
    for campaign in sim.scientific_exploration.definitions.values():
        if campaign.required_units and vehicles:
            vehicle = vehicles[0]
            scenarios.append((str(campaign.origin_id), str(vehicle.id), campaign.required_units,
                              {"science_campaigns": [{"campaign": str(campaign.id),
                                                       "vehicle": str(vehicle.id)}]}))
            break
    for provider in sim.survey.providers.values():
        if provider.source_kind.value != "fleet":
            continue
        compatible = next(((v, mode) for v in vehicles for mode in provider.observation_modes
                           if sim.survey.source_supports_mode(provider, mode, v.id)), None)
        if compatible is not None:
            vehicle, mode = compatible
            node = "survey.vehicle.source"
            scenarios.append((node, str(vehicle.id), mode.minimum_source_units,
                              {"survey_activities": [{
                                  "node": node, "provider": str(provider.id),
                                  "source": str(vehicle.id), "mode": str(mode.id),
                                  "units": mode.minimum_source_units,
                                  "cell": str(cell), "resource": str(resource),
                              }]}))
            break
    if sim.founding.deployment_recipes and vehicles:
        recipe = next(iter(sim.founding.deployment_recipes.values()))
        vehicle = vehicles[0]
        scenarios.append(("founding.vehicle.source", str(vehicle.id), recipe.required_units,
                          {"founding_projects": [{"staging_node": "founding.vehicle.source",
                                                  "recipe": str(recipe.id),
                                                  "target_cell": str(cell),
                                                  "vehicle": str(vehicle.id)}]}))
    passenger_vehicle = next((vehicle for vehicle in vehicles if vehicle.passengers.seats), None)
    if passenger_vehicle is not None:
        scenarios.append(("passenger.vehicle.source", str(passenger_vehicle.id), 1,
                          {"passenger_transfers": [{
                              "origin": "passenger.vehicle.source", "destination": "passenger.destination",
                              "vehicle": str(passenger_vehicle.id), "units": 1,
                              "people": 1, "assumed_onboard_days": 2,
                          }]}))
    for node, vehicle, units, activity in scenarios:
        fleet = {"node": node, "vehicle": vehicle, "units": units}
        phase = {"name": "parallel", "days": 5, "facilities": [],
                 "fleet": [{**fleet, "turnarounds_per_unit_per_day": .2}], **activity}
        with pytest.raises(ValueError, match="overlaps authored turnarounds"):
            evaluate({"initial_fleet": [fleet], "phases": [phase]}, app=definitions)


def test_research_upgrade_investment_and_actual_selected_level_share_one_phase_ledger(definitions):
    """An upgrade is paid before, not inferred as, a higher installed Provider Level."""
    sim = definitions._simulation
    provider = next(p for p in sim.research.providers.values()
                    if p.source_kind.value == "facility" and len(p.levels) > 1)
    facility = next(f for f in sim.facilities.definitions.values()
                    if provider.accepts_source(cap.id for cap in f.capability_supplies)
                    and (f.id, 2) in sim.projects.upgrade_recipes)
    node = "research.level.test"
    base = {"node": node, "facility": str(facility.id), "units": 1}

    def research(level):
        return [{"node": node, "provider": str(provider.id), "source_facility": str(facility.id),
                 "units": 1, "level": level}]

    def plan(after_level=2):
        later = {**base, "level": after_level}
        return {"initial_facilities": [base], "phases": [
            {"name": "investment", "days": 5, "facilities": [base],
             "upgrade_projects": [{"node": node, "facility": str(facility.id),
                                   "target_level": 2, "units": 1}],
             "research_provider_allocations": research(1)},
            {"name": "operations", "days": 10, "facilities": [later],
             "research_provider_allocations": research(after_level)},
        ]}

    base_result, enhanced = (evaluate(plan(level), app=definitions)["phases"]
                             for level in (1, 2))
    invested, operations = enhanced
    assert invested["research_point_balance"]["nominal_generation_points"] == pytest.approx(
        provider.level_spec(1).generation_points_per_day * 5)
    assert operations["research_point_balance"]["nominal_generation_points"] == pytest.approx(
        provider.level_spec(2).generation_points_per_day * 10)
    assert operations["research_point_balance"]["nominal_storage_capacity_points"] == pytest.approx(
        provider.level_spec(2).storage_capacity_points)
    assert operations["research_point_balance"]["nominal_execution_per_day"] == pytest.approx(
        provider.level_spec(2).research_execution_per_day)
    recipe = sim.projects.upgrade_recipes[(facility.id, 2)]
    for req in recipe.resources:
        invested_resources = {(row["node"], row["resource"]): row
                              for row in invested["resources"]}
        assert invested_resources[(node, str(req.resource_id))]["construction_demand_t"] >= req.amount_t
    unupgraded_maintenance = sum(row["maintenance_demand_t"] for row in base_result[1]["resources"])
    upgraded_maintenance = sum(row["maintenance_demand_t"] for row in operations["resources"])
    expected_upkeep = sim.facilities.maintenance_requirements_for_investment(
        facility.id, {req.resource_id: req.amount_t for req in recipe.resources})
    assert upgraded_maintenance - unupgraded_maintenance == pytest.approx(
        10 * sum(expected_upkeep.values()))

    premature = plan()
    premature["phases"][0]["facilities"] = [{**base, "level": 2}]
    with pytest.raises(ValueError, match="prior upgrades"):
        evaluate(premature, app=definitions)
    missing = plan()
    missing["phases"][0].pop("upgrade_projects")
    with pytest.raises(ValueError, match="prior upgrades"):
        evaluate(missing, app=definitions)
    unselected = plan()
    unselected["phases"][1]["research_provider_allocations"] = research(1)
    with pytest.raises(ValueError, match="at its selected Level"):
        evaluate(unselected, app=definitions)

    # The same upgraded holdings may instead be explicitly present initially:
    # no artificial construction phase is required for a sunk starting asset.
    initial = {"initial_facilities": [{**base, "level": 2}], "phases": [
        {"name": "already_owned", "days": 10, "facilities": [{**base, "level": 2}],
         "research_provider_allocations": research(2)}]}
    assert evaluate(initial, app=definitions)["phases"][0]["research_point_balance"][
        "nominal_generation_points"] == pytest.approx(provider.level_spec(2).generation_points_per_day * 10)


def test_registered_cross_domain_activity_provenance_and_comparison_is_content_driven(definitions):
    """The same ledger follows active Process, research, Vehicle investment and upkeep.

    This contract does not depend on a checked-in Facility composition or a
    prescribed scale. New registered coefficients must change the same ledger.
    """
    sim = definitions._simulation
    facility, process = next((f, p) for f, p in _compatible_processes(sim)
                             if p.inputs_per_day and p.outputs_per_day)
    vehicle = next(v for v in sim.transport.vehicle_definitions() if v.production)
    tech = next(iter(sim.research.definitions.values()))
    node = "generic.production"
    asset = {"node": node, "facility": str(facility.id), "units": 1,
             "process": str(process.id), "duty": .5}
    plan = {"initial_facilities": [asset], "phases": [{
        "name": "selected_activity", "days": 7, "facilities": [asset],
        "vehicle_builds": [{"node": node, "vehicle": str(vehicle.id), "units": 1}],
        "research_stages": [{"node": node, "research": str(tech.id),
                             "stage": tech.stage_specs[0].stage_id}],
    }]}
    before = deepcopy(capture_state(sim))
    projection = evaluate(plan, app=definitions)["phases"][0]
    contributed = defaultdict(float)
    dimensions = ("production_t", "process_demand_t", "maintenance_demand_t",
                  "construction_demand_t", "vehicle_build_demand_t",
                  "fleet_turnaround_demand_t", "transport_service_demand_t",
                  "research_material_demand_t", "science_material_demand_t",
                  "founding_payload_demand_t", "passenger_provisions_demand_t",
                  "life_support_demand_t", "external_net_t", "shipped_t", "received_t")
    for item in projection["resource_contributions"]:
        assert item["origin_definition"] and item["quantity_basis"]
        assert item["dimension"] in dimensions
        contributed[item["node"], item["resource"], item["dimension"]] += item["amount_t"]
    for row in projection["resources"]:
        for dimension in dimensions:
            assert contributed[(row["node"], row["resource"], dimension)] == pytest.approx(
                row[dimension], abs=1e-9)
    service_contributed = defaultdict(float)
    for item in projection["service_contributions"]:
        assert item["origin_definition"] and item["quantity_basis"]
        service_contributed[item["node"], item["service"], item["role"]] += item["rate_per_day"]
    for row in projection["service_constraints"]:
        assert service_contributed[row["node"], row["service"], "demand"] == pytest.approx(row["required_per_day"])
        assert service_contributed[row["node"], row["service"], "nominal_supply"] == pytest.approx(row["nominal_capacity_per_day"])
    # Workload alternatives are the same quantity evaluation as the single
    # plan, not a separate Research goal/economy recomputation.
    second = deepcopy(plan)
    second["phases"][0]["facilities"][0]["duty"] = .75
    comparison = compare_cases({"cases": [
        {"name": "first", "plan": plan}, {"name": "second", "plan": second}]}, app=definitions)
    assert comparison["cases"][0]["projection"]["phases"][0] == projection
    assert comparison["cases"][1]["projection"]["phases"][0] != projection
    assert comparison["differences"]
    assert capture_state(sim) == before


def test_typed_research_stages_include_shared_execution_demand_beyond_theory(definitions):
    """Prototype and Demonstration share finite Research execution with Theory."""
    from space_idle.execution_requirements import ServiceCapacityRequirement
    sim = definitions._simulation
    stages = [(str(r.id), s) for r in sim.research.definitions.values() for s in r.stage_specs
              if getattr(s, "required_work", 0) > 0 and any(
                  isinstance(req, ServiceCapacityRequirement) and
                  req.scope.value == "ORGANIZATION" and req.service_type == "research_execution"
                  for req in s.execution_requirements)]
    assert stages  # A registered typed stage, not a fabricated work requirement.
    research_id, stage = stages[0]
    theory = sim.research.definitions[next(r for r in sim.research.definitions if str(r) == research_id)].stage_specs[0]
    provider = next(p for p in sim.research.providers.values() if p.source_kind.value == "facility"
                    and p.levels[0].research_execution_per_day > 0)
    facility = next(f for f in sim.facilities.definitions.values()
                    if provider.accepts_source(cap.id for cap in f.capability_supplies))
    asset = {"node": "research.node", "facility": str(facility.id), "units": 1}
    rate = provider.levels[0].research_execution_per_day
    phase = evaluate({"initial_facilities": [asset], "phases": [{
        "name": "registered stage contract", "days": 10, "facilities": [asset],
        "research_provider_allocations": [{"node": asset["node"], "provider": str(provider.id),
                                           "source_facility": str(facility.id), "units": 1}],
        "research_stages": [
            {"node": asset["node"], "research": research_id, "stage": theory.stage_id},
            {"node": asset["node"], "research": research_id, "stage": stage.stage_id}],
    }]}, app=definitions)["phases"][0]
    expected_work = 0.0
    for spec in (theory, stage):
        for req in spec.execution_requirements:
            if isinstance(req, ServiceCapacityRequirement) and req.scope.value == "ORGANIZATION" and req.service_type == "research_execution":
                expected_work += req.amount_per_execution * (getattr(spec, "research_point_cost", 0) or spec.required_work)
    research = phase["research_point_balance"]
    assert research["total_research_execution_work"] == pytest.approx(expected_work)
    assert research["total_execution_capacity_lower_bound_days"] == pytest.approx(expected_work / rate)
    assert phase["research_service_constraints"] == [{
        "scope": "organization", "service": "research_execution", "total_required": expected_work,
        "nominal_capacity_per_day": rate,
        "conditional_lower_bound_days": pytest.approx(expected_work / rate),
        "status": "conditional_shared_organization_capacity",
    }]


def test_world_opportunity_shared_across_distinct_method_outputs():
    """New registered Method outputs must not each acquire the full shared raw opportunity."""
    from dataclasses import replace
    from space_idle.shared import DefinitionId

    app = build_game_application_for_load()
    sim = app._simulation
    raw = next(m for m in sim.extraction.specs.values() if str(m.id).endswith("crust_mineral"))
    other_resource = next(r for r in app._catalog.resources if r != raw.output_resource_id)
    new_id = DefinitionId("test.extraction.alternate_output")
    sim.extraction.specs[new_id] = replace(raw, id=new_id, output_resource_id=other_resource)
    facility = next(f for f in sim.facilities.definitions.values() if f.extraction_capacity_t_per_day > 0
                    and raw.required_capabilities <= {c.id for c in f.capability_supplies})
    node = "base.location.earth_industrial"
    cell = next(c for c, spec in sim.extraction.graph.surface_cells.items()
                if str(c).endswith("earth.industrial_core"))
    facilities = [{"node": node, "facility": str(facility.id), "units": 1,
                   "extraction": str(mid)} for mid in (raw.id, new_id)]
    data = {"initial_facilities": facilities, "phases": [{
        "name": "two distinct outputs from one raw opportunity", "days": 7,
        "facilities": facilities,
        "extraction_sites": [{"node": node, "developed_cells": [str(cell)],
                              "knowledge": [{"cell": str(cell), "resource": str(raw.resource_id),
                                             "level": 3}]}],
    }]}
    result = evaluate(data, app=app)["phases"][0]
    outputs = {row["resource"]: row["production_t"] for row in result["resources"]
               if row["production_t"] > 0}
    contexts = result["extraction_world_context"]
    assert set(outputs) == {str(raw.output_resource_id), str(other_resource)}
    assert len(contexts) == 2
    assert all(c["effective_opportunity"] == pytest.approx(contexts[0]["effective_opportunity"]) for c in contexts)
    assert sum(outputs.values()) == pytest.approx(sum(c["diminishing_output_t_per_day"] * 7 for c in contexts))
    assert outputs[str(raw.output_resource_id)] > 0 and outputs[str(other_resource)] > 0
    assert outputs[str(raw.output_resource_id)] == pytest.approx(outputs[str(other_resource)])


def test_investment_and_operating_resource_pressures_reconcile_with_actual_definition_ledger(definitions):
    """A single ledger must distinguish capital, sustained throughput and finite opening Stock."""
    from scripts.analysis_balance import summarize_projection

    sim = definitions._simulation
    facility, process = next((f, p) for f, p in _compatible_processes(sim)
                             if p.inputs_per_day and not set(p.inputs_per_day) <= set(p.outputs_per_day))
    resource = str(next(res for res in process.inputs_per_day if res not in process.outputs_per_day))
    node, days = "sensitivity.stock", 12
    asset = {"node": node, "facility": str(facility.id), "units": 2,
             "process": str(process.id), "duty": .75}
    starting_stock = 30.0
    evaluation = evaluate({"initial_facilities": [asset],
                           "initial_stock": [{"node": node, "resource": resource,
                                              "amount_t": starting_stock}],
                           "phases": [{"name": "active", "days": days, "facilities": [asset]}]},
                          app=definitions)
    phase = evaluation["phases"][0]
    for row in phase["resources"]:
        investment = sum(row[key] for key in (
            "construction_demand_t", "vehicle_build_demand_t", "research_material_demand_t",
            "science_material_demand_t", "founding_payload_demand_t"))
        assert row["one_time_investment_and_activity_demand_t"] == pytest.approx(investment)
        assert row["nominal_recurring_net_t_per_day"] * days == pytest.approx(
            row["net_t"] + investment)
        if row["nominal_recurring_net_t_per_day"] < -1e-12 and row["start_t"] >= investment:
            assert row["conditional_stock_exhaustion_days_after_investment"] == pytest.approx(
                (row["start_t"] - investment) / -row["nominal_recurring_net_t_per_day"])
        else:
            assert row["conditional_stock_exhaustion_days_after_investment"] is None
    starving = _rows(phase)[(node, resource)]
    assert starving["nominal_recurring_net_t_per_day"] < 0
    summary = summarize_projection(evaluation)["phases"][0]
    assert any(row["node"] == node and row["resource"] == resource
               for row in summary["recurring_resource_pressures_by_node"])
    # No actual inventory, lifecycle transition or additional Resource Source is generated.
    assert all(item["origin_kind"] != "automatic_supply" for item in phase["resource_contributions"])


def test_spatial_investment_sensitivity_is_definition_derived_and_does_not_develop_a_cell(definitions):
    """Changing prospective World opportunity also carries its *separate* development bill.

    A cell's eligibility and project completion remain unassessed; neither is
    made into State by adding the registered one-time construction burden.
    """
    from scripts.analysis_balance import compare_cases

    sim = definitions._simulation
    recipe = next(iter(sim.projects.spatial_recipes.values()))
    node = "hypothetical.surface"
    base = {"phases": [{"name": "invest", "days": 60, "facilities": []}]}
    addition = {"collection": "spatial_projects", "action": "add", "phase": "invest",
                "row": {"node": node, "recipe": str(recipe.id), "units": 2}}
    before = deepcopy(capture_state(sim))
    results = compare_cases({"base_plan": base, "cases": [
        {"name": "without development"},
        {"name": "with registered development", "updates": [addition]},
    ]}, app=definitions)
    left = results["cases"][0]["projection"]["phases"][0]
    right = results["cases"][1]["projection"]["phases"][0]
    item, = right["spatial_projects"]
    assert item["required_construction_work"] == pytest.approx(recipe.construction_work * 2)
    assert item["status"] == "project_and_cell_eligibility_unassessed"
    assert right["investment_constraints"][0]["pre_investment_work_lower_bound_days"] is None
    assert "spatial_target_site_cell_knowledge_and_finite_construction_allocation" in right["unassessed_constraints"]
    for resource in recipe.resources:
        row = _rows(right)[(node, str(resource.resource_id))]
        assert row["construction_demand_t"] == pytest.approx(resource.amount_t * 2)
        assert any(source["origin_kind"] == "spatial_development" and
                   source["origin_definition"] == str(recipe.id)
                   for source in right["resource_contributions"])
    assert not left["spatial_projects"]
    assert any(row["section"] == "spatial_projects" for row in results["differences"])
    assert capture_state(sim) == before


def test_research_and_economy_cli_share_one_composition_contract(definitions, tmp_path, monkeypatch, capsys):
    """Registered Technology goals and economic choices use one Phase ledger.

    Research goals and other activities share the Phase ledger; alternative
    time horizons are explicitly marked incomparable for direct quantity deltas.
    """
    import json
    import sys
    from scripts.analysis_balance import main
    from space_idle.research_models import ResearchTheoryStageSpec

    sim = definitions._simulation
    source = next(definition for definition in sim.research.definitions.values()
                  if any(isinstance(stage, ResearchTheoryStageSpec) for stage in definition.stage_specs))
    stage = next(stage for stage in source.stage_specs if isinstance(stage, ResearchTheoryStageSpec))
    original_stage_specs = deepcopy(source.stage_specs)
    research_id = str(source.id)
    inputs = []
    for name, days in (("first", 3), ("second", 15)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"phases": [{"name": "activity", "days": days,
            "facilities": [], "research_goal": {"node": "comparison.research.site",
            "research_ids": [research_id]}}]}), encoding="utf-8")
        inputs.append(path)

    monkeypatch.setattr(sys, "argv", ["analysis_balance.py", str(inputs[0])])
    main()
    single = json.loads(capsys.readouterr().out)
    phase = single["phases"][0]
    assert phase["research_goal"]["included_technologies"] == [research_id]
    assert phase["research_time_structure"]
    assert any(row["kind"] == "research_selected_workload" for row in phase["time_constraints"])
    assert sum(row["rp_points"] for row in phase["selected_research_stage_requirements"]) == pytest.approx(
        phase["research_point_balance"]["research_stage_demand_points"])
    assert all("conditional_service_lower_bound_days" in row
               for row in phase["selected_research_stage_requirements"])
    assert "selected_stage_service_bounds" not in phase["research_time_structure"]

    # Alternative research horizons belong in the same case-comparison entry,
    # not a batch report that cannot justify cross-condition deltas.
    cases = tmp_path / "alternatives.json"
    cases.write_text(json.dumps({"cases": [
        {"name": "first", "plan": json.loads(inputs[0].read_text(encoding="utf-8"))},
        {"name": "second", "plan": json.loads(inputs[1].read_text(encoding="utf-8"))},
    ]}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["analysis_balance.py", str(cases)])
    main()
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["baseline_case"] == "first"
    assert comparison["cases"][0]["summary"]["phases"][0] == phase
    assert comparison["cases"][1]["incomparable_phase_basis"] is True

    changed = tmp_path / "definition_changes.json"
    changed.write_text(json.dumps([{
        "kind": "research", "id": research_id,
        "selector": {"stage_id": stage.stage_id}, "field": "stage_specs.research_point_cost",
        "value": stage.research_point_cost * 1.3,
    }]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["analysis_balance.py", str(inputs[0]),
                                     "--content-variant", str(changed)])
    main()
    adjusted = json.loads(capsys.readouterr().out)
    assert adjusted["phases"][0]["research_point_balance"]["research_stage_demand_points"] == pytest.approx(
        phase["research_point_balance"]["research_stage_demand_points"] + stage.research_point_cost * .3)
    assert sim.research.definitions[source.id].stage_specs == original_stage_specs


def test_registered_goal_closure_enters_the_physical_ledger_without_claiming_progress(definitions):
    """A selected Technology goal and authored stages have identical physical bills."""
    sim = definitions._simulation
    tech = next(iter(sim.research.definitions.values()))
    tech_id, node = str(tech.id), "comparison.research.site"
    full = {"phases": [{"name": "work", "days": 37, "facilities": [],
                        "research_goal": {"node": node, "research_ids": [tech_id],
                                          "include_prerequisites": True}}]}
    from scripts.analysis_balance_research import research_goal_closure
    included = research_goal_closure(sim.research.definitions, (tech_id,),
                                      include_prerequisites=True)
    explicit = deepcopy(full)
    del explicit["phases"][0]["research_goal"]
    explicit["phases"][0]["research_stages"] = [
        {"node": node, "research": identifier, "stage": stage.stage_id}
        for identifier in included
        for stage in sim.research.definitions[identifier].stage_specs]
    before = deepcopy(capture_state(sim))
    goal, authored = (evaluate(plan, app=definitions)["phases"][0]
                      for plan in (full, explicit))
    assert goal["research_goal"]["included_technologies"] == list(included)
    assert goal["resource_contributions"] == authored["resource_contributions"]
    assert goal["research_service_constraints"] == authored["research_service_constraints"]
    assert goal["research_point_balance"] == authored["research_point_balance"]
    assert "research_goal_stage_order_unlock_and_site_not_scheduled" in goal["unassessed_constraints"]
    assert capture_state(sim) == before
    duplicate = deepcopy(full)
    duplicate["phases"][0]["research_stages"] = [explicit["phases"][0]["research_stages"][0]]
    with pytest.raises(ValueError, match="duplicate Research Stage"):
        evaluate(duplicate, app=definitions)


def test_content_impact_uses_composition_comparison_and_registered_stage_demand(definitions):
    """An edited registered Stage changes its research and resource accounting."""
    from scripts.analysis_balance import compare_content_variant
    from space_idle.research_models import ResearchTheoryStageSpec
    sim = definitions._simulation
    tech = next(definition for definition in sim.research.definitions.values()
                if any(isinstance(spec, ResearchTheoryStageSpec) for spec in definition.stage_specs))
    stage = next(s for s in tech.stage_specs if isinstance(s, ResearchTheoryStageSpec))
    delta = max(1.0, stage.research_point_cost * .23)
    change = [{"kind": "research", "id": str(tech.id),
               "selector": {"stage_id": stage.stage_id}, "field": "stage_specs.research_point_cost",
               "value": stage.research_point_cost + delta}]
    provider, facility = next((provider, facility)
                              for provider in sim.research.providers.values()
                              for facility in sim.facilities.definitions.values()
                              if provider.source_kind.value == 'facility'
                              and provider.levels[0].generation_points_per_day > 0
                              and provider.levels[0].research_execution_per_day > 0
                              and provider.accepts_source(
                                  capability.id for capability in facility.capability_supplies))
    asset = {'node': 'hypothetical.site', 'facility': str(facility.id), 'units': 1}
    plan = {"initial_facilities": [asset], "phases": [{
        "name": "research", "days": 31, "facilities": [asset],
        "research_provider_allocations": [{
            "node": asset['node'], "provider": str(provider.id),
            "source_facility": str(facility.id), "units": 1}],
        "research_goal": {"node": asset['node'], "research_ids": [str(tech.id)]}}]}
    before = deepcopy(capture_state(sim))
    record = compare_content_variant(plan, change, summary=False)
    changes = record["comparisons"][0]["differences"]
    assert any(r["section"] == "research_point_balance"
               and r["delta_from_baseline"].get("research_stage_demand_points") == pytest.approx(delta)
               for r in changes)
    assert any(r["section"] == "research_stages"
               and r["delta_from_baseline"].get("point_cost") == pytest.approx(delta)
               for r in changes)
    assert any(r['section'] == 'research_time_structure'
               and r['delta_from_baseline'].get('shared_rp_generation_lower_bound_days')
               == pytest.approx(delta / provider.levels[0].generation_points_per_day)
               for r in changes)
    assert any(r['section'] == 'time_constraints'
               and r['identity']['kind'] == 'research_selected_workload'
               for r in changes)
    assert capture_state(sim) == before


def test_content_impact_handles_independent_alternative_cases(definitions):
    from scripts.analysis_balance import compare_content_variant
    from space_idle.research_models import ResearchTheoryStageSpec
    tech = next(v for v in definitions._simulation.research.definitions.values()
                if any(isinstance(s, ResearchTheoryStageSpec) for s in v.stage_specs))
    stage = next(s for s in tech.stage_specs if isinstance(s, ResearchTheoryStageSpec))
    delta = max(1.0, stage.research_point_cost / 10)
    edit = [{"kind": "research", "id": str(tech.id),
             "selector": {"stage_id": stage.stage_id}, "field": "stage_specs.research_point_cost",
             "value": stage.research_point_cost + delta}]
    plan = {"cases": [{"name": "industry-only", "plan": {
        "phases": [{"name": "operation", "days": 17, "facilities": []}]}},
        {"name": "selected-research", "plan": {
        "phases": [{"name": "operation", "days": 17, "facilities": [],
                    "research_goal": {"node": "selected.site", "research_ids": [str(tech.id)]}}]}}]}
    report = compare_content_variant(plan, edit, summary=True)
    assert len(report["comparisons"]) == 2
    assert report["comparisons"][0]["differences"] == []
    assert any(c["section"] == "research_point_balance"
               for c in report["comparisons"][1]["differences"])


def test_facility_investment_and_next_phase_operation_do_not_overlap(definitions):
    """Construction creates future *conditional* capacity, not current-Phase flow."""
    sim = definitions._simulation
    facility, process = next((f, p) for f, p in _compatible_processes(sim)
                             if sim.projects.recipes.get(f.id)
                             and f.process_throughput_per_day > 0 and p.outputs_per_day)
    site = "prospective.installation"
    installed = {"node": site, "facility": str(facility.id),
                 "units": 1, "process": str(process.id)}
    investment = {"node": site, "facility": str(facility.id), "units": 1}
    plan = {"phases": [
        {"name": "investment", "days": 12, "facilities": [],
         "facility_investments": [investment]},
        {"name": "operation", "days": 20, "facilities": [installed]}]}
    original = deepcopy(capture_state(sim))
    first, second = evaluate(plan, app=definitions)["phases"]
    assert first["facility_investments"][0]["status"] == "investment_only_not_operating_in_current_phase"
    assert first["scale"]["facility_units_added"] == 1
    assert sum(row["production_t"] for row in first["resources"]) == 0
    assert sum(row["construction_demand_t"] for row in first["resources"]) > 0
    assert second["scale"]["facility_units_added"] == 0
    assert sum(row["construction_demand_t"] for row in second["resources"]) == 0
    for resource, per_day in process.outputs_per_day.items():
        assert _rows(second)[site, str(resource)]["production_t"] == pytest.approx(
            per_day * facility.process_throughput_per_day * 20)
    assert capture_state(sim) == original
    # Investment has no automatic Project completion deadline. The analyst
    # may assume the same acquisition becomes available later than one Phase.
    postponed = deepcopy(plan)
    postponed["phases"].insert(1, {"name": "uncommissioned", "days": 7, "facilities": []})
    intermediate = evaluate(postponed, app=definitions)["phases"][1]
    assert not intermediate["facility_investments"]
    assert sum(row["production_t"] for row in intermediate["resources"]) == 0
    forbidden = deepcopy(plan)
    forbidden["phases"][0]["facilities"] = [installed]
    with pytest.raises(ValueError, match="opening holdings"):
        evaluate(forbidden, app=definitions)
    unsupported = deepcopy(plan)
    unsupported["phases"][0]["facility_investments"] = []
    with pytest.raises(ValueError, match="opening holdings"):
        evaluate(unsupported, app=definitions)


def test_sensitivity_adds_future_facility_investment_not_instant_production(definitions):
    """A new investment scenario never silently creates operating capacity."""
    sim = definitions._simulation
    facility = next(f for f in sim.facilities.definitions.values()
                    if sim.projects.recipes.get(f.id) and sim.projects.recipes[f.id].resources)
    comparison = compare_cases({
        "base_plan": {"phases": [{"name": "invest", "days": 11, "facilities": []}]},
        "cases": [{"name": "base"}, {"name": "chosen_investment", "updates": [{
            "collection": "facility_investments", "phase": "invest", "action": "add",
            "row": {"node": "hypothetical.construction", "facility": str(facility.id), "units": 1},
        }]}],
    }, app=definitions)
    base, chosen = (item["projection"]["phases"][0] for item in comparison["cases"])
    assert not base["facility_investments"]
    assert chosen["facility_investments"]
    assert sum(r["production_t"] for r in chosen["resources"]) == 0
    assert any(row["section"] == "facility_investments"
               and row["delta_from_baseline"]["units"] == 1
               for row in comparison["differences"])


def test_vehicle_build_orders_are_not_usable_fleet_until_following_phase(definitions):
    """Manufacturing Resource/Service cannot mint Research or Transport Fleet."""
    sim = definitions._simulation
    vehicle = next(v for v in sim.transport.vehicle_definitions() if v.production.resources)
    node = "hypothetical.fleet.yard"
    build = {"node": node, "vehicle": str(vehicle.id), "units": 2}
    plan = {"phases": [
        {"name": "production", "days": 9, "facilities": [], "vehicle_builds": [build]},
        {"name": "available", "days": 15, "facilities": []},
    ]}
    before = deepcopy(capture_state(sim))
    first, second = evaluate(plan, app=definitions)["phases"]
    assert not first["fleet"]
    assert first["scale"]["vehicle_units_ordered"] == 2
    assert first["vehicle_builds"][0]["status"] == "vehicle_build_only_no_current_phase_fleet_use"
    for resource, amount in vehicle.production.resources:
        assert _rows(first)[node, str(resource)]["vehicle_build_demand_t"] == pytest.approx(2 * amount)
    # A build request is not a completed asset transaction. No implicit
    # Fleet is minted merely because the next comparison period begins.
    assert not second["fleet"]
    selected = deepcopy(plan)
    selected["phases"][1]["fleet"] = [build]
    conditionally_held = evaluate(selected, app=definitions)["phases"][1]
    assert conditionally_held["fleet"][0]["units"] == 2
    postponed = deepcopy(plan)
    postponed["phases"].append({"name": "later", "days": 6,
                                 "facilities": [], "fleet": [build]})
    later = evaluate(postponed, app=definitions)["phases"][-1]
    assert later["fleet"][0]["units"] == 2
    assert second["scale"]["vehicle_units_ordered"] == 0
    assert not second["vehicle_builds"]
    assert capture_state(sim) == before
    invented = deepcopy(plan)
    invented["phases"][0]["fleet"] = [build]
    with pytest.raises(ValueError, match="Fleet opening holdings"):
        evaluate(invented, app=definitions)
    invented = deepcopy(plan)
    invented["phases"][0]["transport_allocations"] = [
        {"origin": node, "destination": "hypothetical.transport", "vehicle": str(vehicle.id),
         "units": 1}]
    with pytest.raises(ValueError, match="reuse Fleet holdings"):
        evaluate(invented, app=definitions)
    compared = compare_cases({"base_plan": {"phases": [
        {"name": "production", "days": 9, "facilities": []}]}, "cases": [
        {"name": "without"}, {"name": "build", "updates": [{
            "collection": "vehicle_builds", "phase": "production", "action": "add", "row": build,
        }]}
    ]}, app=definitions)
    assert any(row["section"] == "vehicle_builds"
               and row["delta_from_baseline"]["units"] == 2
               for row in compared["differences"])


def test_shared_facility_use_and_upstream_supply_expose_one_operating_budget(definitions):
    """New compatible Content cannot spend the same Facility duty twice."""
    from dataclasses import replace
    # Create an isolated, Definition-only Content configuration whose Process
    # and Research Provider genuinely compete for a source. No static game ID
    # or balance target is an assertion here.
    app = build_game_application_for_load()
    sim = app._simulation
    provider, facility = next((p, f) for p in sim.research.providers.values()
                              for f in sim.facilities.definitions.values()
                              if p.source_kind.value == 'facility'
                              and p.accepts_source(cap.id for cap in f.capability_supplies)
                              and f.process_throughput_per_day > 0
                              and p.levels[0].research_execution_per_day > 0)
    process = next(p for p in sim.industry.processes.values() if p.outputs_per_day)
    sim.industry.processes[process.id] = replace(
        process, required_capabilities=frozenset(cap.id for cap in facility.capability_supplies))
    output, quantity = next(iter(process.outputs_per_day.items()))
    node = 'shared.operation.site'
    def plan(industry_duty, research_duty):
        asset = {'node': node, 'facility': str(facility.id), 'units': 1,
                 'process': str(process.id), 'duty': industry_duty}
        return {'initial_facilities': [asset], 'phases': [{
            'name': 'shared-work', 'days': 4, 'facilities': [asset],
            'research_provider_allocations': [{
                'node': node, 'provider': str(provider.id),
                'source_facility': str(facility.id), 'units': 1, 'duty': research_duty}],
            'external_rates': [{'node': node, 'resource': str(output),
                                'net_t_per_day': -(quantity * facility.process_throughput_per_day + 3)}],
        }]}
    within = evaluate(plan(.25, .5), app=app)['phases'][0]
    overloaded = evaluate(plan(1, 1), app=app)['phases'][0]
    within_use, = within['facility_use_constraints']
    overloaded_use, = overloaded['facility_use_constraints']
    assert within_use['nominal_shared_unit_duty_gap_per_day'] == pytest.approx(0)
    assert overloaded_use['nominal_shared_unit_duty_gap_per_day'] == pytest.approx(1)
    assert 'selected_activities_exceed_shared_facility_operating_duty' in overloaded['unassessed_constraints']
    compared = compare_cases({'cases': [{'name': 'within', 'plan': plan(.25, .5)},
                                        {'name': 'overload', 'plan': plan(1, 1)}]}, app=app)
    assert any(item['section'] == 'facility_use_constraints'
               and item['delta_from_baseline']['nominal_shared_unit_duty_gap_per_day'] == pytest.approx(1)
               for item in compared['differences'])


def test_shared_source_reservation_and_duty_include_research_and_survey(definitions):
    """A registered Facility is not duplicated between Research, Survey and Process capacities."""
    sim = definitions._simulation
    provider, survey, facility, mode = next(
        (research, survey, facility, mode)
        for facility in sim.facilities.definitions.values()
        for research in sim.research.providers.values()
        if research.source_kind.value == "facility"
        and research.accepts_source(cap.id for cap in facility.capability_supplies)
        for survey in sim.survey.providers.values()
        if survey.source_kind.value == "facility"
        for mode in survey.observation_modes
        if sim.survey.source_supports_mode(survey, mode, facility.id)
    )
    cell, resource = next(iter(sim.survey.targets))
    node = "source.shared.research.survey"
    def chosen(units, research_units=1):
        asset = {"node": node, "facility": str(facility.id), "units": units}
        return {"initial_facilities": [asset], "solar_yield": {node: 1.0}, "phases": [{
            "name": "parallel", "days": 7, "facilities": [asset],
            "research_provider_allocations": [{
                "node": node, "provider": str(provider.id),
                "source_facility": str(facility.id), "units": research_units,
            }],
            "survey_activities": [{
                "node": node, "provider": str(survey.id), "source": str(facility.id),
                "mode": str(mode.id), "units": 1, "cell": str(cell), "resource": str(resource),
            }],
        }]}
    with pytest.raises(ValueError, match="reuse Facility source units"):
        evaluate(chosen(1), app=definitions)
    projection = evaluate(chosen(2), app=definitions)
    shared = projection["phases"][0]
    use, = shared["facility_use_constraints"]
    assert use["installed_unit_duty_per_day"] == 2
    assert use["selected_survey_unit_duty_per_day"] == 1
    assert use["selected_research_unit_duty_per_day"] == 1
    assert use["nominal_shared_unit_duty_gap_per_day"] == 0
    from scripts.analysis_balance import summarize_projection
    shown, = summarize_projection(projection)["phases"][0]["shared_facility_activity_capacity"]
    assert shown["selected_survey_unit_duty_per_day"] == 1
    # The first two physical units are already selected for Research+Survey;
    # neither appears as idle upstream Process throughput.
    assert "selected_activities_exceed_shared_facility_operating_duty" not in shared["unassessed_constraints"]


def test_phase_time_structure_respects_stage_order_and_investment_commissioning(definitions):
    """All chosen Research stages and investments share phase-local time bounds."""
    sim = definitions._simulation
    provider = next(p for p in sim.research.providers.values()
                    if p.source_kind.value == 'facility'
                    and p.levels[0].research_execution_per_day > 0
                    and p.levels[0].generation_points_per_day > 0)
    facility = next(f for f in sim.facilities.definitions.values()
                    if provider.accepts_source(cap.id for cap in f.capability_supplies))
    tech = next(t for t in sim.research.definitions.values()
                if len(t.stage_specs) > 1 and any(getattr(s, 'research_point_cost', 0) > 0
                                                   for s in t.stage_specs))
    node = 'phase.time.research'
    asset = {'node': node, 'facility': str(facility.id), 'units': 1}
    goal = {'node': node, 'research_ids': [str(tech.id)], 'include_prerequisites': False}
    phase = evaluate({'initial_facilities': [asset], 'phases': [{
        'name': 'goal', 'days': 13, 'facilities': [asset], 'research_goal': goal,
        'research_provider_allocations': [{
            'node': node, 'provider': str(provider.id),
            'source_facility': str(facility.id), 'units': 1}],
    }]}, app=definitions)['phases'][0]
    structure = phase['research_time_structure']
    stages = [row for row in structure['selected_stage_service_bounds']
              if row['research'] == str(tech.id)]
    assert len(stages) == len(tech.stage_specs)
    assert structure['serial_prerequisite_stage_service_lower_bound_days'] == pytest.approx(
        sum(row['serial_service_lower_bound_days'] for row in stages))
    assert structure['conditional_known_capacity_lower_bound_days'] >= structure[
        'serial_prerequisite_stage_service_lower_bound_days']
    assert any(row['kind'] == 'research_selected_workload' for row in phase['time_constraints'])
    # Registered prototype/demonstration work cannot be completed in zero
    # days simply because no additional finite Service is requested.
    from space_idle.research_models import site_stage_daily_progress_request_limit
    stage_bounds = {(row['research'], row['stage']): row for row in stages}
    for spec in tech.stage_specs:
        limit = site_stage_daily_progress_request_limit(spec)
        if limit is not None:
            bound = stage_bounds[str(tech.id), spec.stage_id]
            assert bound['site_progress_lower_bound_days'] == pytest.approx(spec.required_work / limit)
            assert bound['serial_service_lower_bound_days'] >= bound['site_progress_lower_bound_days']

    # Scaling a selected Research source changes the same ledger's RP capacity,
    # Stage lower bounds and comparative time sections, not an isolated goal lens.
    doubled = {**asset, 'units': 2}
    def selected_source(units):
        return {'initial_facilities': [doubled], 'phases': [{
            'name': 'goal', 'days': 13, 'facilities': [doubled], 'research_goal': goal,
            'research_provider_allocations': [{
                'node': node, 'provider': str(provider.id),
                'source_facility': str(facility.id), 'units': units}],
        }]}
    different_providers = compare_cases({'cases': [
        {'name': 'single', 'plan': selected_source(1)},
        {'name': 'double', 'plan': selected_source(2)},
    ]}, app=definitions)
    assert any(row['section'] == 'research_time_structure' for row in different_providers['differences'])
    assert any(row['section'] == 'time_constraints' and row['identity']['kind'] == 'research_selected_workload'
               for row in different_providers['differences'])

    builder, builder_source = next((d, sim.facilities.definitions[key])
                                   for key, d in sim.projects.construction_providers.items()
                                   if d.work_per_day > 0 and key in sim.projects.recipes
                                   and sim.projects.recipes[key].construction_work > 0)
    node = 'phase.time.industry'
    source_id = str(builder_source.id)
    first = {'node': node, 'facility': source_id, 'units': 1}
    plan = {'initial_facilities': [first], 'solar_yield': {node: 1.0}, 'phases': [
        {'name': 'acquire', 'days': 5, 'facilities': [first],
         'facility_investments': [{'node': node, 'facility': source_id, 'units': 1}]},
        {'name': 'use-acquired', 'days': 5, 'facilities': [{**first, 'units': 2}],
         'facility_investments': [{'node': node, 'facility': source_id, 'units': 1}]},
        {'name': 'after-commission', 'days': 5,
         'facilities': [{**first, 'units': 3}]},
    ]}
    invest, reinvest, operational = evaluate(plan, app=definitions)['phases']
    first_constraint, = invest['investment_constraints']
    second_constraint, = reinvest['investment_constraints']
    assert first_constraint['pre_investment_work_per_day'] == pytest.approx(builder.work_per_day)
    assert second_constraint['pre_investment_work_per_day'] == pytest.approx(2 * builder.work_per_day)
    assert first_constraint['pre_investment_work_lower_bound_days'] == pytest.approx(
        second_constraint['pre_investment_work_lower_bound_days'] * 2)
    assert not operational['facility_investments']
    assert all(row['kind'] == 'construction' for row in invest['time_constraints'])

    assembly_provider = next(f for f in sim.facilities.definitions.values()
                             if any(supply.service_type == 'vehicle_assembly'
                                    for supply in f.service_capacity_supplies))
    vehicle_a, vehicle_b = list(sim.transport.vehicle_definitions())[:2]
    assembly_node = 'phase.shared.assembly'
    assembly = {'node': assembly_node, 'facility': str(assembly_provider.id), 'units': 1}
    baseline_plan = {'initial_facilities': [assembly], 'phases': [{
        'name': 'vehicle-production', 'days': 15, 'facilities': [assembly],
        'vehicle_builds': [{'node': assembly_node, 'vehicle': str(vehicle_a.id), 'units': 1}],
    }]}
    two_orders = deepcopy(baseline_plan)
    two_orders['phases'][0]['vehicle_builds'].append(
        {'node': assembly_node, 'vehicle': str(vehicle_b.id), 'units': 1})
    assembly_report = evaluate(two_orders, app=definitions)['phases'][0]
    shared, = [item for item in assembly_report['shared_service_workloads']
               if item['node'] == assembly_node and item['service'] == 'vehicle_assembly']
    assert shared['required_work'] == pytest.approx(
        vehicle_a.production.days + vehicle_b.production.days)
    assert shared['conditional_shared_workload_lower_bound_days'] == pytest.approx(
        shared['required_work'] / shared['nominal_capacity_per_day'])
    comparison = compare_cases({'cases': [{'name': 'first', 'plan': baseline_plan},
                                            {'name': 'both', 'plan': two_orders}]}, app=definitions)
    assert any(item['section'] == 'shared_service_workloads'
               and item['delta_from_baseline']['required_work'] == pytest.approx(vehicle_b.production.days)
               for item in comparison['differences'])


def test_transport_capacity_can_use_explicit_scenario_network_without_replaying_state():
    """A selected real initial Movement network yields physical bounds via Transport."""
    from space_idle.bootstrap import build_game_application
    source = build_game_application()
    sim = source._simulation
    candidate = next(
        (vehicle, origin, destination)
        for vehicle in sim.transport.vehicle_definitions()
        for origin in sim.graph.nodes
        for destination in sim.graph.nodes
        if origin != destination and any(
            plan.forward_path and not plan.blockers
            for plan in [sim.transport.transport_service_plan_for(
                vehicle.id, origin, destination)]
        )
    )
    vehicle, origin, destination = candidate
    resource = str(next(iter(source._catalog.resources)))
    base = {'initial_fleet': [{'node': str(origin), 'vehicle': str(vehicle.id), 'units': 1}],
            'phases': [{'name': 'directional_freight', 'days': 16, 'facilities': [],
                        'fleet': [{'node': str(origin), 'vehicle': str(vehicle.id), 'units': 1}],
                        'transport_allocations': [{'origin': str(origin), 'destination': str(destination),
                                                   'vehicle': str(vehicle.id), 'units': 1}],
                        'transfers': [{'origin': str(origin), 'destination': str(destination),
                                       'resource': resource, 't_per_day': 0.2}]}]}
    before = deepcopy(capture_state(sim))
    registered = evaluate({**base, 'movement_reference': 'applied_scenario'})['phases'][0]
    without_network = evaluate(base)['phases'][0]
    trip, = registered['transport_services']
    assert trip['forward_capacity_t_per_day'] > 0
    assert trip['cycle_days'] > 0
    assert trip['forward_latency_days'] is not None
    assert trip['movement_reference'] == 'applied_scenario'
    assert without_network['od_transport_constraints'][0]['nominal_capacity_t_per_day'] is None
    assert registered['time_constraints'][0]['kind'] == 'transport_volume'
    assert registered['time_constraints'][0]['one_way_latency_lower_bound_days'] is not None
    assert registered['transfer_requirements'][0]['status'] == 'cargo_arrival_unassessed'
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match='different Movement reference'):
        compare_cases({'cases': [{'name': 'known', 'plan': {
            **base, 'movement_reference': 'applied_scenario'}},
            {'name': 'unknown', 'plan': base}]})
    from space_idle.bootstrap import build_game_application_for_load
    with pytest.raises(ValueError, match='applied Scenario'):
        evaluate({**base, 'movement_reference': 'applied_scenario'},
                 app=build_game_application_for_load())
    from scripts.analysis_balance import compare_projection_results
    with pytest.raises(ValueError, match='different Movement reference'):
        compare_projection_results([
            {'name': 'known', 'projection': evaluate({**base, 'movement_reference': 'applied_scenario'})},
            {'name': 'unregistered', 'projection': evaluate(base)},
        ])


def test_provider_level_content_hypothesis_uses_registered_research_capacity_and_same_ledger(definitions):
    """Generation, admission and execution sensitivity share the investment/RP ledger."""
    from scripts.analysis_balance import compare_content_variant
    sim = definitions._simulation
    provider = next(p for p in sim.research.providers.values()
                    if p.source_kind.value == 'facility'
                    and p.levels[0].generation_points_per_day > 0
                    and p.levels[0].research_execution_per_day > 0)
    source = next(f for f in sim.facilities.definitions.values()
                  if provider.accepts_source(cap.id for cap in f.capability_supplies))
    tech = next(t for t in sim.research.definitions.values()
                if any(getattr(stage, 'research_point_cost', 0) > 0 for stage in t.stage_specs))
    node = 'hypothetical.research'
    asset = {'node': node, 'facility': str(source.id), 'units': 1}
    plan = {'initial_facilities': [asset], 'phases': [
        {'name': 'research_with_upkeep', 'days': 6, 'facilities': [asset],
         'research_goal': {'node': node, 'research_ids': [str(tech.id)]},
         'research_provider_allocations': [{
             'node': node, 'provider': str(provider.id),
             'source_facility': str(source.id), 'units': 1}]}
    ]}
    level = provider.levels[0]
    edits = [{'kind': 'research_provider', 'id': str(provider.id),
              'selector': {'level': level.level}, 'field': 'levels.' + metric, 'value': value} for metric, value in (
                  ('generation_points_per_day', level.generation_points_per_day * 1.5),
                  ('storage_capacity_points', level.storage_capacity_points * 1.2),
                  ('research_execution_per_day', level.research_execution_per_day * 1.3),
              )]
    before = deepcopy(capture_state(sim))
    result = compare_content_variant(plan, edits)
    baseline, altered = (entry['projection']['phases'][0]
                         for entry in result['comparisons'][0]['cases'])
    assert altered['research_point_balance']['nominal_generation_points'] == pytest.approx(
        baseline['research_point_balance']['nominal_generation_points'] * 1.5)
    assert altered['research_point_balance']['nominal_storage_capacity_points'] == pytest.approx(
        baseline['research_point_balance']['nominal_storage_capacity_points'] * 1.2)
    assert altered['research_point_balance']['nominal_execution_per_day'] == pytest.approx(
        baseline['research_point_balance']['nominal_execution_per_day'] * 1.3)
    assert altered['research_time_structure']['conditional_known_capacity_lower_bound_days'] <= (
        baseline['research_time_structure']['conditional_known_capacity_lower_bound_days'])
    assert altered['resources'] == baseline['resources']  # Provider performance does not mint physical inputs.
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match='tuple selector'):
        compare_content_variant(plan, [{**edits[0], 'selector': {'level': max(s.level for s in provider.levels) + 1}}])


def test_different_horizons_compare_rates_and_burdens_without_subtracting_total_stock(definitions):
    from scripts.analysis_balance import summarize
    facility, process = next((f, p) for f, p in _compatible_processes(definitions._simulation)
                             if p.inputs_per_day and p.outputs_per_day)
    asset = {'node': 'scale.node', 'facility': str(facility.id), 'units': 1,
             'process': str(process.id)}
    def plan(days):
        return {'initial_facilities': [asset], 'phases': [
            {'name': 'same_goal', 'days': days, 'facilities': [asset]}]}
    result = compare_cases({'cases': [
        {'name': 'short', 'plan': plan(4)}, {'name': 'long', 'plan': plan(40)}]}, app=definitions)
    period = next(row['comparison'] for row in result['differences']
                  if row['section'] == 'period_sensitivity')
    first = {(r['node'], r['resource']): r for r in period['baseline']['resources']}
    longer = {(r['node'], r['resource']): r for r in period['case']['resources']}
    assert first.keys() == longer.keys()
    for key in first:
        assert first[key]['nominal_recurring_net_t_per_day'] == pytest.approx(
            longer[key]['nominal_recurring_net_t_per_day'])
        assert first[key]['production_t_per_day'] == pytest.approx(longer[key]['production_t_per_day'])
    assert all(row['section'] != 'resources' for row in result['differences'])
    report = summarize(result)
    assert report['cases'][1]['incomparable_phase_basis']
    assert report['cases'][1]['time_basis_comparisons']
    assert 'summary' not in report['cases'][1]  # avoid a second giant projection


def test_new_process_content_compares_explicit_choices_without_zero_cost_technology(definitions):
    from scripts.analysis_balance import compare_content_variant
    sim = definitions._simulation
    facility, process = next((f, p) for f, p in _compatible_processes(sim)
                             if p.outputs_per_day and p.inputs_per_day)
    output = next(iter(process.outputs_per_day))
    node = 'common.goal.node'
    new_id = 'evaluation.process.materials_route'
    asset = {'node': node, 'facility': str(facility.id), 'units': 1}
    def plan(method):
        return {'initial_facilities': [asset], 'phases': [{
            'name': 'material_capability', 'days': 7,
            'facilities': [{**asset, 'process': method}]}]}
    payload = {'development_goal': 'Compare intermediate-material capacity at the same site',
               'baseline_plan': plan(str(process.id)), 'edited_plan': plan(new_id)}
    edits = [{'operation': 'add', 'kind': 'process', 'id': new_id,
              'definition': {'display_name': 'Alternative material conversion',
                             'required_capabilities': sorted(process.required_capabilities),
                             'inputs_per_day': {str(k): v for k, v in process.inputs_per_day.items()},
                             'outputs_per_day': {str(k): (v * 1.3 if k == output else v)
                                                 for k, v in process.outputs_per_day.items()},
                             'prerequisite_technologies': [str(x) for x in process.prerequisite_technologies]}}]
    before = deepcopy(capture_state(sim))
    result = compare_content_variant(payload, edits)
    assert result['comparison_does_not_claim_equivalent_outcomes']
    assert any(row['status'] == 'newly_selected_quantity' and row['absent_is_not_zero_cost']
               for row in result['comparisons'][0]['differences']
               if row['section'] == 'resource_contributions' and 'status' in row)
    baseline, variant = (r['projection']['phases'][0] for r in result['comparisons'][0]['cases'])
    resource = str(output)
    assert _rows(variant)[(node, resource)]['production_t'] > _rows(baseline)[(node, resource)]['production_t']
    assert capture_state(sim) == before
    invalid = deepcopy(payload)
    invalid['edited_plan']['initial_stock'] = [{'node': node, 'resource': resource, 'amount_t': 100}]
    with pytest.raises(ValueError, match='identical initial conditions'):
        compare_content_variant(invalid, edits)


def test_case_changes_research_dag_and_conditionally_acquired_assets_without_plan_copies(definitions):
    """An alternative authors selected activities; investment must precede use."""
    sim = definitions._simulation
    a, b = list(sim.research.definitions)[:2]
    facility = next(f for f in sim.facilities.definitions.values()
                    if f.id in sim.projects.recipes and sim.projects.recipes[f.id].resources)
    vehicle = next(v for v in sim.transport.vehicle_definitions() if v.production.resources)
    node = 'conditional.development'
    asset = {'node': node, 'facility': str(facility.id), 'units': 1}
    fleet = {'node': node, 'vehicle': str(vehicle.id), 'units': 1}
    base = {'phases': [
        {'name': 'investment', 'days': 12},
        {'name': 'operation', 'days': 20,
         'research_goal': {'node': node, 'research_ids': [str(a)]}},
    ]}
    additions = [
        {'collection': 'facility_investments', 'action': 'add', 'phase': 'investment', 'row': asset},
        {'collection': 'vehicle_builds', 'action': 'add', 'phase': 'investment', 'row': fleet},
        {'collection': 'facilities', 'action': 'add', 'phase': 'operation', 'row': asset},
        {'collection': 'fleet', 'action': 'add', 'phase': 'operation', 'row': fleet},
        {'collection': 'research_goal', 'phase': 'operation', 'set': {'research_ids': [str(b)]}},
    ]
    before = deepcopy(capture_state(sim))
    compared = compare_cases({'base_plan': base, 'cases': [
        {'name': 'no_investment'}, {'name': 'alternative', 'updates': additions}]}, app=definitions)
    old, new = (record['projection']['phases'] for record in compared['cases'])
    assert not old[0]['facility_investments'] and not old[0]['vehicle_builds']
    assert old[1]['scale']['facility_units'] == 0 and not old[1]['fleet']
    assert new[0]['facility_investments'] and new[0]['vehicle_builds']
    assert new[0]['scale']['facility_units'] == 0 and not new[0]['fleet']
    assert new[1]['scale']['facility_units'] == 1 and new[1]['fleet']
    assert new[1]['research_goal']['requested_technologies'] == [str(b)]
    assert old[1]['research_goal']['requested_technologies'] == [str(a)]
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match='opening holdings'):
        compare_cases({'base_plan': base, 'cases': [
            {'name': 'unsupported', 'updates': [additions[2]]}]}, app=definitions)
    with pytest.raises(ValueError, match='Fleet opening holdings'):
        compare_cases({'base_plan': base, 'cases': [
            {'name': 'unsupported', 'updates': [additions[3]]}]}, app=definitions)


def test_world_site_comparison_reuses_one_authored_composition_without_founding_or_stock(definitions):
    """A Surface Cell changes World coefficients, not held assets or Resource ownership.

    This also covers new body/cell Content without a geography-specific fixture.
    """
    sim = definitions._simulation
    method = next(m for m in sim.extraction.specs.values()
                  if any(cell.resource_potential_by_resource.get(m.resource_id, 0) > 0
                         for cell in sim.graph.surface_cells.values()))
    facility = next(f for f in sim.facilities.definitions.values()
                    if method.required_capabilities <= {cap.id for cap in f.capability_supplies})
    sites = sorted(map(str, sim.graph.surface_cells))
    assert len(sites) >= 2
    node = "prospective.site"
    installation = {"node": node, "facility": str(facility.id), "units": 2}
    operating = {**installation, "extraction": str(method.id)}
    plan = {"phases": [
        {"name": "acquire", "days": 10, "facility_investments": [installation]},
        {"name": "operate", "days": 20, "facilities": [operating],
         "extraction_sites": [{"node": node, "developed_cells": ["$world_context"],
                               "knowledge": [{"cell": "$world_context",
                                              "resource": str(method.resource_id), "level": 3}]}]},
    ]}
    source = deepcopy(plan)
    state_before = deepcopy(capture_state(sim))
    sweep = evaluate_world_context_sweep({"world_context_sweep": {
        "plan": plan, "contexts": sites[:2]}}, app=definitions)
    assert plan == source
    assert capture_state(sim) == state_before
    assert [row["context"] for row in sweep["sites"]] == sites[:2]
    assert {row["body"] for row in sweep["sites"]} == {
        str(sim.graph.surface_cells[SurfaceCellId(site)].body_id) for site in sites[:2]
    }
    for item in sweep["sites"]:
        expected = evaluate(_bind_world_context(plan, item["context"]), app=definitions)
        assert item["projection"]["phases"] == expected["phases"]
        activity = item["projection"]["phases"][1]["extraction_world_context"]
        assert activity and activity[0]["world_cells"] == [item["context"]]
        assert activity[0]["contributing_methods"] == [str(method.id)]
        assert not item["projection"]["phases"][1]["od_transport_constraints"]
    brief = summarize_world_context_sweep(sweep)
    assert "projection" not in brief["sites"][0]
    with pytest.raises(ValueError, match="context-dependent"):
        evaluate_world_context_sweep({"world_context_sweep": {
            "plan": {"phases": [{"name": "no_context", "days": 1}]},
            "contexts": sites[:2]}}, app=definitions)
    with pytest.raises(ValueError, match="World context"):
        evaluate_world_context_sweep({"world_context_sweep": {
            "plan": plan, "contexts": ["unknown.cell"]}}, app=definitions)


def test_world_parameters_are_content_variables_in_the_same_site_and_development_comparison(definitions):
    """Resource, terrain, illumination and orbital World values are editable.

    An unchanged Site ID is not an assertion that its geological or physical
    Definition is immutable. No specific planetary distribution is normative.
    """
    from scripts.analysis_balance import compare_content_variant
    from scripts.analysis_variants import apply_content_variant
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.spatial import IlluminationField
    from space_idle.power import SolarGeneration

    sim = definitions._simulation
    method = next(m for m in sim.extraction.specs.values()
                  if any(cell.resource_potential_by_resource.get(m.resource_id, 0) > 0
                         for cell in sim.graph.surface_cells.values()))
    facility = next(f for f in sim.facilities.definitions.values()
                    if method.required_capabilities <= {c.id for c in f.capability_supplies})
    candidates = sorted(str(c.id) for c in sim.graph.surface_cells.values()
                        if sim.environment.static.facets.get((c.id, IlluminationField)) is not None)
    assert len(candidates) >= 2
    cell_id = SurfaceCellId(candidates[0])
    raw = sim.graph.surface_cells[cell_id]
    resource = str(method.resource_id)
    prior = float(raw.resource_potential_by_resource.get(method.resource_id, 0.0))
    solar = sim.environment.static.facets[(cell_id, IlluminationField)]
    node = "world.parameter.construction"
    asset = {"node": node, "facility": str(facility.id), "units": 2}
    generator = next(f for f in sim.facilities.definitions.values()
                     if f.id in sim.power.specs and isinstance(sim.power.specs[f.id].generation, SolarGeneration))
    generator_asset = {"node": node, "facility": str(generator.id), "units": 1}
    selected = {"solar_sites": [{"node": node, "facility": str(generator.id), "context": "$world_context"}],
                "phases": [
        {"name": "investment", "days": 8, "facility_investments": [asset, generator_asset]},
        {"name": "operation", "days": 16,
         "facilities": [{**asset, "extraction": str(method.id)}, generator_asset],
         "extraction_sites": [{"node": node, "developed_cells": ["$world_context"],
                               "knowledge": [{"cell": "$world_context", "resource": resource, "level": 3}]}],
        },
    ]}
    sweep = {"world_context_sweep": {"plan": selected, "contexts": candidates[:2]}}
    changes = [
        {"kind": "world_cell", "id": str(cell_id), "field": "resource_potential",
         "resource_id": resource, "value": prior + max(1., prior)},
        {"kind": "world_cell", "id": str(cell_id), "field": "geology_accessibility",
         "geology_key": method.geology_accessibility_key or "unrelated_geology_key", "value": 0.75},
        {"kind": "world_cell", "id": str(cell_id), "field": "terrain_factor",
         "value": raw.terrain.terrain_factor * .9},
        {"kind": "world_environment", "id": str(cell_id), "facet": "illumination",
         "field": "solar_flux_w_m2", "value": solar.solar_flux_w_m2 * .75},
        {"kind": "world_body", "id": str(raw.body_id), "field": "mean_radius_km",
         "value": sim.graph.bodies[raw.body_id].mean_radius_km * 1.02},
    ]
    current_state = deepcopy(capture_state(sim))
    # Cross-site results are compared in the ordinary Projection. World edits
    # need not affect every selected Method, but they must not leak to other Cells.
    report = compare_content_variant(sweep, changes)
    assert report["world_parameter_edits"] == changes
    assert report["source_world_definition_id"] == definitions.world_definition_id
    assert [row["context"] for row in report["sites"]] == candidates[:2]
    pair = report["sites"][0]["comparison"]["cases"]
    pre, post = pair[0]["projection"], pair[1]["projection"]
    left = pre["phases"][1]["extraction_world_context"][0]
    right = post["phases"][1]["extraction_world_context"][0]
    assert right["effective_opportunity"] != pytest.approx(left["effective_opportunity"])
    left_power = pre["phases"][1]["power_world_context"][0]
    right_power = post["phases"][1]["power_world_context"][0]
    assert right_power["nominal_unallocated_generation_mw"] < left_power["nominal_unallocated_generation_mw"]
    assert report["sites"][1]["comparison"]["differences"] == []
    assert capture_state(sim) == current_state
    assert sim.graph.surface_cells[cell_id] == raw

    orbital_node = next(n for n in sim.graph.nodes.values()
                        if n.body_center_orbit_radius_km is not None)
    stellar = sim.graph.star_systems[sim.graph.bodies[raw.body_id].star_system_id]
    changes += [
        {"kind": "world_node", "id": str(orbital_node.id), "field": "body_center_orbit_radius_km",
         "value": orbital_node.body_center_orbit_radius_km * 1.03},
        {"kind": "world_system", "id": str(stellar.id),
         "field": "central_gravitational_parameter_km3_s2",
         "value": stellar.central_gravitational_parameter_km3_s2 * 1.05},
    ]
    changed = build_game_application_for_load(
        definition_transform=lambda instance, catalog: apply_content_variant(instance, catalog, changes))
    assert changed._simulation.graph.nodes[orbital_node.id].body_center_orbit_radius_km != orbital_node.body_center_orbit_radius_km
    assert changed._simulation.graph.surface_cells[cell_id].resource_potential_by_resource[method.resource_id] > prior
    assert changed._simulation.environment.get(cell_id, IlluminationField).solar_flux_w_m2 == pytest.approx(
        solar.solar_flux_w_m2 * .75)
    assert changed._simulation.graph.bodies[raw.body_id].mean_radius_km != sim.graph.bodies[raw.body_id].mean_radius_km
    for invalid, message in [
        ({"kind": "world_cell", "id": str(cell_id), "field": "resource_potential",
          "resource_id": resource, "value": -1}, "nonnegative"),
        ({"kind": "world_cell", "id": str(cell_id), "field": "area_km2", "value": 0}, "positive"),
        ({"kind": "world_cell", "id": "nonexistent", "field": "terrain_factor", "value": 1}, "unknown"),
        ({"kind": "world_environment", "id": str(cell_id), "facet": "illumination",
          "field": "availability", "value": 1.2}, "illumination"),
        ({"kind": "world_body", "id": str(raw.body_id), "field": "mean_radius_km", "value": -1}, "nonnegative"),
    ]:
        with pytest.raises(ValueError, match=message):
            build_game_application_for_load(
                definition_transform=lambda instance, catalog: apply_content_variant(instance, catalog, [invalid]))


def test_selected_balancing_inputs_do_not_have_a_fixed_activity_allowlist(definitions):
    """The same authored case patch mechanism covers every Plan-owned activity.

    Changing the list of activities is a player/analyst selection, not an
    instruction for the evaluator to synthesize missing acquisitions or routes.
    """
    from scripts.analysis_balance import _apply_case_updates
    sim = definitions._simulation
    resource = str(next(iter(definitions._catalog.resources)))
    node = "parameterized.node"
    plan = {"initial_stock": [{"node": node, "resource": resource, "amount_t": 7}],
            "solar_yield": {node: .6}, "initial_research_points": 12,
            "phases": [{"name": "investment", "days": 10,
                        "external_rates": [{"node": node, "resource": resource, "net_t_per_day": 2}],
                        "market_buys": []}]}
    changes = [
        {"collection": "initial_research_points", "value": 18},
        {"collection": "initial_stock", "match": {"node": node, "resource": resource},
         "set": {"amount_t": 11}},
        {"collection": "solar_yield", "match": {"node": node}, "value": .9},
        {"collection": "phase", "phase": "investment", "set": {"days": 20}},
        {"collection": "external_rates", "phase": "investment",
         "match": {"node": node, "resource": resource}, "set": {"net_t_per_day": 3}},
        {"collection": "external_rates", "phase": "investment", "action": "add",
         "row": {"node": "other.node", "resource": resource, "net_t_per_day": 1}},
    ]
    modified = _apply_case_updates(plan, changes)
    assert plan["initial_stock"][0]["amount_t"] == 7
    before = evaluate(plan, app=definitions)["phases"][0]
    after = evaluate(modified, app=definitions)["phases"][0]
    assert _rows(after)[(node, resource)]["notional_end_t"] == pytest.approx(11 + 3 * 20)
    assert _rows(before)[(node, resource)]["notional_end_t"] == pytest.approx(7 + 2 * 10)
    assert _rows(after)[("other.node", resource)]["external_net_t"] == 20
    assert modified["initial_research_points"] == 18
    assert modified["solar_yield"][node] == .9
    added_yield = _apply_case_updates(modified, [
        {"collection": "solar_yield", "match": {"node": "other.node"}, "action": "add", "value": .5}])
    assert added_yield["solar_yield"]["other.node"] == .5
    removed_yield = _apply_case_updates(added_yield, [
        {"collection": "solar_yield", "match": {"node": node}, "action": "remove"}])
    assert node not in removed_yield["solar_yield"]
    with pytest.raises(ValueError, match="not uniquely selected"):
        _apply_case_updates(plan, [{"collection": "initial_stock", "match": {"node": "absent"},
                                   "set": {"amount_t": 30}}])
    with pytest.raises(ValueError, match="already|distinct"):
        _apply_case_updates(plan, [{"collection": "initial_stock", "action": "add",
                                   "row": plan["initial_stock"][0]}])


def test_registered_numeric_parameter_edits_carry_through_owned_definitions_and_projections(definitions):
    """Balance edits span nested real Domain data rather than a selected ID allowlist."""
    from scripts.analysis_variants import apply_content_variant
    from space_idle.bootstrap import build_game_application_for_load
    sim = definitions._simulation
    power_id, solar = next((id_, spec.generation) for id_, spec in sim.power.specs.items()
                           if hasattr(spec.generation, "reference_flux_w_m2"))
    facility_id, service = next((facility.id, supply)
                                for facility in sim.facilities.definitions.values()
                                for supply in facility.service_capacity_supplies)
    tech_id, stage = next((definition.id, stage)
                          for definition in sim.research.definitions.values()
                          for stage in definition.stage_specs
                          if hasattr(stage, "research_point_cost"))
    vehicle_id, vehicle = next(iter(sim.transport.vehicle_defs.items()))
    science_id, science = next(iter(sim.scientific_exploration.definitions.items()))
    edits = [
        {"kind": "power", "id": str(power_id), "field": "generation.reference_flux_w_m2",
         "value": solar.reference_flux_w_m2 * 2},
        {"kind": "facility", "id": str(facility_id),
         "field": "service_capacity_supplies.nominal_rate",
         "selector": {"service_type": service.service_type}, "value": service.nominal_rate * 1.5},
        {"kind": "research", "id": str(tech_id), "field": "stage_specs.research_point_cost",
         "selector": {"stage_id": stage.stage_id}, "value": stage.research_point_cost * 1.2},
        {"kind": "vehicle", "id": str(vehicle_id), "field": "production.days",
         "value": vehicle.production.days + 2},
        {"kind": "scientific_exploration", "id": str(science_id), "field": "required_crew",
         "value": science.required_crew + 1},
    ]
    before = deepcopy(capture_state(sim))
    edited = build_game_application_for_load(
        definition_transform=lambda target, catalog: apply_content_variant(target, catalog, edits))
    assert edited._simulation.power.specs[power_id].generation.reference_flux_w_m2 == pytest.approx(solar.reference_flux_w_m2 * 2)
    result = edited._simulation.facilities.definitions[facility_id]
    assert next(row.nominal_rate for row in result.service_capacity_supplies
                if row.service_type == service.service_type) == pytest.approx(service.nominal_rate * 1.5)
    spec = edited._simulation.research.definitions[tech_id]
    assert next(row.research_point_cost for row in spec.stage_specs
                if row.stage_id == stage.stage_id) == pytest.approx(stage.research_point_cost * 1.2)
    assert edited._simulation.transport.vehicle_defs[vehicle_id].production.days == vehicle.production.days + 2
    assert edited._simulation.scientific_exploration.definitions[science_id].required_crew == science.required_crew + 1
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match="tuple selector"):
        build_game_application_for_load(definition_transform=lambda target, catalog: apply_content_variant(
            target, catalog, [{**edits[1], "selector": {"service_type": "nonexistent"}}]))
    with pytest.raises(ValueError, match="integer"):
        build_game_application_for_load(definition_transform=lambda target, catalog: apply_content_variant(
            target, catalog, [{**edits[-1], "value": 1.5}]))
    with pytest.raises(ValueError, match="identity"):
        build_game_application_for_load(definition_transform=lambda target, catalog: apply_content_variant(
            target, catalog, [{"kind": "vehicle", "id": str(vehicle_id), "field": "id", "value": 2}]))


def test_world_reference_time_and_funding_are_selected_comparison_conditions(definitions):
    """A World time origin or reference sample is not a hardcoded day zero.

    Phase boundaries change the reference time without simulating a World's
    continuous evolution or turning conditional asset holdings into Game State.
    """
    from scripts.analysis_balance import _apply_case_updates, compare_cases, summarize_projection
    from space_idle.power import SolarGeneration
    sim = definitions._simulation
    generator = next(ident for ident, spec in sim.power.specs.items()
                     if isinstance(spec.generation, SolarGeneration))
    context = str(next(iter(sim.graph.surface_cells)))
    node = "time.sample.node"
    asset = {"node": node, "facility": str(generator), "units": 1}
    plan = {
        "start_day": 13,
        "initial_facilities": [asset],
        "solar_sites": [{"node": node, "facility": str(generator), "context": context}],
        "phases": [
            {"name": "build", "days": 4, "facilities": [asset]},
            {"name": "operate", "days": 7, "facilities": [asset]},
        ],
    }
    previous = deepcopy(capture_state(sim))
    projected = evaluate(plan, app=definitions)
    assert [p["world_reference_day"] for p in projected["phases"]] == [13, 17]
    assert [p["power_world_context"][0]["world_reference_day"] for p in projected["phases"]] == [13, 17]
    assert summarize_projection(projected)["phases"][1]["world_reference_day"] == 17
    updates = [
        {"collection": "start_day", "value": 25},
        {"collection": "phase", "phase": "operate", "set": {"reference_day": 80, "assumed_funds_musd": 500}},
    ]
    changed = _apply_case_updates(plan, updates)
    assert [p["world_reference_day"] for p in evaluate(changed, app=definitions)["phases"]] == [25, 80]
    compared = compare_cases({"base_plan": plan, "cases": [
        {"name": "original"}, {"name": "changed_origin", "updates": updates}]}, app=definitions)
    assert {d["phase"] for d in compared["differences"] if d["section"] == "world_reference_conditions"} == {"build", "operate"}
    explicit = deepcopy(plan)
    explicit["solar_sites"][0]["day"] = 29
    assert [p["power_world_context"][0]["world_reference_day"]
            for p in evaluate(explicit, app=definitions)["phases"]] == [29, 29]
    assert capture_state(sim) == previous


def test_phase_comparison_keeps_named_interval_identity_when_paths_branch(definitions):
    """Different development paths do not turn a new Phase into a false delta.

    Activity order remains an explicit comparison condition, while selected
    common phases are aligned by their identity rather than list positions.
    """
    from scripts.analysis_balance import summarize
    node = "branching.path"
    resource = str(next(iter(definitions._catalog.resources)))
    a = {"name": "research", "days": 3,
         "external_rates": [{"node": node, "resource": resource, "net_t_per_day": -1}]}
    b = {"name": "expansion", "days": 6,
         "external_rates": [{"node": node, "resource": resource, "net_t_per_day": 2}]}
    c = {"name": "survey", "days": 4}
    base = {"phases": [a, b]}
    alternative = {"phases": [c, deepcopy(a), deepcopy(b)]}
    report = compare_cases({"cases": [{"name": "base", "plan": base},
                                     {"name": "alternative", "plan": alternative}]}, app=definitions)
    structural = [row for row in report["differences"]
                  if row["section"] in {"incomparable_phase_basis", "phase_sequence_conditions"}]
    assert any(row["section"] == "phase_sequence_conditions" for row in structural)
    assert [(row["phase"], row.get("reason")) for row in structural
            if row["section"] == "incomparable_phase_basis"] == [("survey", "missing_baseline_phase")]
    assert not any(row.get("phase") in {"research", "expansion"} and
                   row["section"] == "incomparable_phase_basis" for row in report["differences"])
    overview = summarize(report)["cases"][1]
    assert overview["incomparable_phase_basis"]
    assert any(row["section"] == "phase_sequence_conditions"
               for row in overview["time_basis_comparisons"])


def test_movement_definition_parameters_share_the_content_numeric_edit_path(definitions):
    """Movement assumptions are editable registered parameters, not fixed routes."""
    from scripts.analysis_variants import apply_content_variant
    from space_idle.bootstrap import build_game_application_for_load
    sim = definitions._simulation
    surface = sim.transport.surface_movement_rules[0]
    flight = sim.transport.spaceflight_movement_rules[0]
    changes = [
        {"kind": "surface_movement_rule", "id": str(surface.id),
         "field": "transit_days", "value": surface.transit_days + 2},
        {"kind": "spaceflight_movement_rule", "id": str(flight.id),
         "field": "characteristic_speed_km_per_day",
         "value": flight.characteristic_speed_km_per_day * .75},
    ]
    snapshot = deepcopy(capture_state(sim))
    changed = build_game_application_for_load(
        definition_transform=lambda target, catalog: apply_content_variant(target, catalog, changes))
    assert next(rule.transit_days for rule in changed._simulation.transport.surface_movement_rules
                if rule.id == surface.id) == surface.transit_days + 2
    assert next(rule.characteristic_speed_km_per_day
                for rule in changed._simulation.transport.spaceflight_movement_rules
                if rule.id == flight.id) == pytest.approx(flight.characteristic_speed_km_per_day * .75)
    assert capture_state(sim) == snapshot
    with pytest.raises(ValueError, match="positive"):
        build_game_application_for_load(definition_transform=lambda target, catalog: apply_content_variant(
            target, catalog, [{**changes[1], "value": 0}]))


def test_world_context_parameter_uses_registered_surface_and_non_surface_physics(definitions):
    """A selected power investment can be compared across World contexts without a site-specific evaluator."""
    from space_idle.power import SolarGeneration
    sim = definitions._simulation
    generator = next(f for f in sim.facilities.definitions.values()
                     if isinstance(getattr(sim.power.specs.get(f.id), "generation", None), SolarGeneration))
    world = sim.power.environment.graph
    contexts = [str(next(iter(world.surface_cells))), str(next(iter(world.nodes)))]
    site = "selected.world.context"
    asset = {"node": site, "facility": str(generator.id), "units": 1}
    selected = {"initial_facilities": [asset], "solar_sites": [
        {"node": site, "facility": str(generator.id), "context": "$world_context"}],
        "phases": [{"name": "operation", "days": 6, "facilities": [asset]}]}
    before = deepcopy(capture_state(sim))
    result = evaluate_world_context_sweep({"world_context_sweep": {
        "plan": selected, "contexts": contexts,
        "reference_context": contexts[0]}}, app=definitions)
    assert {row["context_kind"] for row in result["sites"]} == {"surface", "non_surface"}
    assert "relative_to_reference" not in result["sites"][0]
    assert result["sites"][1]["relative_to_reference"] == compare_cases({"cases": [
        {"name": contexts[0], "plan": _bind_world_context(selected, contexts[0])},
        {"name": contexts[1], "plan": _bind_world_context(selected, contexts[1])},
    ]}, app=definitions)["differences"]
    for row in result["sites"]:
        phase = row["projection"]["phases"][0]
        assert phase["power_world_context"][0]["world_context"] == row["context"]
        assert phase["resources"] == evaluate(
            _bind_world_context(selected, row["context"]), app=definitions)["phases"][0]["resources"]
        assert not phase["od_transport_constraints"]
    assert capture_state(sim) == before


def test_selected_multistage_industry_is_accounted_through_actual_process_activity(definitions):
    """Upstream selection changes the same Node ledger, not a hypothetical parallel recipe catalog."""
    sim = definitions._simulation
    facilities = list(sim.facilities.definitions.values())
    producer, consumer, upstream_facility, downstream_facility, intermediary = next(
        (p, q, f, g, resource)
        for p in sim.industry.processes.values()
        for q in sim.industry.processes.values() if p.id != q.id
        for resource in set(p.outputs_per_day) & set(q.inputs_per_day)
        if p.outputs_per_day[resource] > 0 and q.inputs_per_day[resource] > 0
        for f in facilities if f.process_throughput_per_day > 0
        and p.required_capabilities <= {cap.id for cap in f.capability_supplies}
        for g in facilities if g.id != f.id and g.process_throughput_per_day > 0
        and q.required_capabilities <= {cap.id for cap in g.capability_supplies}
    )
    node = "shared.industry.site"
    a = {"node": node, "facility": str(upstream_facility.id), "units": 1}
    b = {"node": node, "facility": str(downstream_facility.id), "units": 1}
    def plan(producer_duty):
        return {"initial_facilities": [a, b], "phases": [{"name": "operation", "days": 9,
                "facilities": [{**a, "process": str(producer.id), "duty": producer_duty},
                               {**b, "process": str(consumer.id), "duty": .5}]}]}
    before = deepcopy(capture_state(sim))
    result = compare_cases({"cases": [
        {"name": "downstream", "plan": plan(0)},
        {"name": "connected", "plan": plan(.5)}]}, app=definitions)
    left, right = (entry["projection"]["phases"][0] for entry in result["cases"])
    resource = str(intermediary)
    upstream = _rows(left)[(node, resource)]
    connected = _rows(right)[(node, resource)]
    assert connected["production_t"] - upstream["production_t"] == pytest.approx(
        producer.outputs_per_day[intermediary] * upstream_facility.process_throughput_per_day * 9 * .5)
    assert connected["process_demand_t"] == pytest.approx(upstream["process_demand_t"])
    assert connected["shortfall_t"] <= upstream["shortfall_t"]
    assert any(d["section"] == "resources" and d["identity"] == {"node": node, "resource": resource}
               for d in result["differences"])
    assert capture_state(sim) == before


def test_registered_scenario_opening_is_explicit_read_only_basis_not_automatic_operation():
    """Reuse real opening physical holdings without duplicating a long Scenario manifest."""
    from space_idle.bootstrap import build_game_application
    app = build_game_application()
    sim = app._simulation
    before = deepcopy(capture_state(sim))
    selected = {"opening_from_reference": True, "movement_reference": "applied_scenario",
                "phases": [{"name": "observation", "days": 10}]}
    projected = evaluate(selected, app=app)
    phase = projected["phases"][0]
    assert projected["opening_conditions_source"] == "applied_scenario_domain_state"
    assert projected["scenario_id"] == sim.scenario_id
    assert all(item["precommitted_units"] == item["owned_units"] - item["free_units"]
               for item in projected["opening_fleet_precommitments"])
    assert phase["scale"]["facility_units"] == 0  # no implicit industry/research activity
    assert phase["scale"]["fleet_units"] == sum(
        sim.transport.fleet_pool_snapshot(vehicle, node).total_units
        for vehicle, node in sim.transport.fleet_pool_keys())
    assert all(row["assumed_turnarounds"] == 0 for row in phase["fleet"])
    assert phase["fleet_availability_constraints"] == []  # holdings are not activities
    committed = next((vehicle, node, sim.transport.fleet_pool_snapshot(vehicle, node))
                     for vehicle, node in sim.transport.fleet_pool_keys()
                     if sim.transport.fleet_pool_snapshot(vehicle, node).total_units >
                     sim.transport.fleet_pool_snapshot(vehicle, node).free_units)
    vehicle, node, held = committed
    selected_use = {"node": str(node), "vehicle": str(vehicle),
                    "units": held.total_units, "turnarounds_per_unit_per_day": .1}
    blocked = evaluate({**selected, "phases": [{"name": "operation", "days": 10,
        "fleet": [selected_use]}]}, app=app)["phases"][0]
    bound, = blocked["fleet_availability_constraints"]
    assert bound["selected_duty_units"] == held.total_units
    assert bound["conditional_available_uncommitted_units"] == held.free_units
    assert bound["units_requiring_reallocation"] == held.total_units - held.free_units
    assert "existing_scenario_fleet_commitment_or_acquisition_condition" in blocked["unassessed_constraints"]
    free_vehicle, free_node, free_held = next(
        (vehicle, node, sim.transport.fleet_pool_snapshot(vehicle, node))
        for vehicle, node in sim.transport.fleet_pool_keys()
        if sim.transport.fleet_pool_snapshot(vehicle, node).free_units > 0)
    free_use = {"node": str(free_node), "vehicle": str(free_vehicle),
                "units": free_held.free_units, "turnarounds_per_unit_per_day": .1}
    available = evaluate({**selected, "phases": [{"name": "operation", "days": 10,
        "fleet": [free_use]}]}, app=app)["phases"][0]
    assert available["fleet_availability_constraints"][0]["units_requiring_reallocation"] == 0
    with pytest.raises(ValueError, match="movement_reference=applied_scenario"):
        evaluate({"opening_from_reference": True,
                  "phases": [{"name": "observation", "days": 10}]}, app=app)
    opening = {(row["node"], row["resource"]): row for row in phase["resources"]}
    for (node, resource), amount in sim.inventory.stock.items():
        if amount > 0:
            assert opening[(str(node), str(resource))]["notional_end_t"] == pytest.approx(amount)
    # The State-owned Facility ceiling may be selected without reauthoring
    # the whole registered initial asset inventory or a fictional investment.
    holding = next(iter(sim.facilities.facilities.values()))
    chosen = {"node": str(holding.operational_node_id),
              "facility": str(holding.definition_id), "units": 1,
              "level": holding.level}
    operating = evaluate({**selected, "phases": [
        {"name": "operation", "days": 10, "facilities": [chosen]}]}, app=app)
    assert operating["phases"][0]["scale"]["facility_units"] == 1
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match="cannot be mixed"):
        evaluate({**selected, "initial_stock": []}, app=app)
    with pytest.raises(ValueError, match="requires an applied Scenario"):
        evaluate(selected, app=build_game_application_for_load())
