from __future__ import annotations

from ..projects import (
    ConstructionProviderSpec,
    ConstructionRecipe,
    ConstructionResourceProviderSpec,
    FacilityUpgradeRecipe,
)
from ..site import SiteRequirements
from . import base_ids as ids
from . import base_requirements as req


def build_construction_recipes() -> dict:
    return {
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ConstructionRecipe(
            ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
            (req._structure_component(2.0), req._machinery_component(1.5), req._electronics_component(1.5)),
            0.0,
            SiteRequirements(),
            frozenset({ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS}),
            True,
        ),
        ids.CREWED_ORBITAL_LABORATORY: ConstructionRecipe(
            ids.CREWED_ORBITAL_LABORATORY,
            (req._structure_component(8.0), req._machinery_component(7.0), req._electronics_component(5.0)),
            0.0,
            SiteRequirements(),
            frozenset({ids.TECH_CREWED_ORBITAL_RESEARCH}),
            True,
        ),
        ids.ROBOTIC_GEOLOGY_STATION: req._surface_recipe(
            ids.ROBOTIC_GEOLOGY_STATION,
            3.0,
            3.0,
            2.0,
            0.0,
            technologies=frozenset({ids.TECH_ROBOTIC_FIELD_GEOLOGY}),
            capabilities=frozenset(),
            self_deploying=True,
        ),
        ids.SAMPLE_ANALYSIS_LABORATORY: req._surface_recipe(
            ids.SAMPLE_ANALYSIS_LABORATORY,
            6.0,
            7.0,
            5.0,
            35.0,
            technologies=frozenset({ids.TECH_SAMPLE_ANALYSIS_SYSTEMS}),
            capabilities=frozenset({"surface_survey"}),
        ),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: req._surface_recipe(
            ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
            10.0,
            12.0,
            7.0,
            70.0,
            technologies=frozenset({ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH}),
            capabilities=frozenset({"regolith_excavation"}),
        ),
        ids.ORBITAL_LOGISTICS_NODE: ConstructionRecipe(
            ids.ORBITAL_LOGISTICS_NODE,
            (req._structure_component(3.0), req._machinery_component(2.0), req._electronics_component(1.0)),
            0.0,
            SiteRequirements(),
            frozenset({ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS}),
            True,
        ),
        ids.ROBOTIC_SURVEY_PACKAGE: req._surface_recipe(
            ids.ROBOTIC_SURVEY_PACKAGE, 2.0, 3.0, 1.5, 0.0,
            technologies=frozenset({ids.TECH_LUNAR_PROSPECTING}), capabilities=frozenset(), self_deploying=True,
        ),
        ids.SURFACE_POWER_GRID: req._surface_recipe(ids.SURFACE_POWER_GRID, 12, 5, 2, 45),
        ids.INDUSTRIAL_POWER_BLOCK: req._surface_recipe(ids.INDUSTRIAL_POWER_BLOCK, 14, 9, 3, 60),
        ids.CONSTRUCTION_YARD: req._surface_recipe(ids.CONSTRUCTION_YARD, 10, 6, 2, 50),
        ids.VOLATILE_EXTRACTOR: req._surface_recipe(
            ids.VOLATILE_EXTRACTOR, 4, 4, 1, 25,
            technologies=frozenset({ids.TECH_VOLATILE_ISRU}),
        ),
        ids.REGOLITH_HARVESTER: req._surface_recipe(
            ids.REGOLITH_HARVESTER, 4, 5, 1, 28,
            technologies=frozenset({ids.TECH_REGOLITH_EXCAVATION}),
        ),
        ids.WATER_STORAGE: req._surface_recipe(ids.WATER_STORAGE, 2.5, 1, 0.2, 12),
        ids.CRYOGENIC_STORAGE: req._surface_recipe(ids.CRYOGENIC_STORAGE, 3, 2, 0.8, 22),
        ids.BULK_STORAGE: req._surface_recipe(ids.BULK_STORAGE, 2, 1, 0.1, 10),
        ids.CARGO_WAREHOUSE: req._surface_recipe(ids.CARGO_WAREHOUSE, 3, 1, 0.2, 14),
        ids.ELECTROLYSIS_PLANT: req._surface_recipe(
            ids.ELECTROLYSIS_PLANT, 3, 3, 1.2, 28,
            technologies=frozenset({ids.TECH_INDUSTRIAL_ELECTROLYSIS}),
        ),
        ids.PROPELLANT_PLANT: req._surface_recipe(
            ids.PROPELLANT_PLANT, 3, 3, 1, 30,
            technologies=frozenset({ids.TECH_PROPELLANT_HANDLING}),
        ),
        ids.REGOLITH_SINTERING: req._surface_recipe(
            ids.REGOLITH_SINTERING, 8, 6, 2, 55,
            technologies=frozenset({ids.TECH_LUNAR_MATERIALS}),
        ),
        ids.ORE_PROCESSING: req._surface_recipe(
            ids.ORE_PROCESSING, 10, 7, 2, 60,
            technologies=frozenset({ids.TECH_ORE_BENEFICIATION}),
        ),
        ids.METALLURGY: req._surface_recipe(
            ids.METALLURGY, 12, 8, 3, 70,
            technologies=frozenset({ids.TECH_HIGH_TEMPERATURE_METALLURGY}),
        ),
        ids.FABRICATION_WORKSHOP: req._surface_recipe(
            ids.FABRICATION_WORKSHOP, 8, 8, 4, 65,
            technologies=frozenset({ids.TECH_STRUCTURAL_FABRICATION}),
        ),
        ids.MACHINE_SHOP: req._surface_recipe(
            ids.MACHINE_SHOP, 10, 10, 5, 80,
            technologies=frozenset({ids.TECH_PRECISION_MACHINING}),
        ),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: req._surface_recipe(
            ids.HEAVY_EQUIPMENT_ASSEMBLY, 14, 14, 6, 100,
            technologies=frozenset({ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY}),
        ),
    }


def build_facility_upgrade_recipes() -> dict:
    recipes = (
        FacilityUpgradeRecipe(
            ids.EARTH_RESEARCH_LAB,
            2,
            (
                req._structure_component(1.5),
                req._machinery_component(2.0),
                req._electronics_component(1.2),
            ),
            20.0,
            SiteRequirements(),
            frozenset({ids.TECH_ORBITAL_OPERATIONS}),
        ),
        FacilityUpgradeRecipe(
            ids.EARTH_RESEARCH_LAB,
            3,
            (
                req._structure_component(2.5),
                req._machinery_component(3.0),
                req._electronics_component(2.0),
            ),
            35.0,
            SiteRequirements(),
            frozenset({ids.TECH_CISLUNAR_LOGISTICS}),
        ),
    )
    return {(recipe.facility_def_id, recipe.target_level): recipe for recipe in recipes}


def build_construction_providers() -> dict:
    return {
        ids.ROBOTIC_SURVEY_PACKAGE: ConstructionProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, 0.35),
        ids.CONSTRUCTION_YARD: ConstructionProviderSpec(ids.CONSTRUCTION_YARD, 0.8),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: ConstructionProviderSpec(ids.HEAVY_EQUIPMENT_ASSEMBLY, 1.5),
    }


def build_construction_resource_providers() -> dict:
    return {ids.CONSTRUCTION_EQUIPMENT: ConstructionResourceProviderSpec(ids.CONSTRUCTION_EQUIPMENT, 0.05)}


def sourcing_wait_days() -> dict[str, int]:
    return {"import_now": 0, "mixed": 45, "local_priority": 120}
