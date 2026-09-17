from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook, FacilityLifecycle
from .facility_lifecycle import FacilityLifecycleBlocker
from .inventory import InventoryBook, StorageClass
from .power import PowerSnapshot
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass(frozen=True)
class StorageProviderSpec:
    """Physical storage installed by a facility.

    ``power_sensitive_classes`` identifies storage services whose *usable*
    capacity depends on current power allocation. Physical containment remains
    installed even when service is unavailable; this prevents power loss from
    deleting stock while still blocking additional inflow into unserviced
    storage.
    """

    facility_def_id: DefinitionId
    capacity_t_by_class: dict[StorageClass, float]
    power_sensitive_classes: frozenset[StorageClass] = frozenset()

    def __post_init__(self) -> None:
        if any(amount < 0 for amount in self.capacity_t_by_class.values()):
            raise ValueError("negative storage provider capacity")
        unknown = self.power_sensitive_classes - set(self.capacity_t_by_class)
        if unknown:
            raise ValueError(f"power-sensitive storage class has no capacity: {sorted(unknown)}")


@dataclass
class StorageService:
    providers: dict[DefinitionId, StorageProviderSpec]
    inventory: InventoryBook
    facilities: FacilityBook

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
        for storage_class, target_capacity in provider.capacity_t_by_class.items():
            physical = self.inventory.physical_storage_capacity_t.get((node_id, storage_class), 0.0)
            remaining = max(0.0, physical - target_capacity)
            occupied = self.inventory.stored_in_class(node_id, storage_class)
            if occupied > remaining + 1e-9:
                blockers.append(FacilityLifecycleBlocker(
                    "storage_stock",
                    f"{storage_class}: occupied={occupied:g}, remaining_physical={remaining:g}",
                ))
        return tuple(blockers)

    def refresh(self, day: int, power_by_operational_node: dict[SpatialNodeId, PowerSnapshot]) -> None:
        """Rebuild current physical and serviced capacities from static site state
        plus installed facilities.

        This state is derived and deliberately not persisted. Saves restore
        facilities and static content, then recompute storage capacity.
        """

        physical = dict(self.inventory.base_storage_capacity_t)
        usable = dict(self.inventory.base_storage_capacity_t)

        for facility in self.facilities.facilities.values():
            if facility.lifecycle is FacilityLifecycle.DECOMMISSIONING:
                continue
            provider = self.providers.get(facility.definition_id)
            if provider is None:
                continue
            compatible = self.facilities.is_environmentally_compatible(facility, day)
            snapshot = power_by_operational_node.get(facility.operational_node_id)
            utilization = 1.0
            if snapshot is not None:
                utilization = max(0.0, min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)))
            maintenance = (
                1.0
                if snapshot is None
                else snapshot.maintenance_factor_by_facility.get(facility.id, 1.0)
            )

            for storage_class, capacity in provider.capacity_t_by_class.items():
                key = (facility.operational_node_id, storage_class)
                physical[key] = physical.get(key, 0.0) + capacity
                if not compatible:
                    factor = 0.0
                elif storage_class in provider.power_sensitive_classes:
                    factor = utilization * maintenance
                else:
                    factor = maintenance
                usable[key] = usable.get(key, 0.0) + capacity * factor

        self.inventory.set_capacity_snapshot(physical, usable)
