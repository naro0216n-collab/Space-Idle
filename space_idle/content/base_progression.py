from __future__ import annotations

from ..survey import ExtractionSpec, SurveyProviderSpec, SurveyTarget
from . import base_ids as ids


_EARTH_SURVEY_THRESHOLDS = (1.0, 2.0, 3.0, 4.0)
_LUNAR_SURVEY_THRESHOLDS = (20.0, 60.0, 120.0, 220.0)


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
    return {
        ids.ROBOTIC_SURVEY_PACKAGE: SurveyProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, 5.0),
        ids.ROBOTIC_GEOLOGY_STATION: SurveyProviderSpec(ids.ROBOTIC_GEOLOGY_STATION, 9.0),
    }


def build_extraction_specs() -> dict:
    return {
        ids.SURFACE_AGGREGATE_QUARRY: ExtractionSpec(
            ids.SURFACE_AGGREGATE_QUARRY, ids.AGGREGATE, ids.AGGREGATE, 2.4
        ),
        ids.METAL_ORE_MINE: ExtractionSpec(
            ids.METAL_ORE_MINE, ids.METAL_ORE, ids.METAL_ORE, 1.7
        ),
        ids.INDUSTRIAL_WATER_INTAKE: ExtractionSpec(
            ids.INDUSTRIAL_WATER_INTAKE, ids.WATER, ids.WATER, 1.0
        ),
        ids.VOLATILE_EXTRACTOR: ExtractionSpec(
            ids.VOLATILE_EXTRACTOR, ids.WATER, ids.WATER, 6.0
        ),
        ids.REGOLITH_HARVESTER: ExtractionSpec(
            ids.REGOLITH_HARVESTER, ids.REGOLITH, ids.REGOLITH, 8.0
        ),
    }


def initial_known_surface_resource_knowledge() -> tuple[tuple, ...]:
    """Content-defined Surface Cell knowledge that is complete at game start."""
    return tuple(
        (cell_id, resource_id)
        for cell_id in (ids.EARTH_CELL_INDUSTRIAL, ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND)
        for resource_id in (ids.AGGREGATE, ids.METAL_ORE, ids.WATER)
    )
