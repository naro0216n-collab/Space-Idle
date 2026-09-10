from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook, StorageClass
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId


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

    def refresh(self, day: int, power_by_location: dict[SpatialNodeId, PowerSnapshot]) -> None:
        """Rebuild current physical and serviced capacities from static site state
        plus installed facilities.

        This state is derived and deliberately not persisted. Saves restore
        facilities and static content, then recompute storage capacity.
        """

        physical = dict(self.inventory.base_storage_capacity_t)
        service = dict(self.inventory.base_storage_capacity_t)

        for facility in self.facilities.facilities.values():
            provider = self.providers.get(facility.definition_id)
            if provider is None:
                continue
            compatible = self.facilities.is_environmentally_compatible(facility, day)
            snapshot = power_by_location.get(facility.location_id)
            utilization = 1.0
            if snapshot is not None:
                utilization = max(0.0, min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)))
            maintenance = (
                self.facilities.maintenance_factor(facility.id)
                if snapshot is None
                else snapshot.maintenance_factor_by_facility.get(
                    facility.id, self.facilities.maintenance_factor(facility.id)
                )
            )

            for storage_class, capacity in provider.capacity_t_by_class.items():
                key = (facility.location_id, storage_class)
                physical[key] = physical.get(key, 0.0) + capacity
                if not compatible:
                    factor = 0.0
                elif storage_class in provider.power_sensitive_classes:
                    factor = utilization * maintenance
                else:
                    factor = maintenance
                service[key] = service.get(key, 0.0) + capacity * factor

        self.inventory.set_capacity_snapshot(physical, service)
