from __future__ import annotations

from dataclasses import dataclass, field

from .shared import DefinitionId, EntityId, SpatialNodeId

StorageClass = str

_EPS = 1e-9


@dataclass(frozen=True)
class InventoryAdmissionState:
    operational_node_id: SpatialNodeId
    storage_class: StorageClass | None
    physical_capacity_t: float | None
    usable_capacity_t: float | None
    occupied_t: float
    admission_capacity_t: float | None
    over_capacity_t: float
    conditioning_required: bool
    blockers: tuple[str, ...] = ()

    @property
    def unlimited(self) -> bool:
        return self.storage_class is None


@dataclass(frozen=True)
class InventoryAdmissionResult:
    requested_t: float
    admitted_t: float
    rejected_t: float
    state_before: InventoryAdmissionState
    state_after: InventoryAdmissionState

    @property
    def fully_admitted(self) -> bool:
        return self.rejected_t <= _EPS


@dataclass
class InventoryBook:
    """Operational Node-scoped stock with reservations and optional storage limits.

    Resources without a registered storage class remain unlimited. This keeps the
    generic core lightweight while allowing gameplay content to opt into storage
    as a real bottleneck where it matters.
    """

    stock: dict[tuple[SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    reserved: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    resource_storage_class: dict[DefinitionId, StorageClass] = field(default_factory=dict)
    # Static site capacity comes from content. Current physical/usable Stock
    # Capacities are derived from it plus installed storage facilities.
    base_storage_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float] = field(default_factory=dict)
    physical_storage_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float] = field(default_factory=dict)
    usable_storage_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float] = field(default_factory=dict)
    external_occupancy: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = field(default_factory=dict)

    def register_storage_class(self, resource_id: DefinitionId, storage_class: StorageClass) -> None:
        existing = self.resource_storage_class.get(resource_id)
        if existing is not None and existing != storage_class:
            raise ValueError(f"storage class already defined for {resource_id}: {existing}")
        self.resource_storage_class[resource_id] = storage_class

    def add_capacity(self, operational_node_id: SpatialNodeId, storage_class: StorageClass, amount_t: float) -> None:
        if amount_t < -1e-9:
            raise ValueError("negative storage capacity")
        key = (operational_node_id, storage_class)
        self.base_storage_capacity_t[key] = self.base_storage_capacity_t.get(key, 0.0) + amount_t
        self.physical_storage_capacity_t[key] = self.physical_storage_capacity_t.get(key, 0.0) + amount_t
        self.usable_storage_capacity_t[key] = self.usable_storage_capacity_t.get(key, 0.0) + amount_t

    def set_capacity_snapshot(
        self,
        physical_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float],
        usable_capacity_t: dict[tuple[SpatialNodeId, StorageClass], float],
    ) -> None:
        self.physical_storage_capacity_t = dict(physical_capacity_t)
        self.usable_storage_capacity_t = {
            key: min(physical_capacity_t.get(key, 0.0), max(0.0, amount))
            for key, amount in usable_capacity_t.items()
        }
        for key, amount in physical_capacity_t.items():
            self.usable_storage_capacity_t.setdefault(key, amount)

    def physical_capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        storage_class = self.resource_storage_class.get(resource_id)
        if storage_class is None:
            return None
        return self.physical_storage_capacity_t.get((operational_node_id, storage_class), 0.0)

    def usable_capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        storage_class = self.resource_storage_class.get(resource_id)
        if storage_class is None:
            return None
        return self.usable_storage_capacity_t.get((operational_node_id, storage_class), 0.0)

    def capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        """Current usable/admission capacity for this resource."""
        return self.usable_capacity(operational_node_id, resource_id)

    def stored_in_class(self, operational_node_id: SpatialNodeId, storage_class: StorageClass) -> float:
        stock = sum(
            amount
            for (loc, resource_id), amount in self.stock.items()
            if loc == operational_node_id and self.resource_storage_class.get(resource_id) == storage_class
        )
        external = sum(
            amount
            for (_owner, loc, resource_id), amount in self.external_occupancy.items()
            if loc == operational_node_id and self.resource_storage_class.get(resource_id) == storage_class
        )
        return stock + external

    def occupy_storage(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        if amount < -1e-9:
            raise ValueError("negative storage occupancy")
        state = self.admission_state(operational_node_id, resource_id)
        free = state.admission_capacity_t
        accepted = amount if free is None else min(amount, free)
        if accepted <= 1e-12:
            return 0.0
        key = (owner_id, operational_node_id, resource_id)
        self.external_occupancy[key] = self.external_occupancy.get(key, 0.0) + accepted
        return accepted

    def release_storage_occupancy(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        if amount < -1e-9:
            raise ValueError("negative storage occupancy release")
        key = (owner_id, operational_node_id, resource_id)
        held = self.external_occupancy.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError("storage occupancy shortfall")
        left = held - amount
        if left <= 1e-9:
            self.external_occupancy.pop(key, None)
        else:
            self.external_occupancy[key] = left

    def admission_state_for_class(
        self, operational_node_id: SpatialNodeId, storage_class: StorageClass
    ) -> InventoryAdmissionState:
        key = (operational_node_id, storage_class)
        physical = max(0.0, self.physical_storage_capacity_t.get(key, 0.0))
        usable = min(physical, max(0.0, self.usable_storage_capacity_t.get(key, 0.0)))
        occupied = self.stored_in_class(operational_node_id, storage_class)
        admission = max(0.0, usable - occupied)
        over_capacity = max(0.0, occupied - usable)
        conditioning_required = usable + _EPS < physical
        blockers: list[str] = []
        if over_capacity > _EPS:
            blockers.append("storage_over_capacity")
        if admission <= _EPS:
            if occupied + _EPS >= physical:
                blockers.append("physical_storage_full")
            elif occupied + _EPS >= usable:
                blockers.append("usable_storage_full")
        if conditioning_required:
            blockers.append("storage_conditioning_required")
        return InventoryAdmissionState(
            operational_node_id, storage_class, physical, usable, occupied, admission,
            over_capacity, conditioning_required, tuple(dict.fromkeys(blockers)),
        )

    def admission_state(
        self, operational_node_id: SpatialNodeId, resource_id: DefinitionId
    ) -> InventoryAdmissionState:
        storage_class = self.resource_storage_class.get(resource_id)
        if storage_class is None:
            return InventoryAdmissionState(
                operational_node_id, None, None, None,
                self.amount(operational_node_id, resource_id), None, 0.0, False, (),
            )
        return self.admission_state_for_class(operational_node_id, storage_class)

    def free_capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        """Compatibility projection of the canonical Inventory Admission state."""
        return self.admission_state(operational_node_id, resource_id).admission_capacity_t

    def amount(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return self.stock.get((operational_node_id, resource_id), 0.0)

    def reserved_total(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return sum(
            amount
            for (owner, loc, res), amount in self.reserved.items()
            if loc == operational_node_id and res == resource_id
        )

    def available(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return max(0.0, self.amount(operational_node_id, resource_id) - self.reserved_total(operational_node_id, resource_id))

    def admit(
        self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> InventoryAdmissionResult:
        if amount < -_EPS:
            raise ValueError("negative admission")
        requested = max(0.0, amount)
        before = self.admission_state(operational_node_id, resource_id)
        accepted = requested if before.admission_capacity_t is None else min(
            requested, before.admission_capacity_t
        )
        if accepted > _EPS:
            key = (operational_node_id, resource_id)
            self.stock[key] = self.stock.get(key, 0.0) + accepted
        after = self.admission_state(operational_node_id, resource_id)
        return InventoryAdmissionResult(
            requested, accepted, max(0.0, requested - accepted), before, after
        )

    def add_up_to(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        """Compatibility projection. New physical inflow should use :meth:`admit`."""
        return self.admit(operational_node_id, resource_id, amount).admitted_t

    def add(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        result = self.admit(operational_node_id, resource_id, amount)
        if not result.fully_admitted:
            raise ValueError(f"storage capacity exceeded: {resource_id}")

    def consume_allocated(
        self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> None:
        """Consume material already authorized by a Resource Allocation.

        Shared availability must have been resolved before Domain execution. This
        method therefore validates conservation against physical stock only; it
        never performs a second allocation decision from current ``available``.
        """
        if amount < -1e-9:
            raise ValueError("negative allocated consumption")
        if amount <= 1e-12:
            return
        key = (operational_node_id, resource_id)
        stock = self.stock.get(key, 0.0)
        if stock + 1e-9 < amount:
            raise RuntimeError("allocated resource stock changed before execution")
        self.stock[key] = max(0.0, stock - amount)

    def stage_allocated(
        self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> None:
        """Move an allocated amount into durable owner-scoped staging."""
        if amount < -1e-9:
            raise ValueError("negative allocated staging amount")
        if amount <= 1e-12:
            return
        key = (operational_node_id, resource_id)
        stock = self.stock.get(key, 0.0)
        if stock + 1e-9 < amount:
            raise RuntimeError("allocated resource stock changed before staging")
        self.stock[key] = max(0.0, stock - amount)
        occupancy_key = (owner_id, operational_node_id, resource_id)
        self.external_occupancy[occupancy_key] = (
            self.external_occupancy.get(occupancy_key, 0.0) + amount
        )

    def staged_for(
        self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId
    ) -> float:
        return self.external_occupancy.get((owner_id, operational_node_id, resource_id), 0.0)

    def stage_reserved(
        self,
        reservation_owner_id: EntityId,
        staging_owner_id: EntityId,
        operational_node_id: SpatialNodeId,
        resource_id: DefinitionId,
        amount: float,
    ) -> None:
        """Convert reserved site stock into durable owner-scoped staging.

        This is an atomic reclassification of material that is already present at
        the site.  Physical storage occupancy is unchanged, while the transient
        reservation becomes persisted external occupancy owned by the finite
        project that procured it.
        """
        if amount < -1e-9:
            raise ValueError("negative reserved staging amount")
        if amount <= 1e-12:
            return
        reservation_key = (reservation_owner_id, operational_node_id, resource_id)
        reserved = self.reserved.get(reservation_key, 0.0)
        if reserved + 1e-9 < amount:
            raise ValueError("reservation shortfall while staging")
        stock_key = (operational_node_id, resource_id)
        stock = self.stock.get(stock_key, 0.0)
        if stock + 1e-9 < amount:
            raise ValueError("stock shortfall despite reservation")

        reservation_left = reserved - amount
        if reservation_left <= 1e-9:
            self.reserved.pop(reservation_key, None)
        else:
            self.reserved[reservation_key] = reservation_left
        self.stock[stock_key] = max(0.0, stock - amount)
        occupancy_key = (staging_owner_id, operational_node_id, resource_id)
        self.external_occupancy[occupancy_key] = (
            self.external_occupancy.get(occupancy_key, 0.0) + amount
        )

    def unstage_to_stock(
        self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> None:
        """Return staged stock to ordinary inventory without changing site occupancy.

        Because no material enters the site, current service/admission capacity
        is irrelevant; the same physical storage remains occupied throughout the
        reclassification.
        """
        if amount < -1e-9:
            raise ValueError("negative unstaging amount")
        key = (owner_id, operational_node_id, resource_id)
        held = self.external_occupancy.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError("staged stock shortfall")
        self.release_storage_occupancy(owner_id, operational_node_id, resource_id, amount)
        stock_key = (operational_node_id, resource_id)
        self.stock[stock_key] = self.stock.get(stock_key, 0.0) + amount

    def reserve(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        if amount < -1e-9:
            raise ValueError("negative reservation")
        if amount <= 1e-12:
            return 0.0
        take = min(amount, self.available(operational_node_id, resource_id))
        key = (owner_id, operational_node_id, resource_id)
        self.reserved[key] = self.reserved.get(key, 0.0) + take
        return take

    def release_reservation(self, owner_id: EntityId) -> None:
        for key in [key for key in self.reserved if key[0] == owner_id]:
            self.reserved.pop(key, None)

    def release_reservations_by_owner_prefix(self, prefix: str) -> None:
        """Release a simulation-owned reservation class by stable owner prefix."""
        for key in [key for key in self.reserved if str(key[0]).startswith(prefix)]:
            self.reserved.pop(key, None)

    def release_reserved_amount(
        self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float
    ) -> None:
        if amount < -1e-9:
            raise ValueError("negative reservation release")
        key = (owner_id, operational_node_id, resource_id)
        held = self.reserved.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError("reservation release exceeds held amount")
        left = held - amount
        if left <= 1e-9:
            self.reserved.pop(key, None)
        else:
            self.reserved[key] = left

    def reserved_for(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return self.reserved.get((owner_id, operational_node_id, resource_id), 0.0)

    def consume_reserved(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        key = (owner_id, operational_node_id, resource_id)
        held = self.reserved.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError(f"reservation shortfall for {owner_id}: {resource_id}")
        stock_key = (operational_node_id, resource_id)
        if self.stock.get(stock_key, 0.0) + 1e-9 < amount:
            raise ValueError("stock shortfall despite reservation")
        self.stock[stock_key] = max(0.0, self.stock[stock_key] - amount)
        left = held - amount
        if left <= 1e-9:
            self.reserved.pop(key, None)
        else:
            self.reserved[key] = left
