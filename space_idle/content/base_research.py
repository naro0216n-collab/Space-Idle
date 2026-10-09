from __future__ import annotations

from ..research import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
    ResearchProviderSpec,
)
from ..knowledge import ExperienceContributionRule
from ..shared import DefinitionId
from . import base_ids as ids
from . import base_requirements as req
from .base_research_dag import RESEARCH_DAG_ROWS


def build_experience_contribution_rules() -> tuple[ExperienceContributionRule, ...]:
    return (
        ExperienceContributionRule("transport", ids.EXPERIENCE_TRANSPORT_OPERATIONS, 1.0),
        ExperienceContributionRule("extraction", ids.EXPERIENCE_EXTRACTION_OPERATIONS, 1.0),
        ExperienceContributionRule("manufacturing", ids.EXPERIENCE_MANUFACTURING_OPERATIONS, 1.0),
    )


def research_id(code: str) -> DefinitionId:
    return DefinitionId(code)


def build_research_definitions() -> dict[DefinitionId, ResearchDefinition]:
    definitions: dict[DefinitionId, ResearchDefinition] = {}
    for code, progression_stage, category, series, display_name, prerequisites, theory_cost in RESEARCH_DAG_ROWS:
        definition_id = research_id(code)
        if definition_id in definitions:
            raise ValueError(f"duplicate research definition id: {definition_id}")
        definitions[definition_id] = ResearchDefinition(
            definition_id,
            display_name,
            (ResearchTheoryStageSpec("theory", theory_cost),),
            prerequisites=frozenset(research_id(prerequisite) for prerequisite in prerequisites),
            progression_stage=progression_stage,
            category=category,
            series=series,
        )
    return definitions

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
        ids.ORBITAL_OBSERVATION_RESEARCH_PROVIDER: ResearchProviderSpec(
            ids.ORBITAL_OBSERVATION_RESEARCH_PROVIDER,
            ResearchProviderSourceKind.FLEET,
            ids.ORBITAL_OBSERVATION_SPACECRAFT,
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 2.0, 120.0, 1.0),),
            site_requirements=req.ORBIT_SITE,
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
            crew_person_days_per_research_point=0.18,
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
