from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypeAlias

from ..priority import ActivityPriority
from ..shared import DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from ..site import SiteRequirements

CONSTRUCTION_SERVICE_TYPE = "construction_work"

# Procurement policy controls how long a project waits for inventory already at
# the destination before declaring an off-site Supply Requirement. It does not change the
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


@dataclass(frozen=True)
class FacilityDecommissionRecipe:
    """Physical work/resources needed to dismantle an installed facility."""

    facility_def_id: DefinitionId
    resources: tuple[BuildResourceRequirement, ...] = ()
    construction_work: float = 0.0
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False

    def __post_init__(self) -> None:
        if self.construction_work <= 0:
            raise ValueError("facility decommission work must be positive")
        if self.self_deploying:
            raise ValueError("facility decommission cannot self-deploy")


@dataclass(frozen=True)
class SpatialDevelopmentRecipe:
    """Physical inputs and work for expanding an established surface Location."""

    id: DefinitionId
    display_name: str
    resources: tuple[BuildResourceRequirement, ...]
    construction_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False
    minimum_survey_knowledge_level: int = 0

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("spatial development recipe display name must not be empty")
        if self.self_deploying:
            raise ValueError("location development must consume construction capacity")
        if not 0 <= self.minimum_survey_knowledge_level <= 4:
            raise ValueError("spatial development survey knowledge level must be within 0..4")


ProjectRecipe: TypeAlias = (
    ConstructionRecipe | FacilityUpgradeRecipe | FacilityDecommissionRecipe | SpatialDevelopmentRecipe
)


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


@dataclass(frozen=True)
class FacilityDecommissionTarget:
    facility_id: EntityId
    facility_definition_id: DefinitionId


@dataclass(frozen=True)
class SurfaceCellDevelopmentTarget:
    recipe_id: DefinitionId
    cell_id: SurfaceCellId


ConstructionTarget: TypeAlias = (
    NewFacilityTarget | FacilityUpgradeTarget | FacilityDecommissionTarget | SurfaceCellDevelopmentTarget
)


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
    """Mutable accounting for a recipe resource at the build host Operational Node."""

    committed_t: float = 0.0
    # None while the project is still waiting for host inventory. Once set,
    # logistics may satisfy the remaining physical shortage from lanes.
    import_committed_t: float | None = None


@dataclass
class ConstructionProject:
    id: ProjectId
    target: ConstructionTarget
    # Existing operational Location/Node that owns procurement and supplies
    # construction flow. For surface-cell development this is the Location being
    # expanded; for founding it is the explicit staging/provider Operational Node.
    operational_node_id: SpatialNodeId
    priority: ActivityPriority
    sourcing_policy: SourcingPolicy
    status: ProjectStatus = ProjectStatus.PLANNED
    procurement_started_day: int | None = None
    construction_done: float = 0.0
    paused: bool = False
    pause_started_day: int | None = None
    resources: dict[DefinitionId, ProjectResourceState] = field(default_factory=dict)
    materials_committed: bool = False
    completed_facility_id: EntityId | None = None
    irreversible_started: bool = False
    # Facility placement state only. Geographic project target cells live on
    # their target type so one cell never has two authoritative fields.
    site_cell_id: SurfaceCellId | None = None

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)


@dataclass(frozen=True)
class ProjectBlocker:
    code: str
    detail: str
