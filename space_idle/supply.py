from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Iterable

from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, EntityId, SpatialNodeId

if TYPE_CHECKING:
    from .inventory import InventoryBook


@dataclass(frozen=True)
class SupplyRequirement:
    """Future replenishment need at an Operational Node.

    Supply Requirement is planning state only. It never claims current inventory and never
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
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    recurring_rate_t_per_day: float | None = None
    forecast_requirement_day: int | None = None
    purpose: str = "replenishment"

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
        if not isfinite(self.amount_t) or self.amount_t < 0:
            raise ValueError("supply requirement amount must be finite and non-negative")
        if self.recurring_rate_t_per_day is not None and (
            not isfinite(self.recurring_rate_t_per_day) or self.recurring_rate_t_per_day <= 0
        ):
            raise ValueError("supply requirement recurring rate must be finite and positive")
        if self.forecast_requirement_day is not None and self.forecast_requirement_day < 0:
            raise ValueError("supply requirement forecast day must be non-negative")
        if not self.purpose:
            raise ValueError("supply requirement purpose must be non-empty")


@dataclass(frozen=True)
class TargetStockPolicy:
    """Player-owned stock target integrated into ordinary Supply Planning."""

    id: EntityId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    target_quantity_t: float
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
        if not isfinite(self.target_quantity_t) or self.target_quantity_t < 0:
            raise ValueError("target stock quantity must be finite and non-negative")

    def requirement(self, day: int) -> SupplyRequirement:
        return SupplyRequirement(
            id=EntityId(f"supply.target_stock:{self.destination_id}:{self.resource_id}"),
            owner_kind="target_stock",
            owner_id=self.id,
            destination_id=self.destination_id,
            resource_id=self.resource_id,
            amount_t=self.target_quantity_t,
            priority=self.priority,
            forecast_requirement_day=day,
            purpose="target_stock",
        )



@dataclass(frozen=True)
class SupplyRoutingConstraintScope:
    """Sparse scope for a Player/Scenario hard supply-routing constraint."""

    destination_id: SpatialNodeId
    owner_kind: str | None = None
    owner_id: EntityId | None = None
    resource_id: DefinitionId | None = None

    def __post_init__(self) -> None:
        if (self.owner_kind is None) != (self.owner_id is None):
            raise ValueError("routing constraint owner_kind and owner_id must be set together")
        if self.owner_kind is not None and not self.owner_kind:
            raise ValueError("routing constraint owner kind must be non-empty")

    def matches(self, requirement: SupplyRequirement) -> bool:
        if requirement.destination_id != self.destination_id:
            return False
        if self.resource_id is not None and requirement.resource_id != self.resource_id:
            return False
        if self.owner_kind is not None and (
            requirement.owner_kind != self.owner_kind or requirement.owner_id != self.owner_id
        ):
            return False
        return True


@dataclass(frozen=True)
class SupplyRoutingConstraintState:
    """Player-owned hard routing restriction over the existing logistics network.

    This state does not describe a preferred strategy.  Every populated field is
    a mandatory filter.  Empty constraints are deliberately not representable.
    """

    scope: SupplyRoutingConstraintScope
    source_node_id: SpatialNodeId | None = None
    required_via_node_ids: tuple[SpatialNodeId, ...] = ()
    required_transport_allocation_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "required_via_node_ids", tuple(dict.fromkeys(self.required_via_node_ids))
        )
        object.__setattr__(
            self,
            "required_transport_allocation_ids",
            tuple(dict.fromkeys(self.required_transport_allocation_ids)),
        )
        if (
            self.source_node_id is None
            and not self.required_via_node_ids
            and not self.required_transport_allocation_ids
        ):
            raise ValueError("empty supply routing constraint is not authoritative state")


@dataclass(frozen=True)
class SupplyRequirementResolution:
    """Planning-only local coverage and residual transport need for one requirement."""

    requirement: SupplyRequirement
    local_supply_t: float
    external_required_t: float

    def __post_init__(self) -> None:
        if self.local_supply_t < -1e-9 or self.external_required_t < -1e-9:
            raise ValueError("supply requirement resolution amounts must be non-negative")
        if abs(self.local_supply_t + self.external_required_t - self.requirement.amount_t) > 1e-7:
            raise ValueError("supply requirement resolution must conserve requested quantity")

    def external_requirement(self) -> SupplyRequirement | None:
        if self.external_required_t <= 1e-9:
            return None
        requirement = self.requirement
        return SupplyRequirement(
            id=requirement.id,
            owner_kind=requirement.owner_kind,
            owner_id=requirement.owner_id,
            destination_id=requirement.destination_id,
            resource_id=requirement.resource_id,
            amount_t=self.external_required_t,
            priority=requirement.priority,
            recurring_rate_t_per_day=requirement.recurring_rate_t_per_day,
            forecast_requirement_day=requirement.forecast_requirement_day,
            purpose=requirement.purpose,
        )


def resolve_local_supply(
    requirements: Iterable[SupplyRequirement], inventory: InventoryBook
) -> tuple[SupplyRequirementResolution, ...]:
    """Credit observable on-site stock toward future replenishment planning.

    This is deliberately separate from current-tick Resource Claim allocation.
    Higher-priority future needs receive local planning credit first; same-
    priority needs share a shortage proportionally. Existing durable Inventory
    reservations remain unavailable to planning through ``inventory.available``.
    No Inventory state is mutated.
    """

    ordered = tuple(sorted(requirements, key=lambda row: (-row.priority, str(row.id))))
    by_key: dict[tuple[SpatialNodeId, DefinitionId], list[int]] = {}
    local_credit = [0.0 for _ in ordered]
    for index, requirement in enumerate(ordered):
        by_key.setdefault((requirement.destination_id, requirement.resource_id), []).append(index)

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
        SupplyRequirementResolution(
            requirement,
            min(requirement.amount_t, max(0.0, local_credit[index])),
            max(0.0, requirement.amount_t - local_credit[index]),
        )
        for index, requirement in enumerate(ordered)
    )


def external_supply_requirements(
    requirements: Iterable[SupplyRequirement], inventory: InventoryBook
) -> tuple[SupplyRequirement, ...]:
    """Return future need that requires off-site supply; never reserve stock."""

    rows: list[SupplyRequirement] = []
    for resolution in resolve_local_supply(requirements, inventory):
        requirement = resolution.external_requirement()
        if requirement is not None:
            rows.append(requirement)
    return tuple(rows)
