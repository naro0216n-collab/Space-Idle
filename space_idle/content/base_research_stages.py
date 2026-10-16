"""Authoring of the non-Theory research stages in the eight-stage research catalog.

The prototype equipment, finite consumed stock and operational activity are
separate from Technology unlocks. These are design Content quantities and can
be adjusted alongside actual equipment, processes and their material supply.
"""
from __future__ import annotations

from ..execution_requirements import ServiceCapacityRequirement
from ..research import (
    ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec,
    ResearchOperationalExperienceStageSpec,
)
from ..service_capacity import ServiceCapacityScope
from ..shared import DefinitionId
from . import base_requirements as req

_RESEARCH_EXECUTION = (ServiceCapacityRequirement(
    "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION,
),)

# Research-owned execution work: physical equipment remains installed and
# powered, not acquired or upgraded automatically with Technology completion.
# A Prototype consumes reserved physical stock once; Demonstration requires
# actual active capability throughout its operation.
_SITE_STAGES = {
    # id: (kind, stage id, site requirements, work, prototype consumables)
    "X2-REMOTE-OPERATIONS-LAB": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SURFACE_SITE, "general_research_equipment"), 6.0, {"base.resource.machinery": .3, "base.resource.precision_electronics": .2}),
    "X3-CREW-LIFE-SUPPORT-TEST": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "pressurized_habitation", "closed_cycle_life_support"), 10.0, {}),
    "X4-REUSABLE-CARGO": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.ORBIT_SITE, "vehicle_refueling"), 8.0, {}),
    "X4-SINTER-BUILD": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SURFACE_SITE, "mineral_sintering"), 6.0, {"base.resource.mineral_feedstock": 1.0, "base.resource.machinery": .25}),
    "X5-SPARE-PARTS-REPAIR": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "basic_machine_shop"), 8.0, {}),
    "X5-GEOSPATIAL-EARTHWORK": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SURFACE_SITE, "construction_yard"), 9.0, {"base.resource.construction_equipment": .25, "base.resource.bulk_structure": .7}),
    "X5-INDUSTRIAL-CONSTRUCTION": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SURFACE_SITE, "construction_yard"), 12.0, {"base.resource.fabricated_structure": .8, "base.resource.machinery": .3}),
    "X5-PRECISION-FABRICATION": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SiteRequirements(), "precision_machining"), 11.0, {"base.resource.basic_machine_parts": .8, "base.resource.precision_electronics": .2}),
    "X5-THERMAL-REFINING": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "metallurgy"), 10.0, {}),
    "X5-HEAT-REJECTION": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "heat_pipe_radiator_assembly"), 8.0, {}),
    "X6-DISTRIBUTED-PROCESS-CONTROL": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SiteRequirements(), "inline_microelectronics_inspection"), 10.0, {"base.resource.precision_electronics": .4, "base.resource.machinery": .5}),
    "X6-DIRECT-HANDOFF": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.ORBIT_SITE, "spacecraft_servicing"), 12.0, {"base.resource.machinery": .5, "base.resource.structural_components": .6}),
    "X6-CISLUNAR-MASS-BUILD": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "robotic_orbital_construction"), 12.0, {}),
    "X6-ORBITAL-MANUFACTURING": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.ORBIT_SITE, "precision_machining"), 12.0, {"base.resource.bulk_structure": 1.0, "base.resource.precision_components": .3}),
    "X6-CROSS-SITE-RESEARCH": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "sample_analysis_equipment"), 10.0, {}),
    "X7-DELAY-TOLERANT-AUTONOMY": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "robotic_geology_equipment"), 12.0, {}),
    "X7-DEEP-SPACE-RELAY": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "deep_space_tracking_equipment"), 12.0, {}),
    "X7-EXTREME-POWER": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "fission_reactor_control_instrumentation"), 15.0, {}),
    "X7-REMOTE-LIFE-SUPPORT": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SiteRequirements(), "closed_cycle_life_support"), 14.0, {"base.resource.thermal_control_assemblies": .5, "base.resource.water": 1.0}),
    "X7-RADIATION-HARDENED-COMPONENTS": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SiteRequirements(), "microelectronics_fabrication"), 14.0, {"base.resource.precision_electronics": 1.0, "base.resource.radiation_shielding_panels": .5}),
    "X7-REMOTE-RADIATION-SCIENCE": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "sample_analysis_equipment"), 12.0, {}),
    "X8-AUTONOMOUS-INFRASTRUCTURE": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SURFACE_SITE, "construction_yard"), 15.0, {"base.resource.machinery": 1.0, "base.resource.hardened_electronics": .25}),
    "X8-REMOTE-HABITATION-NETWORK": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.SiteRequirements(), "bioregenerative_biomedical_research"), 16.0, {}),
    "X8-DISTRIBUTED-POWER": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.ORBIT_SITE, "orbital_solar_generation", "deep_space_tracking_equipment"), 16.0, {}),
    "X8-CIRCULAR-MANUFACTURING": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SiteRequirements(), "industrial_machinery_assembly"), 18.0, {"base.resource.hardened_electronics": .25, "base.resource.fabricated_structure": 1.5}),
    "X8-REMOTE-CELL-REMEDIATION": ("PROTOTYPE", "prototype_2", req.with_capabilities(req.SURFACE_SITE, "construction_yard"), 18.0, {"base.resource.construction_equipment": 1.0, "base.resource.bulk_structure": 1.5}),
    "X8-DISTRIBUTED-ASTRONOMY": ("DEMONSTRATION", "demonstration_2", req.with_capabilities(req.ORBIT_SITE, "deep_space_tracking_equipment"), 20.0, {}),
    # Staged fusion evidence uses installed, grid-powered apparatus. The
    # required previous Technology makes the apparatus buildable before each
    # successive stage, without making its own completion a prerequisite.
    'SF-FUSION-02': ('PROTOTYPE', 'magnetic-plasma-ignition-trial',
                     req.with_capabilities(req.SURFACE_SITE, 'magnetic_fusion_confinement_test'),
                     16.0, {'base.resource.hydrogen': 0.8, 'base.resource.thermal_control_assemblies': 0.3}),
    'SF-FUSION-05': ('PROTOTYPE', 'pulsed-fusion-blanket-trial',
                     req.with_capabilities(req.SURFACE_SITE, 'pulsed_fusion_ignition_test'),
                     20.0, {'base.resource.hydrogen': 1.2, 'base.resource.radiation_shielding_panels': 0.5}),
    'SF-FUSION-04': ('PROTOTYPE', 'fusion-blanket-circulation-trial',
                     req.with_capabilities(req.SURFACE_SITE, 'fusion_blanket_irradiation_test'),
                     23.0, {'base.resource.hydrogen': 1.6, 'base.resource.refractory_alloy': 0.8}),
}

_EXPERIENCE_STAGES = {
    "X5-LOCAL-PROPELLANT": ("operational_experience_2", "base.experience.manufacturing_operations", 12.0),
    "X6-INTERPLANETARY-REPAIR": ("operational_experience_2", "base.experience.transport_operations", 22.0),
    "X7-LONG-DURATION-FLEET": ("operational_experience_2", "base.experience.transport_operations", 40.0),
}


def build_new_stage_specs():
    stages = {}
    for technology, (kind, stage_id, site, work, resources) in _SITE_STAGES.items():
        if kind == "PROTOTYPE":
            spec = ResearchPrototypeStageSpec(
                stage_id, {DefinitionId(name): amount for name, amount in resources.items()},
                site, _RESEARCH_EXECUTION, work,
            )
        else:
            spec = ResearchDemonstrationStageSpec(stage_id, work, site, _RESEARCH_EXECUTION)
        stages[DefinitionId(technology)] = (spec,)
    for technology, (stage_id, category, quantity) in _EXPERIENCE_STAGES.items():
        stages[DefinitionId(technology)] = (
            ResearchOperationalExperienceStageSpec(stage_id, {category: quantity}),
        )
    return stages
