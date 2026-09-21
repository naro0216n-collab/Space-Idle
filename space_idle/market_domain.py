from __future__ import annotations

from math import isfinite
from typing import Any

from .domain import (
    DomainExtension, StateCodec, decode_bool, decode_dict, decode_float, decode_int,
    decode_list, decode_str, require_fields,
)
from .market import (
    BuyCommitment, FundsState, MarketInterfaceState, MarketProviderState,
    TradeControlMode, TradeDirection, TradeOrderState,
)
from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, SpatialNodeId
from .validation_support import require as _require, validate_generated_id_counter as _validate_counter


def capture_market(sim: Any) -> dict[str, Any]:
    market = sim.market
    return {
        "funds_balance_musd": market.funds.balance,
        "order_counter": market._order_counter,
        "commitment_counter": market._commitment_counter,
        "provider_states": [
            {
                "provider_id": str(row.provider_id),
                "supply_available_t": {str(key): value for key, value in sorted(row.supply_available_t.items(), key=lambda item: str(item[0]))},
                "demand_available_t": {str(key): value for key, value in sorted(row.demand_available_t.items(), key=lambda item: str(item[0]))},
                "last_replenished_day": row.last_replenished_day,
            }
            for row in sorted(market.provider_states.values(), key=lambda value: str(value.provider_id))
        ],
        "interfaces": [
            {
                "id": str(row.id),
                "provider_id": str(row.provider_id),
                "operational_node_id": str(row.operational_node_id),
                "enabled": row.enabled,
            }
            for row in sorted(market.interfaces.values(), key=lambda value: str(value.id))
        ],
        "orders": [
            {
                "id": str(row.id),
                "direction": row.direction.value,
                "resource_id": str(row.resource_id),
                "market_interface_id": str(row.market_interface_id),
                "priority": int(row.priority),
                "control_mode": row.control_mode.value,
                "quantity_target_t": row.quantity_target_t,
                "rate_target_t_per_day": row.rate_target_t_per_day,
                "price_limit_musd_per_t": row.price_limit_musd_per_t,
                "settled_quantity_t": row.settled_quantity_t,
            }
            for row in sorted(market.orders.values(), key=lambda value: str(value.id))
        ],
        "buy_commitments": [
            {
                "id": str(row.id),
                "order_id": str(row.order_id),
                "resource_id": str(row.resource_id),
                "remaining_quantity_t": row.remaining_quantity_t,
                "committed_price_musd_per_t": row.committed_price_musd_per_t,
                "created_day": row.created_day,
                "maturity_day": row.maturity_day,
            }
            for row in sorted(market.buy_commitments.values(), key=lambda value: str(value.id))
        ],
    }


