from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import build_game_application
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content import base_ids as ids
from space_idle.external_procurement import ExternalSupplyStatus
from space_idle.persistence import load_game, save_game
from space_idle.supply import SupplyRequirement
from space_idle.shared import DefinitionId, EntityId


def _demand(*, destination=ids.EARTH, amount=4.0, source=None) -> SupplyRequirement:
    return SupplyRequirement(
        EntityId("requirement.external-procurement"),
        "test_owner",
        EntityId("owner.external-procurement"),
        destination,
        ids.MACHINERY,
        amount,
        4,
        source,
    )


def _enable_for_demand(sim, demand: SupplyRequirement, *, period_budget_musd=None):
    return sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(ids.EARTH_INDUSTRIAL_MARKET,),
        scope_kind=demand.owner_kind,
        scope_id=demand.owner_id,
        period_budget_musd=period_budget_musd,
        day=sim.day,
    )


def _plan_and_authorize_procurement(sim, demand: SupplyRequirement):
    raw_logistics = sim.logistics.plan_capacity_logistics(sim.day, (demand,))
    raw_procurement = sim.logistics.plan_external_procurement(
        sim.day, (demand,), raw_logistics
    )
    funds = sim.external_economy.allocate(
        raw_logistics.spending_requests + raw_procurement.spending_requests,
        sim.day,
    )
    logistics = sim.logistics.authorize_capacity_logistics(
        raw_logistics, funds, sim.day
    )
    procurement = sim.logistics.authorize_external_procurement(
        raw_procurement, funds
    )
    return raw_logistics, raw_procurement, logistics, procurement, funds


