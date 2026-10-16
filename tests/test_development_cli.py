"""Balance CLI contracts; game transitions are covered by their owning Domain tests."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isclose

import pytest

from space_idle.bootstrap import build_game_application, build_game_application_for_load
from space_idle.balance.analysis import overview, evaluate, inspect
from space_idle.dev_cli.__main__ import main
from space_idle.persistence import save_game, load_game


def _base():
    app = build_game_application()
    return app, app.balance_definitions()


def _assessment(periods):
    return {"format": "space-idle.balance-assessment.v1", "periods": periods}


def test_overview_covers_all_research_and_all_registered_generations():
    _, defs = _base()
    result = overview(defs)
    assert result["counts"]["research"] == len(defs["research"])
    assert sum(row["count"] for row in result["research_by_stage"].values()) == len(defs["research"])
    assert set(result["research_by_stage"]) == {str(x["stage"]) for x in defs["research"].values()}
    assert len(result["resource_links"]) == len(defs["resources"])
    assert all(row["facility_builds"] == sorted(row["facility_builds"]) for row in result["resource_links"].values())


def test_incremental_investment_and_nominal_daily_demand_are_distinct():
    app, defs = _base()
    fid = next(fid for fid, row in defs["facilities"].items() if row["construction_resources_t"])
    node = defs["world"]["nodes"][0]["id"]
    existing = next((row["count"] for row in defs["owned"]["facilities"] if row["node"] == node and row["facility"] == fid), 0)
    input_data = _assessment([
        {"name": "first", "period_days": 30, "facilities": [{"node": node, "facility": fid, "count": existing + 2}]},
        {"name": "later", "period_days": 180, "facilities": [{"node": node, "facility": fid, "count": existing + 5}]},
    ])
    before = app.balance_definitions()["owned"]
    report = evaluate(defs, input_data, current=app.balance_current(), power_site=app.balance_site_power)
    assert app.balance_definitions()["owned"] == before
    expected_unit = defs["facilities"][fid]["construction_resources_t"]
    for row, units in zip(report["periods"], (2, 3)):
        assert [item for item in row["acquisitions"] if item["id"] == fid][0]["units"] == units
        amount = {item["resource"]: item["quantity"] for item in row["investment_by_resource"] if item["node"] == node}
        for rid, per_unit in expected_unit.items():
            assert isclose(amount[rid], units * per_unit)
        assert row["period_days"] in (30, 180)
        assert row["partial_local_nominal_balance"] is not None
        assert all(item["measure"] == "investment_t" for item in row["investment_entries"])


def test_research_prerequisite_closure_is_counted_once():
    _, defs = _base()
    rid = next(k for k, row in defs["research"].items() if row["prerequisites"])
    first = _assessment([{"name": "research", "period_days": 50, "research_ids": [rid, rid, defs["research"][rid]["prerequisites"][0]]}])
    result = evaluate(defs, first)["periods"][0]
    unique = result["research"]["prerequisite_closure"]
    assert len(unique) == len(set(unique))
    expected = sum(stage.get("rp", 0) for key in unique for stage in defs["research"][key]["stages"])
    assert isclose(result["research"]["theory_rp_total"], expected)
    assert result["research"]["average_is_not_completion_or_admission_guarantee"]


def test_process_nominal_balance_and_contributor_are_traceable():
    _, defs = _base()
    process_id, spec = next((pid, row) for pid, row in defs["processes"].items() if row["provider_facilities"] and row["inputs_per_unit_t"])
    facility_id = spec["provider_facilities"][0]
    node = defs["world"]["nodes"][0]["id"]
    count = 4
    period = {"name": "industry", "period_days": 25, "facilities": [
        {"node": node, "facility": facility_id, "count": count, "process": process_id, "utilization": 0.5}
    ]}
    report = evaluate(defs, _assessment([period]))
    scale = defs["facilities"][facility_id]["process_throughput_per_day"] * count * .5
    for resource, rate in spec["inputs_per_unit_t"].items():
        flow = [r for r in report["periods"][0]["operation_entries"] if r["source"] == process_id and r["resource"] == resource]
        assert flow and isclose(flow[0]["quantity"], rate * scale)
    narrowed = inspect(report, resource=next(iter(spec["inputs_per_unit_t"])), period="industry")
    assert narrowed["periods"][0]["operation_entries"]
    assert all(item["resource"] == next(iter(spec["inputs_per_unit_t"])) for item in narrowed["periods"][0]["operation_entries"])


def test_unknown_and_nonfinite_inputs_are_rejected():
    _, defs = _base()
    node = defs["world"]["nodes"][0]["id"]
    examples = [
        {"name": "bad", "period_days": 0},
        {"name": "bad", "period_days": 10, "facilities": [{"node": node, "facility": "invalid", "count": 5}]},
        {"name": "bad", "period_days": 10, "facilities": [{"node": node, "facility": next(iter(defs["facilities"])), "count": True}]},
        {"name": "bad", "period_days": 10, "transport_demands": [{"source": node, "destination": node, "resource": next(iter(defs["resources"])), "tonnes_per_day": float("nan")}]},
    ]
    for period in examples:
        with pytest.raises(ValueError): evaluate(defs, _assessment([period]))


def test_cli_overview_evaluate_inspect_and_canonical_save_input(tmp_path, capsys):
    from space_idle.dev_cli.__main__ import _load
    app = build_game_application()
    path = tmp_path / "start.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    over = tmp_path / "overview.json"
    assert main(["overview", "--from-save", str(path), "--output", str(over)]) == 0
    assert _load(over)["kind"] == "balance_overview"
    spec = tmp_path / "assessment.json"
    spec.write_text(json.dumps(_assessment([{"name": "future", "period_days": 120}])), encoding="utf-8")
    out = tmp_path / "evaluated.json"
    assert main(["evaluate", "--assessment", str(spec), "--from-save", str(path), "--output", str(out)]) == 0
    assert main(["inspect", "--report", str(out), "--period", "future", "--output", str(tmp_path / "inspect.json")]) == 0
    assert _load(tmp_path / "inspect.json")["kind"] == "balance_inspect"
    restored, _ = load_game(path, build_game_application_for_load)
    assert restored.game_day == 0
    assert _load(out)["identity"]["game_day"] == 0
    with pytest.raises(SystemExit): main(["run", "--script", str(spec)])


def test_unestablished_future_location_can_be_assessed_without_creating_game_node():
    app, definitions = _base()
    body_id = definitions["world"]["bodies"][-1]["id"]
    facility_id = next(fid for fid, spec in definitions["facilities"].items() if spec["construction_resources_t"])
    future = "design.prospective.outer_world"
    hypothesis = {"format": "space-idle.balance-assessment.v1",
                  "prospective_locations": [{"id": future, "body_id": body_id}],
                  "periods": [{"name": "industrialization", "period_days": 90,
                               "facilities": [{"node": future, "facility": facility_id, "count": 5}]},
                              {"name": "mature_network", "period_days": 210,
                               "facilities": [{"node": future, "facility": facility_id, "count": 14}]}]}
    report = evaluate(definitions, hypothesis, power_site=app.balance_site_power)
    assert report["prospective_locations"][future] == body_id
    assert report["periods"][0]["acquisitions"][0]["units"] == 5
    assert report["periods"][1]["acquisitions"][0]["units"] == 9
    assert future not in {row["id"] for row in app.balance_definitions()["world"]["nodes"]}
    assert any("Prospective" in reason for reason in report["periods"][0]["caveats"])
    with pytest.raises(ValueError):
        evaluate(definitions, {**hypothesis, "prospective_locations": [{"id": future, "body_id": "invalid"}]})


def test_population_support_materials_and_common_nominal_capacity_ledger():
    _, definitions = _base()
    facility_id = next(fid for fid, row in definitions["facilities"].items()
                       if row["life_support_person_days_per_day"] is not None)
    node = definitions["world"]["nodes"][0]["id"]
    hypothesis = _assessment([{"name": "residents", "period_days": 15,
                              "facilities": [{"node": node, "facility": facility_id, "count": 2}],
                              "population": [{"node": node, "people": 20,
                                              "life_support_facility": facility_id}]}])
    row = evaluate(definitions, hypothesis)["periods"][0]
    life_support = next(item for item in row["capacity_balance"] if item["node"] == node and item["service"] == "life_support")
    assert life_support["stated_requirement"] == 20
    assert life_support["nominal_supply"] >= 0
    for resource_id, rate in definitions["facilities"][facility_id]["life_support_resources_per_person_day_t"].items():
        expected = [item for item in row["operation_entries"] if item["source"] == facility_id
                    and item["purpose"] == "population_life_support" and item["resource"] == resource_id]
        assert expected and isclose(expected[0]["quantity"], rate * 20)


def test_report_distinguishes_material_content_changes_despite_same_content_id():
    app, original = _base()
    from dataclasses import replace
    from space_idle.shared import DefinitionId
    from space_idle.construction.models import ConstructionRecipe
    recipe_id = next(iter(app._simulation.projects.recipes))
    prior = app._simulation.projects.recipes[recipe_id]
    app._simulation.projects.recipes[recipe_id] = replace(prior, construction_work=prior.construction_work + 1)
    modified = app.balance_definitions()
    assert original["identity"]["content_id"] == modified["identity"]["content_id"]
    assert original["identity"]["balance_definition_sha256"] != modified["identity"]["balance_definition_sha256"]


def test_canonical_transport_preview_is_kept_separate_from_assumed_delivery():
    from space_idle.dev_cli.__main__ import _transport_preview
    app, defs = _base()
    first, second = defs["world"]["nodes"][:2]
    hypothesis = _assessment([{"name": "route_demand", "period_days": 20,
                              "transport_demands": [{"source": first["id"], "destination": second["id"],
                                                     "vehicle": next(iter(defs["vehicles"])),
                                                     "resource": next(iter(defs["resources"])),
                                                     "tonnes_per_day": 4.0}]}])
    route = evaluate(defs, hypothesis, transport_preview=_transport_preview(app))["periods"][0]["transport_demands"][0]
    assert route["capacity_status"] == "canonical_preview_not_guaranteed"
    assert route["preview"]["target_capacity"]["forward_t_per_day"] == 4.0
    assert route["preview"]["blockers"] is not None


def test_canonical_growth_observation_tracks_real_investment_and_state_without_replay():
    from space_idle import PlanBuild, AdvanceTime
    from space_idle.content import base_ids as ids
    from space_idle.dev_cli.growth import observe_growth

    app = build_game_application()
    app.execute(PlanBuild(str(ids.EARTH), str(ids.CONSTRUCTION_YARD),
                          procurement_policy="extended_wait"))
    from space_idle.persistence import save_game, load_game
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as folder:
        file = Path(folder) / "queued.json"
        save_game(app, file, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        other, _ = load_game(file, build_game_application_for_load)
    report = observe_growth(app, 60, sample_days=20)
    other.execute(AdvanceTime(days=60))
    assert app.balance_growth_state() == other.balance_growth_state()
    assert report["start_day"] == 0 and report["end_day"] == 60
    assert report["start"] != report["end"]
    assert report["snapshots"][0] == report["start"]
    assert report["snapshots"][-1] == report["end"]
    assert any(row["kind"] == "facilities" and row["facility"] == str(ids.CONSTRUCTION_YARD)
               and row["delta"] > 0 for row in report["asset_and_technology_events"])
    assert report["settlements_by_operation"]
    assert report["allocation_integrals"]
    assert report["inventory_stock_changes"]
    assert all(row["days"] <= 60 for row in report["limiting_factor_days"])
    assert len(report["snapshots"]) < 60  # only sampled boundaries and actual changes


def test_balance_cli_growth_report_and_inspect_uses_real_save(tmp_path):
    from space_idle import PlanBuild
    from space_idle.content import base_ids as ids
    from space_idle.dev_cli.__main__ import _load
    app = build_game_application()
    app.execute(PlanBuild(str(ids.EARTH), str(ids.CONSTRUCTION_YARD),
                          procurement_policy="extended_wait"))
    start = tmp_path / "start.json"
    save_game(app, start, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assessment = tmp_path / "assessment.json"
    assessment.write_text(json.dumps(_assessment([{"name": "design", "period_days": 60}])), encoding="utf-8")
    report_file = tmp_path / "report.json"
    assert main(["evaluate", "--assessment", str(assessment), "--from-save", str(start),
                 "--observe-days", "60", "--sample-days", "25", "--output", str(report_file)]) == 0
    report = _load(report_file)
    assert report["observed_growth"]["end_day"] == 60
    assert report["periods"][0]["name"] == "design"  # model and measured periods stay distinct
    inspect_file = tmp_path / "filtered.json"
    assert main(["inspect", "--report", str(report_file), "--facility", str(ids.CONSTRUCTION_YARD),
                 "--output", str(inspect_file)]) == 0
    measured = _load(inspect_file)["observed_growth"]
    assert any(row["delta"] > 0 for row in measured["asset_and_technology_events"])
    assert load_game(start, build_game_application_for_load)[0].game_day == 0
    with pytest.raises(ValueError):
        from space_idle.dev_cli.growth import observe_growth
        observe_growth(build_game_application(), 0)
