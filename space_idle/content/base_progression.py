from __future__ import annotations

from ..research import ResearchDefinition, ResearchProviderLevelSpec, ResearchProviderSpec
from ..site import SiteRequirements
from ..survey import ExtractionSpec, SurveyProviderSpec, SurveyTarget
from . import base_ids as ids
from . import base_requirements as req


def build_research_definitions() -> dict:
    lab_prototype = SiteRequirements(capability_requirements=req._available_requirements("research_lab"))
    return {
        ids.TECH_ORBITAL_OPERATIONS: ResearchDefinition(ids.TECH_ORBITAL_OPERATIONS, "自律ランデブー・標準ドッキング運用", 80.0, prototype_site_requirements=lab_prototype, prototype_resources={ids.PRECISION_ELECTRONICS: 0.5}),
        ids.TECH_CISLUNAR_LOGISTICS: ResearchDefinition(ids.TECH_CISLUNAR_LOGISTICS, "微小重力推進剤捕捉・軌道上移送", 120.0, frozenset({ids.TECH_ORBITAL_OPERATIONS}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 1.0, ids.PRECISION_ELECTRONICS: 0.5}),
        ids.TECH_LUNAR_PROSPECTING: ResearchDefinition(ids.TECH_LUNAR_PROSPECTING, "中性子分光・多波長鉱物マッピング", 100.0, prototype_site_requirements=lab_prototype, prototype_resources={ids.PRECISION_ELECTRONICS: 1.0}),
        ids.TECH_VOLATILE_ISRU: ResearchDefinition(ids.TECH_VOLATILE_ISRU, "低温揮発性物質加熱抽出", 150.0, frozenset({ids.TECH_LUNAR_PROSPECTING}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}, demonstration_days=20, demonstration_site_requirements=SiteRequirements(req.COLD_VOLATILE_SURFACE_ENV, req._available_requirements("surface_survey"))),
        ids.TECH_REGOLITH_EXCAVATION: ResearchDefinition(ids.TECH_REGOLITH_EXCAVATION, "レゴリス掘削・粒度制御", 110.0, frozenset({ids.TECH_LUNAR_PROSPECTING}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 1.5, ids.PRECISION_ELECTRONICS: 0.5}, demonstration_days=10, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("surface_survey"))),
        ids.TECH_LUNAR_MATERIALS: ResearchDefinition(ids.TECH_LUNAR_MATERIALS, "真空レゴリス焼結", 120.0, frozenset({ids.TECH_REGOLITH_EXCAVATION}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.4}, demonstration_days=10, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("regolith_excavation"))),
        ids.TECH_ORE_BENEFICIATION: ResearchDefinition(ids.TECH_ORE_BENEFICIATION, "真空粒度選別・鉱物濃縮", 130.0, frozenset({ids.TECH_REGOLITH_EXCAVATION}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.6}, demonstration_days=10, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("regolith_excavation"))),
        ids.TECH_HIGH_TEMPERATURE_METALLURGY: ResearchDefinition(ids.TECH_HIGH_TEMPERATURE_METALLURGY, "高温酸化物還元・金属分離", 160.0, frozenset({ids.TECH_ORE_BENEFICIATION}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 0.7}, demonstration_days=12, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("ore_processing"))),
        ids.TECH_STRUCTURAL_FABRICATION: ResearchDefinition(ids.TECH_STRUCTURAL_FABRICATION, "真空成形・構造材接合", 130.0, frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.5}, demonstration_days=8, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("metallurgy"))),
        ids.TECH_PRECISION_MACHINING: ResearchDefinition(ids.TECH_PRECISION_MACHINING, "低重力精密機械加工", 150.0, frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 0.8}, demonstration_days=8, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("metallurgy"))),
        ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY: ResearchDefinition(ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY, "モジュール重機組立・整備", 180.0, frozenset({ids.TECH_STRUCTURAL_FABRICATION, ids.TECH_PRECISION_MACHINING}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 3.0, ids.PRECISION_ELECTRONICS: 1.0}, demonstration_days=12, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("structural_fabrication", "basic_machine_shop"))),
        ids.TECH_INDUSTRIAL_ELECTROLYSIS: ResearchDefinition(ids.TECH_INDUSTRIAL_ELECTROLYSIS, "高圧水電解・酸素水素分離", 140.0, frozenset({ids.TECH_VOLATILE_ISRU}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8}, demonstration_days=12, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("water_extraction"))),
        ids.TECH_PROPELLANT_HANDLING: ResearchDefinition(ids.TECH_PROPELLANT_HANDLING, "酸素・水素液化・極低温推進剤調製", 170.0, frozenset({ids.TECH_INDUSTRIAL_ELECTROLYSIS}), prototype_site_requirements=lab_prototype, prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 1.0}, demonstration_days=15, demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("industrial_electrolysis", "cryogenic_storage"))),
    }


def build_research_providers() -> dict:
    return {ids.EARTH_RESEARCH_LAB: ResearchProviderSpec(ids.EARTH_RESEARCH_LAB, tier=1, levels=(ResearchProviderLevelSpec(1, 4.0, 180.0), ResearchProviderLevelSpec(2, 6.5, 320.0), ResearchProviderLevelSpec(3, 9.5, 560.0)))}


def build_survey_targets() -> dict:
    return {
        (ids.POLAR_COLD_TRAP, ids.WATER): SurveyTarget(ids.POLAR_COLD_TRAP, ids.WATER, 0.08, 1500.0, (20.0, 60.0, 120.0, 220.0), 0.90),
        (ids.SOUTH_POLAR_RIDGE, ids.WATER): SurveyTarget(ids.SOUTH_POLAR_RIDGE, ids.WATER, 0.012, 180.0, (20.0, 60.0, 120.0, 220.0), 0.55),
        (ids.NEARSIDE_MARE, ids.WATER): SurveyTarget(ids.NEARSIDE_MARE, ids.WATER, 0.0, 0.0, (20.0, 60.0, 120.0, 220.0), 0.08),
        (ids.POLAR_COLD_TRAP, ids.REGOLITH): SurveyTarget(ids.POLAR_COLD_TRAP, ids.REGOLITH, 0.92, 10000.0, (20.0, 60.0, 120.0, 220.0), 0.99),
        (ids.SOUTH_POLAR_RIDGE, ids.REGOLITH): SurveyTarget(ids.SOUTH_POLAR_RIDGE, ids.REGOLITH, 0.95, 10000.0, (20.0, 60.0, 120.0, 220.0), 0.99),
        (ids.NEARSIDE_MARE, ids.REGOLITH): SurveyTarget(ids.NEARSIDE_MARE, ids.REGOLITH, 0.97, 10000.0, (20.0, 60.0, 120.0, 220.0), 0.99),
    }


def build_survey_providers() -> dict:
    return {ids.ROBOTIC_SURVEY_PACKAGE: SurveyProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, 5.0)}


def build_extraction_specs() -> dict:
    return {ids.VOLATILE_EXTRACTOR: ExtractionSpec(ids.VOLATILE_EXTRACTOR, ids.WATER, ids.WATER, 6.0, 3), ids.REGOLITH_HARVESTER: ExtractionSpec(ids.REGOLITH_HARVESTER, ids.REGOLITH, ids.REGOLITH, 8.0, 2)}
