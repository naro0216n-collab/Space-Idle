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
    # Added facilities require investment independently of elapsed operation.
    assert any(row["construction_demand_t"] > 0 for row in result["phases"][1]["resources"])
    assert all(row["construction_demand_t"] == 0 for row in result["phases"][0]["resources"])



def test_unsettled_incoming_cargo_never_becomes_an_assured_resource_balance(definitions):
    """A Process covered only by assumed OD arrivals remains exposed to non-delivery."""
    from scripts.analysis_balance import summarize_projection

    facility, process = next((f, p) for f, p in _compatible_processes(definitions._simulation)
                             if p.inputs_per_day and f.process_throughput_per_day > 0)
    resource, units_per_batch = next(iter(process.inputs_per_day.items()))
    days = 9
    rate = facility.process_throughput_per_day * units_per_batch
    asset = {"node": "cargo.destination", "facility": str(facility.id),
             "units": 1, "process": str(process.id)}
    report = evaluate({"initial_facilities": [asset],
                       "initial_stock": [{"node": "cargo.origin", "resource": str(resource),
                                          "amount_t": days * rate}],
                       "phases": [{"name": "conditional delivery", "days": days,
                                   "facilities": [asset], "transfers": [
                                       {"origin": "cargo.origin", "destination": "cargo.destination",
                                        "resource": str(resource), "t_per_day": rate}]}]},
                      app=definitions)
    phase = report["phases"][0]
    received = _rows(phase)[("cargo.destination", str(resource))]
    assert received["received_t"] == pytest.approx(days * rate)
    assert received["shortfall_t"] == pytest.approx(0)
    assert received["shortfall_without_assumed_arrivals_t"] == pytest.approx(days * rate)
    assert received["cumulative_unverified_incoming_cargo_t"] == pytest.approx(days * rate)
    assert phase["od_transport_constraints"][0]["nominal_capacity_t_per_day"] is None
    summary = summarize_projection(report)["phases"][0]
    assert any(row["node"] == "cargo.destination" and row["resource"] == str(resource)
               and row["shortfall_without_assumed_arrivals_t"] == pytest.approx(days * rate)
               for row in summary["conditional_incoming_cargo_risks_by_node"])


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


def test_large_multisite_asset_holding_reports_global_needs_without_selecting_build_order(definitions):
    """Bulk investments produce typed demand without pretending to schedule a strategy.

    Inventory shortages in one node cannot be satisfied by surplus at another
    without an explicitly authored transfer, even when system net stock is positive.
    """
    sim = definitions._simulation
    facilities = sorted(sim.facilities.definitions.values(), key=lambda row: str(row.id))
    vehicles = sorted(sim.transport.vehicle_definitions(), key=lambda row: str(row.id))
    assert facilities and vehicles
    site_a, site_b = "industrial.a", "industrial.b"
    # Real registered definitions, scaled counts, and an explicit fleet work
    # frequency are independent experiment inputs rather than target values.
    initial_assets = [{"node": site_a, "facility": str(f.id), "units": 20} for f in facilities]
    initial_fleet = [{"node": site_a, "vehicle": str(v.id), "units": 30} for v in vehicles]
    holding_fleet = [{"node": site_a, "vehicle": str(v.id), "units": 40,
                      "turnarounds_per_unit_per_day": .1} for v in vehicles]
    demand = next((res for v in vehicles for res, amount in v.production.resources if amount > 0), None)
    assert demand is not None
    plan = {
        "initial_facilities": initial_assets,
        "initial_fleet": initial_fleet,
        "initial_stock": [{"node": site_b, "resource": str(demand), "amount_t": 1000000}],
        "solar_yield": {site_a: .6},
        "phases": [{"name": "fleet expansion", "days": 12,
                    "facilities": [{**row, "units": row["units"] + 10} for row in initial_assets],
                    "fleet": holding_fleet}],
    }
    phase = evaluate(plan, app=definitions)["phases"][0]
    assert phase["scale"] == {
        "facility_units": len(facilities) * 30,
        "facility_units_added": len(facilities) * 10,
        "fleet_units": len(vehicles) * 40,
        "fleet_units_built": len(vehicles) * 10,
    }
    assert len(phase["fleet"]) == len(vehicles)
    for row in phase["fleet"]:
        assert row["units_built"] == 10
        assert row["assumed_turnarounds"] == pytest.approx(40 * .1 * 12)
    resources = _rows(phase)
    for vehicle in vehicles:
        for resource, amount in vehicle.production.resources:
            assert resources[(site_a, str(resource))]["vehicle_build_demand_t"] >= 10 * amount
        for resource, amount in vehicle.maintenance.resources:
            assert resources[(site_a, str(resource))]["fleet_turnaround_demand_t"] >= 40 * .1 * 12 * amount
    totals = {row["resource"]: row for row in phase["system_resources"]}
    for resource in totals:
        local_rows = [r for r in phase["resources"] if r["resource"] == resource]
        assert totals[resource]["shortfall_t"] == pytest.approx(sum(r["shortfall_t"] for r in local_rows))
        assert totals[resource]["net_t"] == pytest.approx(sum(r["net_t"] for r in local_rows))
    assert totals[str(demand)]["notional_end_t"] > 0
    assert resources[(site_a, str(demand))]["shortfall_t"] > 0
    assert totals[str(demand)]["shortfall_t"] > 0
    for service in phase["system_services"]:
        rows = [r for r in phase["service_constraints"] if r["service"] == service["service"]]
        assert service["nominal_gap_per_day"] == pytest.approx(sum(r["nominal_gap_per_day"] for r in rows))
    assert any("not scheduled completion" in assumption for assumption in evaluate(plan, app=definitions)["assumptions"])


def test_fleet_holdings_are_preserved_between_phases_and_production_is_counted_once(definitions):
    vehicle = next(v for v in definitions._simulation.transport.vehicle_definitions() if v.production.resources)
    site = "fleet.production.site"
    spec = {"node": site, "vehicle": str(vehicle.id), "units": 5}
    plan = {"initial_fleet": [spec], "phases": [
        {"name": "acquire", "days": 2, "facilities": [],
         "vehicle_builds": [{"node": site, "vehicle": str(vehicle.id), "units": 15}]},
        {"name": "operate", "days": 20, "facilities": [],
         "fleet": [{**spec, "units": 20, "turnarounds_per_unit_per_day": .2}]},
    ]}
    first, second = evaluate(plan, app=definitions)["phases"]
    assert first["fleet"] == [{"node": site, "vehicle": str(vehicle.id),
                               "units": 20, "units_built": 15, "assumed_turnarounds": 0}]
    assert second["fleet"][0]["units_built"] == 0
    assert second["fleet"][0]["assumed_turnarounds"] == pytest.approx(80)
    assert second["scale"]["fleet_units_built"] == 0
    assert all(row["vehicle_build_demand_t"] == 0 for row in second["resources"])
    with pytest.raises(ValueError, match="removal"):
        evaluate({"initial_fleet": [spec], "phases": [{"name": "discard", "days": 1,
                                                        "facilities": [], "fleet": []}]}, app=definitions)
    with pytest.raises(ValueError, match="cannot both"):
        evaluate({"phases": [{"name": "double", "days": 1, "facilities": [],
                              "fleet": [spec], "vehicle_builds": [spec]}]}, app=definitions)


