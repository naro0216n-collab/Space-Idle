from __future__ import annotations
from dataclasses import dataclass

from .catalog_views import SiteRequirementsDefinitionRow


@dataclass(frozen=True)
class ResearchSiteOptionRow:
    location_id: str
    blockers: tuple[tuple[str, str], ...]
    can_select: bool


@dataclass(frozen=True)
class ResearchProviderRow:
    facility_id: str
    facility_definition_id: str
    location_id: str
    tier: int
    level: int
    generation_points_per_day: float
    storage_capacity_points: float
    blockers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ResearchRow:
    id: str
    display_name: str
    status: str
    paused: bool
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_fund_prototype: bool
    research_point_cost: float
    current_blockers: tuple[tuple[str, str], ...]
    start_blockers: tuple[tuple[str, str], ...]
    prototype_resources: tuple[tuple[str, float], ...]
    prototype_location_id: str | None
    prototype_sites: tuple[ResearchSiteOptionRow, ...]
    demonstration_done_days: int
    demonstration_required_days: int
    demonstration_location_id: str | None
    demonstration_sites: tuple[ResearchSiteOptionRow, ...]
    demonstration_blockers: tuple[tuple[str, str], ...]
    prototype_blockers: tuple[tuple[str, str], ...]
    prerequisites: tuple[str, ...]


@dataclass(frozen=True)
class ResearchView:
    stored_points: float
    storage_capacity_points: float
    generation_points_per_day: float
    over_capacity: bool
    providers: tuple[ResearchProviderRow, ...]
    items: tuple[ResearchRow, ...]



@dataclass(frozen=True)
class ScientificExplorationFleetOptionRow:
    vehicle_definition_id: str
    display_name: str
    location_id: str
    total_units: int
    free_units: int
    required_units: int
    blockers: tuple[str, ...]
    can_assign: bool = False


@dataclass(frozen=True)
class ScientificExplorationRow:
    id: str
    display_name: str
    status: str
    paused: bool
    origin_id: str
    destination_id: str
    operations: tuple[tuple[str, float], ...]
    mission_duration_days: int
    origin_requirements: SiteRequirementsDefinitionRow
    destination_requirements: SiteRequirementsDefinitionRow
    duration_days: float
    progress_days: float
    research_points_total: float
    research_points_per_day: float
    research_points_awarded: float
    consumable_resources: tuple[tuple[str, float], ...]
    required_units: int
    minimum_payload_t: float
    required_vehicle_capabilities: tuple[str, ...]
    assigned_vehicle_definition_id: str | None
    reserved_units: int
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
class SurveyRow:
    cell_id: str
    body_id: str
    cell_label: str
    location_id: str | None
    resource_id: str
    resource_name: str
    active: bool
    provider_location_id: str | None
    complete: bool
    paused: bool
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_set_allocation: bool
    progress: float
    progress_fraction: float
    final_threshold: float
    default_allocation_weight: float
    allocation_weight: float
    knowledge_level: int
    presence_probability: float | None
    visible_potential: float | None
    visible_potential_precision_fraction: float | None
    capacity_points_per_day: float
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class SurveysView:
    items: tuple[SurveyRow, ...]


@dataclass(frozen=True)
class ContractRow:
    id: str
    template_id: str
    display_name: str
    status: str
    deadline_day: int
    reward_musd: float
    target_location_id: str | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ContractsView:
    items: tuple[ContractRow, ...]
