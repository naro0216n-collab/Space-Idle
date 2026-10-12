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


def test_all_registered_process_facility_pairs_use_their_definition_coefficients(definitions):
    """Replacing or adding Content never creates a numeric per-Facility oracle."""
    sim = definitions._simulation
    before = deepcopy(capture_state(sim))
    pairs = list(_compatible_processes(sim))
    node, days, units, duty = "projection.node", 7, 3, .4
    for facility, process in pairs:
        asset = {"node": node, "facility": str(facility.id), "units": units,
                 "process": str(process.id), "duty": duty}
        phase = evaluate({"initial_facilities": [asset], "phases": [
            {"name": "operation", "days": days, "facilities": [asset]}]}, app=definitions)["phases"][0]
        rows = _rows(phase)
        rate = units * duty * days * facility.process_throughput_per_day
        for resource, amount in process.inputs_per_day.items():
            assert rows[(node, str(resource))]["process_demand_t"] == pytest.approx(rate * amount), (facility.id, process.id)
        for resource, amount in process.outputs_per_day.items():
            assert rows[(node, str(resource))]["production_t"] == pytest.approx(rate * amount), (facility.id, process.id)
    assert capture_state(sim) == before


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
            shipped[key[1]] += row["shipped_t"]
            received[key[1]] += row["received_t"]
        assert shipped == pytest.approx(received)
        prior_stock = defaultdict(float, {key: row["notional_end_t"] for key, row in current.items()})
    # Added facilities require investment independently of elapsed operation.
    assert any(row["construction_demand_t"] > 0 for row in result["phases"][1]["resources"])
    assert all(row["construction_demand_t"] == 0 for row in result["phases"][0]["resources"])


def test_registered_facility_quantity_contributions_follow_every_definition(definitions):
    """Exercise every Facility, not one named generation or a preferred scale-up."""
    from space_idle.power import FixedGeneration, SolarGeneration

    sim = definitions._simulation
    units, duty, days = 2, .4, 7
    facilities = tuple(sorted(sim.facilities.definitions.values(), key=lambda f: str(f.id)))
    assets = []
    for index, facility in enumerate(facilities):
        asset = {"node": f"facilities.{index}", "facility": str(facility.id),
                 "units": units, "duty": duty}
        if facility.life_support:
            asset["supported_person_days_per_day"] = units * duty * facility.life_support.person_days_per_day / 2
        assets.append(asset)
    # A Facility may be present as inherited/Scenario capital without a
    # generic construction recipe. Exercise its nominal supply regardless;
    # only authored acquisition recipes produce construction investment.
    initially_owned = [row for row, facility in zip(assets, facilities)
                       if facility.id not in sim.projects.recipes]
    report = evaluate({"initial_facilities": initially_owned,
                       "solar_yield": {row["node"]: .75 for row in assets},
                       "phases": [{"name": "all facilities", "days": days,
                                   "facilities": assets}]}, app=definitions)["phases"][0]
    resources = _rows(report)
    constraints = {row["node"]: row for row in report["constraints"]}
    services = {(row["node"], row["service"]): row for row in report["service_constraints"]}
    pools = {(row["node"], row["pool"]): row for row in report["storage"]}
    for asset, facility in zip(assets, facilities):
        node = asset["node"]
        recipe = sim.projects.recipes.get(facility.id)
        if recipe:
            for requirement in recipe.resources:
                key = node, str(requirement.resource_id)
                assert resources[key]["construction_demand_t"] == pytest.approx(units * requirement.amount_t), facility.id
                assert resources[key]["maintenance_demand_t"] == pytest.approx(
                    units * requirement.amount_t * facility.maintenance_fraction_per_year * days / 365), facility.id
            assert constraints[node]["construction_work_required"] == pytest.approx(units * recipe.construction_work)
        for supply in facility.service_capacity_supplies:
            assert services[(node, supply.service_type)]["nominal_capacity_per_day"] == pytest.approx(
                units * duty * supply.nominal_rate), facility.id
        if facility.id in sim.projects.construction_providers:
            assert services[(node, "construction_work")]["nominal_capacity_per_day"] == pytest.approx(
                units * duty * sim.projects.construction_providers[facility.id].work_per_day)
        if facility.life_support:
            supported = asset["supported_person_days_per_day"]
            assert constraints[node]["life_support_assigned_person_days_per_day"] == pytest.approx(supported)
            assert constraints[node]["life_support_nominal_person_days_per_day"] == pytest.approx(
                units * duty * facility.life_support.person_days_per_day)
            for resource, amount in facility.life_support.net_resources:
                assert resources[(node, str(resource))]["life_support_demand_t"] == pytest.approx(
                    amount * supported * days), facility.id
        power = sim.power.specs.get(facility.id)
        if power:
            assert constraints[node]["power_demand_nominal_mw"] == pytest.approx(
                units * (duty * power.load_mw + (1 - duty) * power.standby_load_mw))
            generation = power.generation
            expected = (generation.mw if isinstance(generation, FixedGeneration) else
                        .75 * generation.rated_mw_at_reference_flux if isinstance(generation, SolarGeneration) else 0)
            assert constraints[node]["power_generation_nominal_mw"] == pytest.approx(units * duty * expected)
        storage = sim.storage.providers.get(facility.id)
        if storage:
            for pool, capacity in storage.capacity_t_by_pool.items():
                assert pools[(node, pool)]["physical_capacity_t"] == pytest.approx(units * capacity)


