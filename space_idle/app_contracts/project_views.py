from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectResourceRow:
    resource_id: str
    required_t: float
    reserved_t: float
    committed_t: float
    shortage_t: float
    import_committed_t: float | None
    demand_id: str | None


@dataclass(frozen=True)
class BuildResourceOption:
    resource_id: str
    required_t: float


@dataclass(frozen=True)
class BuildOptionRow:
    facility_definition_id: str
    display_name: str
    construction_required: float
    self_deploying: bool
    resources: tuple[BuildResourceOption, ...]
    missing_technologies: tuple[str, ...]
    site_blockers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FacilityUpgradeOption:
    target_level: int
    construction_required: float
    resources: tuple[BuildResourceOption, ...]
    missing_technologies: tuple[str, ...]
    site_blockers: tuple[tuple[str, str], ...]
    active_project_id: str | None


@dataclass(frozen=True)
class BuildOptionsView:
    location_id: str
    sourcing_policy_options: tuple[str, ...]
    import_source_options: tuple[str, ...]
    items: tuple[BuildOptionRow, ...]


@dataclass(frozen=True)
class ProjectRow:
    id: str
    target_kind: str
    location_id: str
    facility_definition_id: str
    target_facility_id: str | None
    target_level: int | None
    display_name: str
    status: str
    paused: bool
    priority: int
    sourcing_policy: str
    import_source_id: str | None
    settings_editable: bool
    sourcing_editable: bool
    sourcing_policy_options: tuple[str, ...]
    import_source_options: tuple[str, ...]
    construction_done: float
    construction_required: float
    construction_weight: float
    materials_committed: bool
    completed_facility_id: str | None
    resources: tuple[ProjectResourceRow, ...]
    blockers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ProjectsView:
    items: tuple[ProjectRow, ...]