def restore_market(sim: Any, data: dict[str, Any]) -> None:
    market = sim.market
    market.funds = FundsState(decode_float(data["funds_balance_musd"], "market funds balance"))
    market._order_counter = decode_int(data["order_counter"], "market order_counter")
    market._commitment_counter = decode_int(data["commitment_counter"], "market commitment_counter")

    provider_fields = {
        "provider_id", "supply_available_t", "demand_available_t",
        "last_replenished_day",
    }
    market.provider_states = {}
    for index, raw in enumerate(decode_list(data["provider_states"], "market provider_states")):
        item = require_fields(raw, provider_fields, f"market provider_state[{index}]")
        provider_id = DefinitionId(decode_str(item["provider_id"], "market provider_id"))
        if provider_id in market.provider_states:
            raise ValueError(f"duplicate market provider state: {provider_id}")
        supply = decode_dict(item["supply_available_t"], "market supply_available_t")
        demand = decode_dict(item["demand_available_t"], "market demand_available_t")
        row = MarketProviderState(
            provider_id,
            {
                DefinitionId(key): decode_float(value, "market supply availability")
                for key, value in supply.items()
            },
            {
                DefinitionId(key): decode_float(value, "market demand availability")
                for key, value in demand.items()
            },
            decode_int(item["last_replenished_day"], "market last_replenished_day"),
        )
        market.provider_states[provider_id] = row

    interface_fields = {"id", "provider_id", "operational_node_id", "enabled"}
    market.interfaces = {}
    for index, raw in enumerate(decode_list(data["interfaces"], "market interfaces")):
        item = require_fields(raw, interface_fields, f"market interface[{index}]")
        interface_id = EntityId(decode_str(item["id"], "market interface id"))
        if interface_id in market.interfaces:
            raise ValueError(f"duplicate market interface: {interface_id}")
        row = MarketInterfaceState(
            interface_id,
            DefinitionId(decode_str(item["provider_id"], "market interface provider_id")),
            SpatialNodeId(
                decode_str(item["operational_node_id"], "market interface operational_node_id")
            ),
            decode_bool(item["enabled"], "market interface enabled"),
        )
        market.interfaces[interface_id] = row

    order_fields = {
        "id", "direction", "resource_id", "market_interface_id", "priority",
        "control_mode", "quantity_target_t", "rate_target_t_per_day",
        "price_limit_musd_per_t", "settled_quantity_t",
    }
    market.orders = {}
    for index, raw in enumerate(decode_list(data["orders"], "market orders")):
        item = require_fields(raw, order_fields, f"market order[{index}]")
        order_id = EntityId(decode_str(item["id"], "market order id"))
        if order_id in market.orders:
            raise ValueError(f"duplicate market order: {order_id}")
        row = TradeOrderState(
            order_id,
            TradeDirection(decode_str(item["direction"], "market order direction")),
            DefinitionId(decode_str(item["resource_id"], "market order resource_id")),
            EntityId(
                decode_str(item["market_interface_id"], "market order market_interface_id")
            ),
            ActivityPriority(decode_int(item["priority"], "trade order priority")),
            TradeControlMode(decode_str(item["control_mode"], "market order control_mode")),
            (
                None if item["quantity_target_t"] is None
                else decode_float(item["quantity_target_t"], "trade order quantity_target_t")
            ),
            (
                None if item["rate_target_t_per_day"] is None
                else decode_float(item["rate_target_t_per_day"], "trade order rate_target_t_per_day")
            ),
            (
                None if item["price_limit_musd_per_t"] is None
                else decode_float(item["price_limit_musd_per_t"], "trade order price_limit_musd_per_t")
            ),
            decode_float(item["settled_quantity_t"], "trade order settled_quantity_t"),
        )
        market.orders[order_id] = row

    commitment_fields = {
        "id", "order_id", "resource_id", "remaining_quantity_t",
        "committed_price_musd_per_t", "created_day", "maturity_day",
    }
    market.buy_commitments = {}
    for index, raw in enumerate(
        decode_list(data["buy_commitments"], "market buy_commitments")
    ):
        item = require_fields(raw, commitment_fields, f"market buy_commitment[{index}]")
        commitment_id = EntityId(decode_str(item["id"], "buy commitment id"))
        if commitment_id in market.buy_commitments:
            raise ValueError(f"duplicate buy commitment: {commitment_id}")
        row = BuyCommitment(
            commitment_id,
            EntityId(decode_str(item["order_id"], "buy commitment order_id")),
            DefinitionId(decode_str(item["resource_id"], "buy commitment resource_id")),
            decode_float(item["remaining_quantity_t"], "buy commitment remaining_quantity_t"),
            decode_float(item["committed_price_musd_per_t"], "buy commitment price"),
            decode_int(item["created_day"], "buy commitment created_day"),
            decode_int(item["maturity_day"], "buy commitment maturity_day"),
        )
        market.buy_commitments[commitment_id] = row


def validate_configuration(sim: Any, _ctx) -> None:
    market = sim.market
    for provider_id, definition in market.provider_defs.items():
        _require(provider_id == definition.id, f"market provider definition key mismatch: {provider_id}")


