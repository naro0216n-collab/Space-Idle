from __future__ import annotations
from dataclasses import dataclass
from .logistics_views import (
    CargoOrderRow, LogisticsLaneRow, ResourceDemandRow, RouteRow, TransportMissionRow, VehicleRow,
)


@dataclass(frozen=True)
class LogisticsSummaryView:
    route_count: int
    usable_route_count: int
    vehicle_count: int
    available_vehicle_count: int
    mission_count: int
    order_count: int
    blocked_order_count: int
    lane_count: int
    paused_lane_count: int
    demand_count: int
    queued_demand_t: float
    waiting_t: float
    in_transit_t: float
    arrival_waiting_t: float


@dataclass(frozen=True)
class RoutesView:
    items: tuple[RouteRow, ...]


@dataclass(frozen=True)
class VehiclesView:
    items: tuple[VehicleRow, ...]


@dataclass(frozen=True)
class CargoOrdersView:
    items: tuple[CargoOrderRow, ...]


@dataclass(frozen=True)
class LogisticsLanesView:
    items: tuple[LogisticsLaneRow, ...]
    demands: tuple[ResourceDemandRow, ...]


@dataclass(frozen=True)
class TransportMissionsView:
    items: tuple[TransportMissionRow, ...]
