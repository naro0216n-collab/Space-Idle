from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING, Iterable

from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
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


class SourceSelectionMode(str, Enum):
    PINNED = "pinned"
    PREFERRED = "preferred"
    ALLOW_ANY = "allow_any"


class PathSelectionMode(str, Enum):
    PINNED = "pinned"
    PREFERRED = "preferred"
    ALLOW_ANY = "allow_any"


@dataclass(frozen=True)
class LogisticsPolicyState:
    """Reusable Player/Scenario intent for source and path/handoff selection.

    Source constraints are represented by ``allowed_source_ids``. PINNED fixes
    that set to exactly one source, PREFERRED names a preferred source while
    retaining fallback inside the allowed set, and ALLOW_ANY delegates selection
    across the allowed set. Path constraints may whitelist handoff nodes and/or
    existing Transport Service identities. PINNED fixes the Movement Plan path,
    PREFERRED records an explicit route metric, and ALLOW_ANY uses the canonical
    BALANCED metric.
    """

    id: EntityId
    source_mode: SourceSelectionMode = SourceSelectionMode.ALLOW_ANY
    allowed_source_ids: tuple[SpatialNodeId, ...] | None = None
    preferred_source_id: SpatialNodeId | None = None
    path_mode: PathSelectionMode = PathSelectionMode.ALLOW_ANY
    explicit_path: tuple[MovementPlanId, ...] | None = None
    allowed_handoff_ids: tuple[SpatialNodeId, ...] | None = None
    allowed_service_ids: tuple[str, ...] | None = None
    path_preference: PathPolicy = PathPolicy.BALANCED

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_mode", SourceSelectionMode(self.source_mode))
        object.__setattr__(self, "path_mode", PathSelectionMode(self.path_mode))
        object.__setattr__(self, "path_preference", PathPolicy(self.path_preference))
        if self.allowed_source_ids is not None:
            normalized_sources = tuple(dict.fromkeys(self.allowed_source_ids))
            if not normalized_sources:
                raise ValueError("allowed source set must be non-empty when provided")
            object.__setattr__(self, "allowed_source_ids", normalized_sources)
        if self.allowed_handoff_ids is not None:
            normalized_handoffs = tuple(dict.fromkeys(self.allowed_handoff_ids))
            object.__setattr__(self, "allowed_handoff_ids", normalized_handoffs)
        if self.allowed_service_ids is not None:
            normalized_services = tuple(dict.fromkeys(self.allowed_service_ids))
            if any(not value for value in normalized_services):
                raise ValueError("allowed service identities must be non-empty")
            object.__setattr__(self, "allowed_service_ids", normalized_services)

        if self.source_mode is SourceSelectionMode.PINNED:
            if self.allowed_source_ids is None or len(self.allowed_source_ids) != 1:
                raise ValueError("pinned source policy requires exactly one allowed source")
            if self.preferred_source_id is not None:
                raise ValueError("pinned source policy cannot also prefer a source")
        elif self.source_mode is SourceSelectionMode.PREFERRED:
            if self.preferred_source_id is None:
                raise ValueError("preferred source policy requires preferred_source_id")
            if (
                self.allowed_source_ids is not None
                and self.preferred_source_id not in self.allowed_source_ids
            ):
                raise ValueError("preferred source must belong to allowed source set")
        elif self.preferred_source_id is not None:
            raise ValueError("ALLOW_ANY source policy cannot carry a preferred source")

        if self.path_mode is PathSelectionMode.PINNED:
            if not self.explicit_path:
                raise ValueError("pinned path policy requires explicit_path")
        elif self.explicit_path is not None:
            raise ValueError("non-pinned path policy cannot carry explicit_path")
        if (
            self.path_mode is PathSelectionMode.ALLOW_ANY
            and self.path_preference is not PathPolicy.BALANCED
        ):
            raise ValueError("ALLOW_ANY path policy uses the canonical BALANCED preference")


@dataclass(frozen=True)
class LogisticsPolicyAssignmentState:
    owner_kind: str
    owner_id: EntityId
    policy_id: EntityId

    def __post_init__(self) -> None:
        if not self.owner_kind:
            raise ValueError("logistics policy owner kind must be non-empty")


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
