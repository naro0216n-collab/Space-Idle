from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .shared import DefinitionId, SpatialNodeId, SurfaceCellId

KnowledgeLevel = Literal[0, 1, 2, 3, 4]


@dataclass(frozen=True)
class SurveyTarget:
    cell_id: SurfaceCellId
    resource_id: DefinitionId
    thresholds: tuple[float, float, float, float]
    prior_presence_probability: float = 0.5

    def __post_init__(self) -> None:
        if len(self.thresholds) != 4 or any(v < 0 for v in self.thresholds):
            raise ValueError("survey target requires four non-negative knowledge thresholds")
        if tuple(sorted(self.thresholds)) != self.thresholds:
            raise ValueError("survey knowledge thresholds must be sorted")
        if not 0.0 <= self.prior_presence_probability <= 1.0:
            raise ValueError("survey presence probability must be within 0..1")


@dataclass(frozen=True)
class SurveyProviderSpec:
    facility_def_id: DefinitionId
    points_per_day: float


@dataclass
class SurveyCampaign:
    provider_location_id: SpatialNodeId
    cell_id: SurfaceCellId
    resource_id: DefinitionId
    allocation_weight: float = 1.0
    paused: bool = False


@dataclass(frozen=True)
class ExtractionSpec:
    facility_def_id: DefinitionId
    resource_id: DefinitionId
    output_resource_id: DefinitionId
    nominal_capacity_t_per_day: float

    def __post_init__(self) -> None:
        if self.nominal_capacity_t_per_day < 0:
            raise ValueError("nominal extraction capacity must be non-negative")


@dataclass(frozen=True)
class ExtractionResourceSnapshot:
    resource_id: DefinitionId
    effective_opportunity: float
    installed_nominal_capacity_t_per_day: float
    operational_fulfillment: float
    diminishing_efficiency: float
    marginal_efficiency: float
    output_t_per_day: float


@dataclass(frozen=True)
class ExtractionSnapshot:
    facility_id: object
    facility_def_id: DefinitionId
    resource_id: DefinitionId
    output_resource_id: DefinitionId
    nominal_capacity_t_per_day: float
    effective_opportunity: float
    marginal_efficiency: float
    scale: float
    output_t_per_day: float
    limiting_factors: tuple[str, ...]
