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
    from space_idle.shared import DefinitionId

    base = build_game_application_for_load()
    sim = base._simulation
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
