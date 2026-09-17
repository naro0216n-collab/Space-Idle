from __future__ import annotations

from ..research import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec,
    ResearchOperationalExperienceStageSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
    ResearchProviderSpec,
)
from ..execution_requirements import ServiceCapacityRequirement
from ..knowledge import ExperienceContributionRule
from ..site import SiteRequirements
from . import base_ids as ids
from . import base_requirements as req


def _research_lab_site() -> SiteRequirements:
    return SiteRequirements(capability_requirements=req._available_requirements("research_lab"))


def _orbital_research_site() -> SiteRequirements:
    return req.with_capabilities(req.ORBIT_SITE, "research_lab")


def _surface_research_site() -> SiteRequirements:
    return req.with_capabilities(req.SURFACE_SITE, "research_lab")


def _theory(stage_id: str, cost: float) -> ResearchTheoryStageSpec:
    return ResearchTheoryStageSpec(stage_id, cost)


def _prototype(stage_id: str, site: SiteRequirements, resources: dict) -> ResearchPrototypeStageSpec:
    return ResearchPrototypeStageSpec(
        stage_id, resources, site,
        (ServiceCapacityRequirement("research_execution", 1.0),),
    )


def _demonstration(stage_id: str, work: float, site: SiteRequirements) -> ResearchDemonstrationStageSpec:
    return ResearchDemonstrationStageSpec(
        stage_id, work, site,
        (ServiceCapacityRequirement("research_execution", 1.0),),
    )


def _experience(stage_id: str, category: str, amount: float) -> ResearchOperationalExperienceStageSpec:
    return ResearchOperationalExperienceStageSpec(stage_id, {category: amount})


def build_experience_contribution_rules() -> tuple[ExperienceContributionRule, ...]:
    return (
        ExperienceContributionRule("transport", ids.EXPERIENCE_TRANSPORT_OPERATIONS, 1.0),
        ExperienceContributionRule("extraction", ids.EXPERIENCE_EXTRACTION_OPERATIONS, 1.0),
        ExperienceContributionRule("manufacturing", ids.EXPERIENCE_MANUFACTURING_OPERATIONS, 1.0),
    )


