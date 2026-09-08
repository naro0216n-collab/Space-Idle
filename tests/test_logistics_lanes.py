from __future__ import annotations

import pytest

from space_idle import build_game_application
from space_idle.content.base_game import (
    EARTH,
    LEO,
    MACHINERY,
    ORBITAL_LOGISTICS_NODE,
    PRECISION_ELECTRONICS,
    TECH_CISLUNAR_LOGISTICS,
    TECH_ORBITAL_OPERATIONS,
)
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import EntityId


def _demand(amount_t: float, *, demand_id: str = "demand.test") -> ResourceDemand:
    return ResourceDemand(
        EntityId(demand_id),
        "test",
        EntityId("test.owner"),
        LEO,
        MACHINERY,
        amount_t,
        50,
        EARTH,
    )


def test_lane_is_resource_agnostic_and_requested_capacity_limits_daily_order_creation():
    app = build_game_application()
    sim = app._simulation
    lane_id = sim.logistics.create_lane(EARTH, LEO, 1.0, 50)
    lane = sim.logistics.lanes[lane_id]
    assert not hasattr(lane, "resource_id")
    assert not hasattr(lane, "target_stock_t")
    assert not hasattr(lane, "batch_t")

    demand = _demand(3.0)
    sim.logistics.advance_automation(sim.day, (demand,))
    lane_orders = [order for order in sim.logistics.orders.values() if order.lane_id == lane_id]
    assert sum(order.amount_t for order in lane_orders) == pytest.approx(1.0)
    assert all(order.demand_id == demand.id for order in lane_orders)

    sim.logistics.advance_automation(sim.day, (demand,))
    same_day = [
        order for order in sim.logistics.orders.values()
        if order.lane_id == lane_id and order.created_day == sim.day
    ]
    assert sum(order.amount_t for order in same_day) == pytest.approx(1.0)


def test_demand_without_lane_does_not_create_hidden_transport_order():
    app = build_game_application()
    sim = app._simulation
    before = tuple(sim.logistics.orders)
    sim.logistics.advance_automation(sim.day, (_demand(1.0),))
    assert tuple(sim.logistics.orders) == before


def test_one_demand_is_not_duplicated_across_multiple_matching_lanes():
    app = build_game_application()
    sim = app._simulation
    first = sim.logistics.create_lane(EARTH, LEO, 1.0, 100)
    second = sim.logistics.create_lane(EARTH, LEO, 1.0, 50)
    demand = _demand(1.5)

    sim.logistics.advance_automation(sim.day, (demand,))
    automatic = [
        order for order in sim.logistics.orders.values()
        if order.demand_id == demand.id and order.lane_id in {first, second}
    ]
    assert sum(order.amount_t for order in automatic) == pytest.approx(demand.amount_t)
    assert sim.logistics.demand_pipeline_t(demand.id) == pytest.approx(demand.amount_t)


def _unlock_orbital_logistics(sim) -> None:
    sim.technology.completed.update({TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS})


def test_construction_declares_source_constrained_import_demand_and_waits_for_matching_lane():
    app = build_game_application()
    sim = app._simulation
    _unlock_orbital_logistics(sim)
    project_id = sim.projects.plan_build(
        ORBITAL_LOGISTICS_NODE,
        LEO,
        50,
        "import_now",
        day=sim.day,
        import_source_id=EARTH,
    )

    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.resource_demands(sim.day)
    assert demands
    assert all(demand.owner_kind == "project" for demand in demands)
    assert all(demand.source_id == EARTH and demand.destination_id == LEO for demand in demands)
    assert not [order for order in sim.logistics.orders.values() if order.owner_id == EntityId(project_id)]
    blocker_codes = {blocker.code for blocker in sim.projects.blockers(project_id, sim.day)}
    assert "import_lane" in blocker_codes

    lane_id = sim.logistics.create_lane(EARTH, LEO, 100.0, 100)
    sim.logistics.advance_automation(sim.day, demands)
    generated = [order for order in sim.logistics.orders.values() if order.lane_id == lane_id]
    assert generated
    assert all(order.owner_kind == "project" for order in generated)
    assert all(order.demand_id is not None for order in generated)


def test_construction_without_source_constraint_allows_lane_to_choose_supply_source():
    app = build_game_application()
    sim = app._simulation
    _unlock_orbital_logistics(sim)
    project_id = sim.projects.plan_build(
        ORBITAL_LOGISTICS_NODE,
        LEO,
        50,
        "import_now",
        day=sim.day,
        import_source_id=None,
    )

    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.resource_demands(sim.day)
    assert demands
    assert all(demand.destination_id == LEO for demand in demands)
    assert all(demand.source_id is None for demand in demands)
    assert "import_lane" in {blocker.code for blocker in sim.projects.blockers(project_id, sim.day)}

    lane_id = sim.logistics.create_lane(EARTH, LEO, 100.0, 100)
    sim.logistics.advance_automation(sim.day, demands)
    generated = [
        order for order in sim.logistics.orders.values()
        if order.owner_id == EntityId(project_id) and order.lane_id == lane_id
    ]
    assert generated
    assert all(order.source_id == EARTH and order.destination_id == LEO for order in generated)


def test_selected_research_prototype_site_declares_material_demand_until_stock_arrives():
    app = build_game_application()
    sim = app._simulation
    assert sim.research is not None
    definition = sim.research.definitions[TECH_ORBITAL_OPERATIONS]
    sim.research.stored_points = definition.research_point_cost
    sim.research.start(TECH_ORBITAL_OPERATIONS, day=sim.day)
    sim.research.set_prototype_site(TECH_ORBITAL_OPERATIONS, EARTH, sim.day)

    available = sim.inventory.available(EARTH, PRECISION_ELECTRONICS)
    if available > 0:
        assert sim.inventory.take_unreserved(EARTH, PRECISION_ELECTRONICS, available)
    demands = sim.research.resource_demands(sim.day)
    demand = next(item for item in demands if item.resource_id == PRECISION_ELECTRONICS)
    assert demand.owner_kind == "research"
    assert demand.destination_id == EARTH
    assert demand.source_id is None
    with pytest.raises(ValueError, match="prototype resource shortfall"):
        sim.research.fund_prototype(TECH_ORBITAL_OPERATIONS, sim.day)
