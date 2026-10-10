from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Callable

from .catalog import ResourceDef
from .shared import DefinitionId, EntityId, SpatialNodeId

StoragePoolKey = str
DEFAULT_STORAGE_POOL_KEY: StoragePoolKey = "default"

_EPS = 1e-9


@dataclass(frozen=True)
class InventoryAdmissionState:
    operational_node_id: SpatialNodeId
    storage_pool_key: StoragePoolKey
    physical_capacity_t: float
    usable_capacity_t: float
    occupied_t: float
    admission_capacity_t: float
    over_capacity_t: float
    blockers: tuple[str, ...] = ()
    limiting_factors: tuple[str, ...] = ()


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
    """Operational Node-scoped stock and admission ownership.

    Resource→pool compatibility comes from immutable Content definitions. All
    ordinary physical Resources use the finite default pool; an explicit pool
    key is only needed for genuinely special storage requirements.
    """

    resource_definitions: Mapping[DefinitionId, ResourceDef] = field(default_factory=dict)
    stock: dict[tuple[SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    reserved: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    physical_storage_capacity_t: dict[tuple[SpatialNodeId, StoragePoolKey], float] = field(default_factory=dict)
    usable_storage_capacity_t: dict[tuple[SpatialNodeId, StoragePoolKey], float] = field(default_factory=dict)
    storage_limiting_factors: dict[tuple[SpatialNodeId, StoragePoolKey], tuple[str, ...]] = field(default_factory=dict)
    external_occupancy: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    # Only an explicit analysis scope attaches a sink. This transient callback is
    # neither authoritative State nor part of the Save codec.
    _settlement_observer: Callable[[str, SpatialNodeId, DefinitionId, float, str, str | None, str | None, str | None], None] | None = field(
        default=None, init=False, repr=False, compare=False,
    )

    def _record_settlement(self, direction: str, node_id: SpatialNodeId, resource_id: DefinitionId,
                           amount: float, operation: str, owner: EntityId | None = None,
                           counterparty: str | None = None, activity: str | None = None) -> None:
        if self._settlement_observer is not None and amount > _EPS:
            self._settlement_observer(direction, node_id, resource_id, amount, operation,
                                      None if owner is None else str(owner), counterparty, activity)

    def storage_pool_for_resource(self, resource_id: DefinitionId) -> StoragePoolKey:
        definition = self.resource_definitions.get(resource_id)
        if definition is None or definition.storage_pool_key is None:
            return DEFAULT_STORAGE_POOL_KEY
        return definition.storage_pool_key

    def set_capacity_snapshot(
        self,
        physical_capacity_t: dict[tuple[SpatialNodeId, StoragePoolKey], float],
        usable_capacity_t: dict[tuple[SpatialNodeId, StoragePoolKey], float],
        limiting_factors: dict[tuple[SpatialNodeId, StoragePoolKey], tuple[str, ...]] | None = None,
    ) -> None:
        self.physical_storage_capacity_t = {key: max(0.0, amount) for key, amount in physical_capacity_t.items()}
        self.usable_storage_capacity_t = {
            key: min(self.physical_storage_capacity_t.get(key, 0.0), max(0.0, amount))
            for key, amount in usable_capacity_t.items()
        }
        for key, amount in self.physical_storage_capacity_t.items():
            self.usable_storage_capacity_t.setdefault(key, amount)
        self.storage_limiting_factors = {
            key: tuple(dict.fromkeys(values))
            for key, values in (limiting_factors or {}).items()
            if key in self.physical_storage_capacity_t and values
        }

    def physical_capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        pool_key = self.storage_pool_for_resource(resource_id)
        return self.physical_storage_capacity_t.get((operational_node_id, pool_key), 0.0)

    def usable_capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        pool_key = self.storage_pool_for_resource(resource_id)
        return self.usable_storage_capacity_t.get((operational_node_id, pool_key), 0.0)

    def capacity(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return self.usable_capacity(operational_node_id, resource_id)

    def stored_in_pool(self, operational_node_id: SpatialNodeId, pool_key: StoragePoolKey) -> float:
        stock = sum(
            amount
            for (loc, resource_id), amount in self.stock.items()
            if loc == operational_node_id and self.storage_pool_for_resource(resource_id) == pool_key
        )
        external = sum(
            amount
            for (_owner, loc, resource_id), amount in self.external_occupancy.items()
            if loc == operational_node_id and self.storage_pool_for_resource(resource_id) == pool_key
        )
        return stock + external

    def occupy_storage(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> float:
        if amount < -1e-9:
            raise ValueError("negative storage occupancy")
        state = self.admission_state(operational_node_id, resource_id)
        accepted = min(amount, state.admission_capacity_t)
        if accepted <= 1e-12:
            return 0.0
        key = (owner_id, operational_node_id, resource_id)
        self.external_occupancy[key] = self.external_occupancy.get(key, 0.0) + accepted
        self._record_settlement("external_storage_in", operational_node_id, resource_id, accepted,
                                "inventory.occupy_storage", owner_id)
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
        self._record_settlement("external_storage_out", operational_node_id, resource_id, amount,
                                "inventory.release_storage_occupancy", owner_id)

    def admission_state_for_pool(
        self, operational_node_id: SpatialNodeId, pool_key: StoragePoolKey
    ) -> InventoryAdmissionState:
        key = (operational_node_id, pool_key)
        physical = max(0.0, self.physical_storage_capacity_t.get(key, 0.0))
        usable = min(physical, max(0.0, self.usable_storage_capacity_t.get(key, 0.0)))
        occupied = self.stored_in_pool(operational_node_id, pool_key)
        admission = max(0.0, usable - occupied)
        over_capacity = max(0.0, occupied - usable)
        blockers: list[str] = []
        if over_capacity > _EPS:
            blockers.append("storage_over_capacity")
        if admission <= _EPS:
            if occupied + _EPS >= physical:
                blockers.append("storage_capacity_unavailable" if physical <= _EPS else "physical_storage_full")
            elif occupied + _EPS >= usable:
                blockers.append("usable_storage_shortfall")
        limiting = self.storage_limiting_factors.get(key, ())
        return InventoryAdmissionState(
            operational_node_id, pool_key, physical, usable, occupied, admission,
            over_capacity, tuple(dict.fromkeys(blockers)), limiting,
        )

    def admission_state(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> InventoryAdmissionState:
        return self.admission_state_for_pool(operational_node_id, self.storage_pool_for_resource(resource_id))

    def can_admit_resources(self, operational_node_id: SpatialNodeId,
                            resources: Mapping[DefinitionId, float]) -> bool:
        """Check a batch against shared Storage pools, not each item separately."""
        by_pool: dict[StoragePoolKey, float] = {}
        for resource_id, amount in resources.items():
            if amount <= _EPS:
                continue
            pool = self.storage_pool_for_resource(resource_id)
            by_pool[pool] = by_pool.get(pool, 0.0) + amount
        return all(self.admission_state_for_pool(operational_node_id, pool).admission_capacity_t + _EPS >= amount
                   for pool, amount in by_pool.items())

    def amount(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return self.stock.get((operational_node_id, resource_id), 0.0)

    def reserved_total(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return sum(
            amount
            for (_owner, loc, res), amount in self.reserved.items()
            if loc == operational_node_id and res == resource_id
        )

    def available(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        return max(0.0, self.amount(operational_node_id, resource_id) - self.reserved_total(operational_node_id, resource_id))

    def admit(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float, *,
              source_owner: str | None = None, activity_id: str | None = None) -> InventoryAdmissionResult:
        if amount < -_EPS:
            raise ValueError("negative admission")
        requested = max(0.0, amount)
        before = self.admission_state(operational_node_id, resource_id)
        accepted = min(requested, before.admission_capacity_t)
        if accepted > _EPS:
            key = (operational_node_id, resource_id)
            self.stock[key] = self.stock.get(key, 0.0) + accepted
        self._record_settlement("inventory_in", operational_node_id, resource_id, accepted, "inventory.admit",
                                counterparty=source_owner, activity=activity_id)
        after = self.admission_state(operational_node_id, resource_id)
        return InventoryAdmissionResult(requested, accepted, max(0.0, requested - accepted), before, after)

    def add(self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float) -> None:
        result = self.admit(operational_node_id, resource_id, amount)
        if not result.fully_admitted:
            raise ValueError(f"storage capacity exceeded: {resource_id}")

    def consume_allocated(
        self, operational_node_id: SpatialNodeId, resource_id: DefinitionId, amount: float, *,
        destination_owner: str | None = None, activity_id: str | None = None,
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
        self._record_settlement("inventory_out", operational_node_id, resource_id, amount, "inventory.consume_allocated",
                                counterparty=destination_owner, activity=activity_id)

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
        self._record_settlement("inventory_out", operational_node_id, resource_id, amount,
                                "inventory.stage_allocated", owner_id)
        self._record_settlement("external_storage_in", operational_node_id, resource_id, amount,
                                "inventory.stage_allocated", owner_id)

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
        self._record_settlement("inventory_out", operational_node_id, resource_id, amount,
                                "inventory.stage_reserved", staging_owner_id)
        self._record_settlement("external_storage_in", operational_node_id, resource_id, amount,
                                "inventory.stage_reserved", staging_owner_id)

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
        self._record_settlement("inventory_in", operational_node_id, resource_id, amount,
                                "inventory.unstage_to_stock", owner_id)

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

    def consume_reserved(self, owner_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId,
                         amount: float, *, destination_owner: str | None = None,
                         activity_id: str | None = None) -> None:
        key = (owner_id, operational_node_id, resource_id)
        held = self.reserved.get(key, 0.0)
        if held + 1e-9 < amount:
            raise ValueError(f"reservation shortfall for {owner_id}: {resource_id}")
        stock_key = (operational_node_id, resource_id)
        if self.stock.get(stock_key, 0.0) + 1e-9 < amount:
            raise ValueError("stock shortfall despite reservation")
        self.stock[stock_key] = max(0.0, self.stock[stock_key] - amount)
        self._record_settlement("inventory_out", operational_node_id, resource_id, amount,
                                "inventory.consume_reserved", owner_id,
                                counterparty=destination_owner, activity=activity_id)
        left = held - amount
        if left <= 1e-9:
            self.reserved.pop(key, None)
        else:
            self.reserved[key] = left