def build_research_definitions() -> dict:
    lab = _research_lab_site()
    orbital_lab = _orbital_research_site()
    surface_lab = _surface_research_site()
    surface_survey = req.with_capabilities(req.SURFACE_SITE, "surface_survey")
    regolith_demo = req.with_capabilities(req.SURFACE_SITE, "regolith_excavation")
    return {
        ids.TECH_ORBITAL_OPERATIONS: ResearchDefinition(
            ids.TECH_ORBITAL_OPERATIONS,
            "自律ランデブー・標準ドッキング運用",
            (
                _theory("theory", 120.0),
                _prototype("prototype", lab, {ids.PRECISION_ELECTRONICS: 0.5}),
            ),
            prerequisites=frozenset(),
        ),
        ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS: ResearchDefinition(
            ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS,
            "微小重力実験ラック・遠隔試料ハンドリング",
            (
                _theory("theory", 220.0),
                _prototype("prototype", lab, {ids.MACHINERY: 0.8, ids.PRECISION_ELECTRONICS: 0.8}),
            ),
            prerequisites=frozenset({ids.TECH_ORBITAL_OPERATIONS}),
        ),
        ids.TECH_CISLUNAR_LOGISTICS: ResearchDefinition(
            ids.TECH_CISLUNAR_LOGISTICS,
            "微小重力推進剤捕捉・軌道上移送",
            (
                _theory("theory", 420.0),
                _prototype("prototype", lab, {ids.MACHINERY: 1.0, ids.PRECISION_ELECTRONICS: 0.5}),
            ),
            prerequisites=frozenset({ids.TECH_ORBITAL_OPERATIONS}),
        ),
        ids.TECH_CREWED_ORBITAL_RESEARCH: ResearchDefinition(
            ids.TECH_CREWED_ORBITAL_RESEARCH,
            "閉鎖式生命維持・有人軌道実験運用",
            (
                _theory("theory", 700.0),
                _prototype("prototype", lab, {ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 1.0}),
                _demonstration("demonstration", 8, orbital_lab),
            ),
            prerequisites=frozenset({ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS, ids.TECH_CISLUNAR_LOGISTICS}),
        ),
        ids.TECH_LUNAR_PROSPECTING: ResearchDefinition(
            ids.TECH_LUNAR_PROSPECTING,
            "中性子分光・多波長鉱物マッピング",
            (
                _theory("theory", 900.0),
                _prototype("prototype", lab, {ids.PRECISION_ELECTRONICS: 1.0}),
                _demonstration("demonstration", 6, orbital_lab),
            ),
            prerequisites=frozenset({ids.TECH_CISLUNAR_LOGISTICS}),
        ),
        ids.TECH_ROBOTIC_FIELD_GEOLOGY: ResearchDefinition(
            ids.TECH_ROBOTIC_FIELD_GEOLOGY,
            "自律地質観測・試料採取制御",
            (
                _theory("theory", 1200.0),
                _prototype("prototype", lab, {ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 1.2}),
                _demonstration("demonstration", 8, surface_survey),
            ),
            prerequisites=frozenset({ids.TECH_LUNAR_PROSPECTING}),
        ),
        ids.TECH_VOLATILE_ISRU: ResearchDefinition(
            ids.TECH_VOLATILE_ISRU,
            "低温揮発性物質加熱抽出",
            (
                _theory("theory", 1250.0),
                _prototype("prototype", lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}),
                _demonstration("demonstration",
                20,
                req.with_capabilities(req.COLD_VOLATILE_SURFACE_SITE, "surface_survey"),
            ),
            ),
            prerequisites=frozenset({ids.TECH_LUNAR_PROSPECTING}),
        ),
        ids.TECH_REGOLITH_EXCAVATION: ResearchDefinition(
            ids.TECH_REGOLITH_EXCAVATION,
            "レゴリス掘削・粒度制御",
            (
                _theory("theory", 1350.0),
                _prototype("prototype", lab, {ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 0.5}),
                _demonstration("demonstration", 10, surface_survey),
            ),
            prerequisites=frozenset({ids.TECH_ROBOTIC_FIELD_GEOLOGY}),
        ),
        ids.TECH_SAMPLE_ANALYSIS_SYSTEMS: ResearchDefinition(
            ids.TECH_SAMPLE_ANALYSIS_SYSTEMS,
            "真空試料前処理・鉱物相分析",
            (
                _theory("theory", 2400.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 2.0}),
            ),
            prerequisites=frozenset({ids.TECH_ROBOTIC_FIELD_GEOLOGY, ids.TECH_REGOLITH_EXCAVATION}),
        ),
        ids.TECH_LUNAR_MATERIALS: ResearchDefinition(
            ids.TECH_LUNAR_MATERIALS,
            "真空レゴリス焼結・気孔制御",
            (
                _theory("theory", 2800.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.6}),
                _demonstration("demonstration", 10, regolith_demo),
            ),
            prerequisites=frozenset({ids.TECH_SAMPLE_ANALYSIS_SYSTEMS, ids.TECH_REGOLITH_EXCAVATION}),
        ),
        ids.TECH_ORE_BENEFICIATION: ResearchDefinition(
            ids.TECH_ORE_BENEFICIATION,
            "真空粒度選別・鉱物濃縮",
            (
                _theory("theory", 3000.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}),
                _demonstration("demonstration", 10, regolith_demo),
                _experience("operational_experience", ids.EXPERIENCE_EXTRACTION_OPERATIONS, 20.0),
            ),
            prerequisites=frozenset({ids.TECH_SAMPLE_ANALYSIS_SYSTEMS, ids.TECH_REGOLITH_EXCAVATION}),
        ),
        ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH: ResearchDefinition(
            ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH,
            "真空レゴリス熱処理・反応制御",
            (
                _theory("theory", 5200.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 3.0, ids.PRECISION_ELECTRONICS: 2.0}),
                _demonstration("demonstration",
                12,
                req.with_capabilities(req.VACUUM_SURFACE_SITE, "regolith_excavation"),
            ),
            ),
            prerequisites=frozenset({ids.TECH_LUNAR_MATERIALS, ids.TECH_ORE_BENEFICIATION}),
        ),
        ids.TECH_HIGH_TEMPERATURE_METALLURGY: ResearchDefinition(
            ids.TECH_HIGH_TEMPERATURE_METALLURGY,
            "高温酸化物還元・金属分離",
            (
                _theory("theory", 5800.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 0.9}),
                _demonstration("demonstration",
                12,
                req.with_capabilities(req.SURFACE_SITE, "ore_processing"),
            ),
            ),
            prerequisites=frozenset({ids.TECH_ORE_BENEFICIATION, ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH}),
        ),
        ids.TECH_STRUCTURAL_FABRICATION: ResearchDefinition(
            ids.TECH_STRUCTURAL_FABRICATION,
            "真空成形・構造材接合",
            (
                _theory("theory", 6200.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.7}),
                _demonstration("demonstration",
                8,
                req.with_capabilities(req.SURFACE_SITE, "metallurgy"),
            ),
                _experience("operational_experience", ids.EXPERIENCE_MANUFACTURING_OPERATIONS, 20.0),
            ),
            prerequisites=frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}),
        ),
        ids.TECH_PRECISION_MACHINING: ResearchDefinition(
            ids.TECH_PRECISION_MACHINING,
            "低重力精密機械加工",
            (
                _theory("theory", 6500.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 1.0}),
                _demonstration("demonstration",
                8,
                req.with_capabilities(req.SURFACE_SITE, "metallurgy"),
            ),
            ),
            prerequisites=frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}),
        ),
        ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY: ResearchDefinition(
            ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY,
            "モジュール重機組立・整備",
            (
                _theory("theory", 9500.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 3.0, ids.PRECISION_ELECTRONICS: 1.2}),
                _demonstration("demonstration",
                12,
                req.with_capabilities(
                    req.SURFACE_SITE, "structural_fabrication", "basic_machine_shop"
                ),
            ),
            ),
            prerequisites=frozenset({ids.TECH_STRUCTURAL_FABRICATION, ids.TECH_PRECISION_MACHINING}),
        ),
        ids.TECH_INDUSTRIAL_ELECTROLYSIS: ResearchDefinition(
            ids.TECH_INDUSTRIAL_ELECTROLYSIS,
            "高圧水電解・酸素水素分離",
            (
                _theory("theory", 2200.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}),
                _demonstration("demonstration",
                12,
                req.with_capabilities(req.SURFACE_SITE, "water_extraction"),
            ),
            ),
            prerequisites=frozenset({ids.TECH_VOLATILE_ISRU}),
        ),
        ids.TECH_PROPELLANT_HANDLING: ResearchDefinition(
            ids.TECH_PROPELLANT_HANDLING,
            "酸素・水素液化・極低温推進剤調製",
            (
                _theory("theory", 3600.0),
                _prototype("prototype", surface_lab, {ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 1.0}),
                _demonstration("demonstration",
                15,
                req.with_capabilities(
                    req.SURFACE_SITE, "industrial_electrolysis", "cryogenic_storage"
                ),
            ),
                _experience("operational_experience", ids.EXPERIENCE_TRANSPORT_OPERATIONS, 20.0),
            ),
            prerequisites=frozenset({ids.TECH_INDUSTRIAL_ELECTROLYSIS}),
        ),
    }


