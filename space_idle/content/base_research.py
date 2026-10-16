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
from .base_research_details import RESEARCH_DETAILS
from .base_research_stages import build_new_stage_specs
from .base_extended_assets import build_extended_research_providers


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
        # The plasma discharge and ion-optics designs must be validated on a
        # powered vacuum bench. A Theory-only research completion cannot
        # furnish a spacecraft with an untested high-voltage thruster.
        # The hydrogen-cooled reactor propulsion line has a distinct thermal
        # flow test and nozzle/heat-exchanger integration demonstration. Both
        # need real reactor instrumentation; Research cannot supply a free core.
        # Low-gravity root-zone water transport is an actual plant-growth
        # experiment on installed microgravity equipment, not an instant
        # theoretical upgrade of terrestrial farming or new free food output.
        ids.research_id("PL-PLANT-FOOD-04"): (
            ResearchPrototypeStageSpec(
                "microgravity-root-zone-growth-test",
                {ids.WATER: 0.5, ids.PRECISION_ELECTRONICS: 0.08},
                req.with_capabilities(req.ORBIT_SITE,
                                      "microgravity_experiment_equipment"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=6.0,
            ),
        ),
        ids.research_id("NT-NUCLEAR-THERMAL-02"): (
            ResearchPrototypeStageSpec(
                "reactor-hydrogen-flow-test",
                {ids.HYDROGEN: 0.8, ids.CERAMICS_GLASS: 0.35},
                req.with_capabilities(req.SiteRequirements(),
                                      "nuclear_thermal_flow_test_equipment",
                                      "fission_reactor_control_instrumentation"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=7.0,
            ),
        ),
        ids.research_id("NT-NUCLEAR-THERMAL-04"): (
            ResearchDemonstrationStageSpec(
                "nuclear-thermal-nozzle-integration", 7.0,
                req.with_capabilities(req.SiteRequirements(),
                                      "nuclear_thermal_flow_test_equipment",
                                      "fission_reactor_control_instrumentation"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
            ),
        ),
        ids.research_id("EP-PLASMA-THRUSTERS-02"): (
            ResearchPrototypeStageSpec(
                "hall-discharge-test",
                {ids.PRECISION_ELECTRONICS: 0.18, ids.HYDROGEN: 0.35},
                req.with_capabilities(req.ORBIT_SITE, "plasma_propulsion_test_instrumentation"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=5.0,
            ),
        ),
        ids.research_id("EP-PLASMA-THRUSTERS-03"): (
            ResearchPrototypeStageSpec(
                "ion-optics-beam-test",
                {ids.PRECISION_ELECTRONICS: 0.25, ids.HYDROGEN: 0.25},
                req.with_capabilities(req.ORBIT_SITE, "plasma_propulsion_test_instrumentation"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=6.0,
            ),
        ),
        # Higher-order science consumes finite experimental materials and
        # demands actual powered instrumentation. Its Research output comes
        # from installed assets; completing these stages is no global buff.
        ids.research_id("TH-THERMAL-TRANSPORT-06"): (
            ResearchPrototypeStageSpec(
                "deployable-radiator-flow-loop-trial",
                {ids.THERMAL_CONTROL_ASSEMBLIES: 0.6, ids.PRECISION_COMPONENTS: 0.15},
                req.with_capabilities(req.ORBIT_SITE, "microgravity_experiment_equipment"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),), required_work=8.0,
            ),
        ),
        ids.research_id("HB-HABITATION-PROTECTION-06"): (
            ResearchPrototypeStageSpec(
                "localized-radiation-attenuation-trial",
                {ids.RADIATION_SHIELDING_PANELS: 0.9, ids.PRECISION_ELECTRONICS: 0.12},
                req.with_capabilities(req.SiteRequirements(), "research_lab"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),), required_work=8.0,
            ),
        ),
        ids.research_id("CO-OPTICAL-COMMUNICATIONS-02"): (
            ResearchPrototypeStageSpec(
                "optical-link-modulation-hardware-trial",
                {ids.OPTICAL_INSTRUMENT_PACKAGES: 0.5, ids.PRECISION_ELECTRONICS: 0.12},
                req.with_capabilities(req.SURFACE_SITE, "deep_space_tracking_equipment"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),), required_work=8.0,
            ),
        ),
        ids.research_id("MS-MATERIALS-10"): (
            ResearchPrototypeStageSpec(
                "irradiated-material-fatigue-trial",
                {ids.CERAMICS_GLASS: 1.25, ids.PRECISION_COMPONENTS: 0.32},
                req.with_capabilities(req.SURFACE_SITE, "material_fatigue_beamline"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=10.0,
            ),
        ),
        ids.research_id("TH-THERMAL-TRANSPORT-07"): (
            ResearchDemonstrationStageSpec(
                "orbital-multiloop-thermal-isolation-test", 12.0,
                req.with_capabilities(req.ORBIT_SITE,
                                      "orbital_thermal_vacuum_calorimetry"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
            ),
        ),
        ids.research_id("BIO-HUMAN-BIOLOGY-MEDICINE-12"): (
            ResearchPrototypeStageSpec(
                "controlled-closed-habitat-microbiome-trial",
                {ids.FOOD: 0.35, ids.WATER: 0.65,
                 ids.PRECISION_COMPONENTS: 0.22},
                req.with_capabilities(req.SiteRequirements(),
                                      "bioregenerative_biomedical_research"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=12.0,
            ),
        ),
        # Experimental recovery of volatile fractions uses an actual heated
        # processor and finite process water/parts before a multistage separator
        # can be acquired; it is not a free yield change to existing equipment.
        ids.research_id("RP-RESOURCE-CHAIN-11"): (
            ResearchPrototypeStageSpec(
                "volatile-condensation-process-trial",
                {ids.VOLATILE_BEARING_MATERIAL: 0.65,
                 ids.MACHINERY: 0.14},
                req.with_capabilities(req.SiteRequirements(), "volatile_processing"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0,
                    scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=5.0,
            ),
        ),
        # Plant water recapture needs an operating cultivation module and a
        # finite feed-water/measurement trial. Post-research physical modules
        # must still be constructed: an old farm gains no new process interface.
        ids.research_id("PL-PLANT-FOOD-07"): (
            ResearchPrototypeStageSpec(
                "recirculating-nutrient-loop-trial",
                {ids.WATER: 0.70, ids.PRECISION_ELECTRONICS: 0.12},
                req.with_capabilities(req.SiteRequirements(), "food_hydroponics"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0,
                    scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=6.0,
            ),
        ),
        # Occupied pressure compartments and real life-support systems are
        # needed to validate long-duration low-net-water habitation.
        ids.research_id("LS-ATMOSPHERE-WATER-WASTE-13"): (
            ResearchDemonstrationStageSpec(
                "pressurized-life-support-recovery-trial", 8.0,
                req.with_capabilities(req.SiteRequirements(), "pressurized_habitation"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0,
                    scope=ServiceCapacityScope.ORGANIZATION,
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
        ids.RP_RESOURCE_CHAIN_16: (
            ResearchPrototypeStageSpec(
                "molten-oxide-electrode-trial",
                {ids.CERAMICS_GLASS: 0.45, ids.METAL_FEEDSTOCK: 0.25},
                req.with_capabilities(req.VACUUM_SURFACE_SITE, "vacuum_regolith_research_equipment"),
                (ServiceCapacityRequirement(
                    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
                ),),
                required_work=8.0,
            ),
        ),
    }
    authored = build_new_stage_specs()
    if set(additional_stages) & set(authored):
        raise ValueError("duplicated authored research Stage specifications")
    additional_stages.update(authored)
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
            engineering_problem=RESEARCH_DETAILS[code][0],
            technical_outcome=RESEARCH_DETAILS[code][1],
            application_domain=RESEARCH_DETAILS[code][2],
        )
    return definitions

def build_research_providers() -> dict:
    return {
        **build_extended_research_providers(),
        ids.PROPULSION_TEST_RESEARCH_PROVIDER: ResearchProviderSpec(
            ids.PROPULSION_TEST_RESEARCH_PROVIDER, ResearchProviderSourceKind.FACILITY,
            frozenset({"propulsion_test_equipment"}), tier=2,
            levels=(ResearchProviderLevelSpec(1, 8.0, 500.0, 1.6),),
        ),
        ids.DEEP_SPACE_TRACKING_RESEARCH_PROVIDER: ResearchProviderSpec(
            ids.DEEP_SPACE_TRACKING_RESEARCH_PROVIDER, ResearchProviderSourceKind.FACILITY,
            frozenset({"deep_space_tracking_equipment"}), tier=2,
            levels=(ResearchProviderLevelSpec(1, 6.0, 440.0, 1.4),),
        ),
        ids.MATERIALS_FATIGUE_BEAMLINE: ResearchProviderSpec(
            ids.MATERIALS_FATIGUE_BEAMLINE,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"material_fatigue_beamline"}), tier=4,
            levels=(ResearchProviderLevelSpec(1, 125.0, 12500.0, 24.0),),
        ),
        ids.ORBITAL_THERMAL_VACUUM_LAB: ResearchProviderSpec(
            ids.ORBITAL_THERMAL_VACUUM_LAB,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"orbital_thermal_vacuum_calorimetry"}), tier=4,
            levels=(ResearchProviderLevelSpec(1, 185.0, 18000.0, 32.0),),
        ),
        ids.BIOREGENERATIVE_BIOMEDICAL_LAB: ResearchProviderSpec(
            ids.BIOREGENERATIVE_BIOMEDICAL_LAB,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"bioregenerative_biomedical_research"}), tier=4,
            levels=(ResearchProviderLevelSpec(1, 250.0, 22000.0, 40.0),),
            crew_person_days_per_research_point=0.18,
            site_requirements=req.SiteRequirements(capability_requirements=(CapabilityRequirement(
                "closed_cycle_life_support", CapabilityRequirementState.ACTIVE,
            ),)),
        ),
        ids.RESEARCH_DATA_ARCHIVE: ResearchProviderSpec(
            ids.RESEARCH_DATA_ARCHIVE,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"research_data_retention"}),
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 0.0, 9000.0, 0.0),),
        ),
        ids.GENERAL_RESEARCH_LAB: ResearchProviderSpec(
            ids.GENERAL_RESEARCH_LAB,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"general_research_equipment"}),
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 2.2, 180.0, 1.5),),
        ),
        ids.ORBITAL_OBSERVATION_RESEARCH_PROVIDER: ResearchProviderSpec(
            ids.ORBITAL_OBSERVATION_RESEARCH_PROVIDER,
            ResearchProviderSourceKind.FLEET,
            frozenset({"optical_observation_instrument"}),
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 1.5, 120.0, 1.0),),
            site_requirements=req.ORBIT_SITE,
        ),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ResearchProviderSpec(
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"microgravity_experiment_equipment"}),
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 5.0, 650.0, 3.2),),
        ),
        ids.CREWED_ORBITAL_LABORATORY: ResearchProviderSpec(
            ids.CREWED_ORBITAL_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"crewed_orbital_research_equipment"}),
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 22.0, 1600.0, 5.0),),
            crew_person_days_per_research_point=0.18,
        ),
        ids.ROBOTIC_GEOLOGY_STATION: ResearchProviderSpec(
            ids.ROBOTIC_GEOLOGY_STATION,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"robotic_geology_equipment"}),
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 5.5, 1400.0, 3.5),),
        ),
        ids.SAMPLE_ANALYSIS_LABORATORY: ResearchProviderSpec(
            ids.SAMPLE_ANALYSIS_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"sample_analysis_equipment"}),
            tier=3,
            levels=(ResearchProviderLevelSpec(1, 36.0, 3500.0, 6.0),),
        ),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: ResearchProviderSpec(
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"vacuum_regolith_research_equipment"}),
            tier=4,
            levels=(ResearchProviderLevelSpec(1, 90.0, 9000.0, 12.0),),
        ),
    }
