from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import build_game_application
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content import base_ids as ids
from space_idle.external_procurement import ProcurementDeliveryStatus
from space_idle.persistence import load_game, save_game
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import EntityId
from space_idle.simulation import TickIntents


def _demand(*, destination=ids.EARTH, amount=4.0, source=None) -> ResourceDemand:
    return ResourceDemand(
        EntityId("demand.external-procurement"),
        "test_owner",
        EntityId("owner.external-procurement"),
        destination,
        ids.MACHINERY,
        amount,
        70,
        source,
    )


def _enable_for_demand(sim, demand: ResourceDemand, *, period_budget_musd=None):
    return sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(ids.EARTH_INDUSTRIAL_MARKET,),
        scope_kind=demand.owner_kind,
        scope_id=demand.owner_id,
        period_budget_musd=period_budget_musd,
        day=sim.day,
    )


def _empty_intents(demand: ResourceDemand) -> TickIntents:
    return TickIntents((demand,), (), ())


def test_external_procurement_defaults_to_deny():
    sim = build_base_simulation()
    demand = _demand(amount=5.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0

    plan = sim._plan_tick(_empty_intents(demand))

    assert plan.external_demands == (demand,)
    assert plan.procurement.orders == ()
    assert plan.procurement.spending_requests == ()


def test_external_procurement_uses_funds_then_latency_and_storage_admission():
    sim = build_base_simulation()
    demand = _demand(amount=5.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    _enable_for_demand(sim, demand)

    intents = _empty_intents(demand)
    snapshot = sim._physical_tick_snapshot()
    plan = sim._plan_tick(intents)
    allocations = sim._allocate_tick(snapshot, intents, plan)

    assert len(plan.procurement.orders) == 1
    order = plan.procurement.orders[0]
    assert order.delivery_node_id == ids.EARTH
    assert allocations.procurement.orders[0].amount_t == pytest.approx(5.0)
    assert any(
        row.request_id == order.funds_request_id for row in allocations.funds.rows
    )

    before_funds = sim.external_economy.account.funds_musd
    before_stock = sim.inventory.amount(ids.EARTH, ids.MACHINERY)
    sim.logistics.advance_external_procurement(
        sim.day, allocations.procurement, allocations.funds
    )

    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(before_stock)
    delivery = next(iter(sim.logistics.procurement_deliveries.values()))
    assert delivery.status is ProcurementDeliveryStatus.IN_TRANSIT
    service = sim.logistics.procurement_services[delivery.service_id]
    assert delivery.ready_day == sim.day + service.delivery_latency_days
    assert before_funds - sim.external_economy.account.funds_musd == pytest.approx(
        order.amount_t * order.unit_price_musd_per_t
    )

    sim.logistics.settle_procurement_arrivals(delivery.ready_day - 1)
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(before_stock)
    assert delivery.id in sim.logistics.procurement_deliveries

    sim.logistics.settle_procurement_arrivals(delivery.ready_day)
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(
        before_stock + 5.0
    )
    assert delivery.id not in sim.logistics.procurement_deliveries


def test_external_procurement_budget_scales_physical_order_before_execution():
    sim = build_base_simulation()
    demand = _demand(amount=10.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    service = sim.logistics.procurement_services[ids.EARTH_INDUSTRIAL_MARKET]
    unit_price = service.unit_price_musd_per_t(ids.MACHINERY)
    assert unit_price is not None
    _enable_for_demand(sim, demand, period_budget_musd=unit_price * 2.5)

    intents = _empty_intents(demand)
    snapshot = sim._physical_tick_snapshot()
    plan = sim._plan_tick(intents)
    allocations = sim._allocate_tick(snapshot, intents, plan)

    assert plan.procurement.orders[0].requested_amount_t == pytest.approx(10.0)
    assert allocations.procurement.orders[0].amount_t == pytest.approx(2.5)
    sim.logistics.advance_external_procurement(
        sim.day, allocations.procurement, allocations.funds
    )
    delivery = next(iter(sim.logistics.procurement_deliveries.values()))
    assert delivery.amount_t == pytest.approx(2.5)


def test_external_procurement_arrival_waits_for_storage_capacity():
    sim = build_base_simulation()
    demand = _demand(amount=3.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    _enable_for_demand(sim, demand)

    intents = _empty_intents(demand)
    snapshot = sim._physical_tick_snapshot()
    plan = sim._plan_tick(intents)
    allocations = sim._allocate_tick(snapshot, intents, plan)
    sim.logistics.advance_external_procurement(
        sim.day, allocations.procurement, allocations.funds
    )
    delivery = next(iter(sim.logistics.procurement_deliveries.values()))

    physical = dict(sim.inventory.physical_storage_capacity_t)
    usable = dict(sim.inventory.usable_storage_capacity_t)
    usable[(ids.EARTH, "general_cargo")] = 0.0
    sim.inventory.set_capacity_snapshot(physical, usable)
    sim.logistics.settle_procurement_arrivals(delivery.ready_day)

    assert delivery.status is ProcurementDeliveryStatus.ARRIVAL_WAITING
    assert delivery.amount_t == pytest.approx(3.0)
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(0.0)

    usable[(ids.EARTH, "general_cargo")] = physical[(ids.EARTH, "general_cargo")]
    sim.inventory.set_capacity_snapshot(physical, usable)
    sim.logistics.settle_procurement_arrivals(delivery.ready_day + 1)
    assert delivery.id not in sim.logistics.procurement_deliveries
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(3.0)


def test_external_procurement_delivery_roundtrips_through_save_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    demand = _demand(amount=2.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    _enable_for_demand(sim, demand)

    intents = _empty_intents(demand)
    snapshot = sim._physical_tick_snapshot()
    plan = sim._plan_tick(intents)
    allocations = sim._allocate_tick(snapshot, intents, plan)
    sim.logistics.advance_external_procurement(
        sim.day, allocations.procurement, allocations.funds
    )
    before = next(iter(sim.logistics.procurement_deliveries.values()))

    path = tmp_path / "external-procurement.json"
    save_game(app, path, saved_at=datetime(2026, 9, 15, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    after = loaded._simulation.logistics.procurement_deliveries[before.id]

    assert after == before


def test_remote_procurement_replenishes_logistics_source_without_bypassing_transport():
    sim = build_base_simulation()
    sim.transport.transport_allocations.clear()
    demand = _demand(destination=ids.LEO, amount=1.0, source=ids.EARTH)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    sim.inventory.stock[(ids.LEO, ids.MACHINERY)] = 0.0
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(
            ids.EARTH_INDUSTRIAL_MARKET,
            ids.EARTH_LEO_LAUNCH_SERVICE,
        ),
        day=sim.day,
    )
    sim.logistics.create_lane(ids.EARTH, ids.LEO, 1.0, 70)

    intents = _empty_intents(demand)
    snapshot = sim._physical_tick_snapshot()
    plan = sim._plan_tick(intents)
    assert plan.logistics.dispatches
    assert len(plan.procurement.orders) == 1
    order = plan.procurement.orders[0]
    assert order.delivery_node_id == ids.EARTH
    assert order.delivery_node_id != demand.destination_id

    allocations = sim._allocate_tick(snapshot, intents, plan)
    assert allocations.transport.executable_dispatches == ()
    sim.logistics.advance_external_procurement(
        sim.day, allocations.procurement, allocations.funds
    )
    sim.logistics.advance_capacity_logistics(
        sim.day,
        allocations.logistics,
        allocations.funds,
        allocations.transport,
    )

    assert sim.logistics.cargo_flows == {}
    delivery = next(iter(sim.logistics.procurement_deliveries.values()))
    sim.logistics.settle_procurement_arrivals(delivery.ready_day)
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(1.0)
    assert sim.inventory.amount(ids.LEO, ids.MACHINERY) == pytest.approx(0.0)


def test_explicit_source_demand_is_not_replaced_by_destination_procurement():
    from space_idle.external_procurement import ExternalProcurementServiceDef
    from space_idle.logistics_flow import LogisticsResourcePlan

    sim = build_base_simulation()
    demand = _demand(destination=ids.LEO, amount=1.0, source=ids.EARTH)
    destination_service = ExternalProcurementServiceDef(
        id=ids.EARTH_INDUSTRIAL_MARKET.__class__("test.procurement.leo"),
        display_name="Test LEO Market",
        delivery_node_id=ids.LEO,
        resource_prices_musd_per_t=((ids.MACHINERY, 0.1),),
        delivery_latency_days=1,
    )
    sim.logistics.procurement_services[destination_service.id] = destination_service
    sim.external_economy.register_service(destination_service.id)
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(destination_service.id,),
        day=sim.day,
    )

    plan = sim.logistics.plan_external_procurement(
        sim.day,
        (demand,),
        LogisticsResourcePlan((), (), (), ()),
    )
    assert plan.orders == ()


def test_catalog_exposes_procurement_service_for_policy_configuration():
    from space_idle import GetCatalog

    app = build_game_application()
    catalog = app.query(GetCatalog())
    row = next(
        row for row in catalog.procurement_services
        if row.id == str(ids.EARTH_INDUSTRIAL_MARKET)
    )
    assert row.delivery_node_id == str(ids.EARTH)
    assert row.delivery_latency_days > 0
    prices = dict(row.resource_prices_musd_per_t)
    assert str(ids.MACHINERY) in prices
    assert prices[str(ids.MACHINERY)] >= 0.0
