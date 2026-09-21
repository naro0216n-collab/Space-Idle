from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .execution_requirements import StockOrPoolAdmissionRequirement
from .inventory import InventoryBook, StoragePoolKey
from .shared import DefinitionId, SpatialNodeId

_EPS = 1e-9


@dataclass(frozen=True)
class SalvageRecoveryProjection:
    recoverable_fraction: float
    recovered_by_resource: tuple[tuple[DefinitionId, float], ...]


def _normalized_potential(
    recovery_potential: Mapping[DefinitionId, float] | Iterable[tuple[DefinitionId, float]],
) -> tuple[tuple[DefinitionId, float], ...]:
    items = recovery_potential.items() if isinstance(recovery_potential, Mapping) else recovery_potential
    merged: dict[DefinitionId, float] = {}
    for resource_id, amount in items:
        amount = float(amount)
        if amount < -_EPS:
            raise ValueError("salvage recovery potential must be non-negative")
        if amount <= _EPS:
            continue
        merged[resource_id] = merged.get(resource_id, 0.0) + amount
    return tuple(sorted(merged.items(), key=lambda row: str(row[0])))


def salvage_admission_requirements(
    inventory: InventoryBook,
    recovery_potential: Mapping[DefinitionId, float] | Iterable[tuple[DefinitionId, float]],
) -> tuple[StockOrPoolAdmissionRequirement, ...]:
    """Represent one disposal settlement as shared compatible-pool admission demand."""
    by_pool: dict[StoragePoolKey, float] = {}
    for resource_id, amount in _normalized_potential(recovery_potential):
        pool_key = inventory.storage_pool_for_resource(resource_id)
        by_pool[pool_key] = by_pool.get(pool_key, 0.0) + amount
    return tuple(
        StockOrPoolAdmissionRequirement(pool_key, amount)
        for pool_key, amount in sorted(by_pool.items())
    )


def project_salvage_recovery(
    inventory: InventoryBook,
    operational_node_id: SpatialNodeId,
    recovery_potential: Mapping[DefinitionId, float] | Iterable[tuple[DefinitionId, float]],
    *,
    admission_headroom_by_pool: Mapping[StoragePoolKey, float] | None = None,
) -> SalvageRecoveryProjection:
    """Preview recoverable salvage without becoming settlement authority.

    The authoritative recovery fraction is the shared Execution Allocation
    fulfillment.  This helper is only a read projection for decision UI.
    """
    potential = _normalized_potential(recovery_potential)
    by_pool: dict[StoragePoolKey, float] = {}
    for resource_id, amount in potential:
        pool_key = inventory.storage_pool_for_resource(resource_id)
        by_pool[pool_key] = by_pool.get(pool_key, 0.0) + amount
    fraction = 1.0
    for pool_key, amount in by_pool.items():
        if amount <= _EPS:
            continue
        if admission_headroom_by_pool is None:
            headroom = inventory.admission_state_for_pool(
                operational_node_id, pool_key
            ).admission_capacity_t
        else:
            headroom = max(0.0, float(admission_headroom_by_pool.get(pool_key, 0.0)))
        fraction = min(fraction, headroom / amount)
    fraction = min(1.0, max(0.0, fraction))
    return SalvageRecoveryProjection(
        fraction,
        tuple((resource_id, amount * fraction) for resource_id, amount in potential),
    )


def settle_salvage_recovery(
    inventory: InventoryBook,
    operational_node_id: SpatialNodeId,
    recovery_potential: Mapping[DefinitionId, float] | Iterable[tuple[DefinitionId, float]],
    recoverable_fraction: float,
) -> tuple[tuple[DefinitionId, float], ...]:
    """Materialize only the fraction authorized by shared Allocation."""
    fraction = float(recoverable_fraction)
    if fraction < -_EPS or fraction > 1.0 + _EPS:
        raise ValueError("salvage recoverable fraction must be within 0..1")
    fraction = min(1.0, max(0.0, fraction))
    recovered: list[tuple[DefinitionId, float]] = []
    for resource_id, potential in _normalized_potential(recovery_potential):
        amount = potential * fraction
        if amount <= _EPS:
            continue
        result = inventory.admit(operational_node_id, resource_id, amount)
        if not result.fully_admitted:
            raise RuntimeError("allocated salvage admission changed before settlement")
        recovered.append((resource_id, result.admitted_t))
    return tuple(recovered)