def test_shared_scale_cases_only_edit_declared_quantities(definitions):
    facility = next(iter(definitions._simulation.facilities.definitions))
    vehicle = next(iter(definitions._simulation.transport.vehicle_defs))
    node = "scenario.scale"
    base = {"initial_facilities": [{"node": node, "facility": str(facility), "units": 3}],
            "initial_fleet": [{"node": node, "vehicle": str(vehicle), "units": 1}],
            "phases": [{"name": "growth", "days": 10,
                        "facilities": [{"node": node, "facility": str(facility), "units": 3}],
                        "fleet": [{"node": node, "vehicle": str(vehicle), "units": 1}]}]}
    payload = {"base_plan": base, "cases": [
        {"name": "as authored"},
        {"name": "increased commitments", "updates": [
            {"phase": "growth", "collection": "facilities", "node": node, "id": str(facility), "units": 30},
            {"phase": "growth", "collection": "fleet", "node": node, "id": str(vehicle),
             "units": 100, "turnarounds_per_unit_per_day": .2},
        ]},
    ]}
    result = compare_cases(payload, app=definitions)
    assert base["phases"][0]["facilities"][0]["units"] == 3
    first, second = (case["projection"]["phases"][0] for case in result["cases"])
    assert second["scale"]["facility_units"] == 30
    assert second["scale"]["fleet_units"] == 100
    assert second["scale"]["fleet_units_built"] == 99
    assert first["scale"]["fleet_units_built"] == 0
    assert any(diff["section"] == "fleet" for diff in result["differences"])
    with pytest.raises(ValueError, match="duplicate case update"):
        bad = deepcopy(payload)
        bad["cases"][1]["updates"].append(bad["cases"][1]["updates"][0])
        compare_cases(bad, app=definitions)
    with pytest.raises(ValueError, match="existing"):
        bad = deepcopy(payload)
        bad["cases"][1]["updates"][0]["id"] = "unregistered.facility"
        compare_cases(bad, app=definitions)


def test_asset_bundle_variants_attach_owner_definitions_and_project_new_quantity_contract():
    """One Content list entry can add a Facility or Vehicle through normal owners."""
    from scripts.analysis_variants import apply_content_variant
    from space_idle.content.base_assets import build_base_assets
    from space_idle.shared import DefinitionId

    base = build_game_application_for_load()
    sim = base._simulation
    facility_assets, vehicle_assets = build_base_assets()
    # Standard Content itself uses the same one-row installation that variants
    # use, rather than reproducing ownership maps in separate source files.
    assert {row.definition.id for row in facility_assets} == set(sim.facilities.definitions)
    assert {row.id for row in vehicle_assets} == set(sim.transport.vehicle_defs)
    for row in facility_assets:
        identity = row.definition.id
        assert sim.facilities.definitions[identity] == row.definition
        assert sim.projects.recipes[identity] == row.construction
        assert sim.power.specs[identity] == row.power
        assert sim.projects.decommission_recipes[identity] == row.decommission
        if row.storage is not None:
            assert sim.storage.providers[identity] == row.storage
        if row.construction_provider is not None:
            assert sim.projects.construction_providers[identity] == row.construction_provider
    source_facility = next(fid for fid in sim.facilities.definitions
                           if fid in sim.projects.recipes and fid in sim.power.specs)
    source_vehicle = next(vid for vid, vehicle in sim.transport.vehicle_defs.items()
                          if vehicle.production.resources)
    resource = next(iter(base._catalog.resources))
    new_facility, new_vehicle = "variant.facility.scale", "variant.vehicle.scale"
    changes = [
        {"operation": "add", "kind": "asset_bundle", "asset_kind": "facility",
         "id": new_facility, "source_id": str(source_facility), "edits": [
             {"kind": "facility", "field": "display_name", "value": "Experimental Industry"},
             {"kind": "construction", "field": "resources", "value": {str(resource): 5}},
             {"kind": "facility", "field": "maintenance_fraction_per_year", "value": .12},
         ]},
        {"operation": "add", "kind": "asset_bundle", "asset_kind": "vehicle",
         "id": new_vehicle, "source_id": str(source_vehicle), "edits": [
             {"kind": "vehicle", "field": "display_name", "value": "Experimental Fleet"},
             {"kind": "vehicle", "field": "production_resources", "value": {str(resource): 4}},
             {"kind": "vehicle", "field": "production_days", "value": 8},
         ]},
    ]
    app = build_game_application_for_load(
        definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, changes),
    )
    new_sim = app._simulation
    assert DefinitionId(new_facility) in new_sim.facilities.definitions
    assert DefinitionId(new_facility) in new_sim.projects.recipes
    assert DefinitionId(new_facility) in new_sim.projects.decommission_recipes
    assert DefinitionId(new_facility) in new_sim.power.specs
    assert DefinitionId(new_vehicle) in new_sim.transport.vehicle_defs
    assert DefinitionId(new_facility) not in sim.facilities.definitions
    assert DefinitionId(new_vehicle) not in sim.transport.vehicle_defs
    phase = evaluate({"phases": [{"name": "capacity", "days": 10, "facilities": [
        {"node": "one", "facility": new_facility, "units": 100}],
        "fleet": [{"node": "one", "vehicle": new_vehicle, "units": 50}]}]}, app=app)["phases"][0]
    row = _rows(phase)[("one", str(resource))]
    assert row["construction_demand_t"] == pytest.approx(500)
    assert row["vehicle_build_demand_t"] == pytest.approx(200)
    assert row["maintenance_demand_t"] == pytest.approx(500 * .12 / 365 * 10)
    assert phase["scale"]["facility_units"] == 100
    assert phase["scale"]["fleet_units_built"] == 50
    with pytest.raises(ValueError, match="new target"):
        apply_content_variant(new_sim, app._catalog, changes)
    with pytest.raises(ValueError, match="complete asset bundle"):
        apply_content_variant(new_sim, app._catalog, [{
            "operation": "add", "kind": "facility", "id": "invalid.partial.asset",
            "source_id": str(source_facility),
        }])


def test_stage_requirements_investment_bounds_and_unassessed_constraints_are_not_execution_claims(definitions):
    """Balance evidence distinguishes registered obligations, chosen scale and unresolved execution."""
    sim = definitions._simulation
    source = next((facility for facility in sim.facilities.definitions.values()
                   if facility.id in sim.projects.recipes and
                   sim.projects.recipes[facility.id].construction_work > 0))
    tech = next(definition for definition in sim.research.definitions.values()
                if any(stage.stage_type.value == "operational_experience" for stage in definition.stage_specs))
    exp = next(stage for stage in tech.stage_specs if stage.stage_type.value == "operational_experience")
    node = "planned.satellite"
    plan = {"phases": [{"name": "acquisition", "days": 6,
                        "facilities": [{"node": node, "facility": str(source.id), "units": 2}],
                        "research_stages": [{"node": node, "research": str(tech.id), "stage": exp.stage_id}]}]}
    report = evaluate(plan, app=definitions)["phases"][0]
    assert report["investment_constraints"][0]["pre_investment_work_lower_bound_days"] is None
    assert report["investment_constraints"][0]["status"] == "unassessed_no_initial_capacity"
    assert report["research_stages"][0]["experience_requirements"] == dict(exp.requirements)
    assert report["research_stages"][0]["direct_prerequisites"] == sorted(str(x) for x in tech.prerequisites)
    assert "operational_experience_not_generated_by_elapsed_time" in report["unassessed_constraints"]
    assert "new_facilities_operate_before_construction_completion" in report["unassessed_constraints"]
    assert report["activity_sources"][0]["quantity_source"] == "definition_x_selected_composition"


def test_case_sensitivity_changes_times_stocks_and_solar_without_copying_a_plan(definitions):
    from space_idle.power import SolarGeneration
    sim = definitions._simulation
    facility = next((facility for facility in sim.facilities.definitions.values()
                     if (p := sim.power.specs.get(facility.id)) and isinstance(p.generation, SolarGeneration)
                     and facility.id in sim.projects.recipes))
    resource = next(iter(definitions._catalog.resources))
    node = "author.selected"
    asset = {"node": node, "facility": str(facility.id), "units": 1}
    base = {"initial_facilities": [asset], "initial_stock": [
                {"node": node, "resource": str(resource), "amount_t": 5}],
            "solar_yield": {node: .7},
            "phases": [{"name": "activity", "days": 8, "facilities": [asset]}]}
    original = deepcopy(base)
    output = compare_cases({"base_plan": base, "cases": [{"name": "first"},
        {"name": "vary", "updates": [
            {"collection": "solar_yield", "node": node, "factor": .8},
            {"collection": "initial_stock", "node": node, "id": str(resource), "amount_t": 10},
            {"collection": "phase", "phase": "activity", "days": 10},
        ]}]}, app=definitions)
    assert base == original
    assert output["cases"][0]["projection"]["phases"][0]["days"] == 8
    assert output["cases"][1]["projection"]["phases"][0]["days"] == 10
    assert any(row["section"] == "incomparable_phase_basis" for row in output["differences"])
    with pytest.raises(ValueError, match="duplicate case update"):
        compare_cases({"base_plan": base, "cases": [{"name": "x", "updates": [
            {"collection": "phase", "phase": "activity", "days": 1},
            {"collection": "phase", "phase": "activity", "days": 2},
        ]}]}, app=definitions)


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


