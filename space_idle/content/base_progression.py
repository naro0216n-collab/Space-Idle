from __future__ import annotations

from ..spatial import SpatialGraph
from ..survey import (
    ExtractionSpec, KnowledgeLevel, SurveyReachScope, SurveyReachSpec, SurveyObservationModeSpec,
    SurveyProviderSourceKind, SurveyProviderSpec, SurveyTarget,
)
from . import base_requirements as req
from . import base_ids as ids


_EARTH_SURVEY_THRESHOLDS = (1.0, 2.0, 3.0)
_LUNAR_SURVEY_THRESHOLDS = (20.0, 60.0, 120.0)


def build_survey_targets(graph: SpatialGraph) -> dict:
    """Content-defined geological knowledge targets keyed by Surface Cell × Resource."""
    targets = {}
    for cell_id in (ids.EARTH_CELL_INDUSTRIAL, ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND):
        for resource_id in (ids.MINERAL_FEEDSTOCK, ids.METAL_ORE, ids.WATER):
            targets[(cell_id, resource_id)] = SurveyTarget(
                cell_id, resource_id, _EARTH_SURVEY_THRESHOLDS, 0.99
            )

    lunar_presence = {
        ids.MOON_CELL_SOUTH_POLAR_RIDGE: {ids.VOLATILE_BEARING_MATERIAL: 0.55, ids.MINERAL_FEEDSTOCK: 0.99, ids.METAL_ORE: 0.65},
        ids.MOON_CELL_POLAR_COLD_TRAP: {ids.VOLATILE_BEARING_MATERIAL: 0.90, ids.MINERAL_FEEDSTOCK: 0.99, ids.METAL_ORE: 0.42},
        ids.MOON_CELL_SOUTH_POLAR_PLAIN: {ids.VOLATILE_BEARING_MATERIAL: 0.35, ids.MINERAL_FEEDSTOCK: 0.99, ids.METAL_ORE: 0.58},
        ids.MOON_CELL_NEARSIDE_MARE: {ids.VOLATILE_BEARING_MATERIAL: 0.08, ids.MINERAL_FEEDSTOCK: 0.99, ids.METAL_ORE: 0.82},
        ids.MOON_CELL_EQUATORIAL_HIGHLANDS: {ids.VOLATILE_BEARING_MATERIAL: 0.12, ids.MINERAL_FEEDSTOCK: 0.99, ids.METAL_ORE: 0.74},
        ids.MOON_CELL_FARSIDE_HIGHLANDS: {ids.VOLATILE_BEARING_MATERIAL: 0.15, ids.MINERAL_FEEDSTOCK: 0.99, ids.METAL_ORE: 0.68},
    }
    for cell_id, probabilities in lunar_presence.items():
        for resource_id, probability in probabilities.items():
            targets[(cell_id, resource_id)] = SurveyTarget(
                cell_id, resource_id, _LUNAR_SURVEY_THRESHOLDS, probability
            )
    # Potential remains a World fact; these Survey targets begin with no
    # player-owned Knowledge and are not an inventory or mining allowance.
    for cell_id in (
        ids.MARS_CELL_EQUATORIAL_PLAIN,
        ids.MARS_CELL_NORTHERN_BASIN,
        ids.MARS_CELL_POLAR_HIGHLANDS,
    ):
        for resource_id in (ids.MINERAL_FEEDSTOCK, ids.METAL_ORE, ids.VOLATILE_BEARING_MATERIAL):
            targets[(cell_id, resource_id)] = SurveyTarget(
                cell_id, resource_id, (15.0, 45.0, 110.0), 0.5,
            )
    # Every registered Resource Potential has exactly one Survey target. The
    # physical world defines what could exist; this Content supplies only the
    # initial observation prior and knowledge thresholds, not player Knowledge.
    for cell in graph.surface_cells.values():
        for resource_id in cell.resource_potential_by_resource:
            targets.setdefault((cell.id, resource_id), SurveyTarget(
                cell.id, resource_id, (25.0, 75.0, 160.0), 0.5,
            ))
    return targets


