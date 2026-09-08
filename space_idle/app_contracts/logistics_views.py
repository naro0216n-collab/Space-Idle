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

@dataclass(frozen=True)
class CargoOrderRow:
    id: str
    source_id: str
    destination_id: str
    resource_id: str
    amount_t: float
    delivered_t: float
    priority: int
    path: tuple[str, ...]
    route_modes: tuple[tuple[str, str], ...]
    path_policy: str
    waiting_t: float
    in_transit_t: float
    arrival_waiting_t: float
    blockers: tuple[str, ...]

@dataclass(frozen=True)
class LogisticsRuleRow:
    id: str
    source_id: str
    destination_id: str
    resource_id: str
    target_stock_t: float
    batch_t: float
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
    missions: tuple[TransportMissionRow, ...]
    orders: tuple[CargoOrderRow, ...]
    rules: tuple[LogisticsRuleRow, ...]

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