def test_od_transport_preview_requires_selected_fleet_and_never_settles_cargo(definitions):
    """Fleet service is a conditional Domain preview, not a fictional delivery."""
    origin, destination = "base.node.low_earth_orbit", "base.node.lunar_orbit"
    vehicle = "base.vehicle.reusable_orbital_cargo_tug"
    resource = "base.resource.structural_components"
    phase = {"name": "haul", "days": 12, "facilities": [],
             "transfers": [{"origin": origin, "destination": destination,
                            "resource": resource, "t_per_day": .5}],
             "transport_allocations": [{"origin": origin, "destination": destination,
                                        "vehicle": vehicle, "units": 1}]}
    plan = {"initial_fleet": [{"node": origin, "vehicle": vehicle, "units": 1}],
            "phases": [phase]}
    sim = definitions._simulation
    before = deepcopy(capture_state(sim))
    projection = evaluate(plan, app=definitions)["phases"][0]
    transfer = projection["transfer_requirements"][0]
    assert transfer["status"] == "cargo_arrival_unassessed"
    assert transfer["required_t"] == pytest.approx(6)
    by_node = _rows(projection)
    assert by_node[(origin, resource)]["shipped_t"] == pytest.approx(6)
    assert by_node[(destination, resource)]["received_t"] == pytest.approx(6)
    od = projection["od_transport_constraints"][0]
    service = projection["transport_services"][0]
    assert service["quantity_source"] == "transport_domain_plan_x_selected_fleet"
    if service["blockers"]:
        assert od["status"] != "conditional_capacity_not_cargo_settlement"
    assert "transport_cycle_capacity_not_settled_cargo" in projection["unassessed_constraints"]
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match="reuse Fleet holdings"):
        evaluate({**plan, "phases": [{**phase, "transport_allocations":
                  phase["transport_allocations"] * 2}]}, app=definitions)


def test_summary_preserves_unassessed_limits_and_drill_down(definitions):
    from scripts.analysis_balance import summarize, summarize_projection

    base = {"initial_stock": [{"node": "A", "resource": "base.resource.water", "amount_t": 1}],
            "phases": [{"name": "comparison", "days": 4, "facilities": [],
                        "transfers": [{"origin": "A", "destination": "B",
                                       "resource": "base.resource.water", "t_per_day": 2}]}]}
    full = evaluate(base, app=definitions)
    summary = summarize_projection(full)
    assert summary["phases"][0]["resource_shortfalls_by_node"]
    assert summary["phases"][0]["od_transport_constraints"][0]["nominal_capacity_t_per_day"] is None
    assert "resources" in summary["phases"][0]["detail_sections"]
    assert "resources" not in summary["phases"][0]
    comparison = compare_cases({"cases": [{"name": "baseline", "plan": base},
                                           {"name": "variant", "plan": deepcopy(base)}]}, app=definitions)
    assert [case["name"] for case in summarize(comparison)["cases"]] == ["baseline", "variant"]


def test_world_and_od_composition_sensitivity_changes_only_selected_conditions(definitions):
    from space_idle.shared import DefinitionId
    sim = definitions._simulation
    quarry = sim.facilities.definitions[DefinitionId("base.facility.mineral_quarry")]
    method = sim.extraction.compatible_methods(quarry.id)[0]
    cell = next(c for c in sim.extraction.graph.surface_cells.values()
                if sim.extraction.opportunity_for_cells(method.resource_id, (method,), [c.id], 0,
                       eligible=lambda _method, _cell: True) > 0)
    base = {"initial_facilities": [{"node": "site", "facility": str(quarry.id),
                                     "units": 3, "extraction": str(method.id)}],
            "phases": [{"name": "steady", "days": 8,
                        "facilities": [{"node": "site", "facility": str(quarry.id),
                                        "units": 3, "extraction": str(method.id)}],
                        "extraction_sites": [{"node": "site", "developed_cells": [str(cell.id)]}]}]}
    result = compare_cases({"base_plan": base, "cases": [
        {"name": "unmeasured"},
        {"name": "measured", "updates": [{"collection": "extraction_sites", "phase": "steady",
                                          "node": "site", "knowledge": [
                {"cell": str(cell.id), "resource": str(method.resource_id), "level": 3}]}]},
    ]}, app=definitions)
    original = result["cases"][0]["projection"]["phases"][0]
    measured = result["cases"][1]["projection"]["phases"][0]
    if method.minimum_knowledge_level is not None:
        assert measured["extraction_world_context"][0]["diminishing_output_t_per_day"] > (
            original["extraction_world_context"][0]["diminishing_output_t_per_day"])
    assert base["phases"][0]["extraction_sites"][0].get("knowledge") is None
    assert any(row["section"] == "resources" for row in result["differences"])


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


def test_registered_location_development_science_and_survey_keep_separate_capacities(definitions):
    """Registered project and scientific costs participate without fake completed State."""
    from space_idle.exploration_models import SurveyProviderSourceKind
    from space_idle.shared import DefinitionId

    sim = definitions._simulation
    recipe = next(iter(sim.projects.spatial_recipes.values()))
    campaign = next(iter(sim.scientific_exploration.definitions.values()))
    surveyed = next((provider, mode, source) for provider in sim.survey.providers.values()
                    if provider.source_kind is SurveyProviderSourceKind.FACILITY
                    for mode in provider.observation_modes
                    for source in sim.survey.compatible_source_definition_ids(provider)
                    if sim.survey.source_supports_mode(provider, mode, source))
    provider, mode, source = surveyed
    cell, resource = next(iter(sim.survey.targets))
    node = "hypothetical.survey"
    asset = {"node": node, "facility": str(source), "units": mode.minimum_source_units}
    phase = {"name": "activities", "days": 15, "facilities": [asset],
             "spatial_projects": [{"node": node, "recipe": str(recipe.id), "units": 2}],
             "science_campaigns": [{"campaign": str(campaign.id)}],
             "survey_activities": [{"node": node, "provider": str(provider.id),
                                    "source": str(source), "units": mode.minimum_source_units,
                                    "mode": mode.id, "cell": str(cell), "resource": str(resource)}]}
    plan = {"initial_facilities": [asset], "phases": [phase]}
    before = deepcopy(capture_state(sim))
    report = evaluate(plan, app=definitions)["phases"][0]
    spatial = report["spatial_projects"][0]
    assert spatial["required_construction_work"] == pytest.approx(recipe.construction_work * 2)
    assert spatial["status"] == "project_and_cell_eligibility_unassessed"
    assert {"spatial_development_method"} == {root["kind"] for root in spatial["graph_evidence"]["roots"]}
    site_constraint = next(row for row in report["investment_constraints"] if row["node"] == node)
    assert site_constraint["required_work"] == pytest.approx(recipe.construction_work * 2)
    science = report["science_campaigns"][0]
    assert science["conditional_rp_reward"] == pytest.approx(campaign.research_points_total)
    assert report["research_point_balance"]["conditional_scientific_exploration_reward_points_not_awarded"] == pytest.approx(
        campaign.research_points_total)
    assert report["research_point_balance"]["nominal_generation_points"] == 0
    survey = report["survey_activities"][0]
    assert survey["conditional_minimum_days"] is None
    assert survey["nominal_progress_per_day"] == pytest.approx(
        mode.minimum_source_units * provider.capacity_units_per_source_per_day * mode.survey_rate)
    assert report["unassessed_constraints"]
    for resource_id, amount in campaign.consumable_resources:
        assert _rows(report)[str(campaign.origin_id), str(resource_id)]["science_material_demand_t"] == pytest.approx(amount)
    assert capture_state(sim) == before
    variant = deepcopy(plan)
    variant["phases"][0]["survey_activities"][0]["starting_progress"] = 0
    surveyed = evaluate(variant, app=definitions)["phases"][0]["survey_activities"][0]
    assert surveyed["conditional_minimum_days"] == pytest.approx(
        surveyed["target_progress_threshold"] / surveyed["nominal_progress_per_day"])
    with pytest.raises(ValueError, match="duplicate Scientific Exploration"):
        evaluate({"phases": [phase, {**phase, "name": "later"}]}, app=definitions)


