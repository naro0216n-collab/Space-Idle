"""Whole-game, play-time-first balance tuning contract; no local diagnostic CLI."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isclose

import pytest

from space_idle.bootstrap import build_game_application, build_game_application_for_load
from space_idle.balance.pacing import FORMAT, tune
from space_idle.dev_cli.__main__ import main
from space_idle.persistence import save_game, load_game


def _base():
    app = build_game_application()
    return app, app.balance_definitions()


def _plan(*milestones):
    return {"format": FORMAT, "milestones": list(milestones)}


def _selection(defs):
    pid, process = next((pid, row) for pid, row in defs["processes"].items()
                        if row["provider_facilities"] and row["outputs_per_unit_t"] and
                        defs["facilities"][row["provider_facilities"][0]]["process_throughput_per_day"] > 0)
    return pid, process["provider_facilities"][0], next(iter(process["outputs_per_unit_t"]))


def test_time_goals_expose_current_cost_and_capacity_without_autotuning():
    app, defs = _base()
    rid = next(rid for rid, row in defs["research"].items() if row["prerequisites"])
    plan = _plan({"name": "phase_one", "cumulative_hours": 4,
                  "research_time_share": .5, "research_ids": [rid]},
                 {"name": "phase_two", "cumulative_hours": 12, "research_ids": [rid]})
    data = tune(defs, plan)
    first, second = data["milestones"]
    assert first["interval_game_days_at_base_speed"] == 14400
    assert second["interval_game_days_at_base_speed"] == 28800
    assert first["research"]["theory_rp_cost_at_current_content"] > 0
    assert second["research"]["theory_rp_cost_at_current_content"] == 0
    assert isclose(first["research"]["required_average_rp_per_day_if_full_interval"],
                   first["research"]["theory_rp_cost_at_current_content"] / 14400)
    assert isclose(first["research"]["required_average_rp_per_day_if_share_assumed"],
                   first["research"]["theory_rp_cost_at_current_content"] / 7200)
    assert second["research"]["assumed_research_time_share"] is None
    assert second["research"]["required_average_rp_per_day_if_share_assumed"] is None
    assert first["research"]["single_provider_options"]
    assert all(p["nominal_units_if_sole_provider_from_zero"] >= 1
               for p in first["research"]["single_provider_options"])
    # A higher RP cost changes the required rate, not a supposedly correct Content multiplier.
    edited = {**defs, "research": {**defs["research"]}}
    edited_research = {**defs["research"][rid]}
    edited_research["stages"] = [{**s, "rp": s["rp"] * 3} if s["kind"] == "theory" else s
                                 for s in edited_research["stages"]]
    edited["research"][rid] = edited_research
    after = tune(edited, plan)["milestones"][0]
    assert after["research"]["required_average_rp_per_day_if_full_interval"] > first["research"]["required_average_rp_per_day_if_full_interval"]
    assert after["research"]["nominal_end_target_research_capacity"] == first["research"]["nominal_end_target_research_capacity"]
    assert "theory_rp_cost_scale_to_fit_budget" not in after["research"]


def test_production_goal_is_not_a_purchase_or_supply_plan_across_stages():
    _, defs = _base()
    pid, fid, resource = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    rate = defs["facilities"][fid]["process_throughput_per_day"] * defs["processes"][pid]["outputs_per_unit_t"][resource] * 4
    one = {"name": "one", "cumulative_hours": 4, "production_targets": [
        {"node": node, "resource": resource, "tonnes_per_day": rate, "facility": fid, "method": pid}]}
    two = {"name": "two", "cumulative_hours": 12}
    first, second = tune(defs, _plan(one, two))["milestones"]
    assert first["production_targets"][0]["nominal_units_if_selected"] == 4
    assert second["production_targets"] == first["production_targets"]
    assert not first["capital_resources_t"] and not second["capital_resources_t"]
    actual = {(row["node"], row["facility"]): row["count"] for row in defs["owned"]["facilities"]}
    assert {(r["node"], r["facility"]): r["count"] for r in first["facility_end_targets"]} == actual
    assert {(r["node"], r["facility"]): r["count"] for r in second["facility_end_targets"]} == actual
    assert not first["conditional_reference_process_outputs_t_per_day"]


def test_unselected_providers_are_design_choices_not_fake_installed_assets():
    _, defs = _base()
    pid, fid, resource = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    plan = _plan({"name": "design", "cumulative_hours": 2,
                  "production_targets": [{"node": node, "resource": resource, "tonnes_per_day": 10}]})
    data = tune(defs, plan)["milestones"][0]
    row = data["production_targets"][0]
    assert row["selected"] is None and row["options"]
    assert any(reason["code"] == "production_goal_supply_method_unselected" for reason in data["constraints"])
    before = {(r["node"], r["facility"]): r["count"] for r in defs["owned"]["facilities"]}
    after = {(r["node"], r["facility"]): r["count"] for r in data["facility_end_targets"]}
    assert after == before


def test_all_registered_stages_supported_without_hardcoded_gameplay_gates():
    _, defs = _base()
    candidates = {}
    for rid, row in defs["research"].items():
        if row["stage"] is not None:
            candidates.setdefault(row["stage"], rid)
    stages = sorted(candidates)
    hours = 0
    plan = []
    for stage in stages:
        hours += stage * 2
        plan.append({"name": str(stage), "cumulative_hours": hours,
                     "research_ids": [candidates[stage]]})
    results = tune(defs, _plan(*plan))["milestones"]
    assert [r["name"] for r in results] == list(map(str, stages))
    assert results[-1]["research"]["new_prerequisites_and_research"]
    assert all(row["interval_game_days_at_base_speed"] > 0 for row in results)


def test_prospective_nodes_and_transport_remain_design_estimates():
    _, defs = _base()
    node = "design.outer"
    body = defs["world"]["bodies"][-1]["id"]
    rid = next(iter(defs["resources"]))
    vehicles = next(iter(defs["vehicles"]))
    start = defs["world"]["nodes"][0]["id"]
    plan = {**_plan({"name": "outpost", "cumulative_hours": 120,
                    "transport_targets": [{"source": start, "destination": node, "resource": rid,
                                           "tonnes_per_day": 6, "vehicle": vehicles}],
                    "population_targets": [{"node": node, "people": 150}]}),
            "prospective_locations": [{"id": node, "body_id": body}]}
    data = tune(defs, plan)
    route = data["milestones"][0]["transport_targets"][0]
    assert data["prospective_locations"][node] == body
    assert route["canonical_preview"] is None
    assert route["target_t_per_day"] == 6


def test_invalid_time_targets_and_duplicate_assets_fail_without_fallback():
    _, defs = _base()
    node = defs["world"]["nodes"][0]["id"]
    fid = next(iter(defs["facilities"]))
    invalids = [
        _plan({"name": "one", "cumulative_hours": 3}, {"name": "two", "cumulative_hours": 2}),
        _plan({"name": "one", "cumulative_hours": True}),
        _plan({"name": "one", "cumulative_hours": 1, "research_time_share": 1.1}),
        _plan({"name": "one", "cumulative_hours": 1, "research_ids": ["invalid"]}),
        _plan({"name": "one", "cumulative_hours": 1, "facility_targets": [
            {"node": node, "facility": fid, "count": 2}, {"node": node, "facility": fid, "count": 3}]}),
    ]
    for plan in invalids:
        with pytest.raises(ValueError):
            tune(defs, plan)


def test_cli_uses_one_time_first_workflow_and_preserves_canonical_save(tmp_path):
    app, defs = _base()
    start = tmp_path / "start.json"
    save_game(app, start, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    rid = next(iter(defs["research"]))
    plan = tmp_path / "targets.json"
    plan.write_text(json.dumps(_plan({"name": "target", "cumulative_hours": 4,
                                      "research_ids": [rid]})), encoding="utf-8")
    out = tmp_path / "report.json"
    assert main(["--targets", str(plan), "--from-save", str(start), "--output", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["kind"] == "balance_pacing"
    assert report["milestones"][0]["target_cumulative_hours"] == 4
    assert load_game(start, build_game_application_for_load)[0].game_day == 0
    for obsolete in ("overview", "evaluate", "inspect", "run", "compare"):
        with pytest.raises(SystemExit):
            main([obsolete])


def test_only_explicit_purchases_create_capital_and_inherit_as_planned_assets():
    _, defs = _base()
    pid, fid, resource = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    owned = next((row["count"] for row in defs["owned"]["facilities"] if row["facility"] == fid and row["node"] == node), 0)
    first, second = tune(defs, _plan({"name": "first", "cumulative_hours": 4,
              "facility_targets": [{"node": node, "facility": fid, "count": owned + 3}],
              "population_targets": [{"node": node, "people": 120}]},
              {"name": "second", "cumulative_hours": 12}))["milestones"]
    recipe = defs["facilities"][fid]["construction_resources_t"]
    if recipe:
        for resource, qty in recipe.items():
            assert any(r["node"] == node and r["resource"] == resource and
                       r["quantity_t"] >= qty * 3 for r in first["capital_resources_t"])
    assert not second["capital_resources_t"]
    assert second["state_provenance"]["ending_assets"] == "explicit_authored_targets_not_achieved_game_state"
    assert first["population_targets"] == second["population_targets"]


def test_population_support_reference_does_not_fabricate_asset_but_exposes_operating_demand():
    _, defs = _base()
    fid = next(k for k, r in defs["facilities"].items()
               if r["housing_capacity"] > 0 and (r["life_support_person_days_per_day"] or 0) > 0
               and r["life_support_resources_per_person_day_t"])
    node = defs["world"]["nodes"][0]["id"]
    data = tune(defs, _plan({"name": "pop", "cumulative_hours": 20,
                "population_targets": [{"node": node, "people": 200,
                    "housing_facility": fid, "life_support_facility": fid}]}))["milestones"][0]
    entry = data["population_targets"][0]
    assert entry["housing_nominal_units"] >= 1 and entry["life_support_nominal_units"] >= 1
    assert not data["capital_resources_t"]
    assert any(x["code"] == "planned_population_support_below_reference" for x in data["constraints"])
    for resource, amount in defs["facilities"][fid]["life_support_resources_per_person_day_t"].items():
        assert next(x for x in data["resource_time_budget"] if x["resource"] == resource and x["node"] == node)["end_target_operation_input_t_per_day"] >= 200 * amount


def test_population_targets_do_not_replace_research_selection_or_time_budget():
    _, defs = _base()
    node = defs["world"]["nodes"][0]["id"]
    facility = next(fid for fid, row in defs["facilities"].items()
                    if row["housing_capacity"] > 0 and
                    (row["life_support_person_days_per_day"] or 0) > 0)
    rid = next(rid for rid, row in defs["research"].items()
               if row["stage"] == 1 and row["stages"])
    milestone = {"name": "early_development", "cumulative_hours": 4,
                 "research_ids": [rid],
                 "population_targets": [{"node": node, "people": 120,
                                         "housing_facility": facility,
                                         "life_support_facility": facility}]}
    report = tune(defs, _plan(milestone))["milestones"][0]
    assert report["research"]["selected_ids"] == [rid]
    assert rid in report["research"]["new_prerequisites_and_research"] or rid in defs["owned"]["completed_technologies"]
    assert report["research"]["theory_rp_cost_at_current_content"] >= 0
    assert report["population_targets"][0]["target_people"] == 120


def test_extraction_reference_is_not_achieved_supply_and_requires_site_conditions():
    _, defs = _base()
    eid, method = next((eid, method) for eid, method in defs["extraction"].items()
                       if method["provider_facilities"])
    fid = method["provider_facilities"][0]
    node = defs["world"]["nodes"][0]["id"]
    stage = tune(defs, _plan({"name": "extraction", "cumulative_hours": 12,
                  "production_targets": [{"node": node, "resource": method["output_resource_id"],
                      "tonnes_per_day": 3, "method": eid, "facility": fid}]}))["milestones"][0]
    assert stage["production_targets"][0]["selected"]["kind"] == "extraction"
    assert not stage["conditional_reference_process_outputs_t_per_day"]
    assert stage["production_targets"][0]["quantity_role"] == "authored_goal_not_verified_supply"


def test_supply_assumptions_are_explicit_and_not_inferred_from_production_targets():
    _, defs = _base()
    pid, fid, resource = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    unit_rate = (defs["facilities"][fid]["process_throughput_per_day"] *
                 defs["processes"][pid]["outputs_per_unit_t"][resource])
    stage = {"name": "whole_economy", "cumulative_hours": 4,
             "production_targets": [{"node": node, "resource": resource,
                                     "tonnes_per_day": unit_rate,
                                     "facility": fid, "method": pid}]}
    baseline = tune(defs, _plan(stage))["milestones"][0]
    row = next(r for r in baseline["resource_time_budget"] if r["node"] == node and r["resource"] == resource)
    assert row["authored_supply_assumption_t_per_day"] is None
    assert row["conditional_reference_output_t_per_day"] == 0
    assert "affordable_capital_recipe_scale_if_budget_stated" not in row
    with pytest.raises(ValueError):
        tune(defs, _plan({**stage, "resource_supply_assumptions": [
            {"node": node, "resource": resource, "average_t_per_day": unit_rate}]}))
    assumed = tune(defs, _plan({**stage, "resource_supply_assumptions": [
        {"node": node, "resource": resource, "average_t_per_day": unit_rate,
         "basis": "Independent supply estimate, verify later"}]}))["milestones"][0]
    row = next(r for r in assumed["resource_time_budget"] if r["node"] == node and r["resource"] == resource)
    assert row["assumption_matches_conditional_production_target"]
    assert row["supply_assumption_basis"] == "Independent supply estimate, verify later"
    assert any(note["code"] == "supply_assumption_equals_production_goal" for note in assumed["constraints"])


def test_provider_reference_does_not_create_assets_or_adjust_costs():
    _, defs = _base()
    rid = next(rid for rid, row in defs["research"].items() if row["stages"])
    fid = next(fid for fid, row in defs["facilities"].items() if row["research_provider"])
    node = defs["world"]["nodes"][0]["id"]
    result = tune(defs, _plan({"name": "reference", "cumulative_hours": 4,
                               "research_ids": [rid],
                               "research_provider": {"node": node, "facility": fid}}))["milestones"][0]
    owned = {(r["node"], r["facility"]): r["count"] for r in defs["owned"]["facilities"]}
    counted = {(r["node"], r["facility"]): r["count"] for r in result["facility_end_targets"]}
    assert counted == owned
    assert result["research"]["selected_provider_reference"]["nominal_units_if_sole_provider_from_zero"] >= 1
    assert result["research"]["nominal_start_research_capacity"] == result["research"]["nominal_end_target_research_capacity"]
    assert not result["capital_resources_t"]


def test_full_economy_totals_include_investment_and_operating_but_not_fabricated_supply():
    _, defs = _base()
    node = defs["world"]["nodes"][0]["id"]
    fid = next(fid for fid, spec in defs["facilities"].items()
               if spec["construction_resources_t"] and spec["operating_per_day_t"])
    result = tune(defs, _plan({"name": "industry", "cumulative_hours": 4,
                               "facility_targets": [{"node": node, "facility": fid, "count": 12}]}))["milestones"][0]
    by_resource = {r["resource"]: r for r in result["economy_resources_across_nodes"]}
    assert any(r["capital_investment_t"] > 0 for r in by_resource.values())
    assert all(r["not_deliverable_global_supply"] for r in by_resource.values())
    assert all(r["conditional_reference_output_t_per_day"] == 0 for r in by_resource.values())


def test_demand_first_coproduct_process_is_counted_once_and_has_upstream_unresolved():
    from copy import deepcopy
    _, original = _base()
    defs = deepcopy(original)
    node = defs["world"]["nodes"][0]["id"]
    resources = list(defs["resources"])
    assert len(resources) >= 3
    a, b, raw = resources[:3]
    supplier = next(fid for fid, spec in defs["facilities"].items()
                    if spec["process_throughput_per_day"] > 0)
    purchased = next(fid for fid, spec in defs["facilities"].items()
                     if spec["construction_resources_t"] is not None)
    defs["facilities"][purchased]["construction_resources_t"] = {a: 100, b: 200}
    defs["processes"]["test.co_output"] = {
        "provider_facilities": [supplier], "prerequisites": [],
        "inputs_per_unit_t": {raw: 2}, "outputs_per_unit_t": {a: 5, b: 10}}
    choices = [{"node": node, "resource": r, "method": "test.co_output", "facility": supplier}
               for r in (a, b)]
    present = next((row["count"] for row in defs["owned"]["facilities"]
                    if row["node"] == node and row["facility"] == purchased), 0)
    plan = _plan({"name": "plan", "cumulative_hours": 1,
                  "facility_targets": [{"node": node, "facility": purchased, "count": present + 1}],
                  "supply_choices": choices})
    result = tune(defs, plan)
    stage = result["milestones"][0]
    process = next(p for p in stage["selected_supply_processes"] if p["method"] == "test.co_output")
    assert isclose(process["conditional_activity_units_per_day"], 20 / 3600)
    assert isclose(process["outputs_t_per_day"][a], 100 / 3600)
    assert isclose(process["outputs_t_per_day"][b], 200 / 3600)
    assert isclose(process["inputs_t_per_day"][raw], 40 / 3600)
    assert any(row["code"] == "supply_not_established" and row["resource"] == raw
               for row in stage["constraints"])
    counts = {(row["node"], row["facility"]): row["count"] for row in stage["facility_end_targets"]}
    supplier_actual = next((x["count"] for x in defs["owned"]["facilities"]
                            if x["node"] == node and x["facility"] == supplier), 0)
    assert counts.get((node, supplier), 0) == supplier_actual + (1 if supplier == purchased else 0)
    assert stage["reference_facility_units_not_acquired"]
    # Changing the one canonical Process coefficient affects upstream consumption and all outputs.
    changed = deepcopy(defs)
    changed["processes"]["test.co_output"]["outputs_per_unit_t"] = {a: 10, b: 20}
    other = tune(changed, plan)["milestones"][0]
    modified = next(p for p in other["selected_supply_processes"] if p["method"] == "test.co_output")
    assert isclose(modified["conditional_activity_units_per_day"], process["conditional_activity_units_per_day"] / 2)
    assert isclose(modified["inputs_t_per_day"][raw], process["inputs_t_per_day"][raw] / 2)
    assert modified["reference_nominal_facility_units"] <= process["reference_nominal_facility_units"]
    assert result["summary"][0]["milestone"] == "plan"
    assert any(x["kind"] == "selected_supply_process" for x in result["evidence"])


def test_selected_supply_cycle_is_unverified_not_created_as_self_supply():
    from copy import deepcopy
    _, original = _base()
    defs = deepcopy(original)
    node = defs["world"]["nodes"][0]["id"]
    resource = next(iter(defs["resources"]))
    supplier = next(fid for fid, spec in defs["facilities"].items()
                    if spec["process_throughput_per_day"] > 0)
    purchased = next(fid for fid, spec in defs["facilities"].items()
                     if spec["construction_resources_t"] is not None)
    defs["facilities"][purchased]["construction_resources_t"] = {resource: 10}
    defs["processes"]["test.circular"] = {
        "provider_facilities": [supplier], "prerequisites": [],
        "inputs_per_unit_t": {resource: 1}, "outputs_per_unit_t": {resource: 1}}
    current = next((row["count"] for row in defs["owned"]["facilities"]
                    if row["node"] == node and row["facility"] == purchased), 0)
    report = tune(defs, _plan({"name": "circular", "cumulative_hours": 1,
        "facility_targets": [{"node": node, "facility": purchased, "count": current + 1}],
        "supply_choices": [{"node": node, "resource": resource, "method": "test.circular",
                            "facility": supplier}]}))["milestones"][0]
    assert any(x["code"] == "supply_cycle" for x in report["constraints"])
    assert report["state_provenance"]["reference_units"] == "conditional_not_acquired"


def test_transport_reference_units_never_become_acquired_fleet():
    _, defs = _base()
    src = defs["world"]["nodes"][0]["id"]
    dst = defs["world"]["nodes"][1]["id"]
    vehicle = next(iter(defs["vehicles"]))
    resource = next(iter(defs["resources"]))
    result = tune(defs, _plan({"name": "routes", "cumulative_hours": 5,
        "transport_targets": [{"source": src, "destination": dst, "resource": resource,
                               "vehicle": vehicle, "tonnes_per_day": 1}]}),
        transport_preview=lambda *args: {"required_units": 7})["milestones"][0]
    assert result["transport_targets"][0]["reference_required_units_not_acquired"] == 7
    actual = {(r["node"], r["vehicle"]): r["count"] for r in defs["owned"]["fleet"]}
    assert {(r["node"], r["vehicle"]): r["count"] for r in result["fleet_end_targets"]} == actual
    assert not result["capital_resources_t"]


def test_supply_choices_must_be_unique_and_never_select_missing_method():
    _, defs = _base()
    node = defs["world"]["nodes"][0]["id"]
    resource = next(iter(defs["resources"]))
    facility = next(iter(defs["facilities"]))
    choice = {"node": node, "resource": resource, "method": "unknown_method", "facility": facility}
    base = {"name": "supply", "cumulative_hours": 1}
    with pytest.raises(ValueError, match="duplicate supply choice"):
        tune(defs, _plan({**base, "supply_choices": [choice, choice]}))
    with pytest.raises(ValueError, match="unknown supply method"):
        tune(defs, _plan({**base, "supply_choices": [choice]}))


def test_whole_report_contains_typed_conditions_and_traces_to_canonical_definitions():
    _, defs = _base()
    facility = next(fid for fid, spec in defs["facilities"].items() if spec["construction_resources_t"])
    node = defs["world"]["nodes"][0]["id"]
    owned = next((row["count"] for row in defs["owned"]["facilities"]
                  if row["node"] == node and row["facility"] == facility), 0)
    report = tune(defs, _plan({"name": "stage1", "cumulative_hours": 4,
                               "facility_targets": [{"node": node, "facility": facility, "count": owned + 1}]},
                              {"name": "stage2", "cumulative_hours": 12}))
    assert report["summary"][0]["milestone"] == "stage1"
    assert all(isinstance(issue["limits"], list) and issue["code"]
               for stage in report["milestones"] for issue in stage["constraints"])
    assert any(row["milestone"] == "stage1" and row["id"] == facility and
               row["kind"] == "facility_acquisition" for row in report["evidence"])
    assert report["milestones"][1]["state_provenance"]["starting_assets"] == "planned_previous_milestone_not_actual"
