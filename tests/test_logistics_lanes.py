from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import GetBottlenecks, GetProjects, build_game_application
from space_idle.content.base_game import (
    EARTH,
    LEO,
    LUNAR_ORBIT,
    MACHINERY,
    ORBITAL_LOGISTICS_NODE,
    PRECISION_ELECTRONICS,
    PROPELLANT,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    TECH_CISLUNAR_LOGISTICS,
    TECH_ORBITAL_OPERATIONS,
)
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import DefinitionId, EntityId


def _demand(amount_t: float, *, demand_id: str = "demand.test", destination=LEO, source=EARTH) -> ResourceDemand:
    return ResourceDemand(
        EntityId(demand_id), "test", EntityId("test.owner"), destination,
        MACHINERY, amount_t, 50, source, 0.0,
    )


def _owned_earth_leo_capacity(sim, units: int = 1):
    sim.logistics.external_services.clear()
    return sim.logistics.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=units, day=sim.day
    )


def test_lane_is_resource_agnostic_and_requested_capacity_limits_daily_cargo_flow():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    lane_id = sim.logistics.create_lane(EARTH, LEO, 1.0, 50)
    lane = sim.logistics.lanes[lane_id]
    assert not hasattr(lane, "resource_id")
    assert not hasattr(lane, "target_stock_t")
    assert not hasattr(lane, "batch_t")

    sim.inventory.add(EARTH, MACHINERY, 3.0)
    demand = _demand(3.0)
    sim.logistics.advance_capacity_logistics(sim.day, (demand,))
    flows = [flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id]
    assert sum(flow.amount_t for flow in flows) == pytest.approx(1.0)
    assert all(flow.demand_id == demand.id for flow in flows)
    assert not hasattr(sim.logistics, "orders")
    assert not hasattr(sim.logistics, "missions")


def test_lane_uses_parallel_transport_services_until_requested_capacity_is_filled():
    sim = build_game_application()._simulation
    sim.logistics.transport_allocations.clear()
    base = next(
        service for service in sim.logistics.external_services.values()
        if service.display_name == "商業地表打上げ"
    )
    second_id = DefinitionId("test.service.parallel-earth-leo")
    sim.logistics.external_services[second_id] = replace(
        base, id=second_id, display_name="Parallel Earth-LEO", capacity_t_per_day=0.4
    )
    lane_id = sim.logistics.create_lane(EARTH, LEO, 2.0, 100)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    demand = _demand(2.0, demand_id="demand.parallel-services")

    sim.logistics.advance_capacity_logistics(sim.day, (demand,))

    flows = [flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id]
    assert sum(flow.amount_t for flow in flows) == pytest.approx(2.0)
    assert len(flows) == 2
    used_services = {flow.service_ids[0].split(":", 2)[1] for flow in flows}
    assert used_services == {str(base.id), str(second_id)}


def test_parallel_lanes_share_transport_capacity_without_double_consumption():
    sim = build_game_application()._simulation
    sim.logistics.transport_allocations.clear()
    high_lane = sim.logistics.create_lane(EARTH, LEO, 1.0, 100)
    low_lane = sim.logistics.create_lane(EARTH, LEO, 1.0, 50)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    high_demand = _demand(1.0, demand_id="demand.high")
    low_demand = ResourceDemand(
        EntityId("demand.low"), "test-low", EntityId("owner.low"),
        LEO, MACHINERY, 1.0, 40, EARTH, 0.0,
    )

    sim.logistics.advance_capacity_logistics(sim.day, (high_demand, low_demand))

    by_lane = {high_lane: 0.0, low_lane: 0.0}
    for flow in sim.logistics.cargo_flows.values():
        if flow.lane_id in by_lane:
            by_lane[flow.lane_id] += flow.amount_t
    service_capacity = next(
        service.capacity_t_per_day for service in sim.logistics.external_services.values()
        if service.display_name == "商業地表打上げ"
    )
    assert by_lane[high_lane] == pytest.approx(1.0)
    assert by_lane[low_lane] == pytest.approx(service_capacity - 1.0)
    assert sum(by_lane.values()) == pytest.approx(service_capacity)