def test_founding_is_one_time_payload_and_preparation_without_created_inventory(definitions):
    sim = definitions._simulation
    recipe = next(iter(sim.founding.deployment_recipes.values()))
    cell = next(iter(sim.extraction.graph.surface_cells))
    source = "founding.staging"
    phase = {"name": "found", "days": 8, "facilities": [],
             "founding_projects": [{"staging_node": source, "recipe": str(recipe.id),
                                    "target_cell": str(cell)}]}
    before = deepcopy(capture_state(sim))
    result = evaluate({"phases": [phase]}, app=definitions)["phases"][0]
    founding = result["founding_projects"][0]
    assert founding["payload_t"] == pytest.approx(recipe.payload_t)
    assert founding["required_vehicle_units"] == recipe.required_units
    assert founding["initial_inventory_t"] == {
        str(r): amount for r, amount in recipe.initial_inventory_totals().items()}
    assert founding["status"] == "target_site_preparation_fleet_movement_and_arrival_unassessed"
    assert {root["kind"] for root in founding["graph_evidence"]["roots"]} == {"founding_method"}
    for r in recipe.payload_resources:
        row = _rows(result)[source, str(r.resource_id)]
        assert row["founding_payload_demand_t"] == pytest.approx(r.amount_t)
        assert row["received_t"] == 0
    preparation = next(r for r in result["service_constraints"]
                       if r["node"] == source and r["service"] == recipe.preparation_service_type)
    assert preparation["required_per_day"] == pytest.approx(recipe.preparation_work / 8)
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match="one explicit target"):
        evaluate({"phases": [{**phase, "founding_projects": [
            {"staging_node": source, "recipe": str(recipe.id),
             "target_cell": str(cell), "target_node": "anything"}]}]}, app=definitions)


def test_market_comparison_keeps_provider_supply_shared_and_does_not_credit_stock(definitions):
    market = definitions._simulation.market
    provider = next(p for p in market.provider_defs.values() if p.supply)
    supply = provider.supply[0]
    request = supply.initial_t + supply.replenishment_t_per_day * 10 + 1
    rows = [{"node": node, "provider": str(provider.id), "resource": str(supply.resource_id),
             "requested_t": request / 2} for node in ("market.a", "market.b")]
    report = evaluate({"phases": [{"name": "market", "days": 10, "facilities": [],
                                   "assumed_funds_musd": 0, "market_buys": rows}]},
                      app=definitions)["phases"][0]
    provider_row = report["market_provider_constraints"][0]
    assert provider_row["total_requested_t"] == pytest.approx(request)
    assert provider_row["conditional_total_supply_upper_bound_t"] == pytest.approx(request - 1)
    assert provider_row["theoretical_shortfall_t"] >= 1
    assert provider_row["nominal_cost_musd"] == pytest.approx(
        request * provider.buy_price(supply.resource_id))
    assert report["market_funds_condition"]["conditional_funds_gap_musd"] == pytest.approx(
        provider_row["nominal_cost_musd"])
    assert report["resources"] == []
    assert all(item["graph_evidence"]["roots"] for item in report["market_buys"])


def test_facility_upgrade_investment_uses_registered_recipe_without_free_level_effect(definitions):
    sim = definitions._simulation
    (facility_id, level), recipe = next(iter(sim.projects.upgrade_recipes.items()))
    node = "hypothetical.upgrade"
    asset = {"node": node, "facility": str(facility_id), "units": 2}
    plain = {"name": "invest", "days": 10, "facilities": [asset]}
    selected = {**plain, "upgrade_projects": [{"node": node, "facility": str(facility_id),
                                               "target_level": level, "units": 1}]}
    before = deepcopy(capture_state(sim))
    base = evaluate({"initial_facilities": [asset], "phases": [plain]}, app=definitions)["phases"][0]
    report = evaluate({"initial_facilities": [asset], "phases": [selected]}, app=definitions)["phases"][0]
    assert report["upgrade_projects"][0]["required_construction_work"] == pytest.approx(recipe.construction_work)
    expected_added_upkeep = sim.facilities.maintenance_requirements_for_investment(
        facility_id, {req.resource_id: req.amount_t for req in recipe.resources},
    )
    assert report["upgrade_projects"][0]["conditional_additional_maintenance_t_per_day"] == pytest.approx(
        {str(resource): rate for resource, rate in expected_added_upkeep.items()}
    )
    if level == 2:
        provider = sim.research.providers[facility_id]
        previous_spec = provider.level_spec(1)
        next_spec = provider.level_spec(2)
        change = report["upgrade_projects"][0]["conditional_research_provider_changes"][0]
        assert change["provider"] == str(provider.id)
        assert change["generation_points_per_day_before"] == pytest.approx(
            previous_spec.generation_points_per_day
        )
        assert change["generation_points_per_day_after"] == pytest.approx(
            next_spec.generation_points_per_day
        )
        assert change["research_execution_per_day_after"] == pytest.approx(
            next_spec.research_execution_per_day
        )
    assert report["investment_constraints"][0]["required_work"] == pytest.approx(recipe.construction_work)
    for requirement in recipe.resources:
        assert _rows(report)[(node, str(requirement.resource_id))]["construction_demand_t"] == pytest.approx(requirement.amount_t)
    assert {row["resource"]: row["maintenance_demand_t"] for row in report["resources"]} == pytest.approx(
        {row["resource"]: row["maintenance_demand_t"] for row in base["resources"]}
    )
    assert report["scale"] == base["scale"]
    assert report["research_point_balance"] == base["research_point_balance"]
    assert "facility_upgrade_level_eligibility_and_sequencing" in report["unassessed_constraints"]
    assert capture_state(sim) == before
    with pytest.raises(ValueError, match="exceed selected installed"):
        evaluate({"initial_facilities": [asset], "phases": [{**selected, "upgrade_projects": [
            {"node": node, "facility": str(facility_id), "target_level": level, "units": 3}]}]}, app=definitions)


def test_case_differences_trace_new_definition_activities_and_missing_time_bases(definitions):
    sim = definitions._simulation
    recipe = next(iter(sim.projects.spatial_recipes.values()))
    campaign = next(iter(sim.scientific_exploration.definitions.values()))
    (facility_id, target_level), upgrade = next(iter(sim.projects.upgrade_recipes.items()))
    node = "sensitivity.node"
    asset = {"node": node, "facility": str(facility_id), "units": 1}
    base = {"initial_facilities": [asset], "phases": [
        {"name": "compare", "days": 12, "facilities": [asset]}]}
    expanded = deepcopy(base)
    expanded["phases"][0].update({
        "spatial_projects": [{"node": node, "recipe": str(recipe.id), "units": 2}],
        "upgrade_projects": [{"node": node, "facility": str(facility_id),
                              "target_level": target_level, "units": 1}],
        "science_campaigns": [{"campaign": str(campaign.id)}],
    })
    compared = compare_cases({"cases": [{"name": "original", "plan": base},
                                       {"name": "different activities", "plan": expanded}]}, app=definitions)
    changes = {item["section"]: item for item in compared["differences"]}
    assert changes["spatial_projects"]["delta_from_baseline"]["required_construction_work"] == pytest.approx(
        2 * recipe.construction_work)
    assert changes["upgrade_projects"]["delta_from_baseline"]["required_construction_work"] == pytest.approx(
        upgrade.construction_work)
    assert changes["science_campaigns"]["delta_from_baseline"]["conditional_rp_reward"] == pytest.approx(
        campaign.research_points_total)
    assert changes["research_point_balance"]["delta_from_baseline"][
        "conditional_scientific_exploration_reward_points_not_awarded"] == pytest.approx(campaign.research_points_total)
    assert "pre_investment_work_lower_bound_days" in changes["investment_constraints"][
        "incomparable_unassessed_metrics"]
    # A missing trailing phase is always marked as a missing time basis.
    longer = deepcopy(base)
    longer["phases"].append({"name": "later", "days": 12, "facilities": [asset]})
    result = compare_cases({"cases": [{"name": "first", "plan": base},
                                      {"name": "longer", "plan": longer}]}, app=definitions)
    assert any(row["section"] == "incomparable_phase_basis" and
               row["reason"] == "missing_baseline_phase" for row in result["differences"])
    summary = __import__("scripts.analysis_balance", fromlist=["summarize"]).summarize(compared)
    assert "upgrade_projects" in summary["difference_sections"]
    assert any("science_activity_bounds" in phase["changed_sections"]
               for phase in summary["cases"][1]["changed_phases"])


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


