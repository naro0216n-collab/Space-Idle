from __future__ import annotations
from dataclasses import dataclass
from .logistics_views import (
    CargoFlowRow, FleetPoolRow, FleetRelocationResourceRequirementRow,
    FleetRelocationRow, FleetReleaseRow, InfrastructureRequirementRow,
    LogisticsLaneRow, ResourceDemandRow, RouteRow, TransportAllocationRow,
)


@dataclass(frozen=True)
class LogisticsSummaryView:
    route_count: int
    usable_route_count: int
    fleet_units: int
    free_fleet_units: int
    allocation_count: int
    unfilled_allocation_units: int
    cargo_flow_count: int
    lane_count: int
    paused_lane_count: int
    demand_count: int
    queued_demand_t: float
    in_transit_t: float
    arrival_waiting_t: float


@dataclass(frozen=True)
class RoutesView:
    items: tuple[RouteRow, ...]


@dataclass(frozen=True)
class FleetView:
    pools: tuple[FleetPoolRow, ...]
    relocations: tuple[FleetRelocationRow, ...]
    releases: tuple[FleetReleaseRow, ...]


@dataclass(frozen=True)
class FleetRelocationPreviewView:
    vehicle_definition_id: str
    display_name: str
    units: int
    source_id: str
    destination_id: str
    path_policy: str
    path: tuple[str, ...]
    travel_days: int
    departure_day: int
    arrival_day: int | None
    resource_requirements: tuple[FleetRelocationResourceRequirementRow, ...]
    infrastructure_requirements: tuple[InfrastructureRequirementRow, ...]
    feasible: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class TransportAllocationsView:
    items: tuple[TransportAllocationRow, ...]


@dataclass(frozen=True)
class CargoFlowsView:
    items: tuple[CargoFlowRow, ...]


@dataclass(frozen=True)
class LogisticsLanesView:
    items: tuple[LogisticsLaneRow, ...]
    demands: tuple[ResourceDemandRow, ...]
