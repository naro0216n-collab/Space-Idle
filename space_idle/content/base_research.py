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
from ..knowledge import ExperienceContributionRule
from ..execution_requirements import ServiceCapacityRequirement
from ..service_capacity import ServiceCapacityScope
from ..site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements
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
    # Authored experiments are attached only to technical questions whose
    # resolution actually needs hardware trials or operational evidence.
    # All other DAG entries remain Theory-only; display stages/series never
    # imply an automatic Research Stage kind.
    additional_stages = {
        # Restart-capable propulsion is not established solely by a design
        # calculation: a genuine propulsion test stand, propellant and finite
        # trial time are needed before production of restart-capable vehicles.
        ids.research_id("CH-COMBUSTION-06"): (
            ResearchPrototypeStageSpec(
                "restart-propellant-test",
                {ids.MACHINERY: 0.3, ids.PROPELLANT: 0.5},
                SiteRequirements(capability_requirements=(CapabilityRequirement(
                    "propulsion_test_equipment", CapabilityRequirementState.ACTIVE,
                ),)),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=4.0,
            ),
        ),
        # High-precision planetary navigation requires observations against a
        # tracking system, not an implicit upgrade of existing spacecraft.
        ids.research_id("GN-NAVIGATION-06"): (
            ResearchDemonstrationStageSpec(
                "deep-space-tracking-demonstration", 4.0,
                SiteRequirements(capability_requirements=(CapabilityRequirement(
                    "deep_space_tracking_equipment", CapabilityRequirementState.ACTIVE,
                ),)),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
            ),
        ),
        # Load-following control needs an existing instrumented reactor, not
        # merely any solar / grid power source. Both surface and orbital
        # reactors may provide the physical test interface, independent of ID.
        ids.research_id("FP-REACTOR-POWER-04"): (
            ResearchDemonstrationStageSpec(
                "reactor-load-following-demonstration", 3.0,
                SiteRequirements(capability_requirements=(CapabilityRequirement(
                    "fission_reactor_control_instrumentation", CapabilityRequirementState.ACTIVE,
                ),)),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
            ),
        ),
        ids.RP_RESOURCE_CHAIN_13: (
            ResearchPrototypeStageSpec(
                "oxide-reduction-prototype",
                {ids.MINERAL_FEEDSTOCK: 0.5, ids.MACHINERY: 0.25},
                SiteRequirements(
                    capability_requirements=(CapabilityRequirement(
                        "vacuum_regolith_research_equipment", CapabilityRequirementState.ACTIVE,
                    ),),
                ),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=3.0,
            ),
            ResearchOperationalExperienceStageSpec(
                "manufacturing-experience", {ids.EXPERIENCE_MANUFACTURING_OPERATIONS: 4.0},
            ),
        ),
    }
    definitions: dict[DefinitionId, ResearchDefinition] = {}
    for code, progression_stage, category, series, display_name, prerequisites, theory_cost in RESEARCH_DAG_ROWS:
        definition_id = research_id(code)
        if definition_id in definitions:
            raise ValueError(f"duplicate research definition id: {definition_id}")
        definitions[definition_id] = ResearchDefinition(
            definition_id,
            display_name,
            (ResearchTheoryStageSpec("theory", theory_cost),) + additional_stages.get(definition_id, ()),
            prerequisites=frozenset(research_id(prerequisite) for prerequisite in prerequisites),
            progression_stage=progression_stage,
            category=category,
            series=series,
        )
    return definitions

def build_research_providers() -> dict:
    return {
        ids.PROPULSION_TEST_RESEARCH_PROVIDER: ResearchProviderSpec(
            ids.PROPULSION_TEST_RESEARCH_PROVIDER, ResearchProviderSourceKind.FACILITY,
            frozenset({"propulsion_test_equipment"}), tier=2,
            levels=(ResearchProviderLevelSpec(1, 8.0, 500.0, 0.8),),
        ),
        ids.DEEP_SPACE_TRACKING_RESEARCH_PROVIDER: ResearchProviderSpec(
            ids.DEEP_SPACE_TRACKING_RESEARCH_PROVIDER, ResearchProviderSourceKind.FACILITY,
            frozenset({"deep_space_tracking_equipment"}), tier=2,
            levels=(ResearchProviderLevelSpec(1, 6.0, 440.0, 0.8),),
        ),
        ids.EARTH_RESEARCH_LAB: ResearchProviderSpec(
            ids.EARTH_RESEARCH_LAB,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"general_research_equipment"}),
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
            frozenset({"optical_observation_instrument"}),
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 2.0, 120.0, 1.0),),
            site_requirements=req.ORBIT_SITE,
        ),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ResearchProviderSpec(
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"microgravity_experiment_equipment"}),
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 9.0, 650.0, 1.0),),
        ),
        ids.CREWED_ORBITAL_LABORATORY: ResearchProviderSpec(
            ids.CREWED_ORBITAL_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"crewed_orbital_research_equipment"}),
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 22.0, 1600.0, 1.0),),
            crew_person_days_per_research_point=0.18,
        ),
        ids.ROBOTIC_GEOLOGY_STATION: ResearchProviderSpec(
            ids.ROBOTIC_GEOLOGY_STATION,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"robotic_geology_equipment"}),
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 14.0, 1400.0, 1.0),),
        ),
        ids.SAMPLE_ANALYSIS_LABORATORY: ResearchProviderSpec(
            ids.SAMPLE_ANALYSIS_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"sample_analysis_equipment"}),
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 36.0, 3500.0, 1.0),),
        ),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: ResearchProviderSpec(
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"vacuum_regolith_research_equipment"}),
            tier=4,
            levels=(ResearchProviderLevelSpec(1, 90.0, 9000.0, 1.0),),
        ),
    }