def test_resource_contributions_reconcile_by_source_with_all_projected_dimensions(definitions):
    """The origin ledger is a view of the same accounting, not a competing calculator."""
    import json
    from pathlib import Path
    from scripts.analysis_balance import compare_cases

    named = ("industrial_scale_comparison", "industrial_fleet_scale_comparison",
             "cross_domain_industrial_research_logistics", "world_growth_research_logistics")
    dimensions = ("production_t", "process_demand_t", "maintenance_demand_t",
                  "construction_demand_t", "vehicle_build_demand_t",
                  "fleet_turnaround_demand_t", "transport_service_demand_t",
                  "research_material_demand_t", "science_material_demand_t",
                  "founding_payload_demand_t", "life_support_demand_t",
                  "external_net_t", "shipped_t", "received_t")
    before = deepcopy(capture_state(definitions._simulation))
    for name in named:
        data = json.loads((Path(__file__).resolve().parent.parent / "evaluation_plans" / f"{name}.json").read_text())
        result = compare_cases(data, app=definitions) if "cases" in data else evaluate(data, app=definitions)
        projections = [case["projection"] for case in result["cases"]] if "cases" in result else [result]
        for projection in projections:
            for phase in projection["phases"]:
                attributed = defaultdict(float)
                for item in phase["resource_contributions"]:
                    assert item["quantity_basis"] and item["origin_definition"]
                    assert item["dimension"] in dimensions
                    attributed[(item["node"], item["resource"], item["dimension"])] += item["amount_t"]
                for row in phase["resources"]:
                    for dimension in dimensions:
                        assert attributed[(row["node"], row["resource"], dimension)] == pytest.approx(
                            row[dimension], abs=1e-9), (name, phase["name"], row["node"], row["resource"], dimension)
                service_attributed = defaultdict(float)
                for item in phase["service_contributions"]:
                    assert item["quantity_basis"] and item["origin_definition"]
                    service_attributed[(item["node"], item["service"], item["role"])] += item["rate_per_day"]
                for row in phase["service_constraints"]:
                    identity = (row["node"], row["service"])
                    assert service_attributed[(*identity, "demand")] == pytest.approx(
                        row["required_per_day"], abs=1e-9)
                    assert service_attributed[(*identity, "nominal_supply")] == pytest.approx(
                        row["nominal_capacity_per_day"], abs=1e-9)
    assert capture_state(definitions._simulation) == before


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


def test_research_investment_comparison_preserves_distinct_capital_and_capacity_dimensions(definitions):
    """Check the comparison contract, not which registered option is 'optimal'."""
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent.parent / "evaluation_plans" /
                       "research_capacity_investment.json").read_text())
    before = deepcopy(capture_state(definitions._simulation))
    results = compare_cases(data, app=definitions)["cases"]
    assert len(results) == 3
    sim = definitions._simulation
    lab_id = next(p.id for p in sim.research.providers.values()
                  if len(p.levels) > 1 and p.source_kind.value == "facility")
    provider = sim.research.providers[lab_id]
    upgrade = sim.projects.upgrade_recipes[(lab_id, 2)]
    initial, upgraded, expanded = (row["projection"]["phases"] for row in results)
    for phases in (initial, upgraded, expanded):
        first, second = phases
        assert not first["research_stages"]
        assert second["research_point_balance"]["research_stage_demand_points"] > 0
        assert second["research_point_balance"]["execution_capacity_lower_bound_days"] is not None
    assert upgraded[0]["upgrade_projects"][0]["required_construction_work"] == pytest.approx(
        upgrade.construction_work
    )
    assert expanded[0]["scale"]["facility_units_added"] == 1
    assert upgraded[0]["scale"]["facility_units_added"] == 0
    assert initial[1]["research_point_balance"]["nominal_execution_per_day"] == pytest.approx(
        provider.level_spec(1).research_execution_per_day
    )
    assert upgraded[1]["research_point_balance"]["nominal_execution_per_day"] == pytest.approx(
        provider.level_spec(2).research_execution_per_day
    )
    assert expanded[1]["research_point_balance"]["nominal_execution_per_day"] == pytest.approx(
        2 * provider.level_spec(1).research_execution_per_day
    )
    assert "research_source_facility_level_and_upgrade_investment_unassessed" in upgraded[1][
        "unassessed_constraints"
    ]
    assert capture_state(definitions._simulation) == before


def test_new_node_scoped_research_requirement_shares_node_service_ledger():
    """A future registered Stage with a local Service uses that actual node."""
    from dataclasses import replace
    from space_idle.execution_requirements import ServiceCapacityRequirement
    from space_idle.service_capacity import ServiceCapacityScope

    app = build_game_application_for_load()
    sim = app._simulation
    research = next(iter(sim.research.definitions.values()))
    stage = research.stage_specs[0]
    execution = ServiceCapacityRequirement(
        "cargo_transfer", .5, scope=ServiceCapacityScope.OPERATIONAL_NODE
    )
    sim.research.definitions[research.id] = replace(research, stage_specs=(
        replace(stage, execution_requirements=stage.execution_requirements + (execution,)),
        *research.stage_specs[1:]
    ))
    node, days = "selected.research.node", 5
    report = evaluate({"phases": [{"name": "research service", "days": days,
                                    "facilities": [], "research_stages": [
                                        {"node": node, "research": str(research.id),
                                         "stage": stage.stage_id}]}]}, app=app)["phases"][0]
    progress = getattr(stage, "research_point_cost", 0) or getattr(stage, "required_work", 0)
    expected = .5 * progress / days
    local_service = next(row for row in report["service_constraints"]
                         if row["node"] == node and row["service"] == "cargo_transfer")
    assert local_service["required_per_day"] == pytest.approx(expected)
    assert any(row["node"] == node and row["service"] == "cargo_transfer"
               and row["rate_per_day"] == pytest.approx(expected)
               for row in report["service_contributions"])
    assert not any(row["node"] == f"node:{node}" for row in report["service_constraints"])


def test_registered_solar_power_uses_owner_world_context_without_settling_operation(definitions):
    """World-site generation is Power Domain physics, not authored factor or Game output."""
    from space_idle.power import SolarGeneration
    from space_idle.shared import DefinitionId, SurfaceCellId

    sim = definitions._simulation
    before = deepcopy(capture_state(sim))
    cells = tuple(sim.power.environment.graph.surface_cells)
    solar = [definition for definition, spec in sim.power.specs.items()
             if isinstance(spec.generation, SolarGeneration)]
    assert solar and len(cells) > 1
    node, day = "conditional.solar", 0
    for facility in solar:
        for cell in cells[:2]:
            asset = {"node": node, "facility": str(facility), "units": 3, "duty": .6}
            plan = {"initial_facilities": [asset],
                    "solar_sites": [{"node": node, "facility": str(facility),
                                     "context": str(cell), "day": day}],
                    "phases": [{"name": "assumption", "days": 3, "facilities": [asset]}]}
            report = evaluate(plan, app=definitions)["phases"][0]
            expected, _ = sim.power.nominal_for_definition_at_context(
                DefinitionId(facility), SurfaceCellId(cell), day,
            )
            assert report["constraints"][0]["power_generation_nominal_mw"] == pytest.approx(expected * 3 * .6)
            assert report["power_world_context"][0]["world_context"] == str(cell)
            assert "world_solar_site_placement_and_ongoing_conditions_unassessed" in report["unassessed_constraints"]
    assert capture_state(sim) == before