def test_same_priority_lane_capacity_allocation_is_registration_order_independent():
    def run(capacities: tuple[float, float]) -> dict[float, float]:
        sim = build_game_application()._simulation
        sim.logistics.transport_allocations.clear()
        sim.inventory.add(EARTH, MACHINERY, 3.0)
        lanes = {
            capacity: sim.logistics.create_lane(EARTH, LEO, capacity, 50)
            for capacity in capacities
        }
        demand = _demand(3.0, demand_id="demand.same-priority-lanes")
        sim.logistics.advance_capacity_logistics(sim.day, (demand,))
        used = {capacity: 0.0 for capacity in capacities}
        by_id = {lane_id: capacity for capacity, lane_id in lanes.items()}
        for flow in sim.logistics.cargo_flows.values():
            if flow.lane_id in by_id:
                used[by_id[flow.lane_id]] += flow.amount_t
        return used

    forward = run((1.0, 2.0))
    reverse = run((2.0, 1.0))
    assert forward == pytest.approx(reverse)
    assert forward[1.0] > 0


def test_demand_without_lane_does_not_create_hidden_transport_state():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    sim.logistics.advance_capacity_logistics(sim.day, (_demand(1.0),))
    assert not sim.logistics.cargo_flows
    assert not hasattr(sim.logistics, "orders")


def test_one_demand_is_not_duplicated_across_multiple_matching_lanes():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    first = sim.logistics.create_lane(EARTH, LEO, 1.0, 100)
    second = sim.logistics.create_lane(EARTH, LEO, 1.0, 50)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    demand = _demand(1.5)

    sim.logistics.advance_capacity_logistics(sim.day, (demand,))
    flows = [
        flow for flow in sim.logistics.cargo_flows.values()
        if flow.demand_id == demand.id and flow.lane_id in {first, second}
    ]
    assert sum(flow.amount_t for flow in flows) == pytest.approx(demand.amount_t)
    assert sim.logistics._flow_pipeline_by_demand({demand.id})[demand.id] == pytest.approx(demand.amount_t)


def _unlock_orbital_logistics(sim) -> None:
    sim.technology.completed.update({TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS})


def test_construction_declares_source_constrained_import_demand_and_uses_matching_lane():
    app = build_game_application()
    sim = app._simulation
    _unlock_orbital_logistics(sim)
    _owned_earth_leo_capacity(sim)
    project_id = sim.projects.plan_build(
        ORBITAL_LOGISTICS_NODE, LEO, 50, "import_now", day=sim.day,
        import_source_id=EARTH,
    )
    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.resource_demands(sim.day)
    assert demands
    assert all(demand.source_id == EARTH and demand.destination_id == LEO for demand in demands)
    project_row = next(row for row in app.query(GetProjects()).items if row.id == str(project_id))
    assert "import_lane" in {code for code, _detail in project_row.blockers}
    location_issues = [
        issue for issue in app.query(GetBottlenecks(str(LEO))).items
        if issue.entity_id == str(project_id)
    ]
    assert "import_lane" in {issue.code for issue in location_issues}

    lane_id = sim.logistics.create_lane(EARTH, LEO, 100.0, 100)
    sim.logistics.advance_capacity_logistics(sim.day, demands)
    generated = [flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id]
    assert generated
    assert all(flow.owner_kind == "project" for flow in generated)
    assert all(flow.demand_id is not None for flow in generated)


def test_construction_without_source_constraint_allows_lane_to_choose_supply_source():
    app = build_game_application()
    sim = app._simulation
    _unlock_orbital_logistics(sim)
    _owned_earth_leo_capacity(sim)
    project_id = sim.projects.plan_build(
        ORBITAL_LOGISTICS_NODE, LEO, 50, "import_now", day=sim.day,
        import_source_id=None,
    )
    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.resource_demands(sim.day)
    assert demands and all(demand.source_id is None for demand in demands)
    lane_id = sim.logistics.create_lane(EARTH, LEO, 100.0, 100)
    sim.logistics.advance_capacity_logistics(sim.day, demands)
    generated = [
        flow for flow in sim.logistics.cargo_flows.values()
        if flow.owner_id == EntityId(project_id) and flow.lane_id == lane_id
    ]
    assert generated
    assert all(flow.source_id == EARTH and flow.destination_id == LEO for flow in generated)