def build_survey_providers() -> dict:
    remote_orbital = SurveyObservationModeSpec(
        "remote_orbital_spectrometry", 8.0, SurveyReachSpec(SurveyReachScope.SAME_BODY),
        KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL, 0.35, 0.12,
        required_source_capabilities=frozenset(("survey_sensor",)),
        display_name="軌道分光観測",
    )
    local_robotic = SurveyObservationModeSpec(
        "local_robotic_prospecting", 5.0, SurveyReachSpec(SurveyReachScope.LOCATION_TERRITORY),
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.25, 0.10,
        required_source_capabilities=frozenset(("surface_survey",)),
        display_name="無人地表探査",
    )
    local_geology = SurveyObservationModeSpec(
        "local_geology_measurement", 9.0, SurveyReachSpec(SurveyReachScope.LOCATION_TERRITORY),
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.15, 0.04,
        required_source_capabilities=frozenset(("surface_survey",)),
        display_name="地表地質精密測定",
    )
    fleet_remote = SurveyObservationModeSpec(
        "fleet_remote_mapping", 6.0, SurveyReachSpec(SurveyReachScope.SAME_BODY),
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.22, 0.08,
        required_source_capabilities=frozenset(("survey_sensor",)),
        minimum_source_units=1,
        display_name="機動遠隔マッピング",
    )
    deep_space_remote = SurveyObservationModeSpec(
        "interplanetary_remote_spectrometry", 2.0,
        SurveyReachSpec(SurveyReachScope.SAME_SYSTEM, max_characteristic_distance_km=1_000_000_000.0),
        KnowledgeLevel.PRESENCE_PROBABILITY, 0.65, 0.35,
        required_source_capabilities=frozenset(("survey_sensor",)),
        display_name="惑星間遠隔分光観測",
    )
    return {
        ids.LUNAR_RESOURCE_SURVEY_ORBITER: SurveyProviderSpec(
            ids.LUNAR_RESOURCE_SURVEY_ORBITER, SurveyProviderSourceKind.FACILITY,
            ids.LUNAR_RESOURCE_SURVEY_ORBITER, (remote_orbital, deep_space_remote),
        ),
        ids.ROBOTIC_SURVEY_PACKAGE: SurveyProviderSpec(
            ids.ROBOTIC_SURVEY_PACKAGE, SurveyProviderSourceKind.FACILITY,
            ids.ROBOTIC_SURVEY_PACKAGE, (local_robotic,),
        ),
        ids.ROBOTIC_GEOLOGY_STATION: SurveyProviderSpec(
            ids.ROBOTIC_GEOLOGY_STATION, SurveyProviderSourceKind.FACILITY,
            ids.ROBOTIC_GEOLOGY_STATION, (local_geology,),
        ),
        ids.LUNAR_FLEET_SURVEY_PROVIDER: SurveyProviderSpec(
            ids.LUNAR_FLEET_SURVEY_PROVIDER, SurveyProviderSourceKind.FLEET,
            ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT, (fleet_remote,),
        ),
    }


def build_extraction_specs() -> dict:
    return {
        ids.MINERAL_QUARRY: ExtractionSpec(
            ids.MINERAL_QUARRY, ids.MINERAL_FEEDSTOCK, ids.MINERAL_FEEDSTOCK, 2.4,
            req.SURFACE_SITE, "crust_accessibility", "terrain_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ids.METAL_ORE_MINE: ExtractionSpec(
            ids.METAL_ORE_MINE, ids.METAL_ORE, ids.METAL_ORE, 1.7,
            req.SURFACE_SITE, "crust_accessibility", "bearing_capacity_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ids.INDUSTRIAL_WATER_INTAKE: ExtractionSpec(
            ids.INDUSTRIAL_WATER_INTAKE, ids.WATER, ids.WATER, 1.0,
            req.ATMOSPHERIC_SURFACE_SITE, "crust_accessibility", "terrain_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ids.VOLATILE_EXTRACTOR: ExtractionSpec(
            ids.VOLATILE_EXTRACTOR, ids.VOLATILE_BEARING_MATERIAL, ids.VOLATILE_BEARING_MATERIAL, 6.0,
            req.COLD_VOLATILE_SURFACE_SITE, "regolith_accessibility", "bearing_capacity_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ids.VACUUM_MINERAL_HARVESTER: ExtractionSpec(
            ids.VACUUM_MINERAL_HARVESTER, ids.MINERAL_FEEDSTOCK, ids.MINERAL_FEEDSTOCK, 8.0,
            req.VACUUM_SURFACE_SITE, "regolith_accessibility", "terrain_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
    }