def test_lunar_world_solar_and_extraction_composition_keeps_resource_power_investment_distinct(definitions):
    """Actual registered geology/power creates different conditional bottlenecks, not a winning plan."""
    import json
    from pathlib import Path
    from scripts.analysis_balance import summarize

    payload = json.loads((Path(__file__).resolve().parents[1] /
                          "evaluation_plans/lunar_site_industry_power.json").read_text())
    baseline_input = deepcopy(payload)
    before = deepcopy(capture_state(definitions._simulation))
    comparison = compare_cases(payload, app=definitions)
    summaries = summarize(comparison)
    assert payload == baseline_input
    assert capture_state(definitions._simulation) == before
    cases = {c["name"]: c["projection"]["phases"][0] for c in comparison["cases"]}
    assert len(cases) == 4
    # No pre-founded lunar Node receives a historical Facility endowment.
    assert not payload["base_plan"].get("initial_facilities")
    ridge, cold = cases["lit_ridge_site"], cases["cold_trap_site"]
    assert ridge["investment_constraints"][0]["required_work"] > 0
    assert "new_facilities_operate_before_construction_completion" in ridge["unassessed_constraints"]
    solar, extraction = cases["cold_trap_solar_expansion"], cases["cold_trap_extraction_expansion"]
    assert ridge["constraints"][0]["power_generation_nominal_mw"] > cold["constraints"][0]["power_generation_nominal_mw"]
    assert cold["extraction_world_context"][0]["diminishing_output_t_per_day"] > ridge["extraction_world_context"][0]["diminishing_output_t_per_day"]
    assert solar["constraints"][0]["power_generation_nominal_mw"] > cold["constraints"][0]["power_generation_nominal_mw"]
    assert extraction["extraction_world_context"][0]["diminishing_output_t_per_day"] > cold["extraction_world_context"][0]["diminishing_output_t_per_day"]
    assert extraction["extraction_world_context"][0]["diminishing_output_t_per_day"] < 4 * cold["extraction_world_context"][0]["diminishing_output_t_per_day"]
    for expanded in (solar, extraction):
        assert expanded["investment_constraints"][0]["required_work"] > 0
        assert expanded["investment_constraints"][0]["pre_investment_work_lower_bound_days"] is None
        assert "new_facilities_operate_before_construction_completion" in expanded["unassessed_constraints"]
    assert {"constraints", "power_world_context", "extraction_world_context", "resources", "resource_contributions"} <= {
        row["section"] for row in comparison["differences"]
    }
    assert summaries["cases"][0]["summary"]["phases"][0]["power_world_context"]
    assert summaries["cases"][1]["relative_to_baseline"] == summaries["baseline_case"]
    assert any("power_world_context" in phase["changed_sections"]
               for phase in summaries["cases"][1]["changed_phases"])


def test_solar_world_site_configuration_rejects_ambiguity(definitions):
    from space_idle.power import SolarGeneration

    sim = definitions._simulation
    solar = next(id for id, spec in sim.power.specs.items() if isinstance(spec.generation, SolarGeneration))
    cell = next(iter(sim.power.environment.graph.surface_cells))
    asset = {"node": "site", "facility": str(solar), "units": 1}
    base = {"initial_facilities": [asset], "phases": [{"name": "solar", "days": 1, "facilities": [asset]}]}
    site = {"node": "site", "facility": str(solar), "context": str(cell)}
    with pytest.raises(ValueError, match="solar_yield or solar_sites"):
        evaluate(base, app=definitions)
    with pytest.raises(ValueError, match="conflicts"):
        evaluate({**base, "solar_sites": [site], "solar_yield": {"site": 1.0}}, app=definitions)
    with pytest.raises(ValueError, match="duplicate solar World site"):
        evaluate({**base, "solar_sites": [site, site]}, app=definitions)
    with pytest.raises(ValueError, match="unknown World solar context"):
        evaluate({**base, "solar_sites": [{**site, "context": "not.a.world.site"}]}, app=definitions)
    # Two unrelated bodies may not be reported as one local Power/ore pool.
    graph = sim.power.environment.graph
    moon_cell = next(cell for cell in graph.surface_cells if str(graph.surface_cells[cell].body_id) == "base.body.moon")
    other_cell = next(cell for cell in graph.surface_cells if graph.surface_cells[cell].body_id != graph.surface_cells[moon_cell].body_id)
    with pytest.raises(ValueError, match="different bodies"):
        evaluate({**base, "solar_sites": [{**site, "context": str(other_cell)}],
                  "phases": [{**base["phases"][0], "extraction_sites": [
                      {"node": "site", "developed_cells": [str(moon_cell)]}]}]}, app=definitions)
    with pytest.raises(ValueError, match="exactly one existing target"):
        compare_cases({"base_plan": {**base, "solar_sites": [site]},
                       "cases": [{"name": "before"}, {"name": "changed", "updates": [
                           {"collection": "solar_sites", "node": "site", "id": "unknown.facility", "day": 1},
                       ]}]}, app=definitions)


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


def test_process_method_sensitivity_compares_registered_operating_chemistry_not_authored_target_rate(definitions):
    """Any registered compatible alternative changes material inputs without inventing throughput."""
    sim = definitions._simulation
    pairs = list(_compatible_processes(sim))
    alternative = next((f, a, b) for f, a in pairs for f2, b in pairs
                       if f.id == f2.id and a.id != b.id and
                       (a.inputs_per_day != b.inputs_per_day or a.outputs_per_day != b.outputs_per_day))
    facility, first, second = alternative
    node = "chosen.method"
    asset = {"node": node, "facility": str(facility.id), "units": 2,
             "process": str(first.id), "duty": .5}
    plan = {"initial_facilities": [asset], "phases": [
        {"name": "operation", "days": 10, "facilities": [asset]}]}
    comparison = compare_cases({"base_plan": plan, "cases": [
        {"name": "selected_first", "updates": []},
        {"name": "selected_second", "updates": [{"collection": "facilities", "phase": "operation",
            "node": node, "id": str(facility.id), "process": str(second.id)}]},
    ]}, app=definitions)
    initial = _rows(comparison["cases"][0]["projection"]["phases"][0])
    revised = _rows(comparison["cases"][1]["projection"]["phases"][0])
    for resource in set(first.inputs_per_day) | set(second.inputs_per_day):
        assert revised.get((node, str(resource)), {}).get("process_demand_t", 0) == pytest.approx(
            10 * facility.process_throughput_per_day * second.inputs_per_day.get(resource, 0))
    assert any(row["section"] == "resource_contributions" for row in comparison["differences"])
    assert any(initial.get(key, {}).get("net_t") != revised.get(key, {}).get("net_t")
               for key in set(initial) | set(revised))
    with pytest.raises(ValueError, match="preserve Process/Extraction kind"):
        compare_cases({"base_plan": plan, "cases": [{"name": "illegal", "updates": [
            {"collection": "facilities", "phase": "operation", "node": node,
             "id": str(facility.id), "extraction": "unrelated"}]}]}, app=definitions)