def build_research_providers() -> dict:
    return {
        ids.EARTH_RESEARCH_LAB: ResearchProviderSpec(
            ids.EARTH_RESEARCH_LAB,
            ResearchProviderSourceKind.FACILITY,
            ids.EARTH_RESEARCH_LAB,
            tier=1,
            levels=(
                ResearchProviderLevelSpec(1, 4.0, 180.0, 1.0),
                ResearchProviderLevelSpec(2, 6.5, 320.0, 1.0),
                ResearchProviderLevelSpec(3, 9.5, 560.0, 1.0),
            ),
        ),
        ids.EARTH_OBSERVATION_SATELLITE: ResearchProviderSpec(
            ids.EARTH_OBSERVATION_SATELLITE,
            ResearchProviderSourceKind.FACILITY,
            ids.EARTH_OBSERVATION_SATELLITE,
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 2.0, 120.0, 1.0),),
        ),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ResearchProviderSpec(
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            ResearchProviderSourceKind.FACILITY,
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 9.0, 650.0, 1.0),),
        ),
        ids.CREWED_ORBITAL_LABORATORY: ResearchProviderSpec(
            ids.CREWED_ORBITAL_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            ids.CREWED_ORBITAL_LABORATORY,
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 22.0, 1600.0, 1.0),),
        ),
        ids.ROBOTIC_GEOLOGY_STATION: ResearchProviderSpec(
            ids.ROBOTIC_GEOLOGY_STATION,
            ResearchProviderSourceKind.FACILITY,
            ids.ROBOTIC_GEOLOGY_STATION,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 14.0, 1400.0, 1.0),),
        ),
        ids.SAMPLE_ANALYSIS_LABORATORY: ResearchProviderSpec(
            ids.SAMPLE_ANALYSIS_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            ids.SAMPLE_ANALYSIS_LABORATORY,
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 36.0, 3500.0, 1.0),),
        ),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: ResearchProviderSpec(
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            tier=4,
            levels=(ResearchProviderLevelSpec(1, 90.0, 9000.0, 1.0),),
        ),
    }
