from __future__ import annotations

from ..projects import (
    ConstructionProviderSpec,
    ConstructionRecipe,
    ConstructionResourceProviderSpec,
    FacilityUpgradeRecipe,
    FacilityDecommissionRecipe,
    SpatialDevelopmentRecipe,
    BuildResourceRequirement,
)
from ..site import SiteRequirements
from . import base_ids as ids
from . import base_requirements as req


def build_construction_recipes() -> dict:
    return {
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ConstructionRecipe(
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            (req._structure_resource(2.0), req._machinery_resource(1.5), req._electronics_resource(1.5)),
            0.0,
            SiteRequirements(),
            frozenset({ids.SS_SENSING_01}),
            True,
        ),
        ids.CREWED_ORBITAL_LABORATORY: ConstructionRecipe(
            ids.CREWED_ORBITAL_LABORATORY,
            (req._structure_resource(8.0), req._machinery_resource(7.0), req._electronics_resource(5.0)),
            0.0,
            SiteRequirements(),
            frozenset({ids.BIO_HUMAN_BIOLOGY_MEDICINE_03}),
            True,
        ),
        ids.ROBOTIC_GEOLOGY_STATION: req._surface_recipe(
            ids.ROBOTIC_GEOLOGY_STATION,
            3.0,
            3.0,
            2.0,
            0.0,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_01}),
            capabilities=frozenset(),
            self_deploying=True,
        ),
        ids.SAMPLE_ANALYSIS_LABORATORY: req._surface_recipe(
            ids.SAMPLE_ANALYSIS_LABORATORY,
            6.0,
            7.0,
            5.0,
            35.0,
            technologies=frozenset({ids.SS_SENSING_05}),
            capabilities=frozenset({"surface_survey"}),
        ),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: req._surface_recipe(
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            10.0,
            12.0,
            7.0,
            70.0,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_03}),
            capabilities=frozenset({"granular_mineral_extraction"}),
        ),
        ids.ORBITAL_LOGISTICS_NODE: ConstructionRecipe(
            ids.ORBITAL_LOGISTICS_NODE,
            (req._structure_resource(3.0), req._machinery_resource(2.0), req._electronics_resource(1.0)),
            0.0,
            SiteRequirements(),
            frozenset({ids.LM_LOGISTICS_MAINTENANCE_01, ids.CR_CRYOGENIC_STORAGE_TRANSFER_03}),
            True,
        ),
        ids.ROBOTIC_SURVEY_PACKAGE: req._surface_recipe(
            ids.ROBOTIC_SURVEY_PACKAGE, 2.0, 3.0, 1.5, 0.0,
            technologies=frozenset({ids.SS_SENSING_04}), capabilities=frozenset(), self_deploying=True,
        ),
        ids.SURFACE_POWER_GRID: req._surface_recipe(
            ids.SURFACE_POWER_GRID, 12, 5, 2, 45,
            technologies=frozenset({ids.PG_SOLAR_POWER_02}),
        ),
        ids.INDUSTRIAL_POWER_BLOCK: req._surface_recipe(
            ids.INDUSTRIAL_POWER_BLOCK, 14, 9, 3, 60,
            technologies=frozenset({ids.FP_REACTOR_POWER_02}),
        ),
        ids.CONSTRUCTION_YARD: req._surface_recipe(ids.CONSTRUCTION_YARD, 10, 6, 2, 50),
        ids.VOLATILE_EXTRACTOR: req._surface_recipe(
            ids.VOLATILE_EXTRACTOR, 4, 4, 1, 25,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_05}),
        ),
        ids.VOLATILE_PROCESSING: req._surface_recipe(
            ids.VOLATILE_PROCESSING, 5, 5, 1, 32,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_06}),
        ),
        ids.VACUUM_MINERAL_HARVESTER: req._surface_recipe(
            ids.VACUUM_MINERAL_HARVESTER, 4, 5, 1, 28,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_02}),
        ),
        ids.WATER_STORAGE: req._surface_recipe(ids.WATER_STORAGE, 2.5, 1, 0.2, 12),
        ids.CRYOGENIC_STORAGE: req._surface_recipe(
            ids.CRYOGENIC_STORAGE, 3, 2, 0.8, 22,
            technologies=frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_02}),
        ),
        ids.BULK_STORAGE: req._surface_recipe(ids.BULK_STORAGE, 2, 1, 0.1, 10),
        ids.CARGO_WAREHOUSE: req._surface_recipe(ids.CARGO_WAREHOUSE, 3, 1, 0.2, 14),
        ids.SURFACE_DISTRIBUTION_HUB: req._surface_recipe(
            ids.SURFACE_DISTRIBUTION_HUB, 5, 4, 1, 28
        ),
        ids.ELECTROLYSIS_PLANT: ConstructionRecipe(
            ids.ELECTROLYSIS_PLANT,
            (
                BuildResourceRequirement(ids.FABRICATED_STRUCTURE, 1.5),
                BuildResourceRequirement(ids.CERAMICS_GLASS, 1.0),
                BuildResourceRequirement(ids.BASIC_MACHINE_PARTS, 0.8),
                BuildResourceRequirement(ids.PRECISION_COMPONENTS, 0.2),
            ),
            28,
            req.SURFACE_SITE,
            frozenset({ids.RP_RESOURCE_CHAIN_12}),
        ),
        ids.PROPELLANT_PLANT: ConstructionRecipe(
            ids.PROPELLANT_PLANT,
            (
                BuildResourceRequirement(ids.FABRICATED_STRUCTURE, 1.6),
                BuildResourceRequirement(ids.CERAMICS_GLASS, 0.6),
                BuildResourceRequirement(ids.BASIC_MACHINE_PARTS, 0.9),
                BuildResourceRequirement(ids.PRECISION_COMPONENTS, 0.25),
            ),
            30,
            req.SURFACE_SITE,
            frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_04}),
        ),
        ids.MINERAL_SINTERING: req._surface_recipe(
            ids.MINERAL_SINTERING, 8, 6, 2, 55,
            technologies=frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_10}),
        ),
        ids.ORE_PROCESSING: req._surface_recipe(
            ids.ORE_PROCESSING, 10, 7, 2, 60,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_04}),
        ),
        ids.METALLURGY: req._surface_recipe(
            ids.METALLURGY, 12, 8, 3, 70,
            technologies=frozenset({ids.RP_RESOURCE_CHAIN_13}),
        ),
        ids.FABRICATION_WORKSHOP: req._surface_recipe(
            ids.FABRICATION_WORKSHOP, 8, 8, 4, 65,
            technologies=frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_05}),
        ),
        ids.MACHINE_SHOP: req._surface_recipe(
            ids.MACHINE_SHOP, 10, 10, 5, 80,
            technologies=frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_01}),
        ),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: ConstructionRecipe(
            ids.HEAVY_EQUIPMENT_ASSEMBLY,
            (
                BuildResourceRequirement(ids.FABRICATED_STRUCTURE, 8.0),
                BuildResourceRequirement(ids.BASIC_MACHINE_PARTS, 6.0),
                BuildResourceRequirement(ids.PRECISION_COMPONENTS, 1.0),
            ),
            100,
            req.SURFACE_SITE,
            frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_09}),
        ),
        ids.MINERAL_QUARRY: req._surface_recipe(
            ids.MINERAL_QUARRY, 5, 7, 0, 32,
        ),
        ids.METAL_ORE_MINE: req._surface_recipe(
            ids.METAL_ORE_MINE, 6, 8, 0, 38,
        ),
        ids.INDUSTRIAL_WATER_INTAKE: req._surface_recipe(
            ids.INDUSTRIAL_WATER_INTAKE, 5, 5, 0, 30,
        ),
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: req._surface_recipe(
            ids.BASIC_STRUCTURAL_MATERIAL_PLANT, 8, 8, 1, 45,
        ),
        ids.BASIC_MACHINERY_WORKS: req._surface_recipe(
            ids.BASIC_MACHINERY_WORKS, 8, 10, 1, 52,
        ),
    }


