from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .transport.models import PathPolicy


class CargoFlowStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    ARRIVAL_WAITING = "arrival_waiting"


@dataclass
class CargoFlowBatch:
    id: EntityId
    resource_id: DefinitionId
    amount_t: float
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    lane_id: EntityId | None
    demand_id: EntityId | None
    owner_kind: str
    owner_id: EntityId
    priority: int
    service_ids: tuple[str, ...]
    service_destinations: tuple[SpatialNodeId, ...]
    departure_day: int
    ready_day: int
    status: CargoFlowStatus = CargoFlowStatus.IN_TRANSIT

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("cargo flow amount must be positive")
        if not self.service_ids or len(self.service_ids) != len(self.service_destinations):
            raise ValueError("cargo flow requires aligned service path")


@dataclass
class LogisticsLane:
    id: EntityId
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    requested_capacity_t_per_day: float
    priority: int
    path: tuple[RouteId, ...] | None = None
    path_policy: PathPolicy = PathPolicy.FASTEST
    paused: bool = False

    def __post_init__(self) -> None:
        if self.source_id == self.destination_id:
            raise ValueError("logistics lane endpoints must differ")
        if self.requested_capacity_t_per_day <= 0:
            raise ValueError("logistics lane requested capacity must be positive")
