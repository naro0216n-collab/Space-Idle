from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .inventory import InventoryBook
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass(frozen=True)
class ResourceClaim:
    """Transient request to use physical inventory in the current tick.

    A claim is not a reservation and is never persisted.  It only competes for
    the start-of-tick inventory snapshot; Domain execution may consume or move
    at most the allocated amount.  ``minimum_amount`` and ``atomic`` opt a
    claim into discrete allocation semantics.  Continuous claims use the
    default proportional same-priority sharing rule.
    """

    id: EntityId
    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    requested_amount: float
    priority: int
    owner_kind: str
    owner_id: EntityId
    purpose: str
    minimum_amount: float = 0.0
    atomic: bool = False
    demand_id: EntityId | None = None

    def __post_init__(self) -> None:
        if self.requested_amount < -1e-9:
            raise ValueError("resource claim requested amount must be non-negative")
        if self.minimum_amount < -1e-9:
            raise ValueError("resource claim minimum amount must be non-negative")
        if self.minimum_amount > self.requested_amount + 1e-9:
            raise ValueError("resource claim minimum cannot exceed requested amount")
        if self.atomic and self.minimum_amount not in (0.0, self.requested_amount):
            raise ValueError("atomic resource claim minimum must be zero or full request")

    @property
    def effective_minimum_amount(self) -> float:
        return self.requested_amount if self.atomic else self.minimum_amount


@dataclass(frozen=True)
class ResourceAllocation:
    claim_id: EntityId
    requested_amount: float
    allocated_amount: float
    unmet_amount: float

    def __post_init__(self) -> None:
        if min(self.requested_amount, self.allocated_amount, self.unmet_amount) < -1e-9:
            raise ValueError("resource allocation amounts must be non-negative")
        if abs(self.allocated_amount + self.unmet_amount - self.requested_amount) > 1e-7:
            raise ValueError("resource allocation must conserve the claim")


@dataclass(frozen=True)
class ResourceAllocationPlan:
    claims: tuple[ResourceClaim, ...]
    allocations: tuple[ResourceAllocation, ...]

    def __post_init__(self) -> None:
        claim_ids = [claim.id for claim in self.claims]
        allocation_ids = [row.claim_id for row in self.allocations]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("duplicate resource claim id")
        if set(claim_ids) != set(allocation_ids) or len(allocation_ids) != len(claim_ids):
            raise ValueError("resource allocation plan must contain exactly one allocation per claim")

    def claim(self, claim_id: EntityId) -> ResourceClaim:
        for claim in self.claims:
            if claim.id == claim_id:
                return claim
        raise KeyError(claim_id)

    def allocation(self, claim_id: EntityId) -> ResourceAllocation:
        for allocation in self.allocations:
            if allocation.claim_id == claim_id:
                return allocation
        raise KeyError(claim_id)

    def allocated(self, claim_id: EntityId) -> float:
        return self.allocation(claim_id).allocated_amount

    def allocations_for_owner(self, owner_kind: str, owner_id: EntityId) -> tuple[ResourceAllocation, ...]:
        claim_ids = {
            claim.id for claim in self.claims
            if claim.owner_kind == owner_kind and claim.owner_id == owner_id
        }
        return tuple(row for row in self.allocations if row.claim_id in claim_ids)



def _claim_order_key(claim: ResourceClaim) -> tuple:
    """Stable semantic key; never depends on registration order."""
    return (
        claim.owner_kind,
        str(claim.owner_id),
        claim.purpose,
        str(claim.operational_node_id),
        str(claim.resource_id),
        str(claim.id),
    )


def _allocate_priority_band(
    claims: tuple[ResourceClaim, ...], available: float
) -> tuple[dict[EntityId, float], float]:
    allocated = {claim.id: 0.0 for claim in claims}
    available = max(0.0, available)
    if available <= 1e-12:
        return allocated, 0.0

    ordered = tuple(sorted(claims, key=_claim_order_key))
    threshold_claims = tuple(
        claim for claim in ordered if claim.effective_minimum_amount > 1e-12
    )
    total_threshold = sum(claim.effective_minimum_amount for claim in threshold_claims)

    if total_threshold <= available + 1e-12:
        selected = threshold_claims
    else:
        selected_rows: list[ResourceClaim] = []
        remaining = available
        for claim in threshold_claims:
            threshold = claim.effective_minimum_amount
            if threshold <= remaining + 1e-12:
                selected_rows.append(claim)
                remaining -= threshold
        selected = tuple(selected_rows)

    selected_ids = {claim.id for claim in selected}
    for claim in selected:
        threshold = claim.effective_minimum_amount
        allocated[claim.id] = threshold
        available -= threshold

    # Claims whose explicit minimum could not be met receive no allocation.
    eligible = tuple(
        claim for claim in ordered
        if claim.effective_minimum_amount <= 1e-12 or claim.id in selected_ids
    )
    continuous = tuple(claim for claim in eligible if not claim.atomic)
    remaining_need = {
        claim.id: max(0.0, claim.requested_amount - allocated[claim.id])
        for claim in continuous
    }
    total_need = sum(remaining_need.values())
    if available > 1e-12 and total_need > 1e-12:
        take_total = min(available, total_need)
        for claim in continuous:
            need = remaining_need[claim.id]
            if need <= 1e-12:
                continue
            allocated[claim.id] += take_total * need / total_need
        available -= take_total

    return allocated, max(0.0, available)


def allocate_resource_claims(
    claims: Iterable[ResourceClaim], inventory: InventoryBook
) -> ResourceAllocationPlan:
    """Allocate start-of-tick on-hand inventory across all current consumers.

    Higher priorities are resolved first. Continuous claims in the same priority
    band share shortage proportionally. Explicit minimum/atomic claims use a
    deterministic semantic ordering only when a shortage makes it impossible to
    satisfy every threshold. The input iterable's registration order never
    affects allocation quantities.
    """

    rows = tuple(claims)
    ids = [claim.id for claim in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate resource claim id")

    by_key: dict[tuple[SpatialNodeId, DefinitionId], list[ResourceClaim]] = {}
    for claim in rows:
        by_key.setdefault((claim.operational_node_id, claim.resource_id), []).append(claim)

    amounts: dict[EntityId, float] = {claim.id: 0.0 for claim in rows}
    for (node_id, resource_id), grouped in sorted(
        by_key.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
    ):
        available = max(0.0, inventory.available(node_id, resource_id))
        by_priority: dict[int, list[ResourceClaim]] = {}
        for claim in grouped:
            by_priority.setdefault(claim.priority, []).append(claim)
        for priority in sorted(by_priority, reverse=True):
            band = tuple(by_priority[priority])
            band_allocated, available = _allocate_priority_band(band, available)
            amounts.update(band_allocated)
            if available <= 1e-12:
                # Lower priorities are explicitly unmet.
                continue

    ordered_claims = tuple(sorted(rows, key=lambda claim: (-claim.priority, _claim_order_key(claim))))
    allocations = tuple(
        ResourceAllocation(
            claim.id,
            claim.requested_amount,
            min(claim.requested_amount, max(0.0, amounts[claim.id])),
            max(0.0, claim.requested_amount - amounts[claim.id]),
        )
        for claim in ordered_claims
    )
    return ResourceAllocationPlan(ordered_claims, allocations)
