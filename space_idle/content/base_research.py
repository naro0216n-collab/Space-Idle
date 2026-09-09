from __future__ import annotations

from ..research import (
    ResearchDefinition,
    ResearchDemonstrationSpec,
    ResearchPrototypeSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSpec,
)
from ..site import SiteRequirements
from . import base_ids as ids
from . import base_requirements as req


def _research_lab_site() -> SiteRequirements:
    return SiteRequirements(capability_requirements=req._available_requirements("research_lab"))


def _orbital_research_site() -> SiteRequirements:
    return SiteRequirements(req.ORBIT_ENV, req._available_requirements("research_lab"))


def _surface_research_site() -> SiteRequirements:
    return SiteRequirements(req.SURFACE_ENV, req._available_requirements("research_lab"))


def _prototype(site: SiteRequirements, resources: dict) -> ResearchPrototypeSpec:
    return ResearchPrototypeSpec(resources, site)


def _demonstration(days: int, site: SiteRequirements) -> ResearchDemonstrationSpec:
    return ResearchDemonstrationSpec(days, site)


def build_research_definitions() -> dict:
    lab = _research_lab_site()
    orbital_lab = _orbital_research_site()
    surface_lab = _surface_research_site()
    surface_survey = SiteRequirements(req.SURFACE_ENV, req._available_requirements("surface_survey"))
    regolith_demo = SiteRequirements(req.SURFACE_ENV, req._available_requirements("regolith_excavation"))
    return {
        ids.TECH_ORBITAL_OPERATIONS: ResearchDefinition(
            ids.TECH_ORBITAL_OPERATIONS,
            "自律ランデブー・標準ドッキング運用",
            120.0,
            prototype=_prototype(lab, {ids.PRECISION_ELECTRONICS: 0.5}),
        ),
        ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS: ResearchDefinition(
            ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS,
            "微小重力実験ラック・遠隔試料ハンドリング",
            220.0,
            frozenset({ids.TECH_ORBITAL_OPERATIONS}),
            _prototype(lab, {ids.MACHINERY: 0.8, ids.PRECISION_ELECTRONICS: 0.8}),
        ),
        ids.TECH_CISLUNAR_LOGISTICS: ResearchDefinition(
            ids.TECH_CISLUNAR_LOGISTICS,
            "微小重力推進剤捕捉・軌道上移送",
            420.0,
            frozenset({ids.TECH_ORBITAL_OPERATIONS}),
            _prototype(lab, {ids.MACHINERY: 1.0, ids.PRECISION_ELECTRONICS: 0.5}),
        ),
        ids.TECH_CREWED_ORBITAL_RESEARCH: ResearchDefinition(
            ids.TECH_CREWED_ORBITAL_RESEARCH,
            "閉鎖式生命維持・有人軌道実験運用",
            700.0,
            frozenset({ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS, ids.TECH_CISLUNAR_LOGISTICS}),
            _prototype(lab, {ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 1.0}),
            _demonstration(8, orbital_lab),
        ),
        ids.TECH_LUNAR_PROSPECTING: ResearchDefinition(
            ids.TECH_LUNAR_PROSPECTING,
            "中性子分光・多波長鉱物マッピング",
            900.0,
            frozenset({ids.TECH_CISLUNAR_LOGISTICS}),
            _prototype(lab, {ids.PRECISION_ELECTRONICS: 1.0}),
            _demonstration(6, orbital_lab),
        ),
        ids.TECH_ROBOTIC_FIELD_GEOLOGY: ResearchDefinition(
            ids.TECH_ROBOTIC_FIELD_GEOLOGY,
            "自律地質観測・試料採取制御",
            1200.0,
            frozenset({ids.TECH_LUNAR_PROSPECTING}),
            _prototype(lab, {ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 1.2}),
            _demonstration(8, surface_survey),
        ),
        ids.TECH_VOLATILE_ISRU: ResearchDefinition(
            ids.TECH_VOLATILE_ISRU,
            "低温揮発性物質加熱抽出",
            1250.0,
            frozenset({ids.TECH_LUNAR_PROSPECTING}),
            _prototype(lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}),
            _demonstration(
                20,
                SiteRequirements(req.COLD_VOLATILE_SURFACE_ENV, req._available_requirements("surface_survey")),
            ),
        ),
        ids.TECH_REGOLITH_EXCAVATION: ResearchDefinition(
            ids.TECH_REGOLITH_EXCAVATION,
            "レゴリス掘削・粒度制御",
            1350.0,
            frozenset({ids.TECH_ROBOTIC_FIELD_GEOLOGY}),
            _prototype(lab, {ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 0.5}),
            _demonstration(10, surface_survey),
        ),
        ids.TECH_SAMPLE_ANALYSIS_SYSTEMS: ResearchDefinition(
            ids.TECH_SAMPLE_ANALYSIS_SYSTEMS,
            "真空試料前処理・鉱物相分析",
            2400.0,
            frozenset({ids.TECH_ROBOTIC_FIELD_GEOLOGY, ids.TECH_REGOLITH_EXCAVATION}),
            _prototype(surface_lab, {ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 2.0}),
        ),
        ids.TECH_LUNAR_MATERIALS: ResearchDefinition(
            ids.TECH_LUNAR_MATERIALS,
            "真空レゴリス焼結・気孔制御",
            2800.0,
            frozenset({ids.TECH_SAMPLE_ANALYSIS_SYSTEMS, ids.TECH_REGOLITH_EXCAVATION}),
            _prototype(surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.6}),
            _demonstration(10, regolith_demo),
        ),
        ids.TECH_ORE_BENEFICIATION: ResearchDefinition(
            ids.TECH_ORE_BENEFICIATION,
            "真空粒度選別・鉱物濃縮",
            3000.0,
            frozenset({ids.TECH_SAMPLE_ANALYSIS_SYSTEMS, ids.TECH_REGOLITH_EXCAVATION}),
            _prototype(surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}),
            _demonstration(10, regolith_demo),
        ),
        ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH: ResearchDefinition(
            ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH,
            "真空レゴリス熱処理・反応制御",
            5200.0,
            frozenset({ids.TECH_LUNAR_MATERIALS, ids.TECH_ORE_BENEFICIATION}),
            _prototype(surface_lab, {ids.MACHINERY: 3.0, ids.PRECISION_ELECTRONICS: 2.0}),
            _demonstration(
                12,
                SiteRequirements(req.VACUUM_SURFACE_ENV, req._available_requirements("regolith_excavation")),
            ),
        ),
        ids.TECH_HIGH_TEMPERATURE_METALLURGY: ResearchDefinition(
            ids.TECH_HIGH_TEMPERATURE_METALLURGY,
            "高温酸化物還元・金属分離",
            5800.0,
            frozenset({ids.TECH_ORE_BENEFICIATION, ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH}),
            _prototype(surface_lab, {ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 0.9}),
            _demonstration(
                12,
                SiteRequirements(req.SURFACE_ENV, req._available_requirements("ore_processing")),
            ),
        ),
        ids.TECH_STRUCTURAL_FABRICATION: ResearchDefinition(
            ids.TECH_STRUCTURAL_FABRICATION,
            "真空成形・構造材接合",
            6200.0,
            frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}),
            _prototype(surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.7}),
            _demonstration(
                8,
                SiteRequirements(req.SURFACE_ENV, req._available_requirements("metallurgy")),
            ),
        ),
        ids.TECH_PRECISION_MACHINING: ResearchDefinition(
            ids.TECH_PRECISION_MACHINING,
            "低重力精密機械加工",
            6500.0,
            frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}),
            _prototype(surface_lab, {ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 1.0}),
            _demonstration(
                8,
                SiteRequirements(req.SURFACE_ENV, req._available_requirements("metallurgy")),
            ),
        ),
        ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY: ResearchDefinition(
            ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY,
            "モジュール重機組立・整備",
            9500.0,
            frozenset({ids.TECH_STRUCTURAL_FABRICATION, ids.TECH_PRECISION_MACHINING}),
            _prototype(surface_lab, {ids.MACHINERY: 3.0, ids.PRECISION_ELECTRONICS: 1.2}),
            _demonstration(
                12,
                SiteRequirements(
                    req.SURFACE_ENV,
                    req._available_requirements("structural_fabrication", "basic_machine_shop"),
                ),
            ),
        ),
        ids.TECH_INDUSTRIAL_ELECTROLYSIS: ResearchDefinition(
            ids.TECH_INDUSTRIAL_ELECTROLYSIS,
            "高圧水電解・酸素水素分離",
            2200.0,
            frozenset({ids.TECH_VOLATILE_ISRU}),
            _prototype(surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}),
            _demonstration(
                12,
                SiteRequirements(req.SURFACE_ENV, req._available_requirements("water_extraction")),
            ),
        ),
        ids.TECH_PROPELLANT_HANDLING: ResearchDefinition(
            ids.TECH_PROPELLANT_HANDLING,
            "酸素・水素液化・極低温推進剤調製",
            3600.0,
            frozenset({ids.TECH_INDUSTRIAL_ELECTROLYSIS}),
            _prototype(surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 1.0}),
            _demonstration(
                15,
                SiteRequirements(
                    req.SURFACE_ENV,
                    req._available_requirements("industrial_electrolysis", "cryogenic_storage"),
                ),
            ),
        ),
    }


