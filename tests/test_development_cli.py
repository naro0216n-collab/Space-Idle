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


def test_production_target_derives_facilities_capital_and_time_pressure_with_cumulative_asset_growth():
    _, defs = _base()
    pid, fid, resource = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    per_unit = defs["facilities"][fid]["process_throughput_per_day"] * defs["processes"][pid]["outputs_per_unit_t"][resource]
    rate_a, rate_b = per_unit * 2, per_unit * 5
    targets = lambda rate: {"node": node, "resource": resource,
                            "tonnes_per_day": rate, "method": pid, "facility": fid}
    stage_one = {"name": "first", "cumulative_hours": 4, "production_targets": [targets(rate_a)]}
    stage_two = {"name": "second", "cumulative_hours": 12, "production_targets": [targets(rate_b)]}
    data = tune(defs, _plan(stage_one, stage_two))["milestones"]
    assert data[0]["production_targets"][0]["nominal_units_if_selected"] == 2
    assert data[0]["production_targets"][0]["quantity_role"] == "authored_goal_not_verified_supply"
    assert any(r["basis"] == "conditional_minimum_for_selected_production"
               for r in data[0]["facility_end_targets"] if r["facility"] == fid)
    assert data[1]["production_targets"][0]["nominal_units_if_selected"] == 5
    first_count = next(r["count"] for r in data[0]["facility_end_targets"] if r["facility"] == fid and r["node"] == node)
    second_count = next(r["count"] for r in data[1]["facility_end_targets"] if r["facility"] == fid and r["node"] == node)
    assert first_count >= 2 and second_count >= 5
    unit_cost = defs["facilities"][fid]["construction_resources_t"]
    if unit_cost:
        rid, price = next(iter(unit_cost.items()))
        owned = next((r["count"] for r in defs["owned"]["facilities"] if r["node"] == node and r["facility"] == fid), 0)
        first_capital = next((r["quantity_t"] for r in data[0]["capital_resources_t"] if r["node"] == node and r["resource"] == rid), 0)
        second_capital = next((r["quantity_t"] for r in data[1]["capital_resources_t"] if r["node"] == node and r["resource"] == rid), 0)
        assert first_capital >= max(0, first_count - owned) * price
        assert second_capital >= max(0, second_count - first_count) * price
        assert any(row["resource"] == rid and row["average_capital_requirement_t_per_day_if_spread_over_interval"] >= 0
                   for row in data[1]["resource_time_budget"])
    assert data[1]["end_target_nominal_process_outputs_t_per_day"]
    assert "build-up" in data[0]["interpretation"]


def test_unselected_providers_are_design_choices_not_fake_installed_assets():
    _, defs = _base()
    pid, fid, resource = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    plan = _plan({"name": "design", "cumulative_hours": 2,
                  "production_targets": [{"node": node, "resource": resource, "tonnes_per_day": 10}]})
    data = tune(defs, plan)["milestones"][0]
    row = data["production_targets"][0]
    assert row["selected"] is None and row["options"]
    assert any("not selected" in reason for reason in data["unresolved_assumptions"])
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


def test_ongoing_activity_goals_inherit_across_time_milestones():
    _, defs = _base()
    pid, fid, rid = _selection(defs)
    node = defs["world"]["nodes"][0]["id"]
    initial = {"name": "entry", "cumulative_hours": 4,
               "production_targets": [{"node": node, "resource": rid, "tonnes_per_day": 2,
                                       "method": pid, "facility": fid}],
               "population_targets": [{"node": node, "people": 120}]}
    expanded = {"name": "expansion", "cumulative_hours": 12}
    result = tune(defs, _plan(initial, expanded))["milestones"]
    assert result[1]["production_targets"] == result[0]["production_targets"]
    assert result[1]["end_target_nominal_process_outputs_t_per_day"] == result[0]["end_target_nominal_process_outputs_t_per_day"]
    assert result[1]["population_targets"] == result[0]["population_targets"]
    # Existing assets are not re-purchased just because a new time interval begins.
    costs_one = {(r["node"], r["resource"]): r["quantity_t"] for r in result[0]["capital_resources_t"]}
    costs_two = {(r["node"], r["resource"]): r["quantity_t"] for r in result[1]["capital_resources_t"]}
    assert costs_one
    assert not costs_two


def test_population_outcome_derives_housing_and_life_support_capex_and_consumption():
    _, defs = _base()
    fid = next(k for k, r in defs["facilities"].items()
               if r["housing_capacity"] > 0 and (r["life_support_person_days_per_day"] or 0) > 0
               and r["life_support_resources_per_person_day_t"])
    node = defs["world"]["nodes"][0]["id"]
    data = tune(defs, _plan({"name": "pop", "cumulative_hours": 20,
                              "population_targets": [{"node": node, "people": 200,
                                  "housing_facility": fid, "life_support_facility": fid}]}))["milestones"][0]
    entry = data["population_targets"][0]
    expected = max(entry["housing_nominal_units"], entry["life_support_nominal_units"])
    assert next(x for x in data["facility_end_targets"] if x["facility"] == fid and x["node"] == node)["count"] >= expected
    for resource, amount in defs["facilities"][fid]["life_support_resources_per_person_day_t"].items():
        assert next(x for x in data["end_target_nominal_inputs_t_per_day"] if x["resource"] == resource and x["node"] == node)["quantity_t"] >= 200 * amount



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


def test_extraction_uses_output_upper_bound_without_pretending_geology_is_known():
    _, defs = _base()
    eid, method = next((eid, method) for eid, method in defs["extraction"].items()
                       if method["provider_facilities"])
    fid = method["provider_facilities"][0]
    node = defs["world"]["nodes"][0]["id"]
    stage = tune(defs, _plan({"name": "extraction", "cumulative_hours": 12,
                  "production_targets": [{"node": node, "resource": method["output_resource_id"],
                                          "tonnes_per_day": 3, "method": eid, "facility": fid}]}))["milestones"][0]
    assert stage["production_targets"][0]["selected"]["kind"] == "extraction"
    assert next(x for x in stage["end_target_nominal_process_outputs_t_per_day"] if x["resource"] == method["output_resource_id"])["quantity_t"] == 3
    assert any("geology" in caveat for caveat in stage["unresolved_assumptions"])


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
    assert row["end_target_conditional_output_t_per_day"] == unit_rate
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
    assert any("independent capacity not established" in note for note in assumed["unresolved_assumptions"])


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
    assert all(r["end_target_conditional_output_t_per_day"] == 0 for r in by_resource.values())