def test_selected_research_prototype_site_declares_material_demand_until_stock_arrives():
    sim = build_game_application()._simulation
    assert sim.research is not None
    definition = sim.research.definitions[TECH_ORBITAL_OPERATIONS]
    sim.research.stored_points = definition.research_point_cost
    sim.research.start(TECH_ORBITAL_OPERATIONS, day=sim.day)
    sim.research.set_prototype_site(TECH_ORBITAL_OPERATIONS, EARTH, sim.day)
    available = sim.inventory.available(EARTH, PRECISION_ELECTRONICS)
    if available > 0:
        assert sim.inventory.take_unreserved(EARTH, PRECISION_ELECTRONICS, available)
    demand = next(
        item for item in sim.research.resource_demands(sim.day)
        if item.resource_id == PRECISION_ELECTRONICS
    )
    assert demand.owner_kind == "research"
    assert demand.destination_id == EARTH
    with pytest.raises(ValueError, match="prototype resource shortfall"):
        sim.research.fund_prototype(TECH_ORBITAL_OPERATIONS, sim.day)


def test_available_capacity_tracks_tick_start_propellant_without_changing_required_units():
    sim = build_game_application()._simulation
    allocation_id = _owned_earth_leo_capacity(sim)
    unconstrained = sim.logistics.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert unconstrained.available.forward_t_per_day > 0
    required = unconstrained.required_units

    available_propellant = sim.inventory.available(EARTH, PROPELLANT)
    assert sim.inventory.take_unreserved(EARTH, PROPELLANT, available_propellant)
    constrained = sim.logistics.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert constrained.available.forward_t_per_day == 0
    assert constrained.required_units == required
    assert any(value.startswith("resource:") for value in constrained.limiting_factors)


def test_multistage_lane_requires_capacity_on_every_handoff_leg():
    sim = build_game_application()._simulation
    sim.logistics.external_services.clear()
    sim.logistics.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=sim.day
    )
    lane_id = sim.logistics.create_lane(EARTH, LUNAR_ORBIT, 10.0, 100)
    demand = _demand(1.0, demand_id="demand.multistage", destination=LUNAR_ORBIT, source=EARTH)
    blocked = sim.logistics.lane_snapshot((demand,), sim.day)
    assert next(row for row in blocked.lanes if row.lane_id == lane_id).effective_capacity_t_per_day == 0

    # A reusable cislunar service needs its full operating cycle to be
    # sustainable: refueling infrastructure and propellant must exist at both
    # endpoints, not merely at the allocation anchor.
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.add(LEO, PROPELLANT, 10.0)
    sim.inventory.add(LUNAR_ORBIT, PROPELLANT, 10.0)
    sim.logistics.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT, target_units=1, day=sim.day
    )
    available = sim.logistics.lane_snapshot((demand,), sim.day)
    metric = next(row for row in available.lanes if row.lane_id == lane_id)
    assert metric.effective_capacity_t_per_day > 0

def test_multistage_cargo_flow_records_handoffs_and_cumulative_latency():
    sim = build_game_application()._simulation
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    lane_id = sim.logistics.create_lane(EARTH, LUNAR_ORBIT, 1.0, 100)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    demand = _demand(
        1.0,
        demand_id="demand.multistage-flow",
        destination=LUNAR_ORBIT,
        source=EARTH,
    )

    sim.logistics.advance_capacity_logistics(sim.day, (demand,))

    flow = next(flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id)
    assert flow.service_destinations == (LEO, LUNAR_ORBIT)
    assert len(flow.service_ids) == 2
    assert flow.ready_day - flow.departure_day == 7
    dispatched_amount = flow.amount_t
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == 0

    sim.logistics._progress_cargo_arrivals(flow.ready_day - 1)
    assert flow.id in sim.logistics.cargo_flows
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == 0

    sim.logistics._progress_cargo_arrivals(flow.ready_day)
    assert flow.id not in sim.logistics.cargo_flows
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == pytest.approx(dispatched_amount)
