from __future__ import annotations

from ..research import ResearchDefinition, ResearchProviderSpec
from ..site import SiteRequirements
from ..survey import ExtractionSpec, SurveyProviderSpec, SurveyTarget
from . import base_ids as ids
from . import base_requirements as req


def build_research_definitions() -> dict:
    return {
        ids.TECH_ORBITAL_OPERATIONS: ResearchDefinition(
            ids.TECH_ORBITAL_OPERATIONS, "軌道上運用標準化", 80.0,
            prototype_site_requirements=SiteRequirements(capability_requirements=req._available_requirements("research_lab")),
            prototype_resources={ids.PRECISION_ELECTRONICS: 0.5},
        ),
        ids.TECH_CISLUNAR_LOGISTICS: ResearchDefinition(
            ids.TECH_CISLUNAR_LOGISTICS, "月圏物流運用", 120.0, frozenset(),
            prototype_site_requirements=SiteRequirements(capability_requirements=req._available_requirements("research_lab")),
            prototype_resources={ids.MACHINERY: 1.0, ids.PRECISION_ELECTRONICS: 0.5},
        ),
        ids.TECH_LUNAR_PROSPECTING: ResearchDefinition(
            ids.TECH_LUNAR_PROSPECTING, "月資源精密探査", 100.0, frozenset(),
            prototype_site_requirements=SiteRequirements(capability_requirements=req._available_requirements("research_lab")),
            prototype_resources={ids.PRECISION_ELECTRONICS: 1.0},
        ),
        ids.TECH_VOLATILE_ISRU: ResearchDefinition(
            ids.TECH_VOLATILE_ISRU, "低温揮発性物質抽出", 150.0, frozenset({ids.TECH_LUNAR_PROSPECTING}),
            prototype_site_requirements=SiteRequirements(capability_requirements=req._available_requirements("research_lab")),
            prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 0.8},
            demonstration_days=20,
            demonstration_site_requirements=SiteRequirements(req.COLD_VOLATILE_SURFACE_ENV, req._available_requirements("surface_survey")),
        ),
        ids.TECH_LUNAR_MATERIALS: ResearchDefinition(
            ids.TECH_LUNAR_MATERIALS, "低重力真空環境材料プロセス", 180.0, frozenset({ids.TECH_LUNAR_PROSPECTING}),
            prototype_site_requirements=SiteRequirements(capability_requirements=req._available_requirements("research_lab")),
            prototype_resources={ids.MACHINERY: 2.5, ids.PRECISION_ELECTRONICS: 0.5},
        ),
        ids.TECH_PROPELLANT_HANDLING: ResearchDefinition(
            ids.TECH_PROPELLANT_HANDLING, "現地推進剤製造・取扱", 170.0, frozenset({ids.TECH_VOLATILE_ISRU}),
            prototype_site_requirements=SiteRequirements(capability_requirements=req._available_requirements("research_lab")),
            prototype_resources={ids.MACHINERY: 2.0, ids.PRECISION_ELECTRONICS: 1.0},
            demonstration_days=15,
            demonstration_site_requirements=SiteRequirements(req.SURFACE_ENV, req._available_requirements("water_extraction")),
        ),
    }


def build_research_providers() -> dict:
    return {ids.EARTH_RESEARCH_LAB: ResearchProviderSpec(ids.EARTH_RESEARCH_LAB, 4.0)}


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
    return {
        ids.VOLATILE_EXTRACTOR: ExtractionSpec(ids.VOLATILE_EXTRACTOR, ids.WATER, ids.WATER, 6.0, 3),
        ids.REGOLITH_HARVESTER: ExtractionSpec(ids.REGOLITH_HARVESTER, ids.REGOLITH, ids.REGOLITH, 8.0, 2),
    }
