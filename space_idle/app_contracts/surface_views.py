from __future__ import annotations

from dataclasses import dataclass

from .ui_reports import DecisionConstraintRow
from .location_views import EnvironmentFacetRow
from .ui_reports import ComparisonAxisRow, ComparisonValueRow
from .project_views import BuildResourceOption, BuildProcessOptionRow, BuildResearchCapacityRow, BuildSurveyProviderRow


@dataclass(frozen=True)
class SurfaceResourceKnowledgeRow:
    resource_id: str
    resource_name: str
    knowledge_level: int
    presence_probability: float | None
    visible_potential: float | None
    visible_potential_precision_fraction: float | None




@dataclass(frozen=True)
class SurfaceFacilityPlacementOption:
    facility_definition_id: str
    display_name: str
    location_id: str
    construction_required: float
    self_deploying: bool
    resources: tuple[BuildResourceOption, ...]
    blockers: tuple[DecisionConstraintRow, ...]
    can_plan: bool
    procurement_policy_options: tuple[str, ...] = ()
    projected_material_readiness_day: int | None = None
    capabilities: tuple[str, ...] = ()
    service_capacity_supplies: tuple[tuple[str, float], ...] = ()
    process_options: tuple[BuildProcessOptionRow, ...] = ()
    power_nominal_generation_mw: float | None = 0.0
    power_nominal_load_mw: float | None = 0.0
    power_nominal_standby_load_mw: float = 0.0
    process_nominal_throughput_per_day: float | None = None
    extraction_nominal_capacity_t_per_day: float | None = None
    maintenance_rates_per_day: tuple[tuple[str, float], ...] = ()
    housing_capacity: int = 0
    life_support_person_days_per_day: float = 0.0
    life_support_net_resources_per_person_day: tuple[tuple[str, float], ...] = ()
    research_capacity: BuildResearchCapacityRow | None = None
    survey_providers: tuple[BuildSurveyProviderRow, ...] = ()
    site_knowledge_unverified: bool = False


@dataclass(frozen=True)
class FoundingDeployedFacilityRow:
    facility_definition_id: str
    display_name: str
    nominal_power_generation_mw: float | None
    nominal_power_load_mw: float | None
    storage_capacity_t: tuple[tuple[str, float], ...]
    service_capacity_per_day: tuple[tuple[str, float], ...]
    construction_work_per_day: float
    maintenance_fraction_per_year: float
    nominal_power_standby_load_mw: float = 0.0


@dataclass(frozen=True)
class FoundingOption:
    staging_node_id: str
    deployment_recipe_id: str
    recipe_display_name: str
    vehicle_definition_id: str
    vehicle_display_name: str
    preparation_work: float
    transit_days: int | None
    payload_t: float
    payload_t_per_unit: float
    required_units: int
    resources: tuple[tuple[str, float], ...]
    blockers: tuple[DecisionConstraintRow, ...]
    can_plan: bool
    active_project_id: str | None = None
    comparison_key: str = ""
    comparison_values: tuple[ComparisonValueRow, ...] = ()
    deployed_facilities: tuple[FoundingDeployedFacilityRow, ...] = ()
    site_knowledge_unverified: bool = False


@dataclass(frozen=True)
class SurfaceCellDevelopmentOption:
    location_id: str
    blockers: tuple[DecisionConstraintRow, ...]
    can_plan: bool
    projected_surface_infrastructure_demand: float | None = None
    projected_surface_infrastructure_fulfillment: float | None = None
    limiting_factors: tuple[DecisionConstraintRow, ...] = ()
    construction_required: float | None = None
    resources: tuple[tuple[str, float], ...] = ()
    active_project_id: str | None = None
    procurement_policy_options: tuple[str, ...] = ()
    site_knowledge_unverified: bool = False


@dataclass(frozen=True)
class SurfaceCellRow:
    id: str
    body_id: str
    area_km2: float
    latitude_deg: float
    longitude_deg: float
    neighbor_ids: tuple[str, ...]
    terrain: tuple[tuple[str, float | str], ...]
    environment: tuple[EnvironmentFacetRow, ...]
    resources: tuple[SurfaceResourceKnowledgeRow, ...]
    developed: bool
    location_id: str | None
    is_location_core: bool
    foundation_blockers: tuple[DecisionConstraintRow, ...]
    development_options: tuple[SurfaceCellDevelopmentOption, ...]
    engineering_options: tuple[SurfaceCellDevelopmentOption, ...] = ()
    facility_placement_options: tuple[SurfaceFacilityPlacementOption, ...] = ()
    foundation_options: tuple[FoundingOption, ...] = ()
    display_name: str = ""
    terrain_knowledge_level: int = 0
    environment_knowledge_level: int = 0
    movement_accessible: bool | None = None
    minimum_transit_days: int | None = None


@dataclass(frozen=True)
class SurfaceLocationTerritoryRow:
    id: str
    display_name: str
    body_id: str
    core_cell_id: str
    developed_cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceMapView:
    body_id: str
    display_name: str
    cells: tuple[SurfaceCellRow, ...]
    locations: tuple[SurfaceLocationTerritoryRow, ...]
    founding_comparison_axes: tuple[ComparisonAxisRow, ...] = ()
    physical_surface: str = "solid"


@dataclass(frozen=True)
class NonSurfaceFoundingContextRow:
    spatial_node_id: str
    display_name: str
    kind: str
    operational: bool
    foundation_options: tuple[FoundingOption, ...]


@dataclass(frozen=True)
class NonSurfaceFoundingView:
    body_id: str
    contexts: tuple[NonSurfaceFoundingContextRow, ...]
