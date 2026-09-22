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
from .base_research_dag import RESEARCH_DAG_ROWS


def build_experience_contribution_rules() -> tuple[ExperienceContributionRule, ...]:
    return (
        ExperienceContributionRule("transport", ids.EXPERIENCE_TRANSPORT_OPERATIONS, 1.0),
        ExperienceContributionRule("extraction", ids.EXPERIENCE_EXTRACTION_OPERATIONS, 1.0),
        ExperienceContributionRule("manufacturing", ids.EXPERIENCE_MANUFACTURING_OPERATIONS, 1.0),
    )


def research_id(code: str) -> DefinitionId:
    return DefinitionId(code)


def _theory_cost(progression_stage: int) -> float:
    # Base-content balance only; stage is metadata, not an implicit gate.
    return {1: 180.0, 2: 480.0, 3: 1200.0, 4: 3000.0}[progression_stage]


def build_research_definitions() -> dict[DefinitionId, ResearchDefinition]:
    definitions: dict[DefinitionId, ResearchDefinition] = {}
    for code, progression_stage, category, series, display_name, prerequisites in RESEARCH_DAG_ROWS:
        definition_id = research_id(code)
        if definition_id in definitions:
            raise ValueError(f"duplicate research definition id: {definition_id}")
        definitions[definition_id] = ResearchDefinition(
            definition_id,
            display_name,
            (ResearchTheoryStageSpec("theory", _theory_cost(progression_stage)),),
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
