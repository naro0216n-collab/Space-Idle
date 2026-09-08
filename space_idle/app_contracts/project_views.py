from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectComponentRow:
    component_id: str
    required_t: float
    import_resource_id: str
    local_target_t: float
    reserved_local_t: float
    reserved_import_t: float
    committed_local_t: float
    committed_import_t: float
    import_committed_t: float | None
    import_order_id: str | None
    local_fraction_target: float | None
    selected_local_resource_id: str | None
    local_resource_selection_explicit: bool
    max_local_fraction_available: float


@dataclass(frozen=True)
class BuildComponentOption:
    component_id: str
    required_t: float
    import_resource_id: str
    local_substitutions: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class BuildOptionRow:
    facility_definition_id: str
    display_name: str
    construction_required: float
    self_deploying: bool
    components: tuple[BuildComponentOption, ...]
    missing_technologies: tuple[str, ...]
    site_blockers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FacilityUpgradeOption:
    target_level: int
    construction_required: float
    components: tuple[BuildComponentOption, ...]
    missing_technologies: tuple[str, ...]
    site_blockers: tuple[tuple[str, str], ...]
    active_project_id: str | None


@dataclass(frozen=True)
class BuildOptionsView:
    location_id: str
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
    import_path: tuple[str, ...] | None
    import_route_modes: tuple[tuple[str, str], ...]
    construction_done: float
    construction_required: float
    construction_weight: float
    materials_committed: bool
    completed_facility_id: str | None
    components: tuple[ProjectComponentRow, ...]
    blockers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ProjectsView:
    items: tuple[ProjectRow, ...]
