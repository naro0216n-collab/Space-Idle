from __future__ import annotations
from dataclasses import dataclass
from .project_views import FacilityUpgradeOption, ProjectRow


@dataclass(frozen=True)
class InventoryRow:
    resource_id: str
    display_name: str
    unit: str
    amount: float
    reserved: float
    available: float
    storage_class: str | None
    physical_capacity: float | None
    service_capacity: float | None
    free_capacity: float | None


@dataclass(frozen=True)
class StorageRow:
    storage_class: str
    stock_t: float
    staging_t: float
    physical_capacity_t: float
    service_capacity_t: float
    free_service_t: float
    unserviced_occupied_t: float


@dataclass(frozen=True)
class FacilityRow:
    id: str
    definition_id: str
    display_name: str
    level: int
    paused: bool
    active_and_site_compatible: bool
    activation_blockers: tuple[tuple[str, str], ...]
    power_priority: int | None
    maintenance_priority: int
    capabilities: tuple[tuple[str, float], ...]
    power_utilization: float
    research_tier: int | None
    research_generation_points_per_day: float
    research_storage_capacity_points: float
    next_upgrade: FacilityUpgradeOption | None
    invested_resources: tuple[tuple[str, float], ...] = ()
    maintenance_demand_per_day: tuple[tuple[str, float], ...] = ()
    maintenance_satisfaction: float = 1.0
    operational_utilization: float = 1.0
    operating_blockers: tuple[tuple[str, str], ...] = ()
    placement_scope: str = "LOCATION"
    site_cell_id: str | None = None


@dataclass(frozen=True)
class CapabilityRow:
    id: str
    infrastructure_capacity: float
    active_capacity: float
    available_capacity: float


@dataclass(frozen=True)
class SurfaceInfrastructureLoadRow:
    code: str
    demand: float


@dataclass(frozen=True)
class SurfaceInfrastructureRow:
    nominal_capacity: float
    available_capacity: float
    demand: float
    fulfillment: float
    load_sources: tuple[SurfaceInfrastructureLoadRow, ...]
    limiting_factors: tuple[str, ...]
    improvement_facility_definition_ids: tuple[str, ...]


@dataclass(frozen=True)
class IndustryRow:
    facility_id: str
    facility_definition_id: str
    display_name: str
    process_id: str | None
    process_display_name: str | None
    process_options: tuple[tuple[str, str], ...]
    scale: float
    limiting_factors: tuple[str, ...]
    input_rates_per_day: tuple[tuple[str, float], ...]
    output_rates_per_day: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class EnvironmentFacetRow:
    key: str
    values: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class ExtractionRow:
    facility_id: str
    facility_definition_id: str
    display_name: str
    resource_id: str
    resource_name: str
    output_resource_id: str
    output_resource_name: str
    nominal_capacity_t_per_day: float
    effective_opportunity: float
    marginal_efficiency: float
    scale: float
    output_t_per_day: float
    limiting_factors: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionResourceRow:
    resource_id: str
    resource_name: str
    effective_opportunity: float
    installed_nominal_capacity_t_per_day: float
    operational_fulfillment: float
    diminishing_efficiency: float
    marginal_efficiency: float
    output_t_per_day: float


@dataclass(frozen=True)
class LocationView:
    id: str
    display_name: str
    day: int
    environment: tuple[EnvironmentFacetRow, ...]
    power_generation_mw: float
    power_demand_mw: float
    power_allocated_mw: float
    construction_capacity_per_day: float
    capabilities: tuple[CapabilityRow, ...]
    surface_infrastructure: SurfaceInfrastructureRow | None
    inventory: tuple[InventoryRow, ...]
    storage: tuple[StorageRow, ...]
    facilities: tuple[FacilityRow, ...]
    industry: tuple[IndustryRow, ...]
    extraction: tuple[ExtractionRow, ...]
    extraction_resources: tuple[ExtractionResourceRow, ...]
    projects: tuple[ProjectRow, ...]
