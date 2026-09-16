from __future__ import annotations

from dataclasses import dataclass
from .priority import ActivityPriority
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
    priority: ActivityPriority
    owner_kind: str
    owner_id: EntityId
    purpose: str
    minimum_amount: float = 0.0
    atomic: bool = False
    requirement_id: EntityId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
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
