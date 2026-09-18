from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    CreateTradeOrder,
    GetMarket,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.content.base_market import EARTH_MARKET_INTERFACE
from space_idle.execution_requirements import allocate_execution_requirements
from space_idle.inventory import InventoryBook
from space_idle.market import (
    FundsState,
    MarketAvailabilityDef,
    MarketInterfaceState,
    MarketProviderDef,
    MarketService,
    TradeControlMode,
    TradeDirection,
)
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId


def _market(*, funds: float = 10.0, supply: float = 10.0, demand: float = 10.0, lead: int = 1):
    resource = DefinitionId("test.resource.market")
    provider_id = DefinitionId("test.market.provider")
    interface_id = EntityId("test.market.interface")
    node_id = SpatialNodeId("test.market.node")
    provider = MarketProviderDef(
        provider_id,
        "Test Market",
        buy_offers_musd_per_t=((resource, 1.0),),
        sell_offers_musd_per_t=((resource, 0.5),),
        supply=(MarketAvailabilityDef(resource, supply, supply, 0.0),),
        demand=(MarketAvailabilityDef(resource, demand, demand, 0.0),),
        lead_time_days=lead,
    )
    market = MarketService(FundsState(funds))
    market.register_provider_definition(provider)
    market.initialize_provider_state(provider_id)
    market.set_interface(MarketInterfaceState(interface_id, provider_id, node_id))
    return market, provider_id, interface_id, node_id, resource


def test_buy_commitments_own_funds_and_provider_supply_once_with_fair_competition():
    market, provider_id, interface_id, _node_id, resource = _market(funds=6.0, supply=10.0)
    first = market.create_order(
        direction=TradeDirection.BUY,
        resource_id=resource,
        market_interface_id=interface_id,
        priority=3,
        quantity_target_t=6.0,
    )
    second = market.create_order(
        direction=TradeDirection.BUY,
        resource_id=resource,
        market_interface_id=interface_id,
        priority=3,
        quantity_target_t=6.0,
    )

    plan = market.plan_buy_allocations()
    assert plan.allocated(first) == pytest.approx(3.0)
    assert plan.allocated(second) == pytest.approx(3.0)
    market.create_buy_commitments(plan, day=0)

    assert market.funds.balance == pytest.approx(6.0)
    assert market.reserved_funds_musd == pytest.approx(6.0)
    assert market.available_funds_musd == pytest.approx(0.0)
    assert market.provider_states[provider_id].supply_available_t[resource] == pytest.approx(10.0)
    assert market.reserved_provider_supply_t(provider_id, resource) == pytest.approx(6.0)
    assert market.available_provider_supply_t(provider_id, resource) == pytest.approx(4.0)
    blocked = market.plan_buy_allocations()
    assert blocked.rows and all(row.allocated_t == pytest.approx(0.0) for row in blocked.rows)
    assert all(any("funds_musd" in factor for factor in row.limiting_factors) for row in blocked.rows)

    market.cancel_order(first)
    assert market.reserved_funds_musd == pytest.approx(3.0)
    assert market.available_funds_musd == pytest.approx(3.0)
    assert market.reserved_provider_supply_t(provider_id, resource) == pytest.approx(3.0)


def test_quantity_buy_tracks_remaining_target_but_rate_buy_does_not_accumulate_backlog():
    quantity_market, _provider, interface, _node, resource = _market(funds=100.0, supply=2.0, lead=10)
    quantity = quantity_market.create_order(
        direction="buy", resource_id=resource, market_interface_id=interface,
        control_mode=TradeControlMode.QUANTITY, quantity_target_t=5.0,
    )
    first = quantity_market.plan_buy_allocations()
    assert first.allocated(quantity) == pytest.approx(2.0)
    quantity_market.create_buy_commitments(first, day=0)
    # Existing commitment is already progress toward the cumulative QUANTITY target.
    quantity_market.provider_states[next(iter(quantity_market.provider_states))].supply_available_t[resource] = 5.0
    second = quantity_market.plan_buy_allocations()
    assert second.rows[0].requested_t == pytest.approx(3.0)
    with pytest.raises(ValueError, match="active commitments"):
        quantity_market.update_order(
            quantity, control_mode=TradeControlMode.QUANTITY, quantity_target_t=1.0
        )

    rate_market, _provider, interface, _node, resource = _market(funds=100.0, supply=1.0, lead=10)
    rate = rate_market.create_order(
        direction="buy", resource_id=resource, market_interface_id=interface,
        control_mode=TradeControlMode.RATE, rate_target_t_per_day=4.0,
    )
    day0 = rate_market.plan_buy_allocations()
    assert day0.rows[0].requested_t == pytest.approx(4.0)
    assert day0.allocated(rate) == pytest.approx(1.0)
    rate_market.create_buy_commitments(day0, day=0)
    provider_id = next(iter(rate_market.provider_states))
    rate_market.provider_states[provider_id].supply_available_t[resource] = 5.0
    day1 = rate_market.plan_buy_allocations()
    # The unfilled 3t from day 0 is not added to the new daily 4t target.
    assert day1.rows[0].requested_t == pytest.approx(4.0)


