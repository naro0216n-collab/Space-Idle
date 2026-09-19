from __future__ import annotations
from dataclasses import dataclass

from ..priority import ActivityPriority, ProvisioningPriority


@dataclass(frozen=True)
class DirectionalCapacityRow:
    forward_t_per_day: float
    reverse_t_per_day: float


@dataclass(frozen=True)
class InfrastructureRequirementRow:
    operational_node_id: str
    capability_id: str
    required_state: str




@dataclass(frozen=True)
class MovementEndpointRow:
    node_id: str
    locator_kind: str
    locator_id: str
    surface_cell_id: str | None


@dataclass(frozen=True)
class MovementServiceModeRow:
    id: str
    display_name: str
    kind: str
    vehicle_definition_id: str | None
    fleet_total_units: int
    fleet_free_units: int
    nominal_capacity: DirectionalCapacityRow
    cycle_days: float | None
    forward_latency_days: int
    reverse_latency_days: int | None
    propellant_resource_id: str | None
    full_load_propellant_t: float | None
    service_feasible: bool
    infrastructure_requirements: tuple[InfrastructureRequirementRow, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class MovementPlanRow:
    id: str
    display_name: str
    origin_id: str
    destination_id: str
    origin_endpoint: MovementEndpointRow
    destination_endpoint: MovementEndpointRow
    same_body_surface: bool
    distance_km: float | None
    available: bool
    service_feasible_now: bool
    transit_days: int
    delta_v_km_s: float
    operations: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]
    modes: tuple[MovementServiceModeRow, ...]


@dataclass(frozen=True)
class FleetPoolRow:
    vehicle_definition_id: str
    display_name: str
    operational_node_id: str
    total_units: int
    free_units: int
    transport_units: int
    research_units: int
    survey_units: int
    exploration_units: int
    founding_units: int
    retirement_units: int
    other_committed_units: int
    relocating_units: int
    releasing_units: int


@dataclass(frozen=True)
class FleetCommitmentRow:
    id: str
    owner_activity_type: str
    owner_activity_id: str
    usage_kind: str
    vehicle_definition_id: str
    display_name: str
    quantity: int
    operational_node_id: str | None
    movement_execution_id: str | None


@dataclass(frozen=True)
class TransportAllocationRow:
    id: str
    vehicle_definition_id: str
    display_name: str
    anchor_node_id: str
    destination_id: str
    provisioning_priority: ProvisioningPriority
    target_capacity: DirectionalCapacityRow
    active_units: int
    required_units: int
    unfilled_units: int
    nominal: DirectionalCapacityRow
    available: DirectionalCapacityRow
    used: DirectionalCapacityRow
    spare: DirectionalCapacityRow
    utilization: float
    movement_hard_constraint: tuple[str, ...] | None
    selected_forward_path: tuple[str, ...]
    selected_reverse_path: tuple[str, ...]
    paused: bool
    cycle_days: float
    forward_latency_days: int
    reverse_latency_days: int | None
    operational_supply: tuple[tuple[str, str, float], ...]
    infrastructure_requirements: tuple[InfrastructureRequirementRow, ...]
    blockers: tuple[str, ...]
    limiting_factors: tuple[str, ...]


@dataclass(frozen=True)
class FleetRelocationRow:
    id: str
    vehicle_definition_id: str
    display_name: str
    units: int
    source_id: str
    destination_id: str
    departure_day: int | None
    arrival_day: int | None


@dataclass(frozen=True)
class FleetReleaseRow:
    id: str
    allocation_id: str
    vehicle_definition_id: str
    display_name: str
    operational_node_id: str
    units: int
    release_day: int
    remaining_days: int


@dataclass(frozen=True)
class FleetRetirementRow:
    id: str
    vehicle_definition_id: str
    display_name: str
    operational_node_id: str
    units: int
    phase: str
    irreversible_started: bool
    progress_work: float
    required_work: float
    priority: ActivityPriority
    expected_salvage: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]
    projected_salvage_fraction: float = 1.0
    projected_salvage: tuple[tuple[str, float], ...] = ()
    actual_salvage_fraction: float | None = None
    actual_salvage: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class FleetRelocationResourceRequirementRow:
    operational_node_id: str
    resource_id: str
    required_t: float
    available_t: float


@dataclass(frozen=True)
class CargoFlowRow:
    id: str
    resource_id: str
    amount_t: float
    source_id: str
    destination_id: str
    requirement_id: str | None
    owner_kind: str
    owner_id: str
    priority: ActivityPriority
    service_ids: tuple[str, ...]
    service_destinations: tuple[str, ...]
    departure_day: int
    ready_day: int
    status: str
    admission_blockers: tuple[str, ...] = ()
    final_destination_id: str | None = None
    dispatch_end_day: int | None = None
    dispatch_rate_t_per_day: float | None = None
    latency_days: int | None = None


@dataclass(frozen=True)
class VehicleProductionOptionRow:
    vehicle_definition_id: str
    display_name: str
    operational_node_id: str
    production_service_type: str | None
    production_days: float
    resources: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]
    can_plan: bool


