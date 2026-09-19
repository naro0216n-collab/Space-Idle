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
    storage_pool_key: str


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


@dataclass(frozen=True)
class ProcessDefinitionRow:
    id: str
    display_name: str
    facility_definition_id: str
    inputs_per_day: tuple[tuple[str, float], ...]
    outputs_per_day: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ResearchStageDefinitionRow:
    stage_id: str
    stage_type: str
    required_progress: float | None
    resources: tuple[tuple[str, float], ...] = ()
    site_requirements: SiteRequirementsDefinitionRow = SiteRequirementsDefinitionRow()
    operational_experience: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class ResearchDefinitionRow:
    id: str
    display_name: str
    prerequisites: tuple[str, ...]
    stages: tuple[ResearchStageDefinitionRow, ...]


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


@dataclass(frozen=True)
class OperationalNodeDefinitionRow:
    id: str
    display_name: str
    parent_id: str | None
    body_id: str | None
    kind: str


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
