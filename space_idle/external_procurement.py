from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .external_economy import FundsRequest
from .supply import SupplyRequirement
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass(frozen=True)
class ExternalProcurementServiceDef:
    """Content-owned external Supply Interface at one Operational Node.

    Procurement creates provider-side supply at ``supply_node_id`` after the
    configured lead time.  Physical Resource enters player-owned state only
    through normal Inventory Admission at that endpoint; onward delivery uses
    the regular Cargo / Transport lifecycle.
    """

    id: DefinitionId
    display_name: str
    supply_node_id: SpatialNodeId
    resource_prices_musd_per_t: tuple[tuple[DefinitionId, float], ...]
    supply_latency_days: int

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("external procurement display name must be non-empty")
        if self.supply_latency_days <= 0:
            raise ValueError("external procurement supply latency must be positive")
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


class ExternalSupplyStatus(str, Enum):
    ORDERED = "ordered"
    ADMISSION_WAITING = "admission_waiting"


@dataclass
class ExternalSupplyBatch:
    """Provider-owned external supply awaiting entry at a fixed Supply Endpoint."""

    id: EntityId
    service_id: DefinitionId
    requirement_id: EntityId
    owner_kind: str
    owner_id: EntityId
    supply_node_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float
    order_day: int
    available_day: int
    status: ExternalSupplyStatus = ExternalSupplyStatus.ORDERED

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("external supply amount must be positive")
        if self.available_day <= self.order_day:
            raise ValueError("external supply must have positive lead time")


@dataclass(frozen=True)
class ProcurementOrder:
    service_id: DefinitionId
    requirement: SupplyRequirement
    supply_node_id: SpatialNodeId
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
