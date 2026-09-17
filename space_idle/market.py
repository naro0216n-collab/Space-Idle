from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from math import isfinite

from .execution_requirements import (
    AllocationConstraintKey,
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    PoolRequirement,
    ResourceRequirement,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
    allocate_execution_requirements,
    pool_constraint,
)
from .inventory import InventoryBook
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, EntityId, SpatialNodeId
from .supply import SupplyRequirement

_EPS = 1e-9


@dataclass
class FundsState:
    """Organization-wide settlement balance for the External Resource Market only."""

    balance: float

    def __post_init__(self) -> None:
        if not isfinite(self.balance) or self.balance < -_EPS:
            raise ValueError("funds balance must be finite and non-negative")


@dataclass(frozen=True)
class MarketAvailabilityDef:
    resource_id: DefinitionId
    initial_t: float
    capacity_t: float
    replenishment_t_per_day: float = 0.0

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (self.initial_t, self.capacity_t, self.replenishment_t_per_day)):
            raise ValueError("market availability values must be finite")
        if self.initial_t < -_EPS or self.capacity_t < -_EPS or self.replenishment_t_per_day < -_EPS:
            raise ValueError("market availability values must be non-negative")
        if self.initial_t > self.capacity_t + _EPS:
            raise ValueError("market initial availability exceeds capacity")


