from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .execution_requirements import ExecutionRequirement, ServiceCapacityRequirement
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .service_capacity import ServiceCapacityScope
from .shared import DefinitionId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements


class ResearchStage(str, Enum):
    THEORY = "theory"
    PROTOTYPE = "prototype"
    DEMONSTRATION = "demonstration"
    OPERATIONAL_EXPERIENCE = "operational_experience"


@dataclass(frozen=True)
class ResearchTheoryStageSpec:
    stage_id: str
    research_point_cost: float
    execution_requirements: tuple[ExecutionRequirement, ...] = (
        ServiceCapacityRequirement(
            "research_execution", 1.0, scope=ServiceCapacityScope.ORGANIZATION
        ),
    )

    def __post_init__(self) -> None:
        if not self.stage_id:
            raise ValueError("research stage id must not be empty")
        if self.research_point_cost <= 0:
            raise ValueError("theory stage requires positive research point cost")

    @property
    def stage_type(self) -> ResearchStage:
        return ResearchStage.THEORY


@dataclass(frozen=True)
class ResearchPrototypeStageSpec:
    stage_id: str
    resources: dict[DefinitionId, float]
    site_requirements: SiteRequirements = SiteRequirements()
    execution_requirements: tuple[ExecutionRequirement, ...] = ()
    required_work: float = 1.0

    def __post_init__(self) -> None:
        if not self.stage_id:
            raise ValueError("research stage id must not be empty")
        if any(amount < 0 for amount in self.resources.values()):
            raise ValueError("prototype resource amounts must be non-negative")
        if self.required_work <= 0:
            raise ValueError("prototype required work must be positive")

    @property
    def stage_type(self) -> ResearchStage:
        return ResearchStage.PROTOTYPE


@dataclass(frozen=True)
class ResearchDemonstrationStageSpec:
    stage_id: str
    required_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    execution_requirements: tuple[ExecutionRequirement, ...] = ()

    def __post_init__(self) -> None:
        if not self.stage_id:
            raise ValueError("research stage id must not be empty")
        if self.required_work <= 0:
            raise ValueError("research demonstration work must be positive")

    @property
    def stage_type(self) -> ResearchStage:
        return ResearchStage.DEMONSTRATION


@dataclass(frozen=True)
class ResearchOperationalExperienceStageSpec:
    stage_id: str
    requirements: dict[str, float]

    def __post_init__(self) -> None:
        if not self.stage_id:
            raise ValueError("research stage id must not be empty")
        if not self.requirements:
            raise ValueError("operational experience stage must define requirements")
        if any(not category for category in self.requirements):
            raise ValueError("operational experience category must not be empty")
        if any(amount < 0 for amount in self.requirements.values()):
            raise ValueError("operational experience requirements must be non-negative")

    @property
    def stage_type(self) -> ResearchStage:
        return ResearchStage.OPERATIONAL_EXPERIENCE


ResearchStageSpec: TypeAlias = (
    ResearchTheoryStageSpec
    | ResearchPrototypeStageSpec
    | ResearchDemonstrationStageSpec
    | ResearchOperationalExperienceStageSpec
)


@dataclass(frozen=True)
class ResearchDefinition:
    id: DefinitionId
    display_name: str
    stage_specs: tuple[ResearchStageSpec, ...]
    prerequisites: frozenset[DefinitionId] = frozenset()

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("research display name must not be empty")
        if not self.stage_specs:
            raise ValueError("research definition must explicitly define its stages")
        ids = tuple(spec.stage_id for spec in self.stage_specs)
        if len(set(ids)) != len(ids):
            raise ValueError("research definition stage ids must be unique")

    def stage_spec(self, stage_id: str) -> ResearchStageSpec:
        for spec in self.stage_specs:
            if spec.stage_id == stage_id:
                return spec
        raise KeyError(stage_id)

    def next_stage_spec(self, stage_id: str) -> ResearchStageSpec | None:
        for index, spec in enumerate(self.stage_specs):
            if spec.stage_id != stage_id:
                continue
            return self.stage_specs[index + 1] if index + 1 < len(self.stage_specs) else None
        raise KeyError(stage_id)


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


class ResearchProviderSourceKind(str, Enum):
    FACILITY = "facility"
    FLEET = "fleet"


@dataclass(frozen=True)
class ResearchProviderSpec:
    id: DefinitionId
    source_kind: ResearchProviderSourceKind
    source_definition_id: DefinitionId
    tier: int
    levels: tuple[ResearchProviderLevelSpec, ...]
    fleet_units_per_level: int = 1

    def __post_init__(self) -> None:
        if self.tier < 1:
            raise ValueError("research provider tier must be positive")
        if not self.levels:
            raise ValueError("research provider must define at least one level")
        if self.fleet_units_per_level <= 0:
            raise ValueError("research provider fleet units per level must be positive")
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
    current_stage_id: str
    stage_progress: float | None = None
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    paused: bool = False
    execution_context: ResearchExecutionSite | None = None
    stage_started_day: int = 0

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if not self.current_stage_id:
            raise ValueError("research current stage id must not be empty")
        if self.stage_progress is not None and self.stage_progress < 0:
            raise ValueError("research stage progress must be non-negative")
        if self.stage_started_day < 0:
            raise ValueError("research stage start day must be non-negative")
