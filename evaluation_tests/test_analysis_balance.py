"""Generic quantitative projection contracts; no Content strategy is a test oracle.

These tests check dimensional accounting from registered Definitions, not the
relative desirability of particular Facilities, generations or build orders.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

import pytest

from scripts.analysis_balance import compare_cases, evaluate
from space_idle.bootstrap import build_game_application_for_load
from space_idle.persistence import capture_state


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


def test_registered_cross_domain_activity_provenance_and_comparison_is_content_driven(definitions):
    """The same ledger follows active Process, research, Vehicle investment and upkeep.

    This contract does not depend on a checked-in Facility composition or a
    prescribed scale. New registered coefficients must change the same ledger.
    """
    from scripts.analysis_balance import evaluate_research_with_economies
    from scripts.analysis_balance_research import analyze_research_goal
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
    # The selected Technology goal and the economic alternatives use one
    # public quantity evaluator, with no constant fixture or additional State.
    goal = analyze_research_goal(research_ids=(str(tech.id),), app=definitions)
    second = deepcopy(plan)
    second["phases"][0]["facilities"][0]["duty"] = .75
    joined = evaluate_research_with_economies(goal, {"first": plan, "second": second},
                                              app=definitions, summary=True)
    assert len(joined) == 2
    assert all(row["research_and_economy"]["contexts"] and row["system_balance"]["phases"]
               for row in joined)
    assert joined[0]["system_balance"]["phases"] != joined[1]["system_balance"]["phases"]
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
    """Technology goals can be evaluated with one or many authored economies.

    Neither a repository Fixture nor an alternative research-only quantity
    engine is involved; the CLI reports the same node-local ledger as evaluate.
    """
    import json
    import sys
    from scripts.analysis_balance import main

    research_id = str(next(iter(definitions._simulation.research.definitions)))
    inputs = []
    for name, days in (("first", 3), ("second", 15)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"phases": [{"name": "activity", "days": days,
                                               "facilities": []}]}), encoding="utf-8")
        inputs.append(path)
    for args, expected in (([str(inputs[0])], [str(inputs[0])]),
                           (["--portfolio", *(str(p) for p in inputs)], sorted(map(str, inputs)))):
        monkeypatch.setattr(sys, "argv", ["analysis_balance.py", *args,
                                          "--research-id", research_id, "--summary"])
        main()
        report = json.loads(capsys.readouterr().out)
        assert any(item["research"] == research_id for item in report["goal"]["research_items"])
        assert [row["name"] for row in report["selected_economies"]] == expected
        for record in report["selected_economies"]:
            assert record["system_balance"]["phases"]
            assert record["research_and_economy"]["contexts"]

    # A Definition edit changes the same research/industry lens; neither a
    # parallel experiment simulator nor a second Research rule is involved.
    from space_idle.research_models import ResearchTheoryStageSpec
    original = definitions._simulation.research.definitions
    source = next(definition for definition in original.values()
                  if any(isinstance(stage, ResearchTheoryStageSpec) for stage in definition.stage_specs))
    stage = next(stage for stage in source.stage_specs if isinstance(stage, ResearchTheoryStageSpec))
    changed = tmp_path / "definition_changes.json"
    changed.write_text(json.dumps([{
        "kind": "research_theory_stage", "id": str(source.id),
        "stage_id": stage.stage_id, "field": "research_point_cost",
        "value": stage.research_point_cost * 1.3,
    }]), encoding="utf-8")
    baseline_args = [str(inputs[0]), "--research-id", str(source.id), "--summary"]
    monkeypatch.setattr(sys, "argv", ["analysis_balance.py", *baseline_args])
    main()
    baseline = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "argv", ["analysis_balance.py", *baseline_args,
                                      "--content-variant", str(changed)])
    main()
    adjusted = json.loads(capsys.readouterr().out)
    assert adjusted["goal"]["research_point_requirement"] == pytest.approx(
        baseline["goal"]["research_point_requirement"] + stage.research_point_cost * .3)
    assert [row["name"] for row in adjusted["selected_economies"]] == [str(inputs[0])]
    assert original[source.id].stage_specs == source.stage_specs


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
    from scripts.analysis_balance_research import analyze_research_goal, research_goal_impact
    from scripts.analysis_variants import apply_content_variant
    from space_idle.research_models import ResearchTheoryStageSpec
    sim = definitions._simulation
    tech = next(definition for definition in sim.research.definitions.values()
                if any(isinstance(spec, ResearchTheoryStageSpec) for spec in definition.stage_specs))
    stage = next(s for s in tech.stage_specs if isinstance(s, ResearchTheoryStageSpec))
    delta = max(1.0, stage.research_point_cost * .23)
    change = [{"kind": "research_theory_stage", "id": str(tech.id),
               "stage_id": stage.stage_id, "field": "research_point_cost",
               "value": stage.research_point_cost + delta}]
    plan = {"phases": [{"name": "research", "days": 31, "facilities": [],
                         "research_goal": {"node": "hypothetical.site",
                                           "research_ids": [str(tech.id)]}}]}
    before = deepcopy(capture_state(sim))
    record = compare_content_variant(plan, change, summary=False)
    changes = record["comparisons"][0]["differences"]
    assert any(r["section"] == "research_point_balance"
               and r["delta_from_baseline"].get("research_stage_demand_points") == pytest.approx(delta)
               for r in changes)
    assert any(r["section"] == "research_stages"
               and r["delta_from_baseline"].get("point_cost") == pytest.approx(delta)
               for r in changes)
    variant = build_game_application_for_load(
        definition_transform=lambda simulation, catalog: apply_content_variant(
            simulation, catalog, change))
    observed = research_goal_impact(analyze_research_goal(research_ids=[str(tech.id)], app=definitions),
                                    analyze_research_goal(research_ids=[str(tech.id)], app=variant))
    assert observed["research_point_demand_delta"] == pytest.approx(delta)
    assert observed["stage_changes"]
    assert capture_state(sim) == before


def test_content_impact_handles_independent_alternative_cases(definitions):
    from scripts.analysis_balance import compare_content_variant
    from space_idle.research_models import ResearchTheoryStageSpec
    tech = next(v for v in definitions._simulation.research.definitions.values()
                if any(isinstance(s, ResearchTheoryStageSpec) for s in v.stage_specs))
    stage = next(s for s in tech.stage_specs if isinstance(s, ResearchTheoryStageSpec))
    delta = max(1.0, stage.research_point_cost / 10)
    edit = [{"kind": "research_theory_stage", "id": str(tech.id),
             "stage_id": stage.stage_id, "field": "research_point_cost",
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


def test_goal_join_does_not_rebill_selected_goal_as_an_unrelated_research(definitions):
    from scripts.analysis_balance import evaluate_research_with_economies
    from scripts.analysis_balance_research import analyze_research_goal
    sim = definitions._simulation
    tech = next(iter(sim.research.definitions.values()))
    goal = analyze_research_goal(research_ids=[str(tech.id)], app=definitions)
    plan = {"initial_research_points": 10, "phases": [{
        "name": "activity", "days": 30, "facilities": [],
        "research_goal": {"node": "research.zone", "research_ids": [str(tech.id)]}}]}
    joined = evaluate_research_with_economies(goal, {"selected": plan}, app=definitions)
    context = joined[0]["research_and_economy"]["contexts"][0]
    assert context["goal_stage_demand_already_booked_in_ledger"]
    assert context["goal_stage_rp_booked_in_ledger"] == pytest.approx(
        goal["goal"]["theory_research_point_demand"])
    assert context["current_other_research_rp_claim_per_day"] == pytest.approx(0)
    assert context["opening_rp_conditionally_available_for_goal"] == pytest.approx(10)
    assert context["goal_rp_remaining_after_opening_stock"] == pytest.approx(max(
        0.0, goal["goal"]["theory_research_point_demand"] - 10))


def test_selected_upstream_process_traces_unmet_local_demand_without_creating_supply(definitions):
    """A chosen registered conversion has a bounded conditional bill, not arrivals."""
    sim = definitions._simulation
    facility, process = next((f, p) for f, p in _compatible_processes(sim)
                             if f.process_throughput_per_day > 0 and p.outputs_per_day
                             and p.inputs_per_day)
    resource, amount = next((r, a) for r, a in process.outputs_per_day.items() if a > 0)
    node = "upstream.selected"
    available = {"node": node, "facility": str(facility.id), "units": 1, "duty": 0}
    phase = {"name": "supply", "days": 4, "facilities": [available],
             "external_rates": [{"node": node, "resource": str(resource),
                                 "net_t_per_day": -amount}],
             "upstream_supply_choices": [{"node": node, "resource": str(resource),
                                           "process": str(process.id)}]}
    plan = {"initial_facilities": [available], "phases": [phase]}
    before = deepcopy(capture_state(sim))
    selected = evaluate(plan, app=definitions)["phases"][0]
    plain = evaluate({**plan, "phases": [{key: value for key, value in phase.items()
                                        if key != "upstream_supply_choices"}]},
                     app=definitions)["phases"][0]
    assert selected["resources"] == plain["resources"]
    option = selected["upstream_supply_comparisons"][0]
    assert option["unmet_local_resource_demand_t"][str(resource)] == pytest.approx(4 * amount)
    chain = option["conditional_material_paths"]
    choice = next(r for r in chain["selected_processes"] if r["process"] == str(process.id))
    assert choice["process_run_days_at_unit_throughput"] == pytest.approx(4)
    capacity = next(r for r in option["existing_capacity_options"] if r["process"] == str(process.id))
    assert capacity["separately_available_selected_facility_process_runs_per_day"] == pytest.approx(
        facility.process_throughput_per_day)
    assert capacity["independent_capacity_only_lower_bound_days"] == pytest.approx(
        4 / facility.process_throughput_per_day)
    # Differentiating an explicit demand produces corresponding upstream
    # demand and process-run deltas, never an automatic supply credit.
    more = deepcopy(plan)
    more["phases"][0]["external_rates"][0]["net_t_per_day"] *= 2
    comparison = compare_cases({"cases": [{"name": "base", "plan": plan},
                                           {"name": "more", "plan": more}]}, app=definitions)
    assert any(row["section"] == "conditional_upstream_material_requirements"
               and row["identity"] == {"node": node, "kind": "process", "id": str(process.id)}
               and row["delta_from_baseline"]["process_run_days_at_unit_throughput"] == pytest.approx(4)
               for row in comparison["differences"])
    assert capture_state(sim) == before
    invalid = deepcopy(plan)
    invalid["phases"][0]["upstream_supply_choices"][0]["resource"] = next(
        str(x) for x in definitions._catalog.resources if x not in process.outputs_per_day)
    with pytest.raises(ValueError, match="does not produce"):
        evaluate(invalid, app=definitions)


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
