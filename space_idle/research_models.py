from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .shared import DefinitionId, SpatialNodeId
from .site import SiteRequirements


@dataclass(frozen=True)
class ResearchPrototypeSpec:
    resources: dict[DefinitionId, float]
    site_requirements: SiteRequirements = SiteRequirements()

    def __post_init__(self) -> None:
        if any(amount < 0 for amount in self.resources.values()):
            raise ValueError("prototype resource amounts must be non-negative")


@dataclass(frozen=True)
class ResearchDemonstrationSpec:
    days: int
    site_requirements: SiteRequirements = SiteRequirements()

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError("research demonstration duration must be positive")


@dataclass(frozen=True)
class ResearchDefinition:
    id: DefinitionId
    display_name: str
    research_point_cost: float
    prerequisites: frozenset[DefinitionId] = frozenset()
    prototype: ResearchPrototypeSpec | None = None
    demonstration: ResearchDemonstrationSpec | None = None

    def __post_init__(self) -> None:
        if self.research_point_cost < 0:
            raise ValueError("research point cost must be non-negative")


@dataclass(frozen=True)
class ResearchProviderLevelSpec:
    level: int
    generation_points_per_day: float
    storage_capacity_points: float

    def __post_init__(self) -> None:
        if self.level < 1:
            raise ValueError("research provider level must be positive")
        if self.generation_points_per_day < 0:
            raise ValueError("research provider generation must be non-negative")
        if self.storage_capacity_points < 0:
            raise ValueError("research provider storage must be non-negative")


@dataclass(frozen=True)
class ResearchProviderSpec:
    facility_def_id: DefinitionId
    tier: int
    levels: tuple[ResearchProviderLevelSpec, ...]

    def __post_init__(self) -> None:
        if self.tier < 1:
            raise ValueError("research provider tier must be positive")
        if not self.levels:
            raise ValueError("research provider must define at least one level")
        seen: set[int] = set()
        for level in self.levels:
            if level.level in seen:
                raise ValueError(f"duplicate research provider level: {level.level}")
            seen.add(level.level)

    def level_spec(self, level: int) -> ResearchProviderLevelSpec:
        for spec in self.levels:
            if spec.level == level:
                return spec
        raise ValueError(f"research provider does not define level {level}")


class ResearchPhase(str, Enum):
    PROTOTYPE = "prototype"
    DEMONSTRATION = "demonstration"
    COMPLETE = "complete"


@dataclass
class ResearchState:
    definition_id: DefinitionId
    status: ResearchPhase
    demonstration_done_days: int = 0
    paused: bool = False
    prototype_location_id: SpatialNodeId | None = None
    demonstration_location_id: SpatialNodeId | None = None