def test_matured_buy_settles_funds_supply_and_inventory_atomically_and_waits_for_admission():
    market, provider_id, interface_id, node_id, resource = _market(funds=10.0, supply=10.0, lead=0)
    order_id = market.create_order(
        direction="buy", resource_id=resource, market_interface_id=interface_id,
        priority=1, quantity_target_t=2.0,
    )
    plan = market.plan_buy_allocations()
    market.create_buy_commitments(plan, day=0)
    commitment = next(iter(market.buy_commitments.values()))
    market.update_order(order_id, priority=5)

    inventory = InventoryBook()
    inventory.register_storage_class(resource, "dry")
    inventory.add_capacity(node_id, "dry", 1.0)
    bundles = market.buy_boundary_bundles(1, inventory)
    bundle = next(row for row in bundles if row.owner_id == commitment.id)
    assert int(bundle.priority) == 5
    capacities = {
        key: float("inf")
        for bundle in bundles
        for key, _coefficient in bundle.coefficients()
    }
    for key in tuple(capacities):
        if key.kind == "admission":
            capacities[key] = 1.0
    allocation = allocate_execution_requirements(bundles, capacities)
    market.settle_matured_buys(1, allocation, inventory)

    assert inventory.amount(node_id, resource) == pytest.approx(1.0)
    assert market.funds.balance == pytest.approx(9.0)
    assert market.provider_states[provider_id].supply_available_t[resource] == pytest.approx(9.0)
    assert market.orders[order_id].settled_quantity_t == pytest.approx(1.0)
    assert commitment.remaining_quantity_t == pytest.approx(1.0)
    assert commitment.id in market.buy_commitments

    # With no admission headroom, no ownership or Funds transfer occurs.
    bundles = market.buy_boundary_bundles(2, inventory)
    capacities = {
        key: (0.0 if key.kind == "admission" else float("inf"))
        for bundle in bundles
        for key, _coefficient in bundle.coefficients()
    }
    blocked = allocate_execution_requirements(bundles, capacities)
    market.settle_matured_buys(2, blocked, inventory)
    assert inventory.amount(node_id, resource) == pytest.approx(1.0)
    assert market.funds.balance == pytest.approx(9.0)
    assert market.provider_states[provider_id].supply_available_t[resource] == pytest.approx(9.0)
    assert commitment.remaining_quantity_t == pytest.approx(1.0)


def test_sell_funds_cannot_finance_same_tick_buy():
    app = build_game_application()
    sim = app._simulation
    sim.market.funds.balance = 0.0
    sim.inventory.add(ids.EARTH, ids.WATER, 10.0)

    sell_id = app.execute(CreateTradeOrder(
        direction="sell",
        resource_id=str(ids.WATER),
        market_interface_id=str(EARTH_MARKET_INTERFACE),
        priority=5,
        control_mode="quantity",
        quantity_target_t=1.0,
    )).created_id
    buy_id = app.execute(CreateTradeOrder(
        direction="buy",
        resource_id=str(ids.MACHINERY),
        market_interface_id=str(EARTH_MARKET_INTERFACE),
        priority=5,
        control_mode="quantity",
        quantity_target_t=1.0,
    )).created_id
    assert sell_id and buy_id

    sim.advance_days(1)
    assert sim.market.funds.balance > 0.0
    assert not [row for row in sim.market.buy_commitments.values() if str(row.order_id) == buy_id]

    sim.advance_days(1)
    assert [row for row in sim.market.buy_commitments.values() if str(row.order_id) == buy_id]


def test_market_state_roundtrips_and_replenishes_deterministically(tmp_path):
    app = build_game_application()
    sim = app._simulation
    order_id = app.execute(CreateTradeOrder(
        direction="buy",
        resource_id=str(ids.MACHINERY),
        market_interface_id=str(EARTH_MARKET_INTERFACE),
        priority=4,
        control_mode="quantity",
        quantity_target_t=3.0,
    )).created_id
    assert order_id is not None
    sim.advance_days(1)

    path = tmp_path / "market.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)
    assert capture_state(loaded._simulation)["market"] == capture_state(sim)["market"]

    sim.advance_days(3)
    loaded._simulation.advance_days(3)
    assert capture_state(loaded._simulation)["market"] == capture_state(sim)["market"]
    assert loaded.query(GetMarket()) == app.query(GetMarket())