def test_cross_domain_portfolio_preserves_demand_capacity_and_unknowns_across_strategies(definitions):
    """An explicit portfolio exercises multiple Domains without making its build counts normative."""
    import json
    from pathlib import Path
    from scripts.analysis_balance import summarize

    plan = json.loads((Path(__file__).parents[1] / "evaluation_plans" /
                       "connected_industry_science_settlement_tradeoffs.json").read_text())
    projection = compare_cases(plan, app=definitions)
    assert len(projection["cases"]) == len(plan["cases"])
    assert {row["section"] for row in projection["differences"]} >= {
        "resources", "research_point_balance", "constraints", "extraction_world_context",
        "resource_contributions", "transport_services"}
    base = projection["cases"][0]["projection"]["phases"]
    early, late = base
    assert early["survey_activities"] and early["science_campaigns"] and early["founding_projects"]
    assert early["market_provider_constraints"]
    assert late["transport_services"] and late["od_transport_constraints"]
    assert any(row["notional_end_without_assumed_arrivals_t"] < row["notional_end_t"]
               for row in late["resources"] if row["received_t"] > 0)
    assert late["extraction_world_context"] and late["power_world_context"]
    assert all(not row["status"].startswith("successful") for row in late["transport_services"])
    for case in projection["cases"]:
        for phase in case["projection"]["phases"]:
            for row in phase["resources"]:
                assert row["one_time_investment_and_activity_demand_t"] >= 0
                assert row["net_t"] == pytest.approx(
                    row["nominal_recurring_net_t_per_day"] * phase["days"] -
                    row["one_time_investment_and_activity_demand_t"])
            constraints = {(row["node"], row["service"]): row for row in phase["service_constraints"]}
            for node, service in constraints:
                contributions = [s for s in phase["service_contributions"]
                                 if (s["node"], s["service"]) == (node, service)]
                assert sum(c["rate_per_day"] for c in contributions if c["role"] == "nominal_supply") == pytest.approx(
                    constraints[(node, service)]["nominal_capacity_per_day"])
            for row in phase["constraints"]:
                assert row["conditional_housing_gap_people"] == pytest.approx(max(
                    0, row["conditional_supported_residents_people"] - row["housing_nominal_people"]))
    from scripts.analysis_balance import _SUMMARY_ROW_IDENTITY, summarize_projection

    overview = summarize(projection)
    assert len(overview["cases"]) == len(projection["cases"])
    baseline_phases = overview["cases"][0]["summary"]["phases"]
    for phase in baseline_phases:
        assert "power_and_population_by_node" in phase
        assert "recurring_resource_pressures_by_node" in phase
        for collection in ("resource_shortfalls_by_node", "service_shortfalls_by_node"):
            assert all(len(row["drivers"]) <= 3 and
                       row["total_driver_count"] >= len(row["drivers"]) and
                       row["driver_detail_section"] in ("resource_contributions", "service_contributions")
                       for row in phase[collection])
    for case, summarized in zip(projection["cases"][1:], overview["cases"][1:]):
        assert summarized["relative_to_baseline"] == overview["baseline_case"]
        assert summarized["unchanged_quantities_omitted"] is True
        by_name = {phase["name"]: phase for phase in summarize_projection(case["projection"])["phases"]}
        baseline_by_name = {phase["name"]: phase for phase in baseline_phases}
        for phase in summarized["changed_phases"]:
            base, target = baseline_by_name[phase["name"]], by_name[phase["name"]]
            assert set(phase["changed_sections"]) == {
                key for key in target if key not in {"name", "days", "detail_sections"}
                and target[key] != base[key]}
            for section, change in phase["changed_sections"].items():
                if section not in _SUMMARY_ROW_IDENTITY:
                    continue
                fields = _SUMMARY_ROW_IDENTITY[section]
                identity = lambda row: tuple(row[key] for key in fields)
                before = {identity(row): row for row in base[section]}
                after = {identity(row): row for row in target[section]}
                assert {identity(row) for row in change["changed_or_added"]} == {
                    key for key in after if before.get(key) != after[key]}
                assert {identity(row) for row in change["no_longer_listed"]} == set(before) - set(after)
    # The default overview omits full unchanged case ledgers and detailed deltas.
    assert "differences" not in overview
    assert len(json.dumps(overview)) < len(json.dumps([
        summarize_projection(case["projection"]) for case in projection["cases"]]))


def test_sensitivity_can_add_new_registered_asset_and_provider_without_duplicate_ownership(definitions):
    """Alternative generations change source composition, not the shared baseline or Game State."""
    from space_idle.power import SolarGeneration
    sim = definitions._simulation
    candidate = next((facility, provider) for facility in sim.facilities.definitions.values()
                     for provider in sim.research.providers.values()
                     if provider.source_kind.value == "facility"
                     and provider.levels[0].generation_points_per_day > 0
                     and provider.accepts_source(x.id for x in facility.capability_supplies)
                     and not isinstance(sim.power.specs[facility.id].generation, SolarGeneration)
                     and facility.id in sim.projects.recipes)
    facility, provider = candidate
    node = "comparison.research"
    asset = {"node": node, "facility": str(facility.id), "units": 1}
    allocation = {"node": node, "provider": str(provider.id),
                  "source_facility": str(facility.id), "units": 1}
    base = {"phases": [{"name": "investment", "days": 30, "facilities": []}]}
    base_copy = deepcopy(base)
    additions = [
        {"action": "add", "collection": "facilities", "phase": "investment", "row": asset},
        {"action": "add", "collection": "research_provider_allocations",
         "phase": "investment", "row": allocation},
    ]
    original_state = deepcopy(capture_state(sim))
    result = compare_cases({"base_plan": base, "cases": [
        {"name": "without facility"}, {"name": "with facility", "updates": additions},
    ]}, app=definitions)
    before, after = (case["projection"]["phases"][0] for case in result["cases"])
    assert base == base_copy
    assert capture_state(sim) == original_state
    assert before["scale"]["facility_units"] == 0
    assert after["scale"]["facility_units"] == 1
    assert after["scale"]["facility_units_added"] == 1
    assert after["research_point_balance"]["nominal_generation_points"] > 0
    recipe = sim.projects.recipes[facility.id]
    assert sum(row["construction_demand_t"] for row in after["resources"]) == pytest.approx(
        sum(resource.amount_t for resource in recipe.resources))
    with pytest.raises(ValueError, match="duplicate"):
        compare_cases({"base_plan": base, "cases": [{"name": "bad", "updates":
            additions + [additions[0]]}]}, app=definitions)
    with pytest.raises(ValueError, match="cannot duplicate"):
        compare_cases({"base_plan": {"phases": [{"name": "investment", "days": 30,
            "facilities": [asset]}]}, "cases": [{"name": "bad", "updates":
            [additions[0]]}]}, app=definitions)


def test_registered_passenger_accommodations_book_once_as_one_time_fleet_provisioning(definitions):
    """Each crew-rated Vehicle brings its own seats, life support and Resource rates."""
    sim = definitions._simulation
    initial_state = deepcopy(capture_state(sim))
    for vehicle in sim.transport.vehicle_definitions():
        accommodation = vehicle.passengers
        if accommodation.seats == 0:
            continue
        origin = "hypothetical.passenger.origin"
        dest = "hypothetical.passenger.destination"
        units, people, onboard_days, phase_days = 3, 2, 4.5, 30
        fleet = [{"node": origin, "vehicle": str(vehicle.id), "units": units}]
        result = evaluate({"initial_fleet": fleet,
                           "phases": [{"name": "selected one-shot", "days": phase_days,
                                       "facilities": [], "fleet": fleet,
                                       "passenger_transfers": [{"origin": origin, "destination": dest,
                                                                "vehicle": str(vehicle.id),
                                                                "units": units, "people": people,
                                                                "assumed_onboard_days": onboard_days}]}]},
                          app=definitions)
        phase = result["phases"][0]
        row, = phase["passenger_transfer_requirements"]
        provisions = accommodation.required_provisions(people, onboard_days)
        assert row["nominal_supportable_seats"] == accommodation.supportable_seats(units)
        assert row["nominal_seat_gap_people"] == max(0, people - accommodation.supportable_seats(units))
        assert row["total_departure_payload_t"] == pytest.approx(accommodation.loaded_payload_mass(people, provisions))
        assert row["vehicle_nameplate_payload_upper_bound_t"] == pytest.approx(vehicle.performance.payload_t * units)
        assert "no_route_population_or_arrival_settlement" in row["status"]
        resource_rows = _rows(phase)
        for resource, amount in provisions.items():
            matched = resource_rows[(origin, str(resource))]
            assert matched["passenger_provisions_demand_t"] == pytest.approx(amount)
            assert matched["one_time_investment_and_activity_demand_t"] == pytest.approx(amount)
            assert matched["nominal_recurring_net_t_per_day"] == pytest.approx(0)
            contributions = [item for item in phase["resource_contributions"]
                             if item["resource"] == str(resource) and item["node"] == origin]
            assert sum(item["amount_t"] for item in contributions) == pytest.approx(-0 + amount)
            assert {item["origin_kind"] for item in contributions} == {"passenger_transfer"}
        assert "passenger_dedicated_movement_propellant_route_departure_and_arrival_unassessed" in phase["unassessed_constraints"]
    assert capture_state(sim) == initial_state


