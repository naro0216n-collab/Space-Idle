from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .transport.models import PathPolicy

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
    source_id: SpatialNodeId | None = None
    recurring_rate_t_per_day: float | None = None
    forecast_requirement_day: int | None = None
    purpose: str = "replenishment"

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
        if self.amount_t < 0:
            raise ValueError("supply requirement amount must be non-negative")
        if self.source_id is not None and self.source_id == self.destination_id:
            raise ValueError("supply requirement source and destination must differ")
        if self.recurring_rate_t_per_day is not None and self.recurring_rate_t_per_day <= 0:
            raise ValueError("supply requirement recurring rate must be positive")
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
        if self.target_quantity_t < 0:
            raise ValueError("target stock quantity must be non-negative")

    def requirement(self, day: int) -> SupplyRequirement:
        return SupplyRequirement(
            EntityId(f"supply.target_stock:{self.destination_id}:{self.resource_id}"),
            "target_stock",
            self.id,
            self.destination_id,
            self.resource_id,
            self.target_quantity_t,
            self.priority,
            None,
            None,
            day,
            "target_stock",
        )


@dataclass(frozen=True)
class SupplyPolicy:
    """Player sourcing/path preference; never owns Transport Capacity."""

    id: EntityId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    preferred_source_id: SpatialNodeId | None = None
    path_policy: PathPolicy = PathPolicy.FASTEST
    explicit_path: tuple[RouteId, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_policy", PathPolicy(self.path_policy))
        if self.preferred_source_id == self.destination_id:
            raise ValueError("supply source and destination must differ")


@dataclass(frozen=True)
class SupplyRequirementResolution:
    """Planning-only local coverage and residual transport need for one demand."""

    demand: SupplyRequirement
    local_supply_t: float
    external_required_t: float

    def __post_init__(self) -> None:
        if self.local_supply_t < -1e-9 or self.external_required_t < -1e-9:
            raise ValueError("supply requirement resolution amounts must be non-negative")
        if abs(self.local_supply_t + self.external_required_t - self.demand.amount_t) > 1e-7:
            raise ValueError("supply requirement resolution must conserve requested quantity")

    def external_demand(self) -> SupplyRequirement | None:
        if self.external_required_t <= 1e-9:
            return None
        demand = self.demand
        return SupplyRequirement(
            demand.id,
            demand.owner_kind,
            demand.owner_id,
            demand.destination_id,
            demand.resource_id,
            self.external_required_t,
            demand.priority,
            demand.source_id,
            demand.recurring_rate_t_per_day,
            demand.forecast_requirement_day,
            demand.purpose,
        )


def resolve_local_supply(
    demands: Iterable[SupplyRequirement], inventory: InventoryBook
) -> tuple[SupplyRequirementResolution, ...]:
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
        SupplyRequirementResolution(
            demand,
            min(demand.amount_t, max(0.0, local_credit[index])),
            max(0.0, demand.amount_t - local_credit[index]),
        )
        for index, demand in enumerate(ordered)
    )


def external_supply_requirements(
    demands: Iterable[SupplyRequirement], inventory: InventoryBook
) -> tuple[SupplyRequirement, ...]:
    """Return future need that requires off-site supply; never reserve stock."""

    rows: list[SupplyRequirement] = []
    for resolution in resolve_local_supply(demands, inventory):
        demand = resolution.external_demand()
        if demand is not None:
            rows.append(demand)
    return tuple(rows)
