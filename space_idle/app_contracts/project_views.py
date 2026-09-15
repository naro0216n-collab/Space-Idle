from __future__ import annotations
from dataclasses import dataclass

from ..priority import ActivityPriority, ProvisioningPriority


@dataclass(frozen=True)
class ProjectResourceRow:
    resource_id: str
    required_t: float
    reserved_t: float
    staged_t: float
    committed_t: float
    shortage_t: float
    import_committed_t: float | None
    requirement_id: str | None


@dataclass(frozen=True)
class BuildResourceOption:
    resource_id: str
    required_t: float


@dataclass(frozen=True)
class BuildOptionRow:
    facility_definition_id: str | None
    display_name: str
    construction_required: float
    self_deploying: bool
    resources: tuple[BuildResourceOption, ...]
    blockers: tuple[tuple[str, str], ...]
    can_plan: bool


@dataclass(frozen=True)
class FacilityUpgradeOption:
    target_level: int
    construction_required: float
    resources: tuple[BuildResourceOption, ...]
    blockers: tuple[tuple[str, str], ...]
    can_plan: bool
    active_project_id: str | None


@dataclass(frozen=True)
class BuildOptionsView:
    operational_node_id: str
    sourcing_policy_options: tuple[str, ...]
    import_source_options: tuple[str, ...]
    items: tuple[BuildOptionRow, ...]


@dataclass(frozen=True)
class ProjectRow:
    id: str
    target_kind: str
    operational_node_id: str
    facility_definition_id: str | None
    target_facility_id: str | None
    target_level: int | None
    display_name: str
    status: str
    paused: bool
    priority: ActivityPriority
    sourcing_policy: str
    import_source_id: str | None
    settings_editable: bool
    sourcing_editable: bool
    sourcing_policy_options: tuple[str, ...]
    import_source_options: tuple[str, ...]
    construction_done: float
    construction_required: float
    materials_committed: bool
    completed_facility_id: str | None
    resources: tuple[ProjectResourceRow, ...]
    blockers: tuple[tuple[str, str], ...]
    site_cell_id: str | None = None
    target_cell_id: str | None = None
    target_body_id: str | None = None
    target_location_id: str | None = None
    construction_fulfillment: float = 1.0
    limiting_factors: tuple[str, ...] = ()
    projected_material_readiness_day: int | None = None


@dataclass(frozen=True)
class ProjectsView:
    items: tuple[ProjectRow, ...]
