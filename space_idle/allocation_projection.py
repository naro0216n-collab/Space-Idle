from __future__ import annotations

from dataclasses import dataclass

from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, SpatialNodeId

_EPS = 1e-12


@dataclass(frozen=True)
class ResourceAllocationProjectionRow:
    """Derived current-tick allocation of one physical Resource requirement.

    This is a query projection of the authoritative common execution allocation,
    not a competing request/settlement object and never persisted.
    """

    id: EntityId
    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    owner_kind: str
    owner_id: EntityId
    purpose: str
    priority: ActivityPriority
    requested_amount: float
    allocated_amount: float
    minimum_amount: float = 0.0
    atomic: bool = False
    requirement_id: EntityId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
        if self.requested_amount < -_EPS or self.allocated_amount < -_EPS:
            raise ValueError("resource allocation projection amounts must be non-negative")
        if self.allocated_amount > self.requested_amount + 1e-8:
            raise ValueError("resource allocation projection cannot exceed requested amount")
        if self.minimum_amount < -_EPS:
            raise ValueError("resource allocation projection minimum must be non-negative")
        if self.minimum_amount > self.requested_amount + 1e-8:
            raise ValueError("resource allocation projection minimum cannot exceed requested amount")
        if self.atomic and self.minimum_amount not in (0.0, self.requested_amount):
            raise ValueError("atomic resource allocation minimum must be zero or full request")

    @property
    def unmet_amount(self) -> float:
        return max(0.0, self.requested_amount - self.allocated_amount)

    @property
    def effective_minimum_amount(self) -> float:
        return self.requested_amount if self.atomic else self.minimum_amount


@dataclass(frozen=True)
class ResourceAllocationProjection:
    """Application/query projection derived from one common execution result."""

    rows: tuple[ResourceAllocationProjectionRow, ...]

    def __post_init__(self) -> None:
        ids = [row.id for row in self.rows]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate resource allocation projection id")

    def row(self, row_id: EntityId) -> ResourceAllocationProjectionRow:
        for row in self.rows:
            if row.id == row_id:
                return row
        raise KeyError(row_id)

    def allocated(self, row_id: EntityId) -> float:
        return self.row(row_id).allocated_amount

    def rows_for_owner(
        self, owner_kind: str, owner_id: EntityId
    ) -> tuple[ResourceAllocationProjectionRow, ...]:
        return tuple(
            row
            for row in self.rows
            if row.owner_kind == owner_kind and row.owner_id == owner_id
        )
