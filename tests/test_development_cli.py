"""Contracts of the single whole-horizon balance evaluation, not fixed Content values."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import pytest

from space_idle.bootstrap import build_game_application, build_game_application_for_load
from space_idle.balance.pacing import FORMAT, evaluate
from space_idle.balance.application_inputs import collect_application_inputs
from space_idle.dev_cli.__main__ import main
from space_idle.persistence import load_game, save_game


@pytest.fixture(scope="module")
def source():
    app = build_game_application()
    return app, collect_application_inputs(app)


def design(periods):
    return {"format": FORMAT, "development": {"intent": "Progress from terrestrial manufacturing to remote industrial research", "objectives": [
        {"id": "research", "purpose": "Investigate scientific capability", "role": "Research and engineering", "relationships": ["industry"]},
        {"id": "industry", "purpose": "Produce, build and supply the science sector", "role": "Distributed material industry", "relationships": ["research"]},
    ]}, "periods": periods}


def period(id, hours, activities=()):
    return {"id": id, "cumulative_hours": hours, "purpose": "Industrial capability and scientific progress", "activities": list(activities)}


def activity(id, obj, kind, **kwargs):
    return {"id": id, "objective": obj, "kind": kind, **kwargs}


def sample_process(defs):
    return next((id, row["provider_facilities"][0], row) for id, row in defs["processes"].items()
                if row["provider_facilities"] and row["outputs_per_unit_t"] and row["inputs_per_unit_t"])


def tx(rows, **criteria):
    return [row for row in rows if all(row[k] == v for k, v in criteria.items())]


def test_contract_requires_real_objective_links_and_no_legacy_inputs(source):
    _, defs = source
    original = design([period("one", 4)])
    assert evaluate(defs, original)["decision"]["objectives_with_no_quantified_connection"] == ["industry", "research"]
    for invalid in (
        {**original, "format": "space-idle.pacing-targets.v1"},
        {**original, "development": {**original["development"], "intent": ""}},
        {**original, "development": {**original["development"], "objectives": original["development"]["objectives"][:1]}},
        {**original, "periods": [period("a", 5), period("b", 3)]},
        {**original, "periods": [period("a", 5, [activity("x", "missing", "research", definition="bogus")])]},
        {**original, "periods": [dict(period("one", 4), research_ids=[])]},
    ):
        with pytest.raises(ValueError):
            evaluate(defs, invalid)


def test_research_prerequisite_acquisition_is_shared_and_not_actual_completion(source):
    _, defs = source
    research_id = next(key for key, val in defs["research"].items() if val["prerequisites"])
    content = design([period("one", 4, [activity("r1", "research", "research", definition=research_id)]),
                      period("two", 12, [activity("r2", "research", "research", definition=research_id)])])
    result = evaluate(defs, content)
    evidence = result["technical_evidence"]["transactions"]
    first = tx(evidence, period="one", unit="rp")
    second = tx(evidence, period="two", unit="rp")
    assert sum(row["quantity"] for row in first) >= 0
    assert not second
    assert any(d["relation"] == "prerequisite" for d in result["technical_evidence"]["dependencies"])
    assert result["decision"]["verification"] == "not_verified"
    assert result["technical_evidence"]["periods"][0]["interval_game_days"] == 4 * 3600


def test_capital_and_continuous_operations_share_resource_and_time_with_plan_provenance(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    fid = next(fid for fid, f in defs["facilities"].items()
               if f["construction_resources_t"] and f["maintenance_per_day_t"])
    owned = next((r["count"] for r in defs["owned"]["facilities"] if r["node"] == node and r["facility"] == fid), 0)
    goal = design([period("one", 4, [activity("new", "industry", "facility", node=node, definition=fid, target_count=owned+2)]),
                   period("two", 12)])
    result = evaluate(defs, goal)
    rows = result["technical_evidence"]["transactions"]
    assert tx(rows, period="one", basis="planned_capital")
    assert not tx(rows, period="two", basis="planned_capital")
    assert tx(rows, period="one", basis="planned_continuous_input")
    assert tx(rows, period="two", basis="planned_continuous_input")
    assert all(row["period"] in {"one", "two"} for row in rows)
    connections = result["technical_evidence"]["shared_constraints"]
    assert any(set(c["periods"]) == {"one", "two"} for c in connections)
    assert not any(d.get("relation") == "planned_target" and d["status"] == "actual_at_start" and
                   d["activity"] == "new" for d in result["technical_evidence"]["dependencies"])


def test_process_is_one_authored_activity_with_both_inputs_and_all_coproducts(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    pid, fid, spec = sample_process(defs)
    plan = design([period("one", 4, [activity("method", "industry", "process", node=node,
                                               definition=pid, facility=fid, rate_per_day=2)])])
    result = evaluate(defs, plan)
    evidence = tx(result["technical_evidence"]["transactions"], activity="method")
    for resource, amount in spec["inputs_per_unit_t"].items():
        assert sum(e["quantity"] for e in evidence if e["source"] == f"resource:{node}:{resource}") == pytest.approx(2 * amount)
    for resource, amount in spec["outputs_per_unit_t"].items():
        assert sum(e["quantity"] for e in evidence if e["sink"] == f"resource:{node}:{resource}") == pytest.approx(2 * amount)
    assert all(e["basis"] == "conditional_nominal_output" for e in evidence if e["sink"].startswith("resource:"))
    assert not tx(evidence, basis="planned_capital")
    assert any(d["relation"] == "concurrent_operation" for d in result["technical_evidence"]["dependencies"])
    changed = deepcopy(defs)
    output = next(iter(spec["outputs_per_unit_t"]))
    changed["processes"][pid]["outputs_per_unit_t"][output] *= 2
    after = evaluate(changed, plan)
    before_sum = sum(e["quantity"] for e in evidence if e["sink"] == f"resource:{node}:{output}")
    after_sum = sum(e["quantity"] for e in tx(after["technical_evidence"]["transactions"], activity="method")
                    if e["sink"] == f"resource:{node}:{output}")
    assert after_sum == pytest.approx(2 * before_sum)
    assert after["decision"]["scope"] == "entire_horizon"


def test_transport_outbound_competes_with_industry_and_inbound_is_not_delivered(source):
    _, defs = source
    nodes = defs["world"]["nodes"]
    node = nodes[0]["id"]
    resource = next(iter(defs["resources"]))
    destination = "design.far"
    setup = design([period("one", 4, [activity("shipment", "industry", "transport", source=node,
                                               destination=destination, resource=resource, rate_per_day=3)])])
    setup["prospective_locations"] = [{"id": destination, "body_id": defs["world"]["bodies"][-1]["id"]}]
    result = evaluate(defs, setup)
    rows = result["technical_evidence"]["transactions"]
    assert tx(rows, source=f"resource:{node}:{resource}", quantity=3)
    assert tx(rows, sink=f"resource:{destination}:{resource}", basis="conditional_arrival_not_delivered")
    assert any(c["code"] == "transport_vehicle_unselected" for c in result["technical_evidence"]["conditions"])


def test_all_content_research_display_stages_are_not_gates(source):
    _, defs = source
    candidate = {}
    for rid, item in defs["research"].items():
        if item["stage"] is not None:
            candidate.setdefault(item["stage"], rid)
    steps = [period(str(stage), float(idx + 1), [activity("r"+str(stage), "research", "research", definition=rid)])
             for idx, (stage, rid) in enumerate(sorted(candidate.items()))]
    result = evaluate(defs, design(steps))
    assert len(result["technical_evidence"]["periods"]) == len(candidate)
    assert [r["id"] for r in result["technical_evidence"]["periods"]] == list(map(str, sorted(candidate)))
    assert result["decision"]["verification"] == "not_verified"


def test_population_life_support_is_not_magic_supply_or_mandated_growth(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    life = next(fid for fid, f in defs["facilities"].items()
                if (f["life_support_person_days_per_day"] or 0) > 0 and f["life_support_resources_per_person_day_t"])
    setup = design([period("one", 4, [activity("people", "industry", "population", node=node,
                                               people=100, life_support_facility=life)])])
    report = evaluate(defs, setup)
    assert tx(report["technical_evidence"]["transactions"], activity="people", basis="planned_continuous_input")
    assert any(c["code"] == "housing_method_unselected" for c in report["technical_evidence"]["conditions"])
    assert any(c["code"] == "population_transition_unverified" for c in report["technical_evidence"]["conditions"])


def test_single_cli_workflow_uses_real_application_and_preserves_save(tmp_path, source):
    app, defs = source
    save = tmp_path / "start.json"
    save_game(app, save, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    path, result = tmp_path / "goals.json", tmp_path / "balance.json"
    path.write_text(json.dumps(design([period("one", 4, [activity("r", "research", "research", definition=next(iter(defs["research"])))])])), encoding="utf-8")
    assert main(["--targets", str(path), "--from-save", str(save), "--output", str(result)]) == 0
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["kind"] == "whole_development_constraints"
    assert report["decision"]["scope"] == "entire_horizon"
    assert load_game(save, build_game_application_for_load)[0].game_day == 0
    for old in ("evaluate", "compare", "run", "inspect"):
        with pytest.raises(SystemExit):
            main([old])


def test_common_fleet_and_shared_process_capacity_cannot_be_credited_twice(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    destinations = [r["id"] for r in defs["world"]["nodes"] if r["id"] != node][:2]
    vehicle = next(iter(defs["vehicles"]))
    resource = next(iter(defs["resources"]))
    pid, fid, method = sample_process(defs)
    count = next((r["count"] for r in defs["owned"]["facilities"]
                  if r["node"] == node and r["facility"] == fid), 0)
    rate = defs["facilities"][fid]["process_throughput_per_day"] * (count + 5)
    plan = design([period("one", 4, [
        activity("p", "industry", "process", node=node, definition=pid, facility=fid, rate_per_day=rate),
        activity("t1", "industry", "transport", source=node, destination=destinations[0],
                 resource=resource, vehicle=vehicle, rate_per_day=1),
        activity("t2", "industry", "transport", source=node, destination=destinations[1],
                 resource=resource, vehicle=vehicle, rate_per_day=1),
    ])])
    report = evaluate(defs, plan, transport_preview=lambda *args: {"required_units": 2, "blockers": []})
    assert any(c["code"] == "process_capacity_unproven" for c in report["technical_evidence"]["conditions"])
    assert any(c["code"] == "transport_shared_fleet_insufficient" for c in report["technical_evidence"]["conditions"])
    required = [d["quantity"]["nominal_required_units"] for d in report["technical_evidence"]["dependencies"]
                if d["relation"] == "concurrent_transport_commitment"]
    assert required == [4]
    assert not tx(report["technical_evidence"]["transactions"], basis="planned_capital")


def test_activities_are_typed_and_are_not_silently_coerced(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    pid, fid, _ = sample_process(defs)
    for invalid in [
        activity("p", "industry", "process", node=node, definition=pid, facility=fid, rate_per_day=-1),
        activity("p", "industry", "process", node=node, definition=pid, rate_per_day=1),
        activity("p", "industry", "process", node=node, definition=pid, facility=fid, rate_per_day=1, people=2),
        activity("p", "industry", "facility", node=node, definition=fid, target_count=1.5),
    ]:
        with pytest.raises(ValueError):
            evaluate(defs, design([period("one", 4, [invalid])]))


def test_unchosen_supply_and_start_stock_do_not_certify_end_state(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    fid = next(fid for fid, spec in defs["facilities"].items() if spec["construction_resources_t"])
    owned = next((row["count"] for row in defs["owned"]["facilities"]
                  if row["node"] == node and row["facility"] == fid), 0)
    design_input = design([period("one", 4, [activity("buy", "industry", "facility", node=node,
                                                         definition=fid, target_count=owned+1)])])
    report = evaluate(defs, design_input)
    assert report["decision"]["verification"] == "not_verified"
    balances = [d for d in report["technical_evidence"]["dependencies"]
                if d["relation"] == "shared_resource_balance" and d["quantity"]["capital_t"] > 0]
    assert balances
    assert all(d["status"] == "supply_method_unselected" for d in balances)
    assert all(d["quantity"]["starting_real_stock_t_only"] is not None for d in balances)


def test_conditional_delivery_is_not_equated_to_missing_supply_or_received_inventory(source):
    _, defs = source
    origin, destination = (r["id"] for r in defs["world"]["nodes"][:2])
    facility = next(fid for fid, f in defs["facilities"].items()
                    if "base.resource.structural_components" in (f["construction_resources_t"] or {}))
    plan = design([period("one", 4, [
        activity("shipment", "industry", "transport", source=origin, destination=destination,
                 resource="base.resource.structural_components", rate_per_day=0.25,
                 vehicle="base.vehicle.reusable_launch_vehicle"),
        activity("capital", "research", "facility", node=destination, definition=facility, target_count=1),
    ])])
    result = evaluate(defs, plan, transport_preview=lambda *args: {
        "required_units": 1, "blockers": [{"code": "fleet", "severity": "blocking"}],
        "selected_forward_path": [], "forward_latency_days": 2})
    refs = [d for d in result["technical_evidence"]["dependencies"]
            if d["relation"] == "shared_resource_balance" and
            d["condition"] == f"resource:{destination}:base.resource.structural_components"]
    assert len(refs) == 1
    assert refs[0]["status"] == "conditional_transport_arrival"
    assert refs[0]["quantity"]["conditional_inbound_t_per_day"] == 0.25
    assert refs[0]["quantity"]["capital_t"] > 0
    codes = [i["code"] for i in result["technical_evidence"]["conditions"]]
    assert "conditional_transport_supply" in codes
    assert "transport_preview_blocked" in codes
    assert "transport_forward_path_unverified" in codes
    assert not any(i["code"] == "supply_method_unselected" and
                   i["condition"] == f"{destination}:base.resource.structural_components"
                   for i in result["technical_evidence"]["conditions"])


def test_nominal_supply_relation_and_unselected_unlock_trace_to_whole_horizon(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    pid = "base.process.standard_structural_components"
    provider = defs["processes"][pid]["provider_facilities"][0]
    f = next(fid for fid, row in defs["facilities"].items()
             if row["prerequisites"] and row["construction_resources_t"])
    plan = design([period("one", 4, [
        activity("manufacture", "industry", "process", node=node, definition=pid,
                 facility=provider, rate_per_day=0.05),
        activity("capital", "research", "facility", node=node, definition=f, target_count=10),
    ]), period("two", 12)])
    result = evaluate(defs, plan)
    material = [r for r in result["technical_evidence"]["dependencies"]
                if r["relation"] == "shared_resource_balance" and
                r["condition"] == f"resource:{node}:base.resource.structural_components"]
    assert len(material) == 2
    assert material[0]["quantity"]["conditional_supply_t_per_day"] == 0.05 * (
        defs["processes"][pid]["outputs_per_unit_t"]["base.resource.structural_components"])
    assert material[0]["quantity"]["nominal_use_including_capital_t_per_day"] > 0
    assert all(r["id"].startswith("d") for r in material)
    issues = result["technical_evidence"]["conditions"]
    assert any(i["code"] == "selected_supply_relation_incomplete" for i in issues)
    assert any(i["code"] == "requirement_method_unselected" for i in issues)
    assert result["decision"]["scope"] == "entire_horizon"
    assert any(any(ref.startswith("d") for ref in c["evidence_ids"])
               for c in result["technical_evidence"]["shared_constraints"])


def test_decision_is_a_whole_horizon_view_over_same_evidence_not_a_local_issue_list(source):
    _, defs = source
    node = defs["world"]["nodes"][0]["id"]
    plan = design([period("one", 4, [
        activity("first", "industry", "research", definition="AR-AUTONOMY-ROBOTICS-01"),
        activity("mining", "industry", "extraction", definition="base.extraction.crust_ore",
                 node=node, facility="base.facility.metal_ore_mine", rate_per_day=1.2),
    ]), period("two", 12, [
        activity("second", "research", "research", definition="AR-AUTONOMY-ROBOTICS-02"),
    ])])
    report = evaluate(defs, plan)
    evidence = report["technical_evidence"]
    all_conditions = {i["id"] for i in evidence["conditions"]}
    groups = report["decision"]["unresolved_conditions"]
    assert groups
    assert all("code" not in g and "relation_family" in g for g in groups)
    assert all_conditions == {ref for g in groups for ref in g["condition_evidence_ids"]}
    assert all(g["periods"] and g["meaning"] for g in groups)
    for c in report["decision"]["cross_period_and_cross_objective_relations"]:
        matching = next(e for e in evidence["shared_constraints"] if e["id"] == c["shared_evidence_id"])
        assert set(c["objectives"]) <= set(matching["objectives"])
        assert len(c["objectives"]) > 1
    assert report["decision"]["scope"] == "entire_horizon"


def test_multiple_freight_methods_can_share_a_route_without_silent_override(source):
    _, defs = source
    origin, destination = (r["id"] for r in defs["world"]["nodes"][:2])
    resource = "base.resource.structural_components"
    plan = design([period("one", 4, [
        activity("a", "industry", "transport", source=origin, destination=destination,
                 resource=resource, rate_per_day=0.2, vehicle="base.vehicle.reusable_launch_vehicle"),
        activity("b", "research", "transport", source=origin, destination=destination,
                 resource=resource, rate_per_day=0.3, vehicle="base.vehicle.deep_space_freighter"),
    ])])
    report = evaluate(defs, plan)
    outbound = [q for q in report["technical_evidence"]["transactions"]
                if q["source"] == f"resource:{origin}:{resource}" and
                q["activity"] in {"a", "b"} and
                q["basis"] == "planned_continuous_input"]
    assert {(q["activity"], q["quantity"]) for q in outbound} == {("a", 0.2), ("b", 0.3)}
    assert any(set(r["objectives"]) == {"industry", "research"}
               for r in report["decision"]["cross_period_and_cross_objective_relations"])