def test_registered_extraction_and_research_sources_project_nominal_quantities(definitions):
    """All supported methods and Facility-backed providers share generic coefficients."""
    sim = definitions._simulation
    days, units, duty = 5, 2, .6
    assets = []
    extraction = []
    for facility in sorted(sim.facilities.definitions.values(), key=lambda f: str(f.id)):
        for method in sim.extraction.compatible_methods(facility.id):
            if facility.extraction_capacity_t_per_day <= 0:
                continue
            node = f"extraction.{len(extraction)}"
            assets.append({"node": node, "facility": str(facility.id), "units": units,
                           "duty": duty, "extraction": str(method.id),
                           "extraction_yield_fraction": .25})
            extraction.append((node, facility, method))
    assignments = []
    expected_generation = expected_execution = expected_storage = expected_crew = 0.0
    for provider in sorted(sim.research.providers.values(), key=lambda p: str(p.id)):
        if provider.source_kind.value != "facility":
            continue  # Fleet-backed providers require Fleet assumptions, not free source units.
        matching = [facility for facility in sim.facilities.definitions.values()
                    if provider.required_source_capabilities <= {s.id for s in facility.capability_supplies}]
        # Numeric projection evaluates the usable pairs. A Provider without a
        # present compatible source is a Content-development question, not a
        # failure of projection arithmetic or an entitlement to free capacity.
        if not matching:
            continue
        for level in provider.levels:
            node = f"research.{len(assignments)}"
            source = matching[0]
            assets.append({"node": node, "facility": str(source.id), "units": 1})
            assignments.append({"node": node, "provider": str(provider.id),
                                "source_facility": str(source.id), "units": 1,
                                "level": level.level, "duty": duty})
            expected_generation += level.generation_points_per_day * duty * days
            expected_execution += level.research_execution_per_day * duty
            expected_storage += level.storage_capacity_points
            expected_crew += level.generation_points_per_day * duty * provider.crew_person_days_per_research_point
    result = evaluate({"initial_facilities": assets,
                       "solar_yield": {asset["node"]: .8 for asset in assets},
                       "phases": [{"name": "catalog methods", "days": days,
                                   "facilities": assets, "research_provider_allocations": assignments}]},
                      app=definitions)["phases"][0]
    by_node = {(row["node"], row["resource"]): row for row in result["extraction_projections_t"]}
    rows = _rows(result)
    for node, facility, method in extraction:
        key = node, str(method.output_resource_id)
        nominal = facility.extraction_capacity_t_per_day * units * duty * days
        assert by_node[key]["nominal_t"] == pytest.approx(nominal)
        assert by_node[key]["assumed_t"] == pytest.approx(nominal * .25)
        assert rows[key]["production_t"] == pytest.approx(nominal * .25)
    rp = result["research_point_balance"]
    assert rp["nominal_generation_points"] == pytest.approx(expected_generation)
    assert rp["nominal_execution_per_day"] == pytest.approx(expected_execution)
    assert rp["nominal_storage_capacity_points"] == pytest.approx(expected_storage)
    assert rp["crew_requirement_person_days_per_day"] == pytest.approx(expected_crew)


def test_registered_vehicle_and_research_stage_inputs_keep_typed_dimensions(definitions):
    """Every Vehicle build and Technology stage participates without a named balancing target."""
    sim = definitions._simulation
    vehicles = tuple(vehicle for vehicle in sim.transport.vehicle_definitions()
                     if vehicle.production is not None)
    stages = [(tech, stage) for tech in sim.research.definitions.values()
              for stage in tech.stage_specs]
    builds = [{"node": f"vehicle.{index}", "vehicle": str(vehicle.id), "units": 2}
              for index, vehicle in enumerate(vehicles)]
    research = [{"node": f"stage.{index}", "research": str(tech.id), "stage": stage.stage_id}
                for index, (tech, stage) in enumerate(stages)]
    days = 11
    result = evaluate({"phases": [{"name": "registered acquisitions", "days": days,
                                   "facilities": [], "vehicle_builds": builds,
                                   "research_stages": research}]}, app=definitions)["phases"][0]
    rows = _rows(result)
    services = {(row["node"], row["service"]): row for row in result["service_constraints"]}
    for index, vehicle in enumerate(vehicles):
        node = f"vehicle.{index}"
        for resource, amount in vehicle.production.resources:
            assert rows[(node, str(resource))]["vehicle_build_demand_t"] == pytest.approx(2 * amount), vehicle.id
        if vehicle.production.service_type:
            assert services[(node, vehicle.production.service_type)]["required_per_day"] == pytest.approx(
                2 * vehicle.production.days / days)
    for index, (_tech, stage) in enumerate(stages):
        node = f"stage.{index}"
        for resource, amount in getattr(stage, "resources", {}).items():
            assert rows[(node, str(resource))]["research_material_demand_t"] == pytest.approx(amount)
    assert result["research_point_balance"]["research_stage_demand_points"] == pytest.approx(
        sum(getattr(stage, "research_point_cost", 0) for _, stage in stages))
    assert result["research_work_demand"] == pytest.approx(
        sum(getattr(stage, "required_work", 0) for _, stage in stages))


def test_case_comparison_preserves_named_dimensions_and_validates_inputs(definitions):
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
    with pytest.raises(ValueError, match="unique"):
        compare_cases({"cases": [{"name": "same", "plan": base},
                                 {"name": "same", "plan": increased}]}, app=definitions)
    with pytest.raises(ValueError, match="unknown process"):
        bad = deepcopy(base)
        bad["phases"][0]["facilities"][0]["process"] = "unknown.process"
        evaluate(bad, app=definitions)
    with pytest.raises(ValueError, match="removal"):
        evaluate({"initial_facilities": [{"node": node, "facility": str(facility.id), "units": 1}],
                  "phases": [{"name": "remove", "days": 1, "facilities": []}]}, app=definitions)
