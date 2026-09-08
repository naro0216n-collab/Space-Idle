from __future__ import annotations

from dataclasses import dataclass

from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass(frozen=True)
class ResourceDemand:
    """A domain-owned request for physical material at a location.

    Demand describes need, not transport. Domains choose what is needed and may
    constrain the source when their own procurement policy requires it. The
    logistics domain decides whether an eligible player-configured lane can
    carry that demand and creates ordinary CargoOrders for the allocation.
    """

    id: EntityId
    owner_kind: str
    owner_id: EntityId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float
    priority: int = 50
    source_id: SpatialNodeId | None = None

    def __post_init__(self) -> None:
        if self.amount_t < 0:
            raise ValueError("resource demand amount must be non-negative")
        if self.source_id is not None and self.source_id == self.destination_id:
            raise ValueError("resource demand source and destination must differ")