def build_research_providers() -> dict:
    return {
        ids.EARTH_RESEARCH_LAB: ResearchProviderSpec(
            ids.EARTH_RESEARCH_LAB,
            tier=1,
            levels=(
                ResearchProviderLevelSpec(1, 4.0, 180.0),
                ResearchProviderLevelSpec(2, 6.5, 320.0),
                ResearchProviderLevelSpec(3, 9.5, 560.0),
            ),
        ),
        ids.EARTH_OBSERVATION_SATELLITE: ResearchProviderSpec(
            ids.EARTH_OBSERVATION_SATELLITE,
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 2.0, 120.0),),
        ),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ResearchProviderSpec(
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 9.0, 650.0),),
        ),
        ids.CREWED_ORBITAL_LABORATORY: ResearchProviderSpec(
            ids.CREWED_ORBITAL_LABORATORY,
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 22.0, 1600.0),),
        ),
        ids.ROBOTIC_GEOLOGY_STATION: ResearchProviderSpec(
            ids.ROBOTIC_GEOLOGY_STATION,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 14.0, 1400.0),),
        ),
        ids.SAMPLE_ANALYSIS_LABORATORY: ResearchProviderSpec(
            ids.SAMPLE_ANALYSIS_LABORATORY,
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 36.0, 3500.0),),
        ),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: ResearchProviderSpec(
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            tier=4,
            levels=(ResearchProviderLevelSpec(1, 90.0, 9000.0),),
        ),
    }
