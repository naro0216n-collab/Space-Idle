from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .shared import DefinitionId, EntityId, SpatialNodeId

if TYPE_CHECKING:
    from .inventory import InventoryBook


@dataclass(frozen=True)
class ResourceDemand:
    """Future replenishment need at an Operational Node.

    Demand is planning state only. It never claims current inventory and never
    creates an Inventory reservation. Domains describe destination, resource,
    amount and priority; Logistics may then source only the residual need after
    observable on-site stock and in-flight pipeline are accounted for.
    """

    id: EntityId
    owner_kind: str
    owner_id: EntityId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float
    priority: int = 50
    source_id: SpatialNodeId | None = None
    recurring_rate_t_per_day: float | None = None

    def __post_init__(self) -> None:
        if self.amount_t < 0:
            raise ValueError("resource demand amount must be non-negative")
        if self.source_id is not None and self.source_id == self.destination_id:
            raise ValueError("resource demand source and destination must differ")
        if self.recurring_rate_t_per_day is not None and self.recurring_rate_t_per_day <= 0:
            raise ValueError("resource demand recurring rate must be positive")


@dataclass(frozen=True)
class ResourceDemandResolution:
    """Planning-only local coverage and residual transport need for one demand."""

    demand: ResourceDemand
    local_supply_t: float
    external_required_t: float

    def __post_init__(self) -> None:
        if self.local_supply_t < -1e-9 or self.external_required_t < -1e-9:
            raise ValueError("resource demand resolution amounts must be non-negative")
        if abs(self.local_supply_t + self.external_required_t - self.demand.amount_t) > 1e-7:
            raise ValueError("resource demand resolution must conserve demand")

    def external_demand(self) -> ResourceDemand | None:
        if self.external_required_t <= 1e-9:
            return None
        demand = self.demand
        return ResourceDemand(
            demand.id,
            demand.owner_kind,
            demand.owner_id,
            demand.destination_id,
            demand.resource_id,
            self.external_required_t,
            demand.priority,
            demand.source_id,
            demand.recurring_rate_t_per_day,
        )


def resolve_local_resource_supply(
    demands: Iterable[ResourceDemand], inventory: InventoryBook
) -> tuple[ResourceDemandResolution, ...]:
    """Credit observable on-site stock toward future replenishment planning.

    This is deliberately separate from current-tick Resource Claim allocation.
    Higher-priority future needs receive local planning credit first; same-
    priority needs share a shortage proportionally. Existing durable Inventory
    reservations remain unavailable to planning through ``inventory.available``.
    No Inventory state is mutated.
    """

    ordered = tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))
    by_key: dict[tuple[SpatialNodeId, DefinitionId], list[int]] = {}
    local_credit = [0.0 for _ in ordered]
    for index, demand in enumerate(ordered):
        by_key.setdefault((demand.destination_id, demand.resource_id), []).append(index)

    for key, indices in by_key.items():
        available = max(0.0, inventory.available(key[0], key[1]))
        priority_bands: dict[int, list[int]] = {}
        for index in indices:
            priority_bands.setdefault(ordered[index].priority, []).append(index)
        for priority in sorted(priority_bands, reverse=True):
            band = priority_bands[priority]
            total_need = sum(max(0.0, ordered[index].amount_t) for index in band)
            if available <= 1e-12 or total_need <= 1e-12:
                continue
            take_total = min(available, total_need)
            for index in band:
                need = max(0.0, ordered[index].amount_t)
                local_credit[index] = take_total * need / total_need
            available -= take_total

    return tuple(
        ResourceDemandResolution(
            demand,
            min(demand.amount_t, max(0.0, local_credit[index])),
            max(0.0, demand.amount_t - local_credit[index]),
        )
        for index, demand in enumerate(ordered)
    )


def external_resource_demands(
    demands: Iterable[ResourceDemand], inventory: InventoryBook
) -> tuple[ResourceDemand, ...]:
    """Return future need that requires off-site supply; never reserve stock."""

    rows: list[ResourceDemand] = []
    for resolution in resolve_local_resource_supply(demands, inventory):
        demand = resolution.external_demand()
        if demand is not None:
            rows.append(demand)
    return tuple(rows)
