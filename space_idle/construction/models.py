from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypeAlias

from ..shared import CargoOrderId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from ..site import SiteRequirements

SourcingPolicy = Literal["import_now", "mixed", "local_priority"]


class ProjectStatus(str, Enum):
    PLANNED = "planned"
    PROCURING = "procuring"
    READY = "ready"
    BUILDING = "building"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class LocalSubstitutionTier:
    """A material that may replace part of an imported component requirement."""

    local_resource_id: DefinitionId
    max_fraction: float


@dataclass(frozen=True)
class BuildComponentRequirement:
    component_id: str
    amount_t: float
    import_resource_id: DefinitionId
    local_tiers: tuple[LocalSubstitutionTier, ...] = ()


@dataclass(frozen=True)
class ConstructionRecipe:
    """Requirements for creating one new facility instance."""

    facility_def_id: DefinitionId
    components: tuple[BuildComponentRequirement, ...]
    construction_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False


@dataclass(frozen=True)
class FacilityUpgradeRecipe:
    """Requirements for advancing one facility definition to a specific level."""

    facility_def_id: DefinitionId
    target_level: int
    components: tuple[BuildComponentRequirement, ...]
    construction_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False

    def __post_init__(self) -> None:
        if self.target_level < 2:
            raise ValueError("facility upgrade target level must be at least 2")
        if self.self_deploying:
            raise ValueError("facility upgrades cannot be self-deploying")


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
class ProjectComponentState:
    # Substitutes are content-selected alternatives to the standard component.
    reserved_local_t: float = 0.0
    reserved_local_resource_id: DefinitionId | None = None
    # Standard components already present at the construction site are neither
    # substitutions nor imports and are tracked separately.
    reserved_primary_t: float = 0.0
    reserved_import_t: float = 0.0
    committed_local_t: float = 0.0
    committed_local_resource_id: DefinitionId | None = None
    committed_primary_t: float = 0.0
    committed_import_t: float = 0.0
    local_target_t: float = 0.0
    import_committed_t: float | None = None
    import_order_id: CargoOrderId | None = None


@dataclass
class ConstructionProject:
    id: ProjectId
    target: ConstructionTarget
    location_id: SpatialNodeId
    priority: int
    sourcing_policy: SourcingPolicy
    import_source_id: SpatialNodeId | None
    import_path: tuple[RouteId, ...] | None = None
    import_mode_by_route: dict[RouteId, str] = field(default_factory=dict)
    status: ProjectStatus = ProjectStatus.PLANNED
    procurement_started_day: int | None = None
    construction_done: float = 0.0
    construction_weight: float = 1.0
    paused: bool = False
    pause_started_day: int | None = None
    components: dict[str, ProjectComponentState] = field(default_factory=dict)
    local_fraction_targets: dict[str, float] = field(default_factory=dict)
    local_resource_choices: dict[str, DefinitionId] = field(default_factory=dict)
    materials_committed: bool = False
    completed_facility_id: EntityId | None = None


@dataclass(frozen=True)
class ProjectBlocker:
    code: str
    detail: str
