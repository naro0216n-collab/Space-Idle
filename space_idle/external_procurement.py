from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .external_economy import FundsRequest
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass(frozen=True)
class ExternalProcurementServiceDef:
    """Content-owned offer that delivers purchased physical resources to one node.

    Procurement is not an Inventory shortcut.  An accepted order becomes a
    persisted delivery batch and reaches Inventory only through normal arrival
    admission after ``delivery_latency_days``.
    """

    id: DefinitionId
    display_name: str
    delivery_node_id: SpatialNodeId
    resource_prices_musd_per_t: tuple[tuple[DefinitionId, float], ...]
    delivery_latency_days: int

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("external procurement display name must be non-empty")
        if self.delivery_latency_days <= 0:
            raise ValueError("external procurement delivery latency must be positive")
        seen: set[DefinitionId] = set()
        for resource_id, price in self.resource_prices_musd_per_t:
            if resource_id in seen:
                raise ValueError(
                    f"duplicate external procurement resource offer: {resource_id}"
                )
            seen.add(resource_id)
            if price < -1e-9:
                raise ValueError("external procurement price must be non-negative")

    def unit_price_musd_per_t(self, resource_id: DefinitionId) -> float | None:
        for offered_resource_id, price in self.resource_prices_musd_per_t:
            if offered_resource_id == resource_id:
                return price
        return None


class ProcurementDeliveryStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    ARRIVAL_WAITING = "arrival_waiting"


@dataclass
class ProcurementDeliveryBatch:
    id: EntityId
    service_id: DefinitionId
    demand_id: EntityId
    owner_kind: str
    owner_id: EntityId
    delivery_node_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float
    order_day: int
    ready_day: int
    status: ProcurementDeliveryStatus = ProcurementDeliveryStatus.IN_TRANSIT

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("external procurement delivery amount must be positive")
        if self.ready_day <= self.order_day:
            raise ValueError("external procurement delivery must have positive latency")


@dataclass(frozen=True)
class ProcurementOrder:
    service_id: DefinitionId
    demand: ResourceDemand
    delivery_node_id: SpatialNodeId
    amount_t: float
    requested_amount_t: float
    unit_price_musd_per_t: float
    funds_request_id: EntityId

    def __post_init__(self) -> None:
        if self.amount_t < -1e-9 or self.requested_amount_t < -1e-9:
            raise ValueError("external procurement order amount must be non-negative")
        if self.amount_t > self.requested_amount_t + 1e-9:
            raise ValueError("authorized procurement exceeds requested amount")
        if self.unit_price_musd_per_t < -1e-9:
            raise ValueError("external procurement price must be non-negative")


@dataclass(frozen=True)
class ExternalProcurementPlan:
    orders: tuple[ProcurementOrder, ...]
    spending_requests: tuple[FundsRequest, ...]