@dataclass(frozen=True)
class VehicleProductionRow:
    id: str
    vehicle_definition_id: str
    display_name: str
    operational_node_id: str
    phase: str
    paused: bool
    progress_days: float
    required_days: float
    remaining_days: float
    estimated_completion_day: float | None
    production_service_type: str | None
    resources: tuple[tuple[str, float], ...]
    priority: ActivityPriority
    priority_editable: bool
    blockers: tuple[str, ...]
    completed_units: int


@dataclass(frozen=True)
class SupplyRequirementRow:
    id: str
    owner_kind: str
    owner_id: str
    destination_id: str
    resource_id: str
    requested_t: float
    local_supply_t: float
    external_required_t: float
    pipeline_t: float
    remaining_t: float
    priority: ActivityPriority
    routing_constraint_source_id: str | None = None
    routing_constraint_via_node_ids: tuple[str, ...] = ()
    routing_constraint_transport_allocation_ids: tuple[str, ...] = ()
    selected_source_id: str | None = None
    selected_service_ids: tuple[str, ...] = ()
    selected_movement_plan_ids: tuple[str, ...] = ()
    projected_arrival_day: int | None = None
    selected_latency_days: float | None = None
    selected_propellant_t_per_t: float | None = None
    selected_handoff_count: int | None = None
    selected_bottleneck_capacity_t_per_day: float | None = None
    source_candidate_ids: tuple[str, ...] = ()
    operational_source_ids: tuple[str, ...] = ()
    stocked_source_ids: tuple[str, ...] = ()
    path_candidates: tuple[tuple[str, tuple[str, ...]], ...] = ()
    forecast_requirement_day: int | None = None
    recurring_rate_t_per_day: float | None = None
    local_runway_days: float | None = None
    earliest_confirmed_arrival_day: int | None = None
    projected_gap_days: float | None = None
    candidate_source_count: int = 0
    operational_source_count: int = 0
    stocked_source_count: int = 0
    supply_state: str = "covered"
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupplyRoutingConstraintRow:
    destination_id: str
    owner_kind: str | None
    owner_id: str | None
    resource_id: str | None
    source_node_id: str | None
    required_via_node_ids: tuple[str, ...]
    required_transport_allocation_ids: tuple[str, ...]


@dataclass(frozen=True)
class TargetStockRow:
    id: str
    destination_id: str
    resource_id: str
    target_quantity_t: float
    priority: ActivityPriority


@dataclass(frozen=True)
class TargetStockPresetRow:
    key: str
    display_name: str
    target_quantity_t: float
    days_of_supply: float | None = None


@dataclass(frozen=True)
class TargetStockOptionsView:
    destination_id: str
    resource_id: str
    current_stock_t: float
    inbound_t: float
    normal_demand_t_per_day: float
    current_target_quantity_t: float
    priority: ActivityPriority
    suggested_max_t: float
    presets: tuple[TargetStockPresetRow, ...]


@dataclass(frozen=True)
class LogisticsView:
    movement_plans: tuple[MovementPlanRow, ...]
    fleet_pools: tuple[FleetPoolRow, ...]
    relocations: tuple[FleetRelocationRow, ...]
    releases: tuple[FleetReleaseRow, ...]
    retirements: tuple[FleetRetirementRow, ...]
    allocations: tuple[TransportAllocationRow, ...]
    vehicle_production_options: tuple[VehicleProductionOptionRow, ...]
    vehicle_production: tuple[VehicleProductionRow, ...]
    cargo_flows: tuple[CargoFlowRow, ...]
    routing_constraints: tuple[SupplyRoutingConstraintRow, ...]
    target_stocks: tuple[TargetStockRow, ...]
    requirements: tuple[SupplyRequirementRow, ...]


@dataclass(frozen=True)
class TransportCapacityPresetRow:
    key: str
    display_name: str
    capacity: DirectionalCapacityRow
    units: int


@dataclass(frozen=True)
class TransportAllocationOptionRow:
    vehicle_definition_id: str
    display_name: str
    source_id: str
    destination_id: str
    forward_path: tuple[str, ...]
    reverse_path: tuple[str, ...]
    cycle_days: float
    forward_latency_days: int
    reverse_latency_days: int | None
    nominal_capacity: DirectionalCapacityRow
    suggested_capacity_max: DirectionalCapacityRow
    capacity_presets: tuple[TransportCapacityPresetRow, ...]
    fleet_total_units: int
    fleet_free_units: int
    operational_supply_at_full_unit: tuple[tuple[str, str, float], ...]
    infrastructure_requirements: tuple[InfrastructureRequirementRow, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class TransportAllocationOptionsView:
    source_id: str
    destination_id: str
    options: tuple[TransportAllocationOptionRow, ...]


@dataclass(frozen=True)
class TransportAllocationPreviewView:
    vehicle_definition_id: str
    source_id: str
    destination_id: str
    target_capacity: DirectionalCapacityRow
    nominal_capacity_per_unit: DirectionalCapacityRow
    suggested_capacity_max: DirectionalCapacityRow
    capacity_presets: tuple[TransportCapacityPresetRow, ...]
    achievable_capacity: DirectionalCapacityRow
    required_units: int | None
    available_units: int
    unfilled_units: int | None
    selected_forward_path: tuple[str, ...]
    selected_reverse_path: tuple[str, ...]
    cycle_days: float
    forward_latency_days: int
    reverse_latency_days: int | None
    blockers: tuple[str, ...]
