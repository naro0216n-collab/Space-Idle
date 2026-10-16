from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RequirementConditionRow:
    kind: str
    code: str
    description: str
    parameters: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class CapabilityRequirementRow:
    capability_id: str
    required_state: str


@dataclass(frozen=True)
class SiteRequirementsDefinitionRow:
    environment: tuple[RequirementConditionRow, ...] = ()
    capabilities: tuple[CapabilityRequirementRow, ...] = ()
    spatial_classifications: tuple[RequirementConditionRow, ...] = ()


@dataclass(frozen=True)
class OperationCapabilityDefinitionRow:
    operation_type: str
    parameters: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class ResourceDefinitionRow:
    id: str
    display_name: str
    unit: str
    category: str
    storage_pool_key: str | None


@dataclass(frozen=True)
class ResearchProviderDefinitionRow:
    id: str
    tier: int
    generation_points_per_day: float
    research_execution_per_day: float
    storage_capacity_points: float
    crew_person_days_per_research_point: float = 0.0


@dataclass(frozen=True)
class FacilityDesignCoefficientsRow:
    # Domain-owned technical values; GUI Catalog and development evaluation share
    # this exact definition projection, rather than independently traversing Core.
    construction_resources_t: tuple[tuple[str, float], ...] | None
    construction_work: float | None
    self_deploying: bool | None
    prerequisites: tuple[str, ...]
    maintenance_per_day_t: tuple[tuple[str, float], ...] | None
    operating_per_day_t: tuple[tuple[str, float], ...]
    process_throughput_per_day: float
    construction_work_per_day: float
    power_load_mw: float
    power_generation_kind: str
    power_reference_generation_mw: float
    extraction_capacity_t_per_day: float
    housing_capacity: int
    life_support_person_days_per_day: float | None
    life_support_resources_per_person_day_t: tuple[tuple[str, float], ...]
    research_provider: ResearchProviderDefinitionRow | None


@dataclass(frozen=True)
class ExtractionMethodDefinitionRow:
    id: str
    display_name: str
    resource_id: str
    output_resource_id: str
    prerequisites: tuple[str, ...]
    provider_facilities: tuple[str, ...]


@dataclass(frozen=True)
class FacilityDefinitionRow:
    id: str
    display_name: str
    capabilities: tuple[str, ...]
    service_capacity_supplies: tuple[tuple[str, float], ...] = ()
    installation_requirements: SiteRequirementsDefinitionRow = SiteRequirementsDefinitionRow()
    operating_requirements: SiteRequirementsDefinitionRow = SiteRequirementsDefinitionRow()
    maintenance_fraction_per_year: float = 0.0
    placement_scope: str = "OPERATIONAL_NODE"
    design: FacilityDesignCoefficientsRow | None = None


@dataclass(frozen=True)
class ProcessDefinitionRow:
    id: str
    display_name: str
    required_capabilities: tuple[str, ...]
    inputs_per_day: tuple[tuple[str, float], ...]
    outputs_per_day: tuple[tuple[str, float], ...]
    prerequisites: tuple[str, ...] = ()
    provider_facilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchStageDefinitionRow:
    stage_id: str
    stage_type: str
    required_progress: float | None
    resources: tuple[tuple[str, float], ...] = ()
    site_requirements: SiteRequirementsDefinitionRow = SiteRequirementsDefinitionRow()
    operational_experience: tuple[tuple[str, float], ...] = ()
    execution_requirements: tuple[tuple[tuple[str, object], ...], ...] = ()


@dataclass(frozen=True)
class ResearchDefinitionRow:
    id: str
    display_name: str
    prerequisites: tuple[str, ...]
    stages: tuple[ResearchStageDefinitionRow, ...]
    progression_stage: int | None = None
    category: str | None = None
    series: str | None = None


@dataclass(frozen=True)
class VehicleDefinitionRow:
    id: str
    display_name: str
    concept: str
    dry_mass_t: float
    payload_t: float
    endurance_days: float | None
    propellant_capacity_t: float
    propellant_resource_id: str | None
    capabilities: tuple[str, ...]
    operation_support_requirements: tuple[tuple[str, str, str], ...]
    production_service_type: str | None
    production_days: float
    production_resources: tuple[tuple[str, float], ...]
    turnaround_service_type: str | None
    turnaround_days: float
    turnaround_resources: tuple[tuple[str, float], ...]
    operation_capability_details: tuple[OperationCapabilityDefinitionRow, ...] = ()
    research_providers: tuple[ResearchProviderDefinitionRow, ...] = ()


@dataclass(frozen=True)
class MovementPlanDefinitionRow:
    id: str
    display_name: str
    origin_id: str
    destination_id: str
    transit_days: int
    delta_v_km_s: float
    operations: tuple[tuple[str, float], ...]
    origin_requirements: SiteRequirementsDefinitionRow
    destination_requirements: SiteRequirementsDefinitionRow


@dataclass(frozen=True)
class CelestialBodyDefinitionRow:
    id: str
    display_name: str
    star_system_id: str | None = None
    parent_body_id: str | None = None
    physical_surface: str = "solid"
    surface_cell_count: int = 0
    mean_radius_km: float | None = None
    reference_gravity_m_s2: float | None = None
    heliocentric_semimajor_axis_au: float | None = None
    parent_orbit_semimajor_axis_km: float | None = None
    representative_solar_flux_w_m2: float | None = None


@dataclass(frozen=True)
class OperationalNodeDefinitionRow:
    id: str
    display_name: str
    parent_id: str | None
    body_id: str | None
    kind: str


@dataclass(frozen=True)
class ServiceCapacityDefinitionRow:
    id: str
    display_name: str


@dataclass(frozen=True)
class CatalogView:
    resources: tuple[ResourceDefinitionRow, ...]
    facilities: tuple[FacilityDefinitionRow, ...]
    vehicles: tuple[VehicleDefinitionRow, ...]
    celestial_bodies: tuple[CelestialBodyDefinitionRow, ...]
    operational_nodes: tuple[OperationalNodeDefinitionRow, ...]
    processes: tuple[ProcessDefinitionRow, ...] = ()
    research: tuple[ResearchDefinitionRow, ...] = ()
    movement_plans: tuple[MovementPlanDefinitionRow, ...] = ()
    service_capacities: tuple[ServiceCapacityDefinitionRow, ...] = ()
    extraction_methods: tuple[ExtractionMethodDefinitionRow, ...] = ()


@dataclass(frozen=True)
class OperationalNodeSummary:
    id: str
    display_name: str
    parent_id: str | None
    body_id: str | None
    kind: str
    facility_count: int
    active_project_count: int
    active_founding_count: int = 0


@dataclass(frozen=True)
class WorldView:
    content_id: str
    day: int
    funds_musd: float
    operational_nodes: tuple[OperationalNodeSummary, ...]


@dataclass(frozen=True)
class DevelopmentWorldReferenceView:
    # Physical Content-only world statistics, never a Player knowledge disclosure.
    surface_resource_distribution: dict[str, dict]
