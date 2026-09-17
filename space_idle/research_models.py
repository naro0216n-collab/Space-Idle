from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .execution_requirements import ExecutionRequirement
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements


class ResearchStage(str, Enum):
    THEORY = "theory"
    PROTOTYPE = "prototype"
    DEMONSTRATION = "demonstration"
    OPERATIONAL_EXPERIENCE = "operational_experience"


@dataclass(frozen=True)
class ResearchPrototypeSpec:
    resources: dict[DefinitionId, float]
    site_requirements: SiteRequirements = SiteRequirements()
    execution_requirements: tuple[ExecutionRequirement, ...] = ()

    def __post_init__(self) -> None:
        if any(amount < 0 for amount in self.resources.values()):
            raise ValueError("prototype resource amounts must be non-negative")


@dataclass(frozen=True)
class ResearchDemonstrationSpec:
    days: int
    site_requirements: SiteRequirements = SiteRequirements()
    execution_requirements: tuple[ExecutionRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError("research demonstration duration must be positive")


@dataclass(frozen=True)
class ResearchOperationalExperienceSpec:
    requirements: dict[str, float]

    def __post_init__(self) -> None:
        if not self.requirements:
            raise ValueError("operational experience stage must define requirements")
        if any(not category for category in self.requirements):
            raise ValueError("operational experience category must not be empty")
        if any(amount < 0 for amount in self.requirements.values()):
            raise ValueError("operational experience requirements must be non-negative")


@dataclass(frozen=True)
class ResearchDefinition:
    id: DefinitionId
    display_name: str
    research_point_cost: float
    prerequisites: frozenset[DefinitionId] = frozenset()
    prototype: ResearchPrototypeSpec | None = None
    demonstration: ResearchDemonstrationSpec | None = None
    operational_experience: ResearchOperationalExperienceSpec | None = None
    stages: tuple[ResearchStage, ...] = ()

    def __post_init__(self) -> None:
        if self.research_point_cost < 0:
            raise ValueError("research point cost must be non-negative")
        if not self.stages:
            raise ValueError("research definition must explicitly define its stages")
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("research definition cannot repeat a stage")
        if ResearchStage.THEORY in self.stages and self.research_point_cost <= 0:
            raise ValueError("theory stage requires positive research point cost")
        if ResearchStage.THEORY not in self.stages and self.research_point_cost > 0:
            raise ValueError("research point cost requires a theory stage")
        if (ResearchStage.PROTOTYPE in self.stages) != (self.prototype is not None):
            raise ValueError("prototype stage and prototype definition must agree")
        if (ResearchStage.DEMONSTRATION in self.stages) != (self.demonstration is not None):
            raise ValueError("demonstration stage and demonstration definition must agree")
        if (ResearchStage.OPERATIONAL_EXPERIENCE in self.stages) != (
            self.operational_experience is not None
        ):
            raise ValueError("operational experience stage and definition must agree")


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


@dataclass(frozen=True)
class ResearchExecutionSite:
    operational_node_id: SpatialNodeId
    surface_cell_id: SurfaceCellId | None = None


@dataclass
class ResearchState:
    definition_id: DefinitionId
    stage: ResearchStage
    stage_progress: float = 0.0
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    paused: bool = False
    prototype_execution_site: ResearchExecutionSite | None = None
    demonstration_execution_site: ResearchExecutionSite | None = None
    stage_started_day: int = 0

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.stage_started_day < 0:
            raise ValueError("research stage start day must be non-negative")
