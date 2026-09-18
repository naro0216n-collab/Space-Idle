from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook, FacilityLifecycle
from .facility_lifecycle import FacilityLifecycleBlocker
from .inventory import InventoryBook, StoragePoolKey
from .power import PowerSnapshot
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass(frozen=True)
class StorageProviderSpec:
    """Physical storage capacity supplied by one Facility definition."""

    facility_def_id: DefinitionId
    capacity_t_by_pool: dict[StoragePoolKey, float]
    power_sensitive_pools: frozenset[StoragePoolKey] = frozenset()

    def __post_init__(self) -> None:
        if any(amount < 0 for amount in self.capacity_t_by_pool.values()):
            raise ValueError("negative storage provider capacity")
        unknown = self.power_sensitive_pools - set(self.capacity_t_by_pool)
        if unknown:
            raise ValueError(f"power-sensitive storage pool has no capacity: {sorted(unknown)}")


@dataclass
class StorageService:
    providers: dict[DefinitionId, StorageProviderSpec]
    inventory: InventoryBook
    facilities: FacilityBook
    # Scenario/world infrastructure is authoritative Storage-domain State. It
    # is not an Inventory-owned raw capacity escape hatch.
    infrastructure_capacity_t: dict[tuple[SpatialNodeId, StoragePoolKey], float] = field(default_factory=dict)

    def set_infrastructure_capacity(
        self, operational_node_id: SpatialNodeId, pool_key: StoragePoolKey, amount_t: float
    ) -> None:
        if amount_t < -1e-9:
            raise ValueError("negative storage infrastructure capacity")
        self.infrastructure_capacity_t[(operational_node_id, pool_key)] = max(0.0, amount_t)

    def facility_decommission_blockers(
        self, facility_id: EntityId
    ) -> tuple[FacilityLifecycleBlocker, ...]:
        facility = self.facilities.facilities.get(facility_id)
        if facility is None:
            return ()
        provider = self.providers.get(facility.definition_id)
        if provider is None:
            return ()
        blockers: list[FacilityLifecycleBlocker] = []
        node_id = facility.operational_node_id
        for pool_key, target_capacity in provider.capacity_t_by_pool.items():
            physical = self.inventory.physical_storage_capacity_t.get((node_id, pool_key), 0.0)
            remaining = max(0.0, physical - target_capacity)
            occupied = self.inventory.stored_in_pool(node_id, pool_key)
            if occupied > remaining + 1e-9:
                blockers.append(FacilityLifecycleBlocker(
                    "storage_stock",
                    f"{pool_key}: occupied={occupied:g}, remaining_physical={remaining:g}",
                ))
        return tuple(blockers)

    def _capacity_for_node(
        self, operational_node_id: SpatialNodeId, day: int, power: PowerSnapshot | None
    ) -> tuple[dict[StoragePoolKey, float], dict[StoragePoolKey, float], dict[StoragePoolKey, tuple[str, ...]]]:
        physical = {
            pool_key: amount
            for (node_id, pool_key), amount in self.infrastructure_capacity_t.items()
            if node_id == operational_node_id
        }
        usable = dict(physical)
        limiter_lists: dict[StoragePoolKey, list[str]] = {}
        for facility in self.facilities.all_at(operational_node_id):
            if facility.lifecycle is FacilityLifecycle.DECOMMISSIONING:
                continue
            provider = self.providers.get(facility.definition_id)
            if provider is None:
                continue
            compatible = self.facilities.is_environmentally_compatible(facility, day)
            utilization = (
                1.0
                if power is None
                else max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            )
            maintenance = (
                1.0
                if power is None
                else max(0.0, min(1.0, power.maintenance_factor_by_facility.get(facility.id, 1.0)))
            )
            for pool_key, capacity in provider.capacity_t_by_pool.items():
                physical[pool_key] = physical.get(pool_key, 0.0) + capacity
                if not compatible:
                    factor = 0.0
                    limiter_lists.setdefault(pool_key, []).append("storage_environment_unavailable")
                elif pool_key in provider.power_sensitive_pools:
                    factor = utilization * maintenance
                    if utilization < 1.0 - 1e-9:
                        limiter_lists.setdefault(pool_key, []).append("storage_power_limited")
                    if maintenance < 1.0 - 1e-9:
                        limiter_lists.setdefault(pool_key, []).append("storage_maintenance_limited")
                else:
                    factor = maintenance
                    if maintenance < 1.0 - 1e-9:
                        limiter_lists.setdefault(pool_key, []).append("storage_maintenance_limited")
                usable[pool_key] = usable.get(pool_key, 0.0) + capacity * factor
        limiters = {key: tuple(dict.fromkeys(values)) for key, values in limiter_lists.items() if values}
        return physical, usable, limiters

    def refresh_node(
        self, operational_node_id: SpatialNodeId, day: int, power: PowerSnapshot | None
    ) -> None:
        node_physical, node_usable, node_limiters = self._capacity_for_node(operational_node_id, day, power)
        physical = {key: amount for key, amount in self.inventory.physical_storage_capacity_t.items() if key[0] != operational_node_id}
        usable = {key: amount for key, amount in self.inventory.usable_storage_capacity_t.items() if key[0] != operational_node_id}
        limiters = {key: values for key, values in self.inventory.storage_limiting_factors.items() if key[0] != operational_node_id}
        physical.update({(operational_node_id, pool_key): amount for pool_key, amount in node_physical.items()})
        usable.update({(operational_node_id, pool_key): amount for pool_key, amount in node_usable.items()})
        limiters.update({(operational_node_id, pool_key): values for pool_key, values in node_limiters.items()})
        self.inventory.set_capacity_snapshot(physical, usable, limiters)

    def refresh(self, day: int, power_by_operational_node: dict[SpatialNodeId, PowerSnapshot]) -> None:
        node_ids = {node_id for node_id, _pool_key in self.infrastructure_capacity_t}
        node_ids.update(facility.operational_node_id for facility in self.facilities.facilities.values())
        physical: dict[tuple[SpatialNodeId, StoragePoolKey], float] = {}
        usable: dict[tuple[SpatialNodeId, StoragePoolKey], float] = {}
        limiters: dict[tuple[SpatialNodeId, StoragePoolKey], tuple[str, ...]] = {}
        for operational_node_id in sorted(node_ids, key=str):
            node_physical, node_usable, node_limiters = self._capacity_for_node(
                operational_node_id, day, power_by_operational_node.get(operational_node_id)
            )
            physical.update({(operational_node_id, pool_key): amount for pool_key, amount in node_physical.items()})
            usable.update({(operational_node_id, pool_key): amount for pool_key, amount in node_usable.items()})
            limiters.update({(operational_node_id, pool_key): values for pool_key, values in node_limiters.items()})
        self.inventory.set_capacity_snapshot(physical, usable, limiters)
