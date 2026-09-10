from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RouteModeRow:
    id: str
    display_name: str
    kind: str
    vehicle_definition_id: str | None
    available_vehicle_count: int
    dispatch_capacity_t: float
    transit_days: int
    cost_musd_per_t: float
    propellant_resource_id: str | None
    full_load_propellant_t: float | None
    usable_now: bool
    blockers: tuple[str, ...]

@dataclass(frozen=True)
class RouteRow:
    id: str
    display_name: str
    origin_id: str
    destination_id: str
    available: bool
    usable_now: bool
    dispatch_capacity_t: float
    transit_days: int
    delta_v_km_s: float
    operations: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]
    operational_blockers: tuple[str, ...]
    modes: tuple[RouteModeRow, ...]

@dataclass(frozen=True)
class VehicleRow:
    id: str
    definition_id: str
    display_name: str
    concept: str
    location_id: str | None
    status: str
    available_day: int
    payload_t: float
    dry_mass_t: float
    propellant_t: float
    propellant_capacity_t: float
    propellant_resource_id: str | None
    capabilities: tuple[str, ...]
    transit_destination_id: str | None
    turnaround_capability_id: str | None
    turnaround_cost_musd: float
    turnaround_resources: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]
    assignment_id: str | None = None
    assignment_kind: str | None = None


@dataclass(frozen=True)
class VehicleProductionOptionRow:
    vehicle_definition_id: str
    display_name: str
    location_id: str
    production_capability_id: str | None
    production_days: float
    resources: tuple[tuple[str, float], ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class VehicleProductionRow:
    id: str
    vehicle_definition_id: str
    display_name: str
    location_id: str
    phase: str
    paused: bool
    progress_days: float
    required_days: float
    remaining_days: float
    estimated_completion_day: float | None
    production_capability_id: str | None
    resources: tuple[tuple[str, float], ...]
    priority: int
    allocation_weight: float
    blockers: tuple[str, ...]
    completed_vehicle_id: str | None

@dataclass(frozen=True)
class CargoOrderRow:
    id: str
    owner_kind: str
    owner_id: str
    source_id: str
    destination_id: str
    resource_id: str
    amount_t: float
    delivered_t: float
    priority: int
    path: tuple[str, ...]
    route_modes: tuple[tuple[str, str], ...]
    path_policy: str
    status: str
    waiting_t: float
    in_transit_t: float
    arrival_waiting_t: float
    blockers: tuple[str, ...]
    lane_id: str | None = None
    demand_id: str | None = None

@dataclass(frozen=True)
class ResourceDemandRow:
    id: str
    owner_kind: str
    owner_id: str
    source_id: str | None
    destination_id: str
    resource_id: str
    requested_t: float
    local_supply_t: float
    external_required_t: float
    pipeline_t: float
    remaining_t: float
    priority: int
    recurring_rate_t_per_day: float | None = None
    local_runway_days: float | None = None
    earliest_confirmed_arrival_day: int | None = None
    projected_gap_days: float | None = None
    eligible_lane_count: int = 0
    operational_lane_count: int = 0
    stocked_source_count: int = 0
    supply_state: str = "covered"
    blockers: tuple[str, ...] = ()

@dataclass(frozen=True)
class LogisticsLaneRow:
    id: str
    source_id: str
    destination_id: str
    requested_capacity_t_per_day: float
    effective_capacity_t_per_day: float
    used_t: float
    queued_t: float
    priority: int
    path: tuple[str, ...] | None
    route_modes: tuple[tuple[str, str], ...]
    path_policy: str
    paused: bool
    blockers: tuple[str, ...]

@dataclass(frozen=True)
class TransportMissionRow:
    id: str
    order_id: str
    leg_index: int
    route_id: str
    amount_t: float
    mode_id: str
    vehicle_id: str | None
    vehicle_disposition: str
    status: str
    departure_day: int
    arrival_day: int
    onboard: bool
    handoff_vehicle_id: str | None

@dataclass(frozen=True)
class LogisticsView:
    routes: tuple[RouteRow, ...]
    vehicles: tuple[VehicleRow, ...]
    vehicle_production_options: tuple[VehicleProductionOptionRow, ...]
    vehicle_production: tuple[VehicleProductionRow, ...]
    missions: tuple[TransportMissionRow, ...]
    orders: tuple[CargoOrderRow, ...]
    lanes: tuple[LogisticsLaneRow, ...]
    demands: tuple[ResourceDemandRow, ...]

@dataclass(frozen=True)
class TransportPathOptionRow:
    policy: str
    path: tuple[str, ...]
    route_modes: tuple[tuple[str, str], ...]
    transit_days: int
    estimated_cost_musd_per_t: float
    estimated_propellant_t_per_cargo_t: float

@dataclass(frozen=True)
class TransportPlansView:
    source_id: str
    destination_id: str
    options: tuple[TransportPathOptionRow, ...]