def build_facility_upgrade_recipes() -> dict:
    recipes = (
        FacilityUpgradeRecipe(
            ids.EARTH_RESEARCH_LAB,
            2,
            (
                req._structure_resource(1.5),
                req._machinery_resource(2.0),
                req._electronics_resource(1.2),
            ),
            20.0,
            SiteRequirements(),
            frozenset({ids.LM_LOGISTICS_MAINTENANCE_01}),
        ),
        FacilityUpgradeRecipe(
            ids.EARTH_RESEARCH_LAB,
            3,
            (
                req._structure_resource(2.5),
                req._machinery_resource(3.0),
                req._electronics_resource(2.0),
            ),
            35.0,
            SiteRequirements(),
            frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_03}),
        ),
    )
    return {(recipe.facility_def_id, recipe.target_level): recipe for recipe in recipes}


def build_facility_decommission_recipes(facility_definition_ids) -> dict:
    """Base content uses the common construction-work service for dismantling.

    The exact work value is balance content.  No Facility identity receives a
    special Core path; newly added Facility definitions can opt in by inclusion.
    """
    return {
        facility_definition_id: FacilityDecommissionRecipe(
            facility_def_id=facility_definition_id,
            construction_work=12.0,
        )
        for facility_definition_id in facility_definition_ids
    }


def build_construction_providers() -> dict:
    return {
        ids.ROBOTIC_SURVEY_PACKAGE: ConstructionProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, 0.35),
        ids.CONSTRUCTION_YARD: ConstructionProviderSpec(ids.CONSTRUCTION_YARD, 0.8),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: ConstructionProviderSpec(ids.HEAVY_EQUIPMENT_ASSEMBLY, 1.5),
    }


def build_construction_resource_providers() -> dict:
    return {ids.CONSTRUCTION_EQUIPMENT: ConstructionResourceProviderSpec(ids.CONSTRUCTION_EQUIPMENT, 0.05)}


def procurement_wait_days() -> dict[str, int]:
    return {"immediate": 0, "standard_wait": 45, "extended_wait": 120}


def build_spatial_development_recipes() -> dict:
    surface_site = req.SURFACE_SITE
    recipes = (
        SpatialDevelopmentRecipe(
            ids.SURFACE_CELL_DEVELOPMENT_PROJECT,
            "Surface Territory Development",
            (
                BuildResourceRequirement(ids.STRUCTURAL_COMPONENTS, 5.0),
                BuildResourceRequirement(ids.MACHINERY, 3.0),
                BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 2.0),
            ),
            36.0,
            surface_site,
            knowledge_requirements=(),
        ),
    )
    return {recipe.id: recipe for recipe in recipes}
