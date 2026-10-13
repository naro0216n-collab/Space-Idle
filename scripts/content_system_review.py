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
    def line(text=""):
        lines.append(text)

    lines: list[str] = []
    line("# 全体系Content設計資料")
    line("登録Definition / Worldと初期Scenarioからの読取。適切な施設台数・研究期間・攻略順・実操業は判定しない。")
    initial = report["initial"]
    line(f"\n## 初期構成（{initial['scenario_id']}）")
    for node in initial["established_nodes"]:
        assets = [f["id"] for f in initial["facilities"] if f["node"] == node]
        fleet = [f'{f["id"]}×{f["units"]}' for f in initial["fleet"] if f["node"] == node]
        line(f"- {node}: Facility {', '.join(assets) or 'なし'}; Fleet {', '.join(fleet) or 'なし'}")

    line("\n## 初期地球圏の名目能力と投資負担の起点")
    for node in report["initial_physical_envelopes"]:
        p = node["nominal_power_at_day_0_mw"]
        r = node["nominal_research"]
        line(f"- {node['node']}: 発電 {p['generation']:.3g} MW / 負荷 {p['load']:.3g} MW; RP {r['rp_generation_per_day']:.3g}/日 / 研究実行 {r['execution_per_day']:.3g}/日 / RP保管 {r['rp_storage']:.3g}; 設置設備の施工 {node['nominal_installed_construction_work_per_day']:.3g}/日 / 施工Resource由来 {node['construction_work_per_day_from_initial_resource_stock']:.3g}/日; Housing {node['housing_people']:g} 人 / Life Support {node['life_support_person_days_per_day']:g} 人日/日")
        if node["conditional_resident_demand_t_per_day"] is not None:
            for resource, demand in node["conditional_resident_demand_t_per_day"].items():
                line(f"  - {resource}: {node['scenario_population_people']}人の条件付き居住負担 {demand:.3g} t/日（Allocation・供給成立を意味しない）")
        for resource, rate in node["per_resource_independent_production_upper_bound_t_per_day_before_geology"].items():
            line(f"  - {resource}: 条件付き生産上限 {rate:.3g} t/日（他Resourceとの同時達成は未評価）")
        for resource, rate in node["annual_maintenance_t_by_resource_from_actual_investment"].items():
            if rate:
                line(f"  - {resource}: 初期保有に基づく年換算維持係数 {rate:.3g} t/年")

    line("\n## 研究段階と設備・工程の接続")
    stages = sorted({t["progression_stage"] for t in report["research"] if t["progression_stage"] is not None})
    if stage is not None and stage not in stages:
        raise ValueError(f"研究表示段階 {stage} は登録されていない: {stages}")
    for number in stages:
        if stage is not None and stage != number:
            continue
        members = [t for t in report["research"] if t["progression_stage"] == number]
        theory = [sum(item.get("rp", 0) for item in t["stages"]) for t in members]
        line(f"\n### 表示段階 {number}: {len(members)} Technology（全件履修を前提としない）")
        line(f"- 単一TechnologyあたりTheory RP: {min(theory):g}–{max(theory):g}; 表示段階の合計RPは計算しない")
        gated_facilities = [f["id"] for f in report["facilities"]
                            if f["construction"] and set(f["construction"]["prerequisite_technologies"]) & {t["id"] for t in members}]
        gated_vehicles = [v["id"] for v in report["vehicles"]
                          if set(v["production"]["prerequisite_technologies"]) & {t["id"] for t in members}]
        gated_processes = [p["id"] for p in report["processes"]
                           if set(p["prerequisite_technologies"]) & {t["id"] for t in members}]
        line(f"- この段階のTechnologyを前提に含む取得・工程: Facility {len(gated_facilities)}、Vehicle {len(gated_vehicles)}、Process {len(gated_processes)}（利用可能を意味しない）")
        if stage is not None:
            line("- 関係するFacility: " + (", ".join(gated_facilities) or "なし"))
            line("- 関係するVehicle: " + (", ".join(gated_vehicles) or "なし"))
            line("- 関係するProcess: " + (", ".join(gated_processes) or "なし"))
            line("- 研究内容: " + (", ".join(t["id"] for t in members) or "なし"))

    line("\n## Resourceの供給工程と全Domain取得・運用負担")
    for rid, links in sorted(report["resources"].items()):
        kinds = sorted({u["owner_kind"] for u in links["uses"]})
        products = sorted({(s["owner_id"], s.get("facility_id", "")) for s in links["sources"]})
        line(f"- {rid}: nominal source {len(products)} process/extraction×Facility combinations; use {', '.join(kinds) or 'なし'}")
    line("\n各Resourceの具体的な数量・時間基準・取得元、各TechnologyのStage、全WorldのPotential範囲は `--json` で同じProjectionから取得する。")
    line("産業供給源の数は実際の生産台数・稼働能力ではない。発展段階の設備・Fleet構成の妥当性を調べる際には、ここで判明した関係から設計仮説を作り直す。")
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
