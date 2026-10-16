from __future__ import annotations

from ..projects import ConstructionResourceProviderSpec, SpatialDevelopmentRecipe, BuildResourceRequirement
from . import base_ids as ids
from . import base_requirements as req


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
        SpatialDevelopmentRecipe(
            ids.SURFACE_TERRAIN_GRADING_PROJECT,
            "Surface Terrain Grading",
            (
                BuildResourceRequirement(ids.MACHINERY, 1.0),
                BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 1.0),
            ),
            12.0,
            surface_site,
            target_terrain_profile_id="rolling",
        ),
        SpatialDevelopmentRecipe(
            ids.SURFACE_TERRAIN_ENGINEERING_PROJECT,
            "Surface Terrain Engineering",
            (
                BuildResourceRequirement(ids.STRUCTURAL_COMPONENTS, 3.0),
                BuildResourceRequirement(ids.MACHINERY, 2.0),
            ),
            24.0,
            surface_site,
            target_terrain_profile_id="plain",
        ),
    )
    return {recipe.id: recipe for recipe in recipes}