@dataclass(frozen=True)
class MarketProviderDef:
    id: DefinitionId
    display_name: str
    buy_offers_musd_per_t: tuple[tuple[DefinitionId, float], ...] = ()
    sell_offers_musd_per_t: tuple[tuple[DefinitionId, float], ...] = ()
    supply: tuple[MarketAvailabilityDef, ...] = ()
    demand: tuple[MarketAvailabilityDef, ...] = ()
    lead_time_days: int = 0

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("market provider display name must be non-empty")
        if self.lead_time_days < 0:
            raise ValueError("market lead time must be non-negative")
        for label, offers in (("buy", self.buy_offers_musd_per_t), ("sell", self.sell_offers_musd_per_t)):
            seen: set[DefinitionId] = set()
            for resource_id, price in offers:
                if resource_id in seen:
                    raise ValueError(f"duplicate market {label} offer: {resource_id}")
                seen.add(resource_id)
                if not isfinite(price) or price < -_EPS:
                    raise ValueError("market offer price must be finite and non-negative")
        for label, rows in (("supply", self.supply), ("demand", self.demand)):
            ids = [row.resource_id for row in rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate market {label} availability")
        buy_resources = {resource_id for resource_id, _ in self.buy_offers_musd_per_t}
        sell_resources = {resource_id for resource_id, _ in self.sell_offers_musd_per_t}
        if {row.resource_id for row in self.supply} - buy_resources:
            raise ValueError("market supply availability requires a buy offer")
        if {row.resource_id for row in self.demand} - sell_resources:
            raise ValueError("market demand availability requires a sell offer")

    def buy_price(self, resource_id: DefinitionId) -> float | None:
        return next((price for rid, price in self.buy_offers_musd_per_t if rid == resource_id), None)

    def sell_price(self, resource_id: DefinitionId) -> float | None:
        return next((price for rid, price in self.sell_offers_musd_per_t if rid == resource_id), None)

    def supply_def(self, resource_id: DefinitionId) -> MarketAvailabilityDef | None:
        return next((row for row in self.supply if row.resource_id == resource_id), None)

    def demand_def(self, resource_id: DefinitionId) -> MarketAvailabilityDef | None:
        return next((row for row in self.demand if row.resource_id == resource_id), None)


@dataclass
class MarketProviderState:
    provider_id: DefinitionId
    supply_available_t: dict[DefinitionId, float] = field(default_factory=dict)
    demand_available_t: dict[DefinitionId, float] = field(default_factory=dict)
    last_replenished_day: int = 0


@dataclass
class MarketInterfaceState:
    id: EntityId
    provider_id: DefinitionId
    operational_node_id: SpatialNodeId
    enabled: bool = True


class TradeDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradeControlMode(str, Enum):
    QUANTITY = "quantity"
    RATE = "rate"


@dataclass
class TradeOrderState:
    id: EntityId
    direction: TradeDirection
    resource_id: DefinitionId
    market_interface_id: EntityId
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    control_mode: TradeControlMode = TradeControlMode.QUANTITY
    quantity_target_t: float | None = None
    rate_target_t_per_day: float | None = None
    price_limit_musd_per_t: float | None = None
    settled_quantity_t: float = 0.0

    def __post_init__(self) -> None:
        self.direction = TradeDirection(self.direction)
        self.priority = ActivityPriority(self.priority)
        self.control_mode = TradeControlMode(self.control_mode)
        if self.control_mode is TradeControlMode.QUANTITY:
            if self.quantity_target_t is None or self.rate_target_t_per_day is not None:
                raise ValueError("QUANTITY order requires only quantity_target_t")
            if not isfinite(self.quantity_target_t) or self.quantity_target_t < -_EPS:
                raise ValueError("trade quantity target must be finite and non-negative")
        else:
            if self.rate_target_t_per_day is None or self.quantity_target_t is not None:
                raise ValueError("RATE order requires only rate_target_t_per_day")
            if not isfinite(self.rate_target_t_per_day) or self.rate_target_t_per_day < -_EPS:
                raise ValueError("trade rate target must be finite and non-negative")
        if self.price_limit_musd_per_t is not None:
            if not isfinite(self.price_limit_musd_per_t) or self.price_limit_musd_per_t < -_EPS:
                raise ValueError("trade price limit must be finite and non-negative")
        if not isfinite(self.settled_quantity_t) or self.settled_quantity_t < -_EPS:
            raise ValueError("settled trade quantity must be finite and non-negative")
        if (
            self.control_mode is TradeControlMode.QUANTITY
            and self.settled_quantity_t > (self.quantity_target_t or 0.0) + _EPS
        ):
            raise ValueError("settled QUANTITY trade amount exceeds target")

    @property
    def current_target_t(self) -> float:
        if self.control_mode is TradeControlMode.RATE:
            return max(0.0, self.rate_target_t_per_day or 0.0)
        return max(0.0, (self.quantity_target_t or 0.0) - self.settled_quantity_t)

    def accepts_offer_price(self, offer_price_musd_per_t: float) -> bool:
        """Return whether the current price condition allows a new settlement/commit."""
        if self.price_limit_musd_per_t is None:
            return True
        if self.direction is TradeDirection.BUY:
            return offer_price_musd_per_t <= self.price_limit_musd_per_t + _EPS
        return offer_price_musd_per_t + _EPS >= self.price_limit_musd_per_t


@dataclass
class BuyCommitment:
    id: EntityId
    order_id: EntityId
    resource_id: DefinitionId
    remaining_quantity_t: float
    committed_price_musd_per_t: float
    created_day: int
    maturity_day: int

    def __post_init__(self) -> None:
        if not isfinite(self.remaining_quantity_t) or self.remaining_quantity_t <= _EPS:
            raise ValueError("buy commitment quantity must be finite and positive")
        if not isfinite(self.committed_price_musd_per_t) or self.committed_price_musd_per_t < -_EPS:
            raise ValueError("buy commitment price must be finite and non-negative")
        if self.created_day < 0 or self.maturity_day < self.created_day:
            raise ValueError("invalid buy commitment timing")

    @property
    def reserved_funds_musd(self) -> float:
        return self.remaining_quantity_t * self.committed_price_musd_per_t

    @property
    def reserved_provider_supply_t(self) -> float:
        return self.remaining_quantity_t


@dataclass(frozen=True)
class BuyAllocationRow:
    order_id: EntityId
    requested_t: float
    allocated_t: float
    limiting_factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketBuyAllocationPlan:
    rows: tuple[BuyAllocationRow, ...] = ()

    def allocated(self, order_id: EntityId) -> float:
        return next((row.allocated_t for row in self.rows if row.order_id == order_id), 0.0)


@dataclass
class MarketService:
    funds: FundsState
    provider_defs: dict[DefinitionId, MarketProviderDef] = field(default_factory=dict)
    provider_states: dict[DefinitionId, MarketProviderState] = field(default_factory=dict)
    interfaces: dict[EntityId, MarketInterfaceState] = field(default_factory=dict)
    orders: dict[EntityId, TradeOrderState] = field(default_factory=dict)
    buy_commitments: dict[EntityId, BuyCommitment] = field(default_factory=dict)
    _order_counter: int = 0
    _commitment_counter: int = 0

    def initialize_funds(self, balance_musd: float) -> None:
        if self.funds.balance != 0.0 or self.buy_commitments:
            raise ValueError("Funds state is already initialized")
        self.funds = FundsState(balance_musd)

    @property
    def reserved_funds_musd(self) -> float:
        return sum(row.reserved_funds_musd for row in self.buy_commitments.values())

    @property
    def available_funds_musd(self) -> float:
        return max(0.0, self.funds.balance - self.reserved_funds_musd)

    def register_provider_definition(self, definition: MarketProviderDef) -> None:
        if definition.id in self.provider_defs:
            raise ValueError(f"duplicate market provider definition: {definition.id}")
        self.provider_defs[definition.id] = definition

    def initialize_provider_state(self, provider_id: DefinitionId, *, day: int = 0) -> None:
        if provider_id not in self.provider_defs:
            raise KeyError(provider_id)
        if provider_id in self.provider_states:
            raise ValueError(f"market provider state already exists: {provider_id}")
        definition = self.provider_defs[provider_id]
        self.provider_states[provider_id] = MarketProviderState(
            definition.id,
            {row.resource_id: row.initial_t for row in definition.supply},
            {row.resource_id: row.initial_t for row in definition.demand},
            day,
        )

    def set_interface(self, interface: MarketInterfaceState) -> None:
        if interface.provider_id not in self.provider_defs:
            raise KeyError(interface.provider_id)
        self.interfaces[interface.id] = interface

    def provider_def_for_interface(self, interface_id: EntityId) -> MarketProviderDef:
        interface = self.interfaces[interface_id]
        return self.provider_defs[interface.provider_id]

    def provider_state_for_interface(self, interface_id: EntityId) -> MarketProviderState:
        interface = self.interfaces[interface_id]
        return self.provider_states[interface.provider_id]

    def replenish_to_day(self, day: int) -> None:
        for provider_id, state in sorted(self.provider_states.items(), key=lambda row: str(row[0])):
            if day <= state.last_replenished_day:
                continue
            definition = self.provider_defs[provider_id]
            elapsed = day - state.last_replenished_day
            for row in definition.supply:
                state.supply_available_t[row.resource_id] = min(
                    row.capacity_t,
                    max(0.0, state.supply_available_t.get(row.resource_id, 0.0))
                    + elapsed * row.replenishment_t_per_day,
                )
            for row in definition.demand:
                state.demand_available_t[row.resource_id] = min(
                    row.capacity_t,
                    max(0.0, state.demand_available_t.get(row.resource_id, 0.0))
                    + elapsed * row.replenishment_t_per_day,
                )
            state.last_replenished_day = day

    def reserved_provider_supply_t(self, provider_id: DefinitionId, resource_id: DefinitionId) -> float:
        return sum(
            row.remaining_quantity_t
            for row in self.buy_commitments.values()
            if row.resource_id == resource_id
            and self.interfaces[self.orders[row.order_id].market_interface_id].provider_id == provider_id
        )

    def available_provider_supply_t(self, provider_id: DefinitionId, resource_id: DefinitionId) -> float:
        state = self.provider_states[provider_id]
        return max(
            0.0,
            state.supply_available_t.get(resource_id, 0.0)
            - self.reserved_provider_supply_t(provider_id, resource_id),
        )

    def available_provider_demand_t(self, provider_id: DefinitionId, resource_id: DefinitionId) -> float:
        return max(0.0, self.provider_states[provider_id].demand_available_t.get(resource_id, 0.0))

    @staticmethod
    def sell_requirement_id(order_id: EntityId) -> EntityId:
        return EntityId(f"supply.market.sell:{order_id}")

    @staticmethod
    def sell_execution_id(order_id: EntityId) -> EntityId:
        return EntityId(f"execution.market.sell:{order_id}")

    @staticmethod
    def buy_boundary_execution_id(commitment_id: EntityId) -> EntityId:
        return EntityId(f"boundary.market.buy:{commitment_id}")

    def create_order(
        self,
        *,
        direction: TradeDirection,
        resource_id: DefinitionId,
        market_interface_id: EntityId,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        control_mode: TradeControlMode = TradeControlMode.QUANTITY,
        quantity_target_t: float | None = None,
        rate_target_t_per_day: float | None = None,
        price_limit_musd_per_t: float | None = None,
    ) -> EntityId:
        interface = self.interfaces.get(market_interface_id)
        if interface is None or not interface.enabled:
            raise ValueError("market interface is unavailable")
        definition = self.provider_defs[interface.provider_id]
        direction = TradeDirection(direction)
        offer = definition.buy_price(resource_id) if direction is TradeDirection.BUY else definition.sell_price(resource_id)
        if offer is None:
            raise ValueError("market provider has no offer for resource")
        self._order_counter += 1
        order_id = EntityId(f"trade.order.{self._order_counter}")
        self.orders[order_id] = TradeOrderState(
            order_id,
            direction,
            resource_id,
            market_interface_id,
            priority,
            control_mode,
            quantity_target_t,
            rate_target_t_per_day,
            price_limit_musd_per_t,
        )
        return order_id

    def update_order(
        self,
        order_id: EntityId,
        *,
        priority: ActivityPriority | None = None,
        control_mode: TradeControlMode | None = None,
        quantity_target_t: float | None = None,
        rate_target_t_per_day: float | None = None,
        price_limit_musd_per_t: float | None = None,
        replace_price_limit: bool = False,
    ) -> None:
        current = self.orders[order_id]
        mode = current.control_mode if control_mode is None else TradeControlMode(control_mode)
        quantity = current.quantity_target_t if mode is TradeControlMode.QUANTITY and quantity_target_t is None else quantity_target_t
        rate = current.rate_target_t_per_day if mode is TradeControlMode.RATE and rate_target_t_per_day is None else rate_target_t_per_day
        price = price_limit_musd_per_t if replace_price_limit else current.price_limit_musd_per_t
        replacement = TradeOrderState(
            current.id,
            current.direction,
            current.resource_id,
            current.market_interface_id,
            current.priority if priority is None else priority,
            mode,
            quantity,
            rate,
            price,
            current.settled_quantity_t,
        )
        if (
            replacement.direction is TradeDirection.BUY
            and replacement.control_mode is TradeControlMode.QUANTITY
        ):
            committed = sum(
                row.remaining_quantity_t
                for row in self.buy_commitments.values()
                if row.order_id == order_id
            )
            if replacement.current_target_t + _EPS < committed:
                raise ValueError(
                    "QUANTITY buy target cannot be reduced below active commitments"
                )
        self.orders[order_id] = replacement

    def cancel_order(self, order_id: EntityId) -> None:
        if order_id not in self.orders:
            raise KeyError(order_id)
        # Unsettled buy commitments are cancellable and are the sole owner of
        # both reserved Funds and provider supply. Removing them releases both.
        for commitment_id in [
            cid for cid, row in self.buy_commitments.items() if row.order_id == order_id
        ]:
            del self.buy_commitments[commitment_id]
        del self.orders[order_id]

    def plan_buy_allocations(self) -> MarketBuyAllocationPlan:
        bundles: list[ExecutionRequirementBundle] = []
        capacities: dict[AllocationConstraintKey, float] = {
            pool_constraint("market.buy.funds_musd"): self.available_funds_musd,
        }
        requested_by_order: dict[EntityId, float] = {}
        for order in sorted(self.orders.values(), key=lambda row: (-int(row.priority), str(row.id))):
            if order.direction is not TradeDirection.BUY:
                continue
            interface = self.interfaces.get(order.market_interface_id)
            if interface is None or not interface.enabled:
                continue
            provider = self.provider_defs[interface.provider_id]
            price = provider.buy_price(order.resource_id)
            if price is None or not order.accepts_offer_price(price):
                continue
            active = sum(
                row.remaining_quantity_t
                for row in self.buy_commitments.values()
                if row.order_id == order.id
            )
            requested = order.current_target_t
            if order.control_mode is TradeControlMode.QUANTITY:
                requested = max(0.0, requested - active)
            if requested <= _EPS:
                continue
            supply_pool = f"market.buy.supply:{interface.provider_id}:{order.resource_id}"
            supply_key = pool_constraint(supply_pool)
            capacities[supply_key] = self.available_provider_supply_t(
                interface.provider_id, order.resource_id
            )
            requested_by_order[order.id] = requested
            bundles.append(ExecutionRequirementBundle(
                id=order.id,
                owner_kind="market_buy",
                owner_id=order.id,
                purpose="buy_commitment_acquisition",
                operational_node_id=None,
                requested_execution=requested,
                priority=order.priority,
                requirements=(
                    PoolRequirement("market.buy.funds_musd", price),
                    PoolRequirement(supply_pool, 1.0),
                ),
            ))
        if not bundles:
            return MarketBuyAllocationPlan()
        allocation = allocate_execution_requirements(tuple(bundles), capacities)
        rows: list[BuyAllocationRow] = []
        for order_id, requested in sorted(requested_by_order.items(), key=lambda row: str(row[0])):
            result = allocation.allocation(order_id)
            rows.append(BuyAllocationRow(
                order_id,
                requested,
                result.allocated_execution,
                tuple(f"{key.kind}:{key.scope_id}:{key.name}" for key in result.limiting_constraints),
            ))
        return MarketBuyAllocationPlan(tuple(rows))

    def create_buy_commitments(self, plan: MarketBuyAllocationPlan, day: int) -> None:
        for row in sorted(plan.rows, key=lambda value: str(value.order_id)):
            if row.allocated_t <= _EPS:
                continue
            order = self.orders.get(row.order_id)
            if order is None or order.direction is not TradeDirection.BUY:
                continue
            interface = self.interfaces[order.market_interface_id]
            provider = self.provider_defs[interface.provider_id]
            price = provider.buy_price(order.resource_id)
            if price is None or not order.accepts_offer_price(price):
                continue
            self._commitment_counter += 1
            commitment_id = EntityId(f"buy.commitment.{self._commitment_counter}")
            self.buy_commitments[commitment_id] = BuyCommitment(
                commitment_id,
                order.id,
                order.resource_id,
                row.allocated_t,
                price,
                day,
                day + provider.lead_time_days,
            )

    def matured_buy_commitments(self, day: int) -> tuple[BuyCommitment, ...]:
        return tuple(
            row
            for row in sorted(self.buy_commitments.values(), key=lambda value: str(value.id))
            if row.created_day < day and row.maturity_day <= day and row.remaining_quantity_t > _EPS
        )

    def buy_boundary_bundles(self, day: int, inventory: InventoryBook) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for commitment in self.matured_buy_commitments(day):
            order = self.orders.get(commitment.order_id)
            if order is None or order.direction is not TradeDirection.BUY:
                continue
            interface = self.interfaces.get(order.market_interface_id)
            if interface is None or not interface.enabled:
                continue
            requirements: list = [ServiceCapacityRequirement("cargo_transfer", 1.0)]
            storage_class = inventory.resource_storage_class.get(commitment.resource_id)
            if storage_class is not None:
                requirements.append(StockOrPoolAdmissionRequirement(storage_class, 1.0))
            rows.append(ExecutionRequirementBundle(
                id=self.buy_boundary_execution_id(commitment.id),
                owner_kind="market_buy_boundary",
                owner_id=commitment.id,
                purpose="market_buy_admission",
                operational_node_id=interface.operational_node_id,
                requested_execution=commitment.remaining_quantity_t,
                priority=order.priority,
                requirements=tuple(requirements),
            ))
        return tuple(rows)

    def settle_matured_buys(self, day: int, allocation: ExecutionAllocationPlan, inventory: InventoryBook) -> None:
        for commitment in self.matured_buy_commitments(day):
            request_id = self.buy_boundary_execution_id(commitment.id)
            try:
                amount = min(commitment.remaining_quantity_t, max(0.0, allocation.allocated(request_id)))
            except KeyError:
                amount = 0.0
            if amount <= _EPS:
                continue
            order = self.orders[commitment.order_id]
            interface = self.interfaces[order.market_interface_id]
            cost = amount * commitment.committed_price_musd_per_t
            if self.funds.balance + _EPS < cost:
                raise RuntimeError("reserved market Funds disappeared before settlement")
            provider_state = self.provider_states[interface.provider_id]
            provider_supply = provider_state.supply_available_t.get(commitment.resource_id, 0.0)
            if provider_supply + _EPS < amount:
                raise RuntimeError("reserved provider supply disappeared before settlement")
            admission = inventory.admit(interface.operational_node_id, commitment.resource_id, amount)
            if abs(admission.admitted_t - amount) > 1e-7:
                raise RuntimeError("market buy boundary allocation exceeded Inventory Admission")
            self.funds.balance -= cost
            provider_state.supply_available_t[commitment.resource_id] = max(0.0, provider_supply - amount)
            commitment.remaining_quantity_t = max(0.0, commitment.remaining_quantity_t - amount)
            order = self.orders.get(commitment.order_id)
            if order is not None:
                order.settled_quantity_t += amount
            if commitment.remaining_quantity_t <= _EPS:
                del self.buy_commitments[commitment.id]

    def sell_supply_requirements(self) -> tuple[SupplyRequirement, ...]:
        rows: list[SupplyRequirement] = []
        for order in sorted(self.orders.values(), key=lambda value: (-int(value.priority), str(value.id))):
            if order.direction is not TradeDirection.SELL:
                continue
            interface = self.interfaces.get(order.market_interface_id)
            if interface is None or not interface.enabled:
                continue
            provider = self.provider_defs[interface.provider_id]
            price = provider.sell_price(order.resource_id)
            if price is None or not order.accepts_offer_price(price):
                continue
            target = order.current_target_t
            if target <= _EPS:
                continue
            requirement_id = self.sell_requirement_id(order.id)
            rows.append(SupplyRequirement(
                id=requirement_id,
                owner_kind="market_sell",
                owner_id=order.id,
                destination_id=interface.operational_node_id,
                resource_id=order.resource_id,
                amount_t=target,
                priority=order.priority,
                recurring_rate_t_per_day=(
                    order.rate_target_t_per_day
                    if order.control_mode is TradeControlMode.RATE
                    else None
                ),
                purpose="market_sell_delivery",
            ))
        return tuple(rows)

    def sell_execution_bundles(self) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for order in sorted(self.orders.values(), key=lambda value: (-int(value.priority), str(value.id))):
            if order.direction is not TradeDirection.SELL:
                continue
            interface = self.interfaces.get(order.market_interface_id)
            if interface is None or not interface.enabled:
                continue
            provider = self.provider_defs[interface.provider_id]
            price = provider.sell_price(order.resource_id)
            if price is None or not order.accepts_offer_price(price):
                continue
            requested = order.current_target_t
            if requested <= _EPS:
                continue
            pool_id = f"market.sell.demand:{interface.provider_id}:{order.resource_id}"
            rows.append(ExecutionRequirementBundle(
                id=self.sell_execution_id(order.id),
                owner_kind="market_sell",
                owner_id=order.id,
                purpose="market_sell_settlement",
                operational_node_id=interface.operational_node_id,
                requested_execution=requested,
                priority=order.priority,
                requirements=(
                    ResourceRequirement(order.resource_id, 1.0),
                    PoolRequirement(pool_id, 1.0),
                ),
            ))
        return tuple(rows)

    def allocation_pool_capacities(self, day: int) -> dict[AllocationConstraintKey, float]:
        return self.sell_pool_capacities()

    def sell_pool_capacities(self) -> dict[AllocationConstraintKey, float]:
        rows: dict[AllocationConstraintKey, float] = {}
        for order in self.orders.values():
            if order.direction is not TradeDirection.SELL:
                continue
            interface = self.interfaces.get(order.market_interface_id)
            if interface is None:
                continue
            pool_id = f"market.sell.demand:{interface.provider_id}:{order.resource_id}"
            key = pool_constraint(pool_id)
            rows[key] = self.available_provider_demand_t(interface.provider_id, order.resource_id)
        return rows

    def settle_sells(self, allocation: ExecutionAllocationPlan, inventory: InventoryBook) -> None:
        for order in sorted(self.orders.values(), key=lambda value: str(value.id)):
            if order.direction is not TradeDirection.SELL:
                continue
            execution_id = self.sell_execution_id(order.id)
            try:
                amount = max(0.0, allocation.allocated(execution_id))
            except KeyError:
                continue
            if amount <= _EPS:
                continue
            interface = self.interfaces[order.market_interface_id]
            provider = self.provider_defs[interface.provider_id]
            price = provider.sell_price(order.resource_id)
            if price is None or not order.accepts_offer_price(price):
                continue
            demand = self.provider_states[interface.provider_id].demand_available_t.get(order.resource_id, 0.0)
            if demand + _EPS < amount:
                raise RuntimeError("market sell allocation exceeded provider demand")
            inventory.consume_allocated(interface.operational_node_id, order.resource_id, amount)
            self.provider_states[interface.provider_id].demand_available_t[order.resource_id] = max(0.0, demand - amount)
            self.funds.balance += amount * price
            order.settled_quantity_t += amount

    def order_rows(self) -> tuple[TradeOrderState, ...]:
        return tuple(replace(row) for row in sorted(self.orders.values(), key=lambda value: str(value.id)))
