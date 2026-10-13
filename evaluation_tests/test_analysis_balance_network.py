"""Shared balance capacities and cyclic upstream demand in selected activities."""
from __future__ import annotations

import pytest

from scripts.analysis_balance import evaluate
from space_idle.bootstrap import build_game_application_for_load


@pytest.fixture(scope="module")
def source():
    return build_game_application_for_load()


def test_local_stock_not_credited_from_an_unselected_remote_node(source):
    """Existing remote Resource must not silently fill a local investment bill."""
    sim = source._simulation
    recipe = next(recipe for recipe in sim.projects.recipes.values()
                  if recipe.resources and recipe.facility_def_id in sim.facilities.definitions)
    material = str(recipe.resources[0].resource_id)
    origin, destination = "physical.supplier", "physical.consumer"
    plan = {"initial_stock": [{"node": origin, "resource": material, "amount_t": 10000}],
            "phases": [{"name": "invest", "days": 10,
                        "facility_investments": [{"node": destination,
                                                  "facility": str(recipe.facility_def_id), "units": 1}]}]}
    phase = evaluate(plan, app=source)["phases"][0]
    by_site = {(row["node"], row["resource"]): row for row in phase["resources"]}
    assert by_site[(destination, material)]["shortfall_without_assumed_arrivals_t"] > 0
    assert by_site[(origin, material)]["notional_end_t"] > 0
    assert not phase["od_transport_constraints"]  # no analyst-selected OD


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
