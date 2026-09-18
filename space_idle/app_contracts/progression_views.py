from __future__ import annotations
from dataclasses import dataclass

from ..priority import ActivityPriority, ProvisioningPriority

from .catalog_views import SiteRequirementsDefinitionRow


@dataclass(frozen=True)
class ResearchSiteOptionRow:
    operational_node_id: str
    surface_cell_id: str | None
    blockers: tuple[tuple[str, str], ...]
    can_select: bool


@dataclass(frozen=True)
class ResearchExecutionSiteRow:
    operational_node_id: str
    surface_cell_id: str | None = None


@dataclass(frozen=True)
class ResearchProviderRow:
    id: str
    provider_definition_id: str
    source_kind: str
    source_definition_id: str
    operational_node_id: str
    tier: int
    level: int | None
    committed_units: int | None
    fleet_commitment_id: str | None
    paused: bool
    priority: ActivityPriority
    generation_points_per_day: float
    admitted_generation_points_per_day: float
    storage_capacity_points: float
    research_execution_per_day: float
    blockers: tuple[tuple[str, str], ...]
    can_pause: bool
    can_resume: bool
    can_resize: bool
    can_release: bool
    # Facility identity remains explicit for inspection links; Fleet rows use None.
    facility_id: str | None = None
    facility_definition_id: str | None = None


@dataclass(frozen=True)
class ResearchProviderAssignmentOptionRow:
    provider_definition_id: str
    source_definition_id: str
    operational_node_id: str
    tier: int
    free_units: int
    blockers: tuple[tuple[str, str], ...]
    can_create: bool


@dataclass(frozen=True)
class ResearchPrototypeResourceRow:
    resource_id: str
    required_t: float
    reserved_t: float
    requested_t: float
    allocated_t: float
    pipeline_t: float
    unmet_t: float


@dataclass(frozen=True)
class ResearchExperienceRow:
    category_id: str
    required: float
    current: float
    unmet: float


@dataclass(frozen=True)
class ResearchKnowledgeRow:
    category_id: str
    value: float


@dataclass(frozen=True)
class ResearchStageRow:
    stage_id: str
    stage_type: str


@dataclass(frozen=True)
class ResearchRow:
    id: str
    display_name: str
    status: str
    stages: tuple[ResearchStageRow, ...]
    current_stage_id: str | None
    current_stage_type: str | None
    paused: bool
    priority: ActivityPriority
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_set_priority: bool
    total_theory_research_point_cost: float
    stage_progress: float
    stage_required: float
    rp_requested: float
    rp_allocated: float
    rp_remaining: float
    execution_requested: float
    execution_allocated: float
    current_blockers: tuple[tuple[str, str], ...]
    start_blockers: tuple[tuple[str, str], ...]
    stage_resources: tuple[ResearchPrototypeResourceRow, ...]
    execution_context: ResearchExecutionSiteRow | None
    execution_context_options: tuple[ResearchSiteOptionRow, ...]
    operational_experience: tuple[ResearchExperienceRow, ...]
    prerequisites: tuple[str, ...]


@dataclass(frozen=True)
class ResearchView:
    stored_points: float
    storage_capacity_points: float
    generation_points_per_day: float
    admitted_generation_points_per_day: float
    over_capacity: bool
    providers: tuple[ResearchProviderRow, ...]
    provider_assignment_options: tuple[ResearchProviderAssignmentOptionRow, ...]
    knowledge: tuple[ResearchKnowledgeRow, ...]
    items: tuple[ResearchRow, ...]



@dataclass(frozen=True)
class ScientificExplorationFleetOptionRow:
    vehicle_definition_id: str
    display_name: str
    operational_node_id: str
    total_units: int
    free_units: int
    required_units: int
    blockers: tuple[str, ...]
    outbound_latency_days: int | None = None
    return_latency_days: int | None = None
    can_assign: bool = False


@dataclass(frozen=True)
class ScientificExplorationRow:
    id: str
    display_name: str
    status: str
    paused: bool
    priority: ActivityPriority
    can_set_priority: bool
    origin_id: str
    destination_id: str
    movement_operations: tuple[tuple[str, float], ...]
    outbound_latency_days: int | None
    return_latency_days: int | None
    origin_requirements: SiteRequirementsDefinitionRow
    destination_requirements: SiteRequirementsDefinitionRow
    duration_days: float
    progress_days: float
    research_points_total: float
    research_points_per_day: float
    research_points_awarded: float
    rp_admission_headroom: float
    rp_requested_today: float
    rp_admitted_today: float
    rp_admission_blocker: str | None
    consumable_resources: tuple[tuple[str, float], ...]
    required_units: int
    minimum_payload_t: float
    required_vehicle_capabilities: tuple[str, ...]
    assigned_vehicle_definition_id: str | None
    fleet_commitment_id: str | None
    committed_units: int
    completion_disposition: str
    transition_options: tuple[str, ...]
    blockers: tuple[str, ...]
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_unassign: bool
    fleet_options: tuple[ScientificExplorationFleetOptionRow, ...]


@dataclass(frozen=True)
class ScientificExplorationsView:
    items: tuple[ScientificExplorationRow, ...]



@dataclass(frozen=True)
class SurveyProviderAssignmentRow:
    id: str
    provider_definition_id: str
    source_definition_id: str
    operational_node_id: str
    committed_units: int
    fleet_commitment_id: str
    capacity_units_per_day: float
    can_resize: bool
    can_release: bool


@dataclass(frozen=True)
class SurveyProviderAssignmentOptionRow:
    provider_definition_id: str
    source_definition_id: str
    operational_node_id: str
    free_units: int
    can_create: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class SurveyStartOption:
    provider_operational_node_id: str
    provider_definition_id: str
    provider_source_kind: str
    observation_mode_id: str
    target_knowledge_level: int
    max_knowledge_level: int
    survey_rate: float
    capacity_points_per_day: float
    estimate_uncertainty_fraction: float
    measurement_precision_fraction: float
    minimum_source_units: int
    blockers: tuple[str, ...]
    can_start: bool


@dataclass(frozen=True)
class SurveyRow:
    cell_id: str
    body_id: str
    cell_label: str
    location_id: str | None
    resource_id: str
    resource_name: str
    active: bool
    provider_operational_node_id: str | None
    provider_definition_id: str | None
    provider_source_kind: str | None
    observation_mode_id: str | None
    complete: bool
    paused: bool
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_set_priority: bool
    progress: float
    progress_fraction: float
    target_knowledge_level: int
    target_threshold: float
    priority: ActivityPriority
    requested_service_points_per_day: float
    allocated_service_points_per_day: float
    knowledge_level: int
    presence_probability: float | None
    visible_potential: float | None
    visible_potential_precision_fraction: float | None
    capacity_points_per_day: float
    blockers: tuple[str, ...]
    start_options: tuple[SurveyStartOption, ...] = ()


@dataclass(frozen=True)
class SurveysView:
    provider_assignments: tuple[SurveyProviderAssignmentRow, ...]
    provider_assignment_options: tuple[SurveyProviderAssignmentOptionRow, ...]
    items: tuple[SurveyRow, ...]


@dataclass(frozen=True)
class ContractRow:
    id: str
    template_id: str
    display_name: str
    status: str
    deadline_day: int
    target_operational_node_id: str | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ContractsView:
    items: tuple[ContractRow, ...]
