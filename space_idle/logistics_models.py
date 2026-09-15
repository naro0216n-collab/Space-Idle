from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .priority import ActivityPriority
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
    demand_id: EntityId | None
    owner_kind: str
    owner_id: EntityId
    priority: ActivityPriority
    service_ids: tuple[str, ...]
    service_destinations: tuple[SpatialNodeId, ...]
    departure_day: int
    ready_day: int
    status: CargoFlowStatus = CargoFlowStatus.IN_TRANSIT

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.amount_t <= 0:
            raise ValueError("cargo flow amount must be positive")
        if not self.service_ids or len(self.service_ids) != len(self.service_destinations):
            raise ValueError("cargo flow requires aligned service path")
