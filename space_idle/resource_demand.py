from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .shared import DefinitionId, EntityId, SpatialNodeId

if TYPE_CHECKING:
    from .inventory import InventoryBook


@dataclass(frozen=True)
class ResourceDemand:
    """A domain-owned request for physical material at a location.

    Domains declare the amount they still need after any reservation they own.
    They do not independently spend the site's remaining unreserved inventory
    when deciding how much must be transported. The simulation demand resolver
    nets all demands at the same location/resource against that shared local
    supply first; logistics receives only the residual external requirement.

    Demand describes need, not transport. Domains may constrain the source when
    their procurement policy requires it. Logistics decides whether an eligible
    player-configured lane can carry the residual demand and creates ordinary
    Cargo Flow batches for the allocation.
    """

    id: EntityId
    owner_kind: str
    owner_id: EntityId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float
    priority: int = 50
    source_id: SpatialNodeId | None = None
    local_claim_t: float | None = None
    external_allowed: bool = True
    recurring_rate_t_per_day: float | None = None

    def __post_init__(self) -> None:
        if self.amount_t < 0:
            raise ValueError("resource demand amount must be non-negative")
        claim = self.amount_t if self.local_claim_t is None else self.local_claim_t
        if claim < -1e-9:
            raise ValueError("resource demand local claim must be non-negative")
        if claim > self.amount_t + 1e-9:
            raise ValueError("resource demand local claim cannot exceed planned demand")
        if self.source_id is not None and self.source_id == self.destination_id:
            raise ValueError("resource demand source and destination must differ")
        if self.recurring_rate_t_per_day is not None and self.recurring_rate_t_per_day <= 0:
            raise ValueError("resource demand recurring rate must be positive")

    @property
    def claim_amount_t(self) -> float:
        return self.amount_t if self.local_claim_t is None else self.local_claim_t


@dataclass(frozen=True)
class ResourceDemandResolution:
    """Local-supply allocation and residual transport requirement for one demand."""

    demand: ResourceDemand
    local_supply_t: float
    external_required_t: float

    def __post_init__(self) -> None:
        if self.local_supply_t < -1e-9 or self.external_required_t < -1e-9:
            raise ValueError("resource demand resolution amounts must be non-negative")
        if abs(self.local_supply_t + self.external_required_t - self.demand.amount_t) > 1e-7:
            raise ValueError("resource demand resolution must conserve demand")

    def external_demand(self) -> ResourceDemand | None:
        if not self.demand.external_allowed or self.external_required_t <= 1e-9:
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
            0.0,
            demand.external_allowed,
            demand.recurring_rate_t_per_day,
        )


def resolve_local_resource_supply(
    demands: Iterable[ResourceDemand], inventory: InventoryBook
) -> tuple[ResourceDemandResolution, ...]:
    """Net shared on-site supply before any external transport is requested.

    Allocation is deterministic and independent of entity registration order.
    Higher priority bands are served first. Within one priority band, scarce
    stock is shared proportionally rather than by entity id. Immediate claims
    are allocated before replenishment/buffer targets, so a large maintenance
    buffer cannot silently pre-empt another demand's same-priority current-day
    requirement. Inventory already reserved by a demand is credited only to
    that demand and is excluded from the shared pool.

    This function is planning-only: it does not reserve or consume inventory.
    """

    ordered = tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))
    by_key: dict[tuple[SpatialNodeId, DefinitionId], list[int]] = {}
    local_credit = [0.0 for _ in ordered]

    for index, demand in enumerate(ordered):
        key = (demand.destination_id, demand.resource_id)
        by_key.setdefault(key, []).append(index)
        own_reserved = inventory.reserved_for(
            demand.id, demand.destination_id, demand.resource_id
        )
        local_credit[index] = min(max(0.0, demand.amount_t), max(0.0, own_reserved))

    def allocate_band(indices: list[int], available: float, needs: dict[int, float]) -> float:
        total_need = sum(max(0.0, needs.get(index, 0.0)) for index in indices)
        if available <= 1e-12 or total_need <= 1e-12:
            return available
        take_total = min(available, total_need)
        for index in indices:
            need = max(0.0, needs.get(index, 0.0))
            if need <= 1e-12:
                continue
            share = take_total * need / total_need
            local_credit[index] += min(need, share)
        return max(0.0, available - take_total)

    for key, indices in by_key.items():
        available = max(0.0, inventory.available(key[0], key[1]))
        priority_bands: dict[int, list[int]] = {}
        for index in indices:
            priority_bands.setdefault(ordered[index].priority, []).append(index)

        # Stage 1: protect current-day/discrete claims.
        for priority in sorted(priority_bands, reverse=True):
            band = priority_bands[priority]
            needs = {
                index: max(
                    0.0,
                    min(ordered[index].claim_amount_t, ordered[index].amount_t)
                    - local_credit[index],
                )
                for index in band
            }
            available = allocate_band(band, available, needs)

        # Stage 2: credit any remaining local stock toward planning buffers.
        for priority in sorted(priority_bands, reverse=True):
            if available <= 1e-12:
                break
            band = priority_bands[priority]
            needs = {
                index: max(0.0, ordered[index].amount_t - local_credit[index])
                for index in band
            }
            available = allocate_band(band, available, needs)

    resolutions: list[ResourceDemandResolution] = []
    for index, demand in enumerate(ordered):
        local = min(demand.amount_t, max(0.0, local_credit[index]))
        external = max(0.0, demand.amount_t - local)
        resolutions.append(ResourceDemandResolution(demand, local, external))
    return tuple(resolutions)




def reconcile_local_resource_claims(
    demands: Iterable[ResourceDemand], inventory: InventoryBook
) -> tuple[ResourceDemandResolution, ...]:
    """Atomically rebuild transient local reservations from current demand state.

    Resource-demand reservations are derived allocation state. Reconciliation
    discards the previous allocation and deterministically rebuilds immediate
    claims from current inventory, priorities, and demand amounts. Planning-only
    stock targets remain unreserved and influence only external replenishment.
    """

    rows = tuple(demands)
    demand_ids = {demand.id for demand in rows}
    if len(demand_ids) != len(rows):
        raise ValueError("duplicate resource demand id")

    # ResourceDemand is the sole creator of Inventory reservations. Releasing
    # them here is an atomic recalculation of derived allocation, not a Domain
    # state transition. No consumer executes between release and rebuild.
    for owner_id in {key[0] for key in tuple(inventory.reserved)}:
        inventory.release_reservation(owner_id)

    resolutions = resolve_local_resource_supply(rows, inventory)
    for resolution in resolutions:
        demand = resolution.demand
        target = min(demand.claim_amount_t, resolution.local_supply_t)
        if target > 1e-12:
            inventory.reserve(
                demand.id, demand.destination_id, demand.resource_id, target
            )
    return resolutions


def external_resource_demands(
    demands: Iterable[ResourceDemand], inventory: InventoryBook
) -> tuple[ResourceDemand, ...]:
    """Return only the residual demand that actually needs off-site supply."""

    rows: list[ResourceDemand] = []
    for resolution in resolve_local_resource_supply(demands, inventory):
        demand = resolution.external_demand()
        if demand is not None:
            rows.append(demand)
    return tuple(rows)
