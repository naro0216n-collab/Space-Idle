"""Produce source-grounded material for design of the *whole Content system*.

Usage: python scripts/content_system_review.py [--json] [--stage N]
No cases, scoring, hypothetical game state, or optimizer are implemented here.
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="registered physical coefficients and provenance")
    parser.add_argument("--stage", type=int, help="focus on research display stage; not an assumed completed portfolio")
    args = parser.parse_args()
    if args.json and args.stage is not None:
        parser.error("--stageは閲覧用の段階絞り込みです。全係数をJSONで取得する場合は--stageを省略してください")
    catalog = build_base_catalog()
    scenario = build_standard_scenario_definition()
    sim = build_base_simulation(catalog, population_rules=scenario.population_rules,
                                external_population_sources=scenario.external_population_sources)
    report = review_content(sim, catalog, scenario)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.stage))


if __name__ == "__main__":
    main()