def test_external_procurement_defaults_to_deny():
    sim = build_base_simulation()
    demand = _demand(amount=5.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0

    logistics = sim.logistics.plan_capacity_logistics(sim.day, (demand,))
    procurement = sim.logistics.plan_external_procurement(
        sim.day, (demand,), logistics
    )

    assert procurement.orders == ()
    assert procurement.spending_requests == ()


def test_external_procurement_uses_funds_then_persisted_supply_lead_time_and_inventory_admission(tmp_path):
    app = build_game_application()
    sim = app._simulation
    demand = _demand(amount=5.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    _enable_for_demand(sim, demand)

    _, raw_procurement, _, procurement, funds = _plan_and_authorize_procurement(
        sim, demand
    )

    assert len(raw_procurement.orders) == 1
    order = raw_procurement.orders[0]
    assert order.supply_node_id == ids.EARTH
    assert procurement.orders[0].amount_t == pytest.approx(5.0)
    assert any(row.request_id == order.funds_request_id for row in funds.rows)

    before_funds = sim.external_economy.account.funds_musd
    before_stock = sim.inventory.amount(ids.EARTH, ids.MACHINERY)
    sim.logistics.advance_external_procurement(sim.day, procurement, funds)

    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(before_stock)
    supply = next(iter(sim.logistics.external_supply_batches.values()))
    assert supply.status is ExternalSupplyStatus.ORDERED
    service = sim.logistics.procurement_services[supply.service_id]
    assert supply.available_day == sim.day + service.supply_latency_days
    assert before_funds - sim.external_economy.account.funds_musd == pytest.approx(
        order.amount_t * order.unit_price_musd_per_t
    )

    path = tmp_path / "external-procurement.json"
    save_game(app, path, saved_at=datetime(2026, 9, 15, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    loaded_sim = loaded._simulation
    loaded_supply = loaded_sim.logistics.external_supply_batches[supply.id]
    assert loaded_supply == supply

    loaded_sim.logistics.settle_external_supply(loaded_supply.available_day - 1)
    assert loaded_sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(before_stock)
    assert loaded_supply.id in loaded_sim.logistics.external_supply_batches

    loaded_sim.logistics.settle_external_supply(loaded_supply.available_day)
    assert loaded_sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(
        before_stock + 5.0
    )
    assert loaded_supply.id not in loaded_sim.logistics.external_supply_batches


def test_external_procurement_budget_scales_physical_order_before_execution():
    sim = build_base_simulation()
    demand = _demand(amount=10.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    service = sim.logistics.procurement_services[ids.EARTH_INDUSTRIAL_MARKET]
    unit_price = service.unit_price_musd_per_t(ids.MACHINERY)
    assert unit_price is not None
    _enable_for_demand(sim, demand, period_budget_musd=unit_price * 2.5)

    _, raw_procurement, _, procurement, funds = _plan_and_authorize_procurement(
        sim, demand
    )

    assert raw_procurement.orders[0].requested_amount_t == pytest.approx(10.0)
    assert procurement.orders[0].amount_t == pytest.approx(2.5)
    sim.logistics.advance_external_procurement(sim.day, procurement, funds)
    supply = next(iter(sim.logistics.external_supply_batches.values()))
    assert supply.amount_t == pytest.approx(2.5)


def test_external_supply_waits_for_inventory_admission_capacity():
    sim = build_base_simulation()
    demand = _demand(amount=3.0)
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    _enable_for_demand(sim, demand)

    _, _, _, procurement, funds = _plan_and_authorize_procurement(sim, demand)
    sim.logistics.advance_external_procurement(sim.day, procurement, funds)
    supply = next(iter(sim.logistics.external_supply_batches.values()))

    physical = dict(sim.inventory.physical_storage_capacity_t)
    usable = dict(sim.inventory.usable_storage_capacity_t)
    usable[(ids.EARTH, "general_cargo")] = 0.0
    sim.inventory.set_capacity_snapshot(physical, usable)
    sim.logistics.settle_external_supply(supply.available_day)

    assert supply.status is ExternalSupplyStatus.ADMISSION_WAITING
    assert supply.amount_t == pytest.approx(3.0)
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(0.0)

    usable[(ids.EARTH, "general_cargo")] = physical[(ids.EARTH, "general_cargo")]
    sim.inventory.set_capacity_snapshot(physical, usable)
    sim.logistics.settle_external_supply(supply.available_day + 1)
    assert supply.id not in sim.logistics.external_supply_batches
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) == pytest.approx(3.0)


def test_remote_procurement_replenishes_logistics_source_without_bypassing_transport():
    sim = build_base_simulation()
    sim.transport.transport_allocations.clear()
    sim.inventory.stock[(ids.EARTH, ids.MACHINERY)] = 0.0
    sim.inventory.stock[(ids.LEO, ids.MACHINERY)] = 0.0
    sim.logistics.set_supply_policy(
        ids.LEO, ids.MACHINERY, preferred_source_id=ids.EARTH
    )
    target_id = sim.logistics.set_target_stock(ids.LEO, ids.MACHINERY, 1.0, 4)
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(
            ids.EARTH_INDUSTRIAL_MARKET,
            ids.EARTH_LEO_LAUNCH_SERVICE,
        ),
        day=sim.day,
    )

    initial = sim.tick_decision_projection()
    assert not [
        row for row, _amount in initial.allocations.transport.executable_dispatches
        if row.requirement.owner_id == target_id
    ]

    sim.advance_days(1)
    supply = next(
        row for row in sim.logistics.external_supply_batches.values()
        if row.requirement_id.startswith("supply.target_stock:")
        and row.supply_node_id == ids.EARTH
        and row.resource_id == ids.MACHINERY
    )
    assert supply.supply_node_id != ids.LEO
    assert sim.inventory.amount(ids.LEO, ids.MACHINERY) == pytest.approx(0.0)

    sim.advance_to_day(supply.available_day)
    assert sim.inventory.amount(ids.EARTH, ids.MACHINERY) >= 1.0
    assert sim.inventory.amount(ids.LEO, ids.MACHINERY) == pytest.approx(0.0)
    ready = sim.tick_decision_projection()
    assert any(
        row.requirement.owner_id == target_id and amount > 0.0
        for row, amount in ready.allocations.transport.executable_dispatches
    )

    sim.advance_days(1)
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    assert flow.source_id == ids.EARTH
    assert flow.final_destination_id == ids.LEO
    assert flow.leg.external_service_id == ids.EARTH_LEO_LAUNCH_SERVICE
    assert sim.inventory.amount(ids.LEO, ids.MACHINERY) == pytest.approx(0.0)

    sim.advance_to_day(flow.first_arrival_day)
    assert sim.inventory.amount(ids.LEO, ids.MACHINERY) >= 1.0

def test_explicit_source_demand_is_not_replaced_by_destination_procurement():
    from space_idle.external_procurement import ExternalProcurementServiceDef
    from space_idle.logistics_flow import LogisticsResourcePlan

    sim = build_base_simulation()
    demand = _demand(destination=ids.LEO, amount=1.0, source=ids.EARTH)
    destination_service = ExternalProcurementServiceDef(
        id=DefinitionId("test.procurement.leo"),
        display_name="Test LEO Market",
        supply_node_id=ids.LEO,
        resource_prices_musd_per_t=((ids.MACHINERY, 0.1),),
        supply_latency_days=1,
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
        LogisticsResourcePlan((), (), ()),
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
    assert row.supply_node_id == str(ids.EARTH)
    assert row.supply_latency_days > 0
    prices = dict(row.resource_prices_musd_per_t)
    assert str(ids.MACHINERY) in prices
    assert prices[str(ids.MACHINERY)] >= 0.0
