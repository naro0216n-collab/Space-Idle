from __future__ import annotations

from dataclasses import dataclass, field

from .shared import DefinitionId, EntityId, SpatialNodeId

StorageClass = str


@dataclass
class InventoryBook:
    """Location-scoped stock with reservations and optional storage limits.

    Resources without a registered storage class remain unlimited. This keeps the
    generic core lightweight while allowing gameplay content to opt into storage
    as a real bottleneck where it matters.
    """

    stock: dict[tuple[SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    reserved: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    resource_storage_class: dict[DefinitionId, StorageClass] = field(default_factory=dict)
    # Static site capacity comes from content. Current physical/service
    # capacities are derived from it plus installed storage facilities.
    base_storage_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float] = field(default_factory=dict)
    storage_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float] = field(default_factory=dict)
    storage_service_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float] = field(default_factory=dict)
    external_occupancy: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = field(default_factory=dict)

    def register_storage_class(self, resource_id: DefinitionId, storage_class: StorageClass) -> None:
        existing = self.resource_storage_class.get(resource_id)
        if existing is not None and existing != storage_class:
            raise ValueError(f"storage class already defined for {resource_id}: {existing}")
        self.resource_storage_class[resource_id] = storage_class

    def add_capacity(self, location_id: SpatialNodeId, storage_class: StorageClass, amount_t: float) -> None:
        if amount_t < -1e-9:
            raise ValueError("negative storage capacity")
        key = (location_id, storage_class)
        self.base_storage_capacity_t[key] = self.base_storage_capacity_t.get(key, 0.0) + amount_t
        self.storage_capacity_t[key] = self.storage_capacity_t.get(key, 0.0) + amount_t
        self.storage_service_capacity_t[key] = self.storage_service_capacity_t.get(key, 0.0) + amount_t

    def set_capacity_snapshot(
        self,
        physical_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float],
        service_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float],
    ) -> None:
        self.storage_capacity_t = dict(physical_capacity_t)
        self.storage_service_capacity_t = {
            key: min(physical_capacity_t.get(key, 0.0), max(0.0, amount))
            for key, amount in service_capacity_t.items()
        }
        for key, amount in physical_capacity_t.items():
            self.storage_service_capacity_t.setdefault(key, amount)

    def physical_capacity(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        storage_class = self.resource_storage_class.get(resource_id)
        if storage_class is None:
            return None
        return self.storage_capacity_t.get((location_id, storage_class), 0.0)

    def service_capacity(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        storage_class = self.resource_storage_class.get(resource_id)
        if storage_class is None:
            return None
        return self.storage_service_capacity_t.get((location_id, storage_class), 0.0)

    def capacity(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        """Current usable/admission capacity for this resource."""
        return self.service_capacity(location_id, resource_id)

    def stored_in_class(self, location_id: SpatialNodeId, storage_class: StorageClass) -> float:
        stock = sum(
            amount
            for (loc, resource_id), amount in self.stock.items()
            if loc == location_id and self.resource_storage_class.get(resource_id) == storage_class
        )
        external = sum(
            amount
            for (_owner, loc, resource_id), amount in self.external_occupancy.items()
            if loc == location_id and self.resource_storage_class.get(resource_id) == storage_class
        )
        return stock + external

    def occupy_storage(self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        if amount < -1e-9:
            raise ValueError("negative storage occupancy")
        free = self.free_capacity(location_id, resource_id)
        accepted = amount if free is None else min(amount, free)
        if accepted <= 1e-12:
            return 0.0
        key = (owner_id, location_id, resource_id)
        self.external_occupancy[key] = self.external_occupancy.get(key, 0.0) + accepted
        return accepted

    def release_storage_occupancy(self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        if amount < -1e-9:
            raise ValueError("negative storage occupancy release")
        key = (owner_id, location_id, resource_id)
        held = self.external_occupancy.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError("storage occupancy shortfall")
        left = held - amount
        if left <= 1e-9:
            self.external_occupancy.pop(key, None)
        else:
            self.external_occupancy[key] = left

    def free_capacity(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        storage_class = self.resource_storage_class.get(resource_id)
        if storage_class is None:
            return None
        capacity = self.storage_service_capacity_t.get((location_id, storage_class), 0.0)
        return max(0.0, capacity - self.stored_in_class(location_id, storage_class))

    def amount(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return self.stock.get((location_id, resource_id), 0.0)

    def reserved_total(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return sum(
            amount
            for (owner, loc, res), amount in self.reserved.items()
            if loc == location_id and res == resource_id
        )

    def available(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return max(0.0, self.amount(location_id, resource_id) - self.reserved_total(location_id, resource_id))

    def add_up_to(self, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        if amount < -1e-9:
            raise ValueError("negative add")
        free = self.free_capacity(location_id, resource_id)
        accepted = amount if free is None else min(amount, free)
        if accepted <= 1e-12:
            return 0.0
        key = (location_id, resource_id)
        self.stock[key] = self.stock.get(key, 0.0) + accepted
        return accepted

    def add(self, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        accepted = self.add_up_to(location_id, resource_id, amount)
        if accepted + 1e-9 < amount:
            raise ValueError(f"storage capacity exceeded: {resource_id}")

    def take_unreserved(self, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> bool:
        if amount < -1e-9:
            raise ValueError("negative take")
        if self.available(location_id, resource_id) + 1e-9 < amount:
            return False
        key = (location_id, resource_id)
        self.stock[key] = max(0.0, self.stock.get(key, 0.0) - amount)
        return True

    def stage_unreserved(
        self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> bool:
        """Move owned stock into a staging bucket without changing site occupancy.

        This is an internal reclassification, not a new inflow. It therefore remains
        valid when service capacity has temporarily fallen below already occupied
        physical capacity (for example, underpowered refrigerated storage).
        """
        if amount < -1e-9:
            raise ValueError("negative staging amount")
        if self.available(location_id, resource_id) + 1e-9 < amount:
            return False
        stock_key = (location_id, resource_id)
        self.stock[stock_key] = max(0.0, self.stock.get(stock_key, 0.0) - amount)
        occupancy_key = (owner_id, location_id, resource_id)
        self.external_occupancy[occupancy_key] = self.external_occupancy.get(occupancy_key, 0.0) + amount
        return True

    def reserve(self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        if amount < -1e-9:
            raise ValueError("negative reservation")
        if amount <= 1e-12:
            return 0.0
        take = min(amount, self.available(location_id, resource_id))
        key = (owner_id, location_id, resource_id)
        self.reserved[key] = self.reserved.get(key, 0.0) + take
        return take

    def release_reservation(self, owner_id: EntityId) -> None:
        for key in [key for key in self.reserved if key[0] == owner_id]:
            self.reserved.pop(key, None)

    def release_reserved_amount(
        self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> None:
        if amount < -1e-9:
            raise ValueError("negative reservation release")
        key = (owner_id, location_id, resource_id)
        held = self.reserved.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError("reservation release exceeds held amount")
        left = held - amount
        if left <= 1e-9:
            self.reserved.pop(key, None)
        else:
            self.reserved[key] = left

    def reserved_for(self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return self.reserved.get((owner_id, location_id, resource_id), 0.0)

    def consume_reserved(self, owner_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        key = (owner_id, location_id, resource_id)
        held = self.reserved.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError(f"reservation shortfall for {owner_id}: {resource_id}")
        stock_key = (location_id, resource_id)
        if self.stock.get(stock_key, 0.0) + 1e-9 < amount:
            raise ValueError("stock shortfall despite reservation")
        self.stock[stock_key] = max(0.0, self.stock[stock_key] - amount)
        left = held - amount
        if left <= 1e-9:
            self.reserved.pop(key, None)
        else:
            self.reserved[key] = left
