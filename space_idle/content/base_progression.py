from __future__ import annotations

from ..spatial import SpatialGraph
from ..survey import (
    ExtractionSpec, KnowledgeLevel, SurveyReachScope, SurveyReachSpec, SurveyObservationModeSpec,
    SurveyProviderSourceKind, SurveyProviderSpec, SurveyTarget,
)
from . import base_requirements as req
from . import base_ids as ids
from ..shared import DefinitionId


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
        prerequisite_technologies=frozenset({DefinitionId("SS-SENSING-02")}),
    )
    return {
        ids.SURFACE_PROSPECTOR_SURVEY_PROVIDER: SurveyProviderSpec(
            ids.SURFACE_PROSPECTOR_SURVEY_PROVIDER, SurveyProviderSourceKind.FLEET,
            frozenset({"robotic_prospecting_sensor"}),
            (SurveyObservationModeSpec(
                "mobile_surface_geology", 6.0,
                SurveyReachSpec(SurveyReachScope.LOCATION_TERRITORY),
                KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.20, 0.08,
                required_source_capabilities=frozenset({"robotic_prospecting_sensor"}),
                display_name="探査車地質測定",
            ),),
        ),
        ids.RADAR_MAPPING_SURVEY_PROVIDER: SurveyProviderSpec(
            ids.RADAR_MAPPING_SURVEY_PROVIDER, SurveyProviderSourceKind.FLEET,
            frozenset({"radar_sounder"}),
            (SurveyObservationModeSpec(
                "orbital_radar_sounding", 7.0,
                SurveyReachSpec(SurveyReachScope.SAME_BODY),
                KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.28, 0.07,
                required_source_capabilities=frozenset({"radar_sounder"}),
                display_name="軌道レーダー地下探査",
            ),),
        ),
        ids.ROBOTIC_SURVEY_PACKAGE: SurveyProviderSpec(
            ids.ROBOTIC_SURVEY_PACKAGE, SurveyProviderSourceKind.FACILITY,
            frozenset({"surface_survey", "robotic_prospecting_kit"}), (local_robotic,),
        ),
        ids.ROBOTIC_GEOLOGY_STATION: SurveyProviderSpec(
            ids.ROBOTIC_GEOLOGY_STATION, SurveyProviderSourceKind.FACILITY,
            frozenset({"surface_survey", "robotic_geology_equipment"}), (local_geology,),
        ),
        ids.LUNAR_FLEET_SURVEY_PROVIDER: SurveyProviderSpec(
            ids.LUNAR_FLEET_SURVEY_PROVIDER, SurveyProviderSourceKind.FLEET,
            frozenset({"survey_sensor"}),
            (remote_orbital, fleet_remote, deep_space_remote),
        ),
    }


def build_extraction_specs() -> dict:
    methods = (
        ExtractionSpec(
            ids.EXTRACTION_CRUST_MINERAL, frozenset({"mineral_extraction"}),
            ids.MINERAL_FEEDSTOCK, ids.MINERAL_FEEDSTOCK,
            req.SURFACE_SITE, "crust_accessibility", "terrain_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ExtractionSpec(
            ids.EXTRACTION_CRUST_ORE, frozenset({"metal_ore_extraction"}),
            ids.METAL_ORE, ids.METAL_ORE,
            req.SURFACE_SITE, "crust_accessibility", "bearing_capacity_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ExtractionSpec(
            ids.EXTRACTION_WATER_INTAKE, frozenset({"industrial_water_supply"}),
            ids.WATER, ids.WATER,
            req.ATMOSPHERIC_SURFACE_SITE, "crust_accessibility", "terrain_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ExtractionSpec(
            ids.EXTRACTION_COLD_VOLATILES, frozenset({"volatile_extraction"}),
            ids.VOLATILE_BEARING_MATERIAL, ids.VOLATILE_BEARING_MATERIAL,
            req.COLD_VOLATILE_SURFACE_SITE, "regolith_accessibility", "bearing_capacity_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
        ExtractionSpec(
            ids.EXTRACTION_VACUUM_GRANULAR, frozenset({"granular_mineral_extraction"}),
            ids.MINERAL_FEEDSTOCK, ids.MINERAL_FEEDSTOCK,
            req.VACUUM_SURFACE_SITE, "regolith_accessibility", "terrain_factor",
            minimum_knowledge_level=KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL,
        ),
    )
    return {method.id: method for method in methods}