def test_passenger_comparison_shares_fleet_with_other_activities_and_preserves_seat_shortfall(definitions):
    """One-shot people cannot reuse the same Fleet; their mass is not extra Cargo."""
    from scripts.analysis_balance import compare_cases, summarize

    sim = definitions._simulation
    vehicle = next(v for v in sim.transport.vehicle_definitions() if v.passengers.supportable_seats(1) > 0)
    origin, dest = "passenger.origin", "passenger.dest"
    asset = {"node": origin, "vehicle": str(vehicle.id), "units": 2}
    plan = {"initial_fleet": [asset], "phases": [{"name": "movement window", "days": 8,
                                                  "facilities": [], "fleet": [asset]}]}
    change = {"action": "add", "collection": "passenger_transfers", "phase": "movement window",
              "row": {"origin": origin, "destination": dest, "vehicle": str(vehicle.id),
                      "units": 2, "people": vehicle.passengers.supportable_seats(2) + 1,
                      "assumed_onboard_days": 2}}
    result = compare_cases({"base_plan": plan, "cases": [
        {"name": "no trip"}, {"name": "dedicated trip", "updates": [change]}]}, app=definitions)
    detail = result["cases"][1]["projection"]["phases"][0]["passenger_transfer_requirements"][0]
    assert detail["nominal_seat_gap_people"] == 1
    assert detail["nameplate_payload_gap_t"] == pytest.approx(
        max(0, detail["total_departure_payload_t"] - detail["vehicle_nameplate_payload_upper_bound_t"]))
    assert any(row["section"] == "passenger_transfer_requirements" for row in result["differences"])
    changed = summarize(result)["cases"][1]["changed_phases"][0]["changed_sections"]
    assert "passenger_transfer_requirements" in changed
    # All two units are already claimed by the dedicated transfer.
    invalid = deepcopy(plan)
    invalid["phases"][0]["passenger_transfers"] = [change["row"]]
    invalid["phases"][0]["transport_allocations"] = [
        {"origin": origin, "destination": dest, "vehicle": str(vehicle.id), "units": 1}]
    with pytest.raises(ValueError, match="reuses Fleet"):
        evaluate(invalid, app=definitions)
    invalid = deepcopy(plan)
    invalid["phases"][0]["passenger_transfers"] = [change["row"]]
    invalid["phases"][0]["fleet"] = [{**asset, "turnarounds_per_unit_per_day": 0.1}]
    with pytest.raises(ValueError, match="overlap authored Fleet turnarounds"):
        evaluate(invalid, app=definitions)


def test_scientific_exploration_crew_site_resources_are_registered_lower_bounds(definitions):
    """Crew site days are physical at an unfounded target; flight duration remains unknown."""
    from space_idle.transport import MovementEndpoint

    sim = definitions._simulation
    initial_state = deepcopy(capture_state(sim))
    crewed = [c for c in sim.scientific_exploration.definitions.values() if c.required_crew]
    assert crewed
    for campaign in crewed:
        vehicle = next(v for v in sim.transport.vehicle_definitions()
                       if v.passengers.supportable_seats(campaign.required_units) >= campaign.required_crew)
        origin = str(campaign.origin_id)
        fleet = {"node": origin, "vehicle": str(vehicle.id), "units": campaign.required_units}
        report = evaluate({"initial_fleet": [fleet], "phases": [
            {"name": "selected campaign", "days": 70, "facilities": [], "fleet": [fleet],
             "science_campaigns": [{"campaign": str(campaign.id), "vehicle": str(vehicle.id)}]}]},
            app=definitions)["phases"][0]
        detail, = report["science_campaigns"]
        assert detail["crew_seat_gap_people"] == 0
        extra = (vehicle.passengers.required_provisions(campaign.required_crew, campaign.duration_days)
                 if isinstance(campaign.destination, MovementEndpoint) else {})
        if extra:
            assert detail["crew_registered_site_days_lower_bound"] == pytest.approx(campaign.duration_days)
            assert detail["crew_site_provisions_lower_bound_t"] == {
                str(resource): pytest.approx(amount) for resource, amount in extra.items()}
            assert detail["crew_minimum_loaded_payload_lower_bound_t"] == pytest.approx(
                campaign.minimum_payload_t * campaign.required_units +
                vehicle.passengers.loaded_payload_mass(campaign.required_crew, extra))
        else:
            assert detail["crew_site_provisions_lower_bound_t"] is None
            assert detail["crew_registered_site_days_lower_bound"] is None
        resources = _rows(report)
        for resource in set(extra) | {resource for resource, _ in campaign.consumable_resources}:
            nominal = sum(amount for item, amount in campaign.consumable_resources if item == resource)
            assert resources[(origin, str(resource))]["science_material_demand_t"] == pytest.approx(
                nominal + extra.get(resource, 0))
        assert "scientific_crew_transit_and_return_provisions_not_assessed" in report["unassessed_constraints"]
    assert capture_state(sim) == initial_state


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
    with pytest.raises(ValueError, match="duplicate|existing"):
        compare_cases({"base_plan": base, "cases": [
            {"name": "duplicated", "updates": [addition, addition]}]}, app=definitions)
    assert capture_state(sim) == before


def test_operating_industrial_scale_portfolio_compares_shared_opportunity_and_distinct_obligations(definitions):
    """The scaling portfolio exercises operating Definitions, not passive asset counts.

    Comparisons are conditional nameplate projections, not preferred Facility
    counts, a decided Cargo route, or a canonical-day progression.
    """
    import json
    from pathlib import Path
    from scripts.analysis_balance import compare_cases

    data = json.loads((Path(__file__).resolve().parent.parent / "evaluation_plans" /
                       "industrial_fleet_scale_comparison.json").read_text())
    before = deepcopy(capture_state(definitions._simulation))
    result = compare_cases(data, app=definitions)
    by_name = {case["name"]: case["projection"]["phases"][-1]
               for case in result["cases"]}
    base = by_name["installed_asset_group"]
    growth = by_name["expanded_industrial_and_fleet_group"]
    area = by_name["developed_cell_instead_of_additional_extraction_machinery"]
    industrial = by_name["industrial_capacity_growth_without_fleet_growth"]
    fleet = by_name["fleet_growth_without_industrial_capacity_growth"]
    utilization = by_name["reduced_industrial_utilization_same_assets"]
    combined = by_name["expanded_industry_with_developed_resource_area"]
    # Both asset families expand, while independent sensitivities isolate their costs.
    assert growth["scale"]["facility_units"] > base["scale"]["facility_units"]
    assert growth["scale"]["fleet_units"] > base["scale"]["fleet_units"]
    assert industrial["scale"]["fleet_units"] == base["scale"]["fleet_units"]
    assert fleet["scale"]["facility_units"] == base["scale"]["facility_units"]
    assert utilization["scale"] == base["scale"]
    assert area["scale"] == base["scale"]
    # Same World opportunity saturates as installed mine capacity grows. Area
    # development changes the available geology without duplicating the mine.
    def world(phase):
        return {(row["node"], row["resource"]): row for row in phase["extraction_world_context"]}
    b, g, a, c = map(world, (base, growth, area, combined))
    assert b.keys() == g.keys() == a.keys() == c.keys()
    for key in b:
        assert g[key]["diminishing_output_t_per_day"] >= b[key]["diminishing_output_t_per_day"]
        assert g[key]["diminishing_output_t_per_day"] <= (
            b[key]["diminishing_output_t_per_day"] *
            g[key]["adjusted_installed_capacity_t_per_day"] /
            b[key]["adjusted_installed_capacity_t_per_day"] + 1e-9)
        assert a[key]["diminishing_output_t_per_day"] >= b[key]["diminishing_output_t_per_day"]
        assert c[key]["diminishing_output_t_per_day"] >= g[key]["diminishing_output_t_per_day"]
    assert any(row["required_construction_work"] > 0 for row in area["spatial_projects"])
    assert not base["spatial_projects"]
    # Actual activities, not construction count alone, drive the Resource and
    # Service ledger, and the stage uses the already assigned research equipment.
    kinds = {row["origin_kind"] for row in base["resource_contributions"]}
    assert {"process", "extraction_opportunity", "facility_construction", "vehicle_manufacture"} <= (
        kinds | {row["origin_kind"] for row in result["cases"][0]["projection"]["phases"][0]["resource_contributions"]})
    assert base["research_point_balance"]["nominal_execution_per_day"] > 0
    assert growth["research_point_balance"]["nominal_execution_per_day"] > (
        base["research_point_balance"]["nominal_execution_per_day"])
    assert any(row["production_t"] > 0 and row["process_demand_t"] > 0
               for row in base["system_resources"])
    assert all(row["status"] in {"fleet_route_unassessed", "blocked_nominal_capacity_only",
                                      "conditional_capacity_not_cargo_settlement"}
               for row in growth["od_transport_constraints"])
    assert any(row["shortfall_without_assumed_arrivals_t"] >= row["shortfall_t"]
               for row in growth["resources"])
    assert capture_state(definitions._simulation) == before
