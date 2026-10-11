from __future__ import annotations
from dataclasses import dataclass

from .ui_reports import DecisionConstraintRow
from ..priority import ActivityPriority, ProvisioningPriority


@dataclass(frozen=True)
class ProjectResourceRow:
    resource_id: str
    required_t: float
    reserved_t: float
    staged_t: float
    committed_t: float
    shortage_t: float
    requirement_id: str | None


@dataclass(frozen=True)
class BuildResourceOption:
    resource_id: str
    required_t: float
    available_t: float = 0.0
    projected_source_id: str | None = None
    projected_arrival_day: int | None = None


@dataclass(frozen=True)
class BuildProcessOptionRow:
    process_id: str
    display_name: str
    # Nominal mass flows at the candidate facility's installed throughput.
    # Actual execution remains bounded by allocation, upkeep and storage.
    input_rates_per_day: tuple[tuple[str, float], ...]
    output_rates_per_day: tuple[tuple[str, float], ...]
    missing_technology_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildOptionRow:
    facility_definition_id: str | None
    display_name: str
    construction_required: float
    self_deploying: bool
    resources: tuple[BuildResourceOption, ...]
    blockers: tuple[DecisionConstraintRow, ...]
    can_plan: bool
    capabilities: tuple[str, ...] = ()
    service_capacity_supplies: tuple[tuple[str, float], ...] = ()
    process_options: tuple[BuildProcessOptionRow, ...] = ()
    placement_scope: str = "OPERATIONAL_NODE"
    projected_material_readiness_day: int | None = None
    power_nominal_generation_mw: float = 0.0
    power_nominal_load_mw: float = 0.0
    process_nominal_throughput_per_day: float | None = None
    extraction_nominal_capacity_t_per_day: float | None = None


@dataclass(frozen=True)
class FacilityUpgradeDifferenceRow:
    kind: str
    label: str
    current_value: float | str
    target_value: float | str
    unit: str | None = None


@dataclass(frozen=True)
class FacilityUpgradeOption:
    target_level: int
    construction_required: float
    resources: tuple[BuildResourceOption, ...]
    blockers: tuple[DecisionConstraintRow, ...]
    can_plan: bool
    active_project_id: str | None
    differences: tuple[FacilityUpgradeDifferenceRow, ...] = ()
    unchanged_aspects: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildOptionsView:
    operational_node_id: str
    procurement_policy_options: tuple[str, ...]
    items: tuple[BuildOptionRow, ...]


@dataclass(frozen=True)
class ProjectKnowledgeRequirementRow:
    target_cell_id: str
    subject_resource_id: str
    minimum_level: int
    current_level: int
    met: bool


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
    procurement_policy: str
    settings_editable: bool
    procurement_editable: bool
    procurement_policy_options: tuple[str, ...]
    construction_done: float
    construction_required: float
    materials_committed: bool
    completed_facility_id: str | None
    resources: tuple[ProjectResourceRow, ...]
    blockers: tuple[DecisionConstraintRow, ...]
    site_cell_id: str | None = None
    target_cell_id: str | None = None
    target_body_id: str | None = None
    target_location_id: str | None = None
    construction_fulfillment: float = 1.0
    limiting_factors: tuple[DecisionConstraintRow, ...] = ()
    projected_material_readiness_day: int | None = None
    irreversible_started: bool = False
    expected_salvage: tuple[tuple[str, float], ...] = ()
    projected_salvage_fraction: float | None = None
    projected_salvage: tuple[tuple[str, float], ...] = ()
    actual_salvage_fraction: float | None = None
    actual_salvage: tuple[tuple[str, float], ...] = ()
    founding_target_type: str | None = None
    founding_knowledge_requirements: tuple[ProjectKnowledgeRequirementRow, ...] = ()
    fleet_commitment_id: str | None = None
    manifest_ready: bool | None = None
    deployment_phase: str | None = None
    site_blockers: tuple[DecisionConstraintRow, ...] = ()
    movement_blockers: tuple[DecisionConstraintRow, ...] = ()


@dataclass(frozen=True)
class ProjectsView:
    items: tuple[ProjectRow, ...]
