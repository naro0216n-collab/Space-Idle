from __future__ import annotations

from dataclasses import dataclass

from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY


@dataclass(frozen=True)
class SetTargetStock:
    destination_id: str
    resource_id: str
    target_quantity_t: float
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY


@dataclass(frozen=True)
class DeleteTargetStock:
    destination_id: str
    resource_id: str


@dataclass(frozen=True)
class SetSupplyRoutingConstraint:
    destination_id: str
    owner_kind: str | None = None
    owner_id: str | None = None
    resource_id: str | None = None
    source_node_id: str | None = None
    required_via_node_ids: tuple[str, ...] = ()
    required_transport_allocation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClearSupplyRoutingConstraint:
    destination_id: str
    owner_kind: str | None = None
    owner_id: str | None = None
    resource_id: str | None = None
