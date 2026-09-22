from __future__ import annotations
from dataclasses import dataclass

from .ui_reports import DecisionConstraintRow
from ..priority import ActivityPriority, ProvisioningPriority

from .catalog_views import SiteRequirementsDefinitionRow
from .ui_reports import ComparisonAxisRow, ComparisonValueRow


@dataclass(frozen=True)
class ResearchSiteOptionRow:
    operational_node_id: str
    surface_cell_id: str | None
    blockers: tuple[DecisionConstraintRow, ...]
    can_select: bool
    comparison_key: str = ""
    comparison_values: tuple[ComparisonValueRow, ...] = ()


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
    blockers: tuple[DecisionConstraintRow, ...]
    can_pause: bool
    can_resume: bool
    # Facility identity remains explicit for inspection links; Fleet rows use None.
    facility_id: str | None = None
    facility_definition_id: str | None = None


@dataclass(frozen=True)
class ResearchProviderFleetRow:
    provider_definition_id: str
    vehicle_definition_id: str
    operational_node_id: str
    tier: int
    assignment_id: str | None
    committed_units: int
    free_units: int
    max_units: int
    blockers: tuple[DecisionConstraintRow, ...]
    can_set_quantity: bool


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
class ResearchUnlockRow:
    kind: str
    id: str
    display_name: str
    remaining_prerequisite_ids: tuple[str, ...] = ()


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
    current_blockers: tuple[DecisionConstraintRow, ...]
    start_blockers: tuple[DecisionConstraintRow, ...]
    stage_resources: tuple[ResearchPrototypeResourceRow, ...]
    execution_context: ResearchExecutionSiteRow | None
    execution_context_options: tuple[ResearchSiteOptionRow, ...]
    execution_context_comparison_axes: tuple[ComparisonAxisRow, ...]
    operational_experience: tuple[ResearchExperienceRow, ...]
    prerequisites: tuple[str, ...]
    progression_stage: int | None = None
    category: str | None = None
    series: str | None = None
    unlocks: tuple[ResearchUnlockRow, ...] = ()


@dataclass(frozen=True)
class ResearchView:
    stored_points: float
    storage_capacity_points: float
    generation_points_per_day: float
    admitted_generation_points_per_day: float
    over_capacity: bool
    providers: tuple[ResearchProviderRow, ...]
    provider_fleet: tuple[ResearchProviderFleetRow, ...]
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
    blockers: tuple[DecisionConstraintRow, ...]
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
    rp_admission_blocker: DecisionConstraintRow | None
    consumable_resources: tuple[tuple[str, float], ...]
    required_units: int
    minimum_payload_t: float
    required_vehicle_capabilities: tuple[str, ...]
    assigned_vehicle_definition_id: str | None
    fleet_commitment_id: str | None
    committed_units: int
    completion_disposition: str
    transition_options: tuple[str, ...]
    termination_intent: str | None
    blockers: tuple[DecisionConstraintRow, ...]
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_abort: bool
    can_return: bool
    can_set_completion_disposition: bool
    can_unassign: bool
    fleet_options: tuple[ScientificExplorationFleetOptionRow, ...]


@dataclass(frozen=True)
class ScientificExplorationsView:
    items: tuple[ScientificExplorationRow, ...]



@dataclass(frozen=True)
class SurveyProviderFleetRow:
    provider_definition_id: str
    provider_display_name: str
    vehicle_definition_id: str
    operational_node_id: str
    committed_units: int
    free_units: int
    max_units: int
    capacity_units_per_day: float
    blockers: tuple[DecisionConstraintRow, ...]
    can_set_quantity: bool


@dataclass(frozen=True)
class SurveyCandidateRow:
    comparison_key: str
    provider_operational_node_id: str
    provider_definition_id: str
    provider_display_name: str
    provider_source_kind: str
    source_definition_id: str
    observation_mode_id: str
    observation_mode_display_name: str
    survey_rate: float
    max_knowledge_level: int
    estimate_uncertainty_fraction: float
    measurement_precision_fraction: float
    minimum_source_units: int
    assigned_source_units: int
    capacity_units_per_day: float
    matches_constraints: bool
    viable: bool
    blockers: tuple[DecisionConstraintRow, ...]
    comparison_values: tuple[ComparisonValueRow, ...]


@dataclass(frozen=True)
class SurveyCampaignTargetRow:
    cell_id: str
    resource_id: str
    current_knowledge_level: int
    goal_knowledge_level: int
    progress: float
    target_threshold: float
    complete: bool


@dataclass(frozen=True)
class SurveyCampaignRow:
    id: str
    status: str
    paused: bool
    priority: ActivityPriority
    target_cell_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    goal_knowledge_level: int
    provider_constraint_definition_id: str | None
    provider_constraint_operational_node_id: str | None
    observation_mode_constraint: str | None
    projected_provider_definition_id: str | None
    projected_provider_display_name: str | None
    projected_provider_operational_node_id: str | None
    projected_observation_mode_id: str | None
    projected_observation_mode_display_name: str | None
    observation_mode_constraint_display_name: str | None
    covered_targets: int
    remaining_targets: int
    requested_service_units_per_day: float
    allocated_service_units_per_day: float
    capacity_points_per_day: float
    projected_remaining_days: float | None
    required_fleet_units: int | None
    assigned_fleet_units: int | None
    blockers: tuple[DecisionConstraintRow, ...]
    can_pause: bool
    can_resume: bool
    can_set_priority: bool
    targets: tuple[SurveyCampaignTargetRow, ...]
    candidates: tuple[SurveyCandidateRow, ...]
    comparison_axes: tuple[ComparisonAxisRow, ...]


@dataclass(frozen=True)
class SurveyRow:
    cell_id: str
    body_id: str
    cell_label: str
    location_id: str | None
    resource_id: str
    resource_name: str
    progress: float
    knowledge_level: int
    presence_probability: float | None
    visible_potential: float | None
    visible_potential_precision_fraction: float | None


@dataclass(frozen=True)
class SurveyCampaignIntentPreviewView:
    target_cell_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    goal_knowledge_level: int
    campaign_id: str | None
    blockers: tuple[DecisionConstraintRow, ...]
    can_apply: bool


@dataclass(frozen=True)
class SurveysView:
    provider_fleet: tuple[SurveyProviderFleetRow, ...]
    items: tuple[SurveyRow, ...]
    campaigns: tuple[SurveyCampaignRow, ...]


@dataclass(frozen=True)
class ContractRow:
    id: str
    template_id: str
    display_name: str
    status: str
    deadline_day: int
    target_operational_node_id: str | None
    blockers: tuple[DecisionConstraintRow, ...]


@dataclass(frozen=True)
class ContractsView:
    items: tuple[ContractRow, ...]
