from __future__ import annotations

from ..survey import (
    ExtractionSpec, KnowledgeLevel, SurveyCoverage, SurveyObservationModeSpec,
    SurveyProviderSourceKind, SurveyProviderSpec, SurveyTarget,
)
from . import base_requirements as req
from . import base_ids as ids


_EARTH_SURVEY_THRESHOLDS = (1.0, 2.0, 3.0)
_LUNAR_SURVEY_THRESHOLDS = (20.0, 60.0, 120.0)


def build_survey_targets() -> dict:
    """Content-defined geological knowledge targets keyed by Surface Cell × Resource."""
    targets = {}
    for cell_id in (ids.EARTH_CELL_INDUSTRIAL, ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND):
        for resource_id in (ids.AGGREGATE, ids.METAL_ORE, ids.WATER):
            targets[(cell_id, resource_id)] = SurveyTarget(
                cell_id, resource_id, _EARTH_SURVEY_THRESHOLDS, 0.99
            )

    lunar_presence = {
        ids.MOON_CELL_SOUTH_POLAR_RIDGE: {ids.WATER: 0.55, ids.REGOLITH: 0.99},
        ids.MOON_CELL_POLAR_COLD_TRAP: {ids.WATER: 0.90, ids.REGOLITH: 0.99},
        ids.MOON_CELL_SOUTH_POLAR_PLAIN: {ids.WATER: 0.35, ids.REGOLITH: 0.99},
        ids.MOON_CELL_NEARSIDE_MARE: {ids.WATER: 0.08, ids.REGOLITH: 0.99},
        ids.MOON_CELL_EQUATORIAL_HIGHLANDS: {ids.WATER: 0.12, ids.REGOLITH: 0.99},
        ids.MOON_CELL_FARSIDE_HIGHLANDS: {ids.WATER: 0.15, ids.REGOLITH: 0.99},
    }
    for cell_id, probabilities in lunar_presence.items():
        for resource_id, probability in probabilities.items():
            targets[(cell_id, resource_id)] = SurveyTarget(
                cell_id, resource_id, _LUNAR_SURVEY_THRESHOLDS, probability
            )
    return targets


def build_survey_providers() -> dict:
    remote_orbital = SurveyObservationModeSpec(
        "remote_orbital_spectrometry", 8.0, SurveyCoverage.BODY_REMOTE,
        KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL, 0.35, 0.12,
        required_source_capabilities=frozenset(("survey_sensor",)),
    )
    local_robotic = SurveyObservationModeSpec(
        "local_robotic_prospecting", 5.0, SurveyCoverage.LOCATION_TERRITORY,
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.25, 0.10,
        required_source_capabilities=frozenset(("surface_survey",)),
    )
    local_geology = SurveyObservationModeSpec(
        "local_geology_measurement", 9.0, SurveyCoverage.LOCATION_TERRITORY,
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.15, 0.04,
        required_source_capabilities=frozenset(("surface_survey",)),
    )
    fleet_remote = SurveyObservationModeSpec(
        "fleet_remote_mapping", 6.0, SurveyCoverage.BODY_REMOTE,
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, 0.22, 0.08,
        required_source_capabilities=frozenset(("survey_sensor",)),
        required_fleet_units=1,
    )
    return {
        ids.LUNAR_RESOURCE_SURVEY_ORBITER: SurveyProviderSpec(
            ids.LUNAR_RESOURCE_SURVEY_ORBITER, SurveyProviderSourceKind.FACILITY,
            ids.LUNAR_RESOURCE_SURVEY_ORBITER, (remote_orbital,),
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
        ids.SURFACE_AGGREGATE_QUARRY: ExtractionSpec(
            ids.SURFACE_AGGREGATE_QUARRY, ids.AGGREGATE, ids.AGGREGATE, 2.4,
            req.SURFACE_SITE, "crust_accessibility", "terrain_factor",
        ),
        ids.METAL_ORE_MINE: ExtractionSpec(
            ids.METAL_ORE_MINE, ids.METAL_ORE, ids.METAL_ORE, 1.7,
            req.SURFACE_SITE, "crust_accessibility", "bearing_capacity_factor",
        ),
        ids.INDUSTRIAL_WATER_INTAKE: ExtractionSpec(
            ids.INDUSTRIAL_WATER_INTAKE, ids.WATER, ids.WATER, 1.0,
            req.ATMOSPHERIC_SURFACE_SITE, "crust_accessibility", "terrain_factor",
        ),
        ids.VOLATILE_EXTRACTOR: ExtractionSpec(
            ids.VOLATILE_EXTRACTOR, ids.WATER, ids.WATER, 6.0,
            req.COLD_VOLATILE_SURFACE_SITE, "regolith_accessibility", "bearing_capacity_factor",
        ),
        ids.REGOLITH_HARVESTER: ExtractionSpec(
            ids.REGOLITH_HARVESTER, ids.REGOLITH, ids.REGOLITH, 8.0,
            req.VACUUM_SURFACE_SITE, "regolith_accessibility", "terrain_factor",
        ),
    }
