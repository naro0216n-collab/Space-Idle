from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .shared import DefinitionId, SpatialNodeId

KnowledgeLevel = Literal[0, 1, 2, 3, 4]

@dataclass(frozen=True)
class SurveyTarget:
    location_id: SpatialNodeId
    resource_id: DefinitionId
    actual_concentration: float
    reserve_t: float
    thresholds: tuple[float, float, float, float]
    prior_presence_probability: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.actual_concentration <= 1.0:
            raise ValueError("survey concentration must be within 0..1")
        if self.reserve_t < 0:
            raise ValueError("survey reserve must be non-negative")
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
    location_id: SpatialNodeId
    resource_id: DefinitionId
    progress: float = 0.0
    allocation_weight: float = 1.0
    paused: bool = False

@dataclass(frozen=True)
class ExtractionSpec:
    facility_def_id: DefinitionId
    deposit_resource_id: DefinitionId
    output_resource_id: DefinitionId
    excavated_t_per_day: float
    min_knowledge_level: int = 3

@dataclass(frozen=True)
class ExtractionSnapshot:
    facility_id: object
    facility_def_id: DefinitionId
    output_resource_id: DefinitionId
    scale: float
    output_t_per_day: float
    limiting_factors: tuple[str, ...]
