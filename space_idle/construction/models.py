from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypeAlias

from ..shared import DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from ..site import SiteRequirements

# Procurement policy controls how long a project waits for inventory already at
# the destination before declaring an import demand. It does not change the
# recipe or substitute one material for another.
SourcingPolicy = Literal["import_now", "mixed", "local_priority"]


class ProjectStatus(str, Enum):
    PLANNED = "planned"
    PROCURING = "procuring"
    READY = "ready"
    BUILDING = "building"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BuildResourceRequirement:
    """One physical resource consumed by construction or an upgrade."""

    resource_id: DefinitionId
    amount_t: float

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("construction resource amount must be positive")


@dataclass(frozen=True)
class ConstructionRecipe:
    """Physical resource and work requirements for a new facility instance."""

    facility_def_id: DefinitionId
    resources: tuple[BuildResourceRequirement, ...]
    construction_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False


@dataclass(frozen=True)
class FacilityUpgradeRecipe:
    """Physical resource and work requirements for one level transition."""

    facility_def_id: DefinitionId
    target_level: int
    resources: tuple[BuildResourceRequirement, ...]
    construction_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False

    def __post_init__(self) -> None:
        if self.target_level < 2:
            raise ValueError("facility upgrade target level must be at least 2")
        if self.self_deploying:
            raise ValueError("facility upgrades cannot self-deploy")


ProjectRecipe: TypeAlias = ConstructionRecipe | FacilityUpgradeRecipe


@dataclass(frozen=True)
class NewFacilityTarget:
    facility_def_id: DefinitionId


@dataclass(frozen=True)
class FacilityUpgradeTarget:
    facility_id: EntityId
    target_level: int

    def __post_init__(self) -> None:
        if self.target_level < 2:
            raise ValueError("facility upgrade target level must be at least 2")


ConstructionTarget: TypeAlias = NewFacilityTarget | FacilityUpgradeTarget


@dataclass(frozen=True)
class ConstructionProviderSpec:
    facility_def_id: DefinitionId
    work_per_day: float


@dataclass(frozen=True)
class ConstructionResourceProviderSpec:
    resource_id: DefinitionId
    work_per_t_per_day: float


@dataclass
class ProjectResourceState:
    """Mutable accounting for a recipe resource at the build destination."""

    committed_t: float = 0.0
    # None while the project is still waiting for destination inventory. Once
    # set, logistics may satisfy the remaining physical shortage from lanes.
    import_committed_t: float | None = None


@dataclass
class ConstructionProject:
    id: ProjectId
    target: ConstructionTarget
    location_id: SpatialNodeId
    priority: int
    sourcing_policy: SourcingPolicy
    import_source_id: SpatialNodeId | None
    status: ProjectStatus = ProjectStatus.PLANNED
    procurement_started_day: int | None = None
    construction_done: float = 0.0
    construction_weight: float = 1.0
    paused: bool = False
    pause_started_day: int | None = None
    resources: dict[DefinitionId, ProjectResourceState] = field(default_factory=dict)
    materials_committed: bool = False
    completed_facility_id: EntityId | None = None
    site_cell_id: SurfaceCellId | None = None


@dataclass(frozen=True)
class ProjectBlocker:
    code: str
    detail: str
