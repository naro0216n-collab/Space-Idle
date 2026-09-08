from __future__ import annotations
from dataclasses import dataclass
from .project_views import ProjectRow

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
    capabilities: tuple[tuple[str, float], ...]
    power_utilization: float

@dataclass(frozen=True)
class CapabilityRow:
    id: str
    infrastructure_capacity: float
    active_capacity: float
    available_capacity: float

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
    output_resource_id: str
    output_resource_name: str
    scale: float
    output_t_per_day: float
    limiting_factors: tuple[str, ...]

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
    inventory: tuple[InventoryRow, ...]
    storage: tuple[StorageRow, ...]
    facilities: tuple[FacilityRow, ...]
    industry: tuple[IndustryRow, ...]
    extraction: tuple[ExtractionRow, ...]
    projects: tuple[ProjectRow, ...]
