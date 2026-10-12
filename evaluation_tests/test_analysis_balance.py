"""Quantitative Content experiments are not game progress or Core invariants."""
from __future__ import annotations

from copy import deepcopy
import math

import pytest

from scripts.analysis_balance import compare_cases, evaluate
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state


@pytest.fixture(scope="module")
def definitions():
    return build_game_application_for_load()


def _resource(phase, node, resource):
    return next(row for row in phase["resources"] if (row["node"], row["resource"]) == (str(node), str(resource)))


def test_quantity_model_keeps_construction_operation_maintenance_and_shortfall_distinct(definitions):
    plan = {
        "initial_stock": [
            {"node": str(ids.EARTH), "resource": str(ids.WATER), "amount_t": 1.0},
            {"node": str(ids.EARTH), "resource": str(ids.STRUCTURAL_COMPONENTS), "amount_t": 100.0},
            {"node": str(ids.EARTH), "resource": str(ids.MACHINERY), "amount_t": 100.0},
            {"node": str(ids.EARTH), "resource": str(ids.PRECISION_ELECTRONICS), "amount_t": 100.0},
        ],
        "phases": [
            {"name": "investment", "days": 2, "facilities": [
                {"node": str(ids.EARTH), "facility": str(ids.FOOD_FARM), "units": 2, "process": str(ids.PROCESS_FOOD_PRODUCTION)},
                {"node": str(ids.EARTH), "facility": str(ids.GRID_POWER_SUPPLY), "units": 1},
            ]},
            {"name": "expanded", "days": 2, "facilities": [
                {"node": str(ids.EARTH), "facility": str(ids.FOOD_FARM), "units": 3, "process": str(ids.PROCESS_FOOD_PRODUCTION)},
                {"node": str(ids.EARTH), "facility": str(ids.GRID_POWER_SUPPLY), "units": 1},
            ]},
        ],
    }
    before = deepcopy(capture_state(definitions._simulation))
    result = evaluate(plan, app=definitions)
    assert capture_state(definitions._simulation) == before
    first, second = result["phases"]
    food = _resource(first, ids.EARTH, ids.FOOD)
    water = _resource(first, ids.EARTH, ids.WATER)
    structure = _resource(first, ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    assert food["production_t"] == pytest.approx(2 * 2 * 0.36)
    assert water["process_demand_t"] == pytest.approx(2 * 2 * 0.18)
    assert structure["construction_demand_t"] == pytest.approx(2 * 6 + 8)
    assert structure["maintenance_demand_t"] == pytest.approx((2 * 6 + 8) * .05 / 365 * 2)
    assert _resource(second, ids.EARTH, ids.STRUCTURAL_COMPONENTS)["construction_demand_t"] == pytest.approx(6)
    assert _resource(second, ids.EARTH, ids.FOOD)["production_t"] == pytest.approx(3 * 2 * .36)
    assert first["constraints"][0]["power_generation_nominal_mw"] == 20
    assert first["constraints"][0]["power_demand_nominal_mw"] == pytest.approx(.28)
    assert all(row["shortfall_t"] == 0 for row in first["resources"])
    # Insufficient water is reported as a planning shortfall, not repaired by
    # invented Market purchases or interpreted as actually executed production.
    assert _resource(second, ids.EARTH, ids.WATER)["shortfall_t"] > 0
    assert result == evaluate(plan, app=definitions)


def test_transfer_is_mass_conserving_assumption_and_exposes_finite_constraints(definitions):
    first = {
        "name": "cislunar", "days": 5,
        "facilities": [{"node": str(ids.LEO), "facility": str(ids.AUTONOMOUS_ORBITAL_OUTPOST), "units": 1}],
        "transfers": [{"origin": str(ids.EARTH), "destination": str(ids.LEO),
                       "resource": str(ids.PROPELLANT), "t_per_day": 0.4}],
    }
    plan = {
        "initial_facilities": first["facilities"],
        "initial_stock": [{"node": str(ids.EARTH), "resource": str(ids.PROPELLANT), "amount_t": 5}],
        "phases": [first],
    }
    result = evaluate(plan, app=definitions)["phases"][0]
    origin, target = (_resource(result, node, ids.PROPELLANT) for node in (ids.EARTH, ids.LEO))
    assert origin["shipped_t"] == target["received_t"] == pytest.approx(2)
    assert origin["net_t"] + target["net_t"] == pytest.approx(0)
    outpost = next(row for row in result["constraints"] if row["node"] == str(ids.LEO))
    assert outpost["cargo_transfer_demand_t_per_day"] == pytest.approx(.4)
    assert outpost["cargo_transfer_gap_t_per_day"] > 0
    pool = next(row for row in result["storage"] if row["node"] == str(ids.LEO))
    assert pool["physical_capacity_t"] == 1
    assert pool["capacity_excess_t"] == pytest.approx(1)
    # Nothing in the snapshot means cargo actually unloaded or power remained on.
    assert any("not settled Game flow" in note for note in evaluate(plan, app=definitions)["assumptions"])


def test_distinct_cases_and_invalid_assumptions(definitions):
    base = {"phases": [{"name": "comparison", "days": 3, "facilities": []}]}
    future = {"phases": [{"name": "comparison", "days": 3, "facilities": [
        {"node": str(ids.EARTH), "facility": str(ids.GRID_POWER_SUPPLY), "units": 2},
    ]}]}
    comparison = compare_cases({"cases": [{"name": "without", "plan": base},
                                            {"name": "with", "plan": future}]}, app=definitions)
    assert comparison["cases"][0]["name"] == "without"
    assert comparison["cases"][1]["projection"]["phases"][0]["constraints"][0]["power_generation_nominal_mw"] == 40
    with pytest.raises(ValueError, match="unique"):
        compare_cases({"cases": [{"name": "A", "plan": base}, {"name": "A", "plan": future}]}, app=definitions)
    with pytest.raises(ValueError, match="incompatible"):
        evaluate({"phases": [{"name": "wrong", "days": 1, "facilities": [
            {"node": str(ids.EARTH), "facility": str(ids.GRID_POWER_SUPPLY),
             "process": str(ids.PROCESS_FOOD_PRODUCTION), "units": 1}]}]}, app=definitions)
    with pytest.raises(ValueError, match="removal"):
        evaluate({"initial_facilities": [{"node": str(ids.EARTH), "facility": str(ids.FOOD_FARM), "units": 2}],
                  "phases": [{"name": "remove", "days": 1, "facilities": []}]}, app=definitions)


def test_stage_inputs_and_extraction_are_explicit_numeric_assumptions(definitions):
    sim = definitions._simulation
    extraction = next((f, m) for f in sim.facilities.definitions.values()
                      for m in sim.extraction.compatible_methods(f.id)
                      if f.extraction_capacity_t_per_day > 0)
    stage_owner = next(t for t in sim.research.definitions.values() if len(t.stage_specs) > 1)
    prototype = next(t for t in stage_owner.stage_specs if t.stage_type.value == "prototype")
    plan = {"phases": [{
        "name": "resource-and-research", "days": 10,
        "facilities": [{"node": str(ids.EARTH), "facility": str(extraction[0].id),
                        "units": 2, "extraction": str(extraction[1].id),
                        "extraction_yield_fraction": 0.25}],
        "research_stages": [{"node": str(ids.EARTH), "research": str(stage_owner.id),
                             "stage": prototype.stage_id}],
    }]}
    phase = evaluate(plan, app=definitions)["phases"][0]
    row = next(p for p in phase["extraction_projections_t"] if p["resource"] == str(extraction[1].output_resource_id))
    assert row["nominal_t"] == pytest.approx(2 * 10 * extraction[0].extraction_capacity_t_per_day)
    assert row["assumed_t"] == pytest.approx(row["nominal_t"] / 4)
    assert _resource(phase, ids.EARTH, extraction[1].output_resource_id)["production_t"] == pytest.approx(row["assumed_t"])
    assert phase["research_work_demand"] == pytest.approx(prototype.required_work)
    for resource, quantity in prototype.resources.items():
        assert _resource(phase, ids.EARTH, resource)["research_material_demand_t"] == quantity
    with pytest.raises(ValueError, match="extraction_yield_fraction"):
        evaluate({"phases": [{"name": "invalid", "days": 1,
                   "facilities": [{"node": str(ids.EARTH), "facility": str(extraction[0].id), "units": 1,
                                   "extraction": str(extraction[1].id), "extraction_yield_fraction": 1.1}]}]},
                 app=definitions)


def test_case_differences_keep_independent_dimensions(definitions):
    base = {"phases": [{"name": "same", "days": 1, "facilities": []}]}
    changed = {"phases": [{"name": "same", "days": 1, "facilities": [
        {"node": str(ids.EARTH), "facility": str(ids.GRID_POWER_SUPPLY), "units": 1}]}]}
    result = compare_cases({"cases": [{"name": "no_power", "plan": base},
                                      {"name": "new_power", "plan": changed}]}, app=definitions)
    power = next(row for row in result["differences"]
                 if row["section"] == "constraints" and row["identity"]["node"] == str(ids.EARTH))
    assert power["delta_from_baseline"]["power_generation_nominal_mw"] == 20
    assert all(row["section"] != "aggregate_score" for row in result["differences"])