def validate_runtime(sim: Any) -> None:
    market = sim.market
    _validate_counter(market._order_counter, market.orders, "trade.order.", "market order")
    _validate_counter(
        market._commitment_counter, market.buy_commitments, "buy.commitment.",
        "market buy commitment",
    )
    _require(isfinite(market.funds.balance) and market.funds.balance >= -1e-9, "invalid market Funds")
    for interface_id, interface in market.interfaces.items():
        _require(interface_id == interface.id, f"market interface key mismatch: {interface_id}")
        _require(interface.provider_id in market.provider_defs, f"market interface references unknown provider: {interface_id}")
        _require(
            sim.graph.has_operational_node(interface.operational_node_id),
            f"market interface references unknown Operational Node: {interface_id}",
        )
    _require(
        market.reserved_funds_musd <= market.funds.balance + 1e-9,
        "market Buy commitments over-reserve Funds",
    )
    for provider_id, state in market.provider_states.items():
        _require(provider_id in market.provider_defs, f"unknown market provider state: {provider_id}")
        definition = market.provider_defs[provider_id]
        _require(0 <= state.last_replenished_day <= sim.day, f"invalid market provider replenishment day: {provider_id}")
        supply_defs = {row.resource_id: row for row in definition.supply}
        demand_defs = {row.resource_id: row for row in definition.demand}
        _require(
            set(state.supply_available_t) == set(supply_defs),
            f"market provider supply state does not match definition: {provider_id}",
        )
        _require(
            set(state.demand_available_t) == set(demand_defs),
            f"market provider demand state does not match definition: {provider_id}",
        )
        for resource_id, amount in state.supply_available_t.items():
            _require(isfinite(amount) and amount >= -1e-9, f"invalid market provider supply: {provider_id}/{resource_id}")
            _require(
                amount <= supply_defs[resource_id].capacity_t + 1e-9,
                f"market provider supply exceeds capacity: {provider_id}/{resource_id}",
            )
            _require(
                market.reserved_provider_supply_t(provider_id, resource_id) <= amount + 1e-9,
                f"market Buy commitments over-reserve provider supply: {provider_id}/{resource_id}",
            )
        for resource_id, amount in state.demand_available_t.items():
            _require(isfinite(amount) and amount >= -1e-9, f"invalid market provider demand: {provider_id}/{resource_id}")
            _require(
                amount <= demand_defs[resource_id].capacity_t + 1e-9,
                f"market provider demand exceeds capacity: {provider_id}/{resource_id}",
            )
    for order_id, order in market.orders.items():
        _require(order_id == order.id, f"trade order key mismatch: {order_id}")
        _require(order.market_interface_id in market.interfaces, f"trade order references unknown Market Interface: {order_id}")
        if order.control_mode is TradeControlMode.QUANTITY:
            _require(
                order.settled_quantity_t <= (order.quantity_target_t or 0.0) + 1e-9,
                f"QUANTITY trade order settled quantity exceeds target: {order_id}",
            )
    for commitment_id, row in market.buy_commitments.items():
        _require(commitment_id == row.id, f"buy commitment key mismatch: {commitment_id}")
        _require(row.order_id in market.orders, f"buy commitment references missing order: {commitment_id}")
        _require(row.remaining_quantity_t > 0.0, f"empty buy commitment retained: {commitment_id}")
        order = market.orders[row.order_id]
        _require(order.market_interface_id in market.interfaces, f"buy commitment order references missing interface: {commitment_id}")
        interface = market.interfaces[order.market_interface_id]
        _require(interface.provider_id in market.provider_states, f"buy commitment order references missing provider: {commitment_id}")
        _require(order.direction.value == "buy", f"buy commitment references non-buy order: {commitment_id}")
        _require(order.resource_id == row.resource_id, f"buy commitment resource mismatch: {commitment_id}")

    for order_id, order in market.orders.items():
        if order.direction is not TradeDirection.BUY or order.control_mode is not TradeControlMode.QUANTITY:
            continue
        active_committed = sum(
            row.remaining_quantity_t
            for row in market.buy_commitments.values()
            if row.order_id == order_id
        )
        _require(
            active_committed <= order.current_target_t + 1e-9,
            f"QUANTITY buy commitments exceed remaining target: {order_id}",
        )


STATE_CODEC = StateCodec("market", capture_market, restore_market)
DOMAIN_EXTENSION = DomainExtension(
    "market",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    allocation_pool_provider=lambda sim: sim.market,
)
