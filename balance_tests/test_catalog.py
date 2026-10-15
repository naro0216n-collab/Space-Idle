"""Content-design evidence is a read-only view of registered physical contracts.

There is deliberately no winning build, fixed research duration or reference
playthrough in this suite.
"""
from dataclasses import replace

from space_idle.content.base_catalog import build_base_catalog
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.composition.base_simulation import build_base_simulation
from content_balance.catalog import review_content


def _assembled():
    catalog = build_base_catalog()
    scenario = build_standard_scenario_definition()
    sim = build_base_simulation(
        catalog, population_rules=scenario.population_rules,
        external_population_sources=scenario.external_population_sources,
    )
    return sim, catalog, scenario


def test_content_evidence_preserves_owner_coefficients_and_separates_units():
    sim, catalog, scenario = _assembled()
    reviewed = review_content(sim, catalog, scenario)

    # The real Scenario is the opening, without applying it to mutable State.
    assert {row["node"] for row in reviewed["initial"]["facilities"]} <= set(
        reviewed["initial"]["established_nodes"]
    )
    assert sim.facilities.facilities == {}
    assert sim.research.active == {}

    # Resource links are actual Process × compatible installed Facility
    # coefficients. No fixed resource, Facility or technology names required.
    process = next(row for row in reviewed["processes"] if row["compatible_facilities"] and row["outputs_t_per_execution"])
    resource, output = next(iter(process["outputs_t_per_execution"].items()))
    provider = process["compatible_facilities"][0]
    links = reviewed["resources"][resource]["sources"]
    assert any(row["owner_id"] == process["id"] and row["facility_id"] == provider["id"]
               and row["basis"] == "t_per_day_per_nominal_facility"
               and row["quantity_t"] == output * provider["executions_per_day_nominal"]
               for row in links)

    # A yearly maintenance coefficient must never be summed into per-unit
    # construction investment or the per-day Process stream.
    facility = next(row for row in reviewed["facilities"] if row["construction"] and row["maintenance_fraction_per_year"] > 0)
    rid, cost = next(iter(facility["construction"]["resources_t"].items()))
    uses = reviewed["resources"][rid]["uses"]
    assert any(u["owner_id"] == facility["id"] and u["basis"] == "t_per_year_per_new_facility_at_recipe_investment"
               and u["quantity_t"] == cost * facility["maintenance_fraction_per_year"] for u in uses)
    assert any(u["owner_id"] == facility["id"] and u["basis"] == "t_per_new_facility"
               and u["quantity_t"] == cost for u in uses)


def test_content_edits_change_evidence_without_stale_balancing_fixtures():
    sim, catalog, scenario = _assembled()
    before = review_content(sim, catalog, scenario)
    process = next(row for row in sim.industry.processes.values() if row.outputs_per_day)
    rid, old_rate = next(iter(process.outputs_per_day.items()))
    sim.industry.processes[process.id] = replace(
        process, outputs_per_day={**process.outputs_per_day, rid: old_rate * 1.7}
    )
    after = review_content(sim, catalog, scenario)
    old = next(row for row in before["processes"] if row["id"] == process.id)
    new = next(row for row in after["processes"] if row["id"] == process.id)
    assert new["outputs_t_per_execution"][str(rid)] == old["outputs_t_per_execution"][str(rid)] * 1.7
    assert after["initial"] == before["initial"]
    assert after["research"] == before["research"]

    # Preserve all researched technologies as authored individuals, not a
    # mandatory sum of all projects sharing a display-stage label.
    assert all("mandatory_stage_cost" not in stage for stage in after["research"])
    assert all(row["id"] in sim.research.definitions for row in after["research"])

    # An opening change must only change the authored scenario evidence,
    # not silently recompute a per-resource attainable throughput envelope.
    larger_opening = replace(scenario, initial_population=tuple(
        replace(row, count=row.count + 1) for row in scenario.initial_population
    ))
    enlarged = review_content(sim, catalog, larger_opening)
    assert enlarged["initial"]["population"] != before["initial"]["population"]
    assert enlarged["processes"] == after["processes"]
    assert "initial_physical_envelopes" not in enlarged


def test_world_and_founding_contribute_to_the_same_resource_context():
    sim, catalog, scenario = _assembled()
    before = review_content(sim, catalog, scenario)
    recipe = next(iter(sim.founding.deployment_recipes.values()))
    resource, amount = next(iter(recipe.investment_totals().items()))
    manifest = {str(req.resource_id): req.amount_t for req in recipe.payload_resources}
    assert manifest[str(resource)] >= amount
    assert sum(link["quantity_t"] for link in before["resources"][str(resource)]["uses"]
               if link["owner_kind"] == "founding_payload" and link["owner_id"] == recipe.id) == manifest[str(resource)]

    cell = next(cell for cell in sim.graph.surface_cells.values() if cell.resource_potential_by_resource)
    resource, value = next(iter(cell.resource_potential_by_resource.items()))
    sim.graph.surface_cells[cell.id] = replace(
        cell, resource_potential_by_resource={**cell.resource_potential_by_resource, resource: value + 10}
    )
    after = review_content(sim, catalog, scenario)
    before_world = next(row for row in before["world"] if row["id"] == cell.body_id)
    after_world = next(row for row in after["world"] if row["id"] == cell.body_id)
    assert before_world != after_world
    assert after["initial"] == before["initial"]


def test_authored_stage_site_and_starting_conditions_preserve_physical_requirements():
    sim, catalog, scenario = _assembled()
    reviewed = review_content(sim, catalog, scenario)
    assert reviewed["initial"]["funds_balance_musd"] == scenario.funds_balance_musd
    assert len(reviewed["initial"]["market_interfaces"]) == len(scenario.market_interfaces)
    assert len(reviewed["initial"]["research_fleet_assignments"]) == len(scenario.research_fleet_assignments)

    # The registered ownership of active-vs-installed Capability and finite
    # service demand may not be erased when inspected for Content design.
    capability_sites = [row["construction"]["site"] for row in reviewed["facilities"]
                        if row["construction"] and row["construction"]["site"]["capabilities"]]
    assert capability_sites
    assert all("required_state" in capability for site in capability_sites
               for capability in site["capabilities"])
    assert any(any("minimum_pa" in condition for condition in facility["site"]["environment"])
               for facility in reviewed["facilities"])
    assert any(stage.get("execution_requirements") for item in reviewed["research"]
               for stage in item["stages"])
    assert sim.facilities.facilities == {}
    assert sim.research.active == {}




def test_physical_world_evidence_covers_registered_cells_without_climate_forecasting():
    from content_balance.world import world_evidence
    from space_idle.spatial import IlluminationField
    sim, _, _ = _assembled()
    report = world_evidence(sim)
    assert {body['id'] for body in report['bodies']} == set(map(str, sim.graph.bodies))
    all_cells = [cell for body in report['bodies'] for cell in body['surface_cells']]
    assert {cell['id'] for cell in all_cells} == set(map(str, sim.graph.surface_cells))
    for cell in all_cells:
        registered = sim.graph.surface_cells[cell['id']]
        assert cell['resource_potential_by_resource'] == {
            str(key): value for key, value in registered.resource_potential_by_resource.items()
        }
        assert cell['environment']['illumination']['values']['availability'] == (
            sim.environment.require(registered.id, IlluminationField).availability
        )
    assert 'day' not in report
    assert sim.graph.locations == {}
    assert sim.facilities.facilities == {}
