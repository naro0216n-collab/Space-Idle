"""Produce source-grounded material for design of the *whole Content system*.

Usage: python scripts/content_system_review.py [--json] [--stage N]
       python scripts/content_system_review.py --site CONTEXT --facility FACILITY [--method METHOD]
       python scripts/content_system_review.py --route FROM TO --vehicle VEHICLE
       python scripts/content_system_review.py --ledger worksheet.json

Worksheet JSON: {"period_days": 30, "activities": [{"kind": "process", "node": "source",
"id": "process-definition-id", "rate_per_day": 1.0}, ...]}.
All rows require `node` (explicit accounting label) and `kind`. Other kinds and keys:
  facility_operation: id, count, context_id; optional selected_process_id,
    selected_extraction_method_id, level, day
  extraction: id (method), facility_id, facility_units, context_id, rate_t_per_day
  facility_construction / vehicle_production / founding / spatial_development: id, count
  research_stage: id (technology), stage_id, count
  research_fleet_provider: id (provider), vehicle_id, units
  survey_provider: id (provider), source_id (facility/vehicle), mode_id, units
  construction_resource: id (resource), available_stock_t
  life_support: id (facility), people
  movement: id (vehicle), origin_context_id, destination_context_id,
    movement_plan_id, cargo_t, count
  transport_cycle: id (vehicle), units, origin_context_id, destination_context_id,
    destination_node, forward_plan_id, optional reverse_plan_id
  market_trade: id (resource), provider_id, direction (buy/sell), quantity_t
All physical quantities are conditional hypotheses; no registered operational
State, Cargo, Funds, Research, or Game time is advanced. No cases, scoring,
hypothetical game state, or optimizer are implemented here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from space_idle.content.base_catalog import build_base_catalog
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content_system_review import review_content
from space_idle.content_physical_evidence import site_evidence, movement_evidence
from space_idle.content_quantity_ledger import quantity_ledger


def render(report: dict, stage: int | None = None) -> str:
    """Brief entry point to authored conditions, not a balance scorecard."""
    initial = report["initial"]
    lines = ["# Content調整の入力資料", "構成・数量は調整対象。記載の資産は初期保有であり、同時稼働や将来取得を意味しない。",
             f"\n## 開始条件: {initial['scenario_id']}",
             f"Funds: {initial['funds_balance_musd']:g} MUSD"]
    for node in initial["established_nodes"]:
        lines.append(f"\n### {node}")
        assets = [f"{f['id']} (level {f['level']}, process {f['selected_process_id'] or '未選択'}, extraction {f['selected_extraction_method_id'] or '未選択'})"
                  for f in initial["facilities"] if f["node"] == node]
        lines.extend("- Facility: " + row for row in assets)
        lines.extend(f"- Fleet: {f['id']} ×{f['units']}" for f in initial["fleet"] if f["node"] == node)
        lines.extend(f"- Inventory: {f['resource']} {f['quantity_t']:g} t" for f in initial["inventory"] if f["node"] == node)
        lines.extend(f"- Population: {f['people']}人" for f in initial["population"] if f["node"] == node)
    lines.extend(f"- Market interface: {row['id']} at {row['node']} ({'enabled' if row['enabled'] else 'disabled'})"
                 for row in initial["market_interfaces"])
    lines.extend(f"- Research Fleet: {row['vehicle_id']} ×{row['units']} ({row['provider_definition_id']})"
                 for row in initial["research_fleet_assignments"])
    lines.extend(f"- Survey Fleet: {row['vehicle_id']} ×{row['units']} ({row['provider_definition_id']})"
                 for row in initial["survey_fleet_assignments"])
    if stage is not None:
        members = [t for t in report["research"] if t["progression_stage"] == stage]
        if not members:
            raise ValueError(f"未登録の研究表示段階: {stage}")
        lines.append(f"\n## 研究表示段階 {stage}（履修義務はない）")
        for item in members:
            lines.append(f"- {item['id']}: prerequisites={','.join(item['prerequisites']) or 'なし'}")
            for spec in item["stages"]:
                lines.append(f"  - {spec['id']} ({spec['kind']}): RP={spec.get('rp','-')} "
                             f"resources={spec.get('resources_t',{})} work={spec.get('work','-')} "
                             f"execution={spec.get('execution_requirements', [])}")
    else:
        lines.append("\n研究の前提と個別Stageは --stage N、全Definition係数は --json で参照する。")
    lines.append("この出力にない実稼働率・実移動負担・技術取得結果は推定していない。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="registered physical coefficients and provenance")
    parser.add_argument("--stage", type=int, help="focus on research display stage; not an assumed completed portfolio")
    parser.add_argument("--ledger", type=Path, help="single-period conditional Resource/Service worksheet JSON")
    parser.add_argument("--site", help="World context id: static physical environment, not a founded Location")
    parser.add_argument("--facility", help="Facility id to measure at --site")
    parser.add_argument("--method", help="Extraction method id (requires --site and --facility)")
    parser.add_argument("--level", type=int, default=1, help="hypothetical Facility level (site coefficient only)")
    parser.add_argument("--route", nargs=2, metavar=("ORIGIN_CONTEXT", "DEST_CONTEXT"),
                        help="physical World contexts, not active Transport endpoints")
    parser.add_argument("--vehicle", help="Vehicle id (required with --route)")
    parser.add_argument("--cargo-t", type=float, default=0.0, help="specified one-way mass in tonnes")
    parser.add_argument("--day", type=int, default=0, help="day to sample Environment coefficients")
    args = parser.parse_args()
    physical_site = args.site is not None or args.facility is not None or args.method is not None
    physical_route = args.route is not None or args.vehicle is not None
    if args.ledger is not None and (physical_site or physical_route or args.stage is not None):
        parser.error("--ledger is a separate quantity worksheet")
    if physical_site and physical_route:
        parser.error("--site/--facility and --route/--vehicle are separate physical queries")
    if physical_site and (args.site is None or args.facility is None):
        parser.error("--site requires --facility and vice versa")
    if physical_route and (args.route is None or args.vehicle is None):
        parser.error("--route requires --vehicle and vice versa")
    if (physical_site or physical_route) and args.stage is not None:
        parser.error("--stage filters only the registered Research catalog")
    if args.json and args.stage is not None:
        parser.error("--stageは閲覧用の段階絞り込みです。全係数をJSONで取得する場合は--stageを省略してください")
    catalog = build_base_catalog()
    scenario = build_standard_scenario_definition()
    sim = build_base_simulation(catalog, population_rules=scenario.population_rules,
                                external_population_sources=scenario.external_population_sources)
    if args.ledger is not None:
        worksheet = json.loads(args.ledger.read_text(encoding="utf-8"))
        result = quantity_ledger(sim, period_days=worksheet["period_days"],
                                 activities=worksheet["activities"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if physical_site:
        print(json.dumps(site_evidence(sim, args.site, args.facility,
                                       method_id=args.method, level=args.level, day=args.day),
                         ensure_ascii=False, indent=2))
        return
    if physical_route:
        print(json.dumps(movement_evidence(sim, *args.route, args.vehicle,
                                           cargo_t=args.cargo_t, day=args.day),
                         ensure_ascii=False, indent=2))
        return
    report = review_content(sim, catalog, scenario)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.stage))


if __name__ == "__main__":
    main()
