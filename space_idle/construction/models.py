from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from enum import Enum

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
    """A material that may replace part of an imported component requirement.

    Eligibility is carried by the material itself, not by a facility located at
    the construction site. This allows one industrial node to manufacture a
    material and another node to consume it after logistics has moved the stock.
    """

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
    facility_def_id: DefinitionId
    components: tuple[BuildComponentRequirement, ...]
    construction_work: float
    site_requirements: SiteRequirements = SiteRequirements()
    prerequisite_technologies: frozenset[DefinitionId] = frozenset()
    self_deploying: bool = False

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
    reserved_local_t: float = 0.0
    reserved_local_resource_id: DefinitionId | None = None
    reserved_import_t: float = 0.0
    committed_local_t: float = 0.0
    committed_local_resource_id: DefinitionId | None = None
    committed_import_t: float = 0.0
    local_target_t: float = 0.0
    import_committed_t: float | None = None
    import_order_id: CargoOrderId | None = None

@dataclass
class BuildProject:
    id: ProjectId
    facility_def_id: DefinitionId
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
    # Optional player target for local substitution, expressed as a fraction of
    # the component mass. Absence means the sourcing policy chooses the default.
    local_fraction_targets: dict[str, float] = field(default_factory=dict)
    local_resource_choices: dict[str, DefinitionId] = field(default_factory=dict)
    materials_committed: bool = False
    installed_facility_id: EntityId | None = None

@dataclass(frozen=True)
class ProjectBlocker:
    code: str
    detail: str
