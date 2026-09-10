from __future__ import annotations

from ..survey import ExtractionSpec, SurveyProviderSpec, SurveyTarget
from . import base_ids as ids


def build_survey_targets() -> dict:
    return {
        (ids.EARTH, ids.AGGREGATE): SurveyTarget(ids.EARTH, ids.AGGREGATE, 0.90, 250000.0, (1.0, 2.0, 3.0, 4.0), 0.99),
        (ids.EARTH, ids.METAL_ORE): SurveyTarget(ids.EARTH, ids.METAL_ORE, 0.55, 120000.0, (1.0, 2.0, 3.0, 4.0), 0.99),
        (ids.EARTH, ids.WATER): SurveyTarget(ids.EARTH, ids.WATER, 1.0, 500000.0, (1.0, 2.0, 3.0, 4.0), 0.99),
        (ids.POLAR_COLD_TRAP, ids.WATER): SurveyTarget(ids.POLAR_COLD_TRAP, ids.WATER, 0.08, 1500.0, (20.0, 60.0, 120.0, 220.0), 0.90),
        (ids.SOUTH_POLAR_RIDGE, ids.WATER): SurveyTarget(ids.SOUTH_POLAR_RIDGE, ids.WATER, 0.012, 180.0, (20.0, 60.0, 120.0, 220.0), 0.55),
        (ids.NEARSIDE_MARE, ids.WATER): SurveyTarget(ids.NEARSIDE_MARE, ids.WATER, 0.0, 0.0, (20.0, 60.0, 120.0, 220.0), 0.08),
        (ids.POLAR_COLD_TRAP, ids.REGOLITH): SurveyTarget(ids.POLAR_COLD_TRAP, ids.REGOLITH, 0.92, 10000.0, (20.0, 60.0, 120.0, 220.0), 0.99),
        (ids.SOUTH_POLAR_RIDGE, ids.REGOLITH): SurveyTarget(ids.SOUTH_POLAR_RIDGE, ids.REGOLITH, 0.95, 10000.0, (20.0, 60.0, 120.0, 220.0), 0.99),
        (ids.NEARSIDE_MARE, ids.REGOLITH): SurveyTarget(ids.NEARSIDE_MARE, ids.REGOLITH, 0.97, 10000.0, (20.0, 60.0, 120.0, 220.0), 0.99),
    }


def build_survey_providers() -> dict:
    return {
        ids.ROBOTIC_SURVEY_PACKAGE: SurveyProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, 5.0),
        ids.ROBOTIC_GEOLOGY_STATION: SurveyProviderSpec(ids.ROBOTIC_GEOLOGY_STATION, 9.0),
    }


def build_extraction_specs() -> dict:
    return {
        ids.SURFACE_AGGREGATE_QUARRY: ExtractionSpec(ids.SURFACE_AGGREGATE_QUARRY, ids.AGGREGATE, ids.AGGREGATE, 2.4, 3),
        ids.METAL_ORE_MINE: ExtractionSpec(ids.METAL_ORE_MINE, ids.METAL_ORE, ids.METAL_ORE, 1.7, 3),
        ids.INDUSTRIAL_WATER_INTAKE: ExtractionSpec(ids.INDUSTRIAL_WATER_INTAKE, ids.WATER, ids.WATER, 1.0, 3),
        ids.VOLATILE_EXTRACTOR: ExtractionSpec(ids.VOLATILE_EXTRACTOR, ids.WATER, ids.WATER, 6.0, 3),
        ids.REGOLITH_HARVESTER: ExtractionSpec(ids.REGOLITH_HARVESTER, ids.REGOLITH, ids.REGOLITH, 8.0, 2),
    }


def initial_known_deposits() -> tuple[tuple, ...]:
    """Content-defined deposits whose knowledge is complete at game start."""
    return (
        (ids.EARTH, ids.AGGREGATE),
        (ids.EARTH, ids.METAL_ORE),
        (ids.EARTH, ids.WATER),
    )
