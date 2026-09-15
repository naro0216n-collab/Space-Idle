from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import GetBottlenecks, GetCargoFlows, GetProjects, build_game_application
from space_idle.content.base_game import (
    EARTH,
    LEO,
    LUNAR_ORBIT,
    MACHINERY,
    WATER,
    ORBITAL_LOGISTICS_NODE,
    PRECISION_ELECTRONICS,
    PROPELLANT,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    TECH_CISLUNAR_LOGISTICS,
    TECH_ORBITAL_OPERATIONS,
)
from space_idle.resource_claim import allocate_resource_claims
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import DefinitionId, EntityId


def _demand(amount_t: float, *, demand_id: str = "demand.test", destination=LEO, source=EARTH, resource=MACHINERY) -> ResourceDemand:
    return ResourceDemand(
        EntityId(demand_id), "test", EntityId("test.owner"), destination,
        resource, amount_t, 3, source,
    )


def _owned_earth_leo_capacity(sim, units: int = 1):
    sim.transport.external_services.clear()
    return sim.transport.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=units, day=sim.day
    )


def _allow_external_transport(sim) -> None:
    for service_id in sim.transport.external_services:
        sim.external_economy.register_service(service_id)
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=tuple(sim.transport.external_services),
        day=sim.day,
    )


def _advance_logistics(sim, day, demands):
    plan = sim.logistics.plan_capacity_logistics(day, tuple(demands))
    funds = sim.external_economy.allocate(plan.spending_requests, day)
    authorized = sim.logistics.authorize_capacity_logistics(plan, funds, day)
    allocations = allocate_resource_claims(authorized.claims, sim.inventory)
    services = _transport_service_allocations(sim, day, authorized)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        day, authorized, allocations, services
    )
    sim.logistics.advance_capacity_logistics(
        day, authorized, funds, execution,
    )
    return authorized, allocations



def _transport_service_allocations(sim, day, plan):
    requests = sim.transport.transport_service_capacity_requests(day, plan.planned_usage)
    locations = sim._active_locations() | set(sim.graph.operational_node_ids())
    powers = {
        location_id: sim.power.snapshot(location_id, sim.facilities, day)
        for location_id in locations
    }
    return sim._allocate_tick_services(powers, requests)

def test_lane_is_resource_agnostic_and_requested_capacity_limits_daily_cargo_flow():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    lane_id = sim.logistics.create_lane(EARTH, LEO, 1.0, 3)

    sim.inventory.add(EARTH, MACHINERY, 1.0)
    sim.inventory.add(EARTH, WATER, 1.0)
    demands = (
        _demand(0.5, demand_id="demand.machinery", resource=MACHINERY),
        _demand(0.5, demand_id="demand.water", resource=WATER),
    )
    _advance_logistics(sim, sim.day, demands)
    flows = [flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id]
    assert sum(flow.amount_t for flow in flows) == pytest.approx(1.0)
    assert {flow.resource_id for flow in flows} == {MACHINERY, WATER}
    assert {flow.demand_id for flow in flows} == {demand.id for demand in demands}


def test_lane_uses_parallel_transport_services_until_requested_capacity_is_filled():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    base = next(
        service for service in sim.transport.external_services.values()
        if service.display_name == "商業地表打上げ"
    )
    second_id = DefinitionId("test.service.parallel-earth-leo")
    sim.transport.external_services[second_id] = replace(
        base, id=second_id, display_name="Parallel Earth-LEO", capacity_t_per_day=0.4
    )
    _allow_external_transport(sim)
    lane_id = sim.logistics.create_lane(EARTH, LEO, 2.0, 5)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    demand = _demand(2.0, demand_id="demand.parallel-services")

    _advance_logistics(sim, sim.day, (demand,))

    flows = [flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id]
    assert sum(flow.amount_t for flow in flows) == pytest.approx(2.0)
    assert len(flows) == 2
    used_services = {flow.service_ids[0].split(":", 2)[1] for flow in flows}
    assert used_services == {str(base.id), str(second_id)}


def test_parallel_lanes_share_transport_capacity_without_double_consumption():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    high_lane = sim.logistics.create_lane(EARTH, LEO, 1.0, 5)
    low_lane = sim.logistics.create_lane(EARTH, LEO, 1.0, 3)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    high_demand = _demand(1.0, demand_id="demand.high")
    low_demand = ResourceDemand(
        EntityId("demand.low"), "test-low", EntityId("owner.low"),
        LEO, MACHINERY, 1.0, 2, EARTH,
    )

    _advance_logistics(sim, sim.day, (high_demand, low_demand))

    by_lane = {high_lane: 0.0, low_lane: 0.0}
    for flow in sim.logistics.cargo_flows.values():
        if flow.lane_id in by_lane:
            by_lane[flow.lane_id] += flow.amount_t
    service_capacity = next(
        service.capacity_t_per_day for service in sim.transport.external_services.values()
        if service.display_name == "商業地表打上げ"
    )
    assert by_lane[high_lane] == pytest.approx(1.0)
    assert by_lane[low_lane] == pytest.approx(service_capacity - 1.0)
    assert sum(by_lane.values()) == pytest.approx(service_capacity)


def test_same_priority_lane_capacity_allocation_is_registration_order_independent():
    def run(capacities: tuple[float, float]) -> dict[float, float]:
        sim = build_game_application()._simulation
        sim.transport.transport_allocations.clear()
        _allow_external_transport(sim)
        sim.inventory.add(EARTH, MACHINERY, 3.0)
        lanes = {
            capacity: sim.logistics.create_lane(EARTH, LEO, capacity, 3)
            for capacity in capacities
        }
        demand = _demand(3.0, demand_id="demand.same-priority-lanes")
        _advance_logistics(sim, sim.day, (demand,))
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


def test_demand_without_lane_creates_no_cargo_flow():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    _advance_logistics(sim, sim.day, (_demand(1.0),))
    assert not sim.logistics.cargo_flows


def test_one_demand_is_not_duplicated_across_multiple_matching_lanes():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    first = sim.logistics.create_lane(EARTH, LEO, 1.0, 5)
    second = sim.logistics.create_lane(EARTH, LEO, 1.0, 3)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    demand = _demand(1.5)

    _advance_logistics(sim, sim.day, (demand,))
    flows = [
        flow for flow in sim.logistics.cargo_flows.values()
        if flow.demand_id == demand.id and flow.lane_id in {first, second}
    ]
    assert sum(flow.amount_t for flow in flows) == pytest.approx(demand.amount_t)
    assert sim.logistics.cargo_flow_pipeline_t(demand.id) == pytest.approx(demand.amount_t)


def _unlock_orbital_logistics(sim) -> None:
    sim.technology.completed.update({TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS})


def test_construction_declares_source_constrained_import_demand_and_uses_matching_lane():
    app = build_game_application()
    sim = app._simulation
    _unlock_orbital_logistics(sim)
    _owned_earth_leo_capacity(sim)
    project_id = sim.projects.plan_build(
        ORBITAL_LOGISTICS_NODE, LEO, 3, "import_now", day=sim.day,
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

    lane_id = sim.logistics.create_lane(EARTH, LEO, 100.0, 5)
    _advance_logistics(sim, sim.day, demands)
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
        ORBITAL_LOGISTICS_NODE, LEO, 3, "import_now", day=sim.day,
        import_source_id=None,
    )
    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.resource_demands(sim.day)
    assert demands and all(demand.source_id is None for demand in demands)
    lane_id = sim.logistics.create_lane(EARTH, LEO, 100.0, 5)
    _advance_logistics(sim, sim.day, demands)
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
    for _ in range(2000):
        state = sim.research.active[TECH_ORBITAL_OPERATIONS]
        if state.stage.value == "prototype":
            break
        sim.advance_days(1)
    assert sim.research.active[TECH_ORBITAL_OPERATIONS].stage.value == "prototype"
    sim.research.set_prototype_site(TECH_ORBITAL_OPERATIONS, EARTH, sim.day)
    available = sim.inventory.available(EARTH, PRECISION_ELECTRONICS)
    if available > 0:
        sim.inventory.consume_allocated(EARTH, PRECISION_ELECTRONICS, available)
    demand = next(
        item for item in sim.research.resource_demands(sim.day)
        if item.resource_id == PRECISION_ELECTRONICS
    )
    assert demand.owner_kind == "research"
    assert demand.destination_id == EARTH
    reservation = next(
        item for item in sim.research.reservation_acquisition_requirements(sim.day)
        if item.resource_id == PRECISION_ELECTRONICS
    )
    assert reservation.requested_amount > 0
    assert reservation.operational_node_id == EARTH


def test_available_capacity_uses_shared_propellant_allocation_without_changing_required_units():
    sim = build_game_application()._simulation
    allocation_id = _owned_earth_leo_capacity(sim)
    unconstrained = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert unconstrained.available.forward_t_per_day > 0
    required = unconstrained.required_units
    sim.logistics.create_lane(EARTH, LEO, 1.0, 3)
    sim.inventory.add(EARTH, MACHINERY, 1.0)

    available_propellant = sim.inventory.available(EARTH, PROPELLANT)
    sim.inventory.consume_allocated(EARTH, PROPELLANT, available_propellant)
    raw = sim.logistics.plan_capacity_logistics(
        sim.day, (_demand(1.0, demand_id="demand.resource-limited-capacity"),)
    )
    funds = sim.external_economy.allocate(raw.spending_requests, sim.day)
    plan = sim.logistics.authorize_capacity_logistics(raw, funds, sim.day)
    resources = allocate_resource_claims(plan.claims, sim.inventory)
    services = _transport_service_allocations(sim, sim.day, plan)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        sim.day, plan, resources, services
    )
    constrained = sim.logistics.current_transport_capacity_snapshot(
        allocation_id,
        day=sim.day,
        execution_allocation=execution,
    )

    assert constrained.available.forward_t_per_day == 0
    assert constrained.required_units == required
    assert any(
        value.startswith("resource_allocation:")
        for value in constrained.limiting_factors
    )


def test_multistage_lane_requires_capacity_on_every_handoff_leg():
    sim = build_game_application()._simulation
    sim.transport.external_services.clear()
    sim.transport.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=sim.day
    )
    lane_id = sim.logistics.create_lane(EARTH, LUNAR_ORBIT, 10.0, 5)
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
    sim.transport.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT, target_units=1, day=sim.day
    )
    available = sim.logistics.lane_snapshot((demand,), sim.day)
    metric = next(row for row in available.lanes if row.lane_id == lane_id)
    assert metric.effective_capacity_t_per_day > 0

def test_multistage_cargo_flow_records_handoffs_and_cumulative_latency():
    sim = build_game_application()._simulation
    _allow_external_transport(sim)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    lane_id = sim.logistics.create_lane(EARTH, LUNAR_ORBIT, 1.0, 5)
    lane = sim.logistics.lanes[lane_id]
    planned_path = sim.logistics.lane_service_path(lane, sim.day)
    assert len(planned_path) > 1
    initial_destination_machinery = sim.inventory.amount(LUNAR_ORBIT, MACHINERY)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    demand = _demand(
        1.0,
        demand_id="demand.multistage-flow",
        destination=LUNAR_ORBIT,
        source=EARTH,
    )

    _advance_logistics(sim, sim.day, (demand,))

    flow = next(flow for flow in sim.logistics.cargo_flows.values() if flow.lane_id == lane_id)
    assert flow.service_ids == tuple(edge.key for edge in planned_path)
    assert flow.service_destinations == tuple(edge.destination_id for edge in planned_path)
    assert flow.ready_day - flow.departure_day == sum(
        edge.latency_days for edge in planned_path
    )
    dispatched_amount = flow.amount_t
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == pytest.approx(
        initial_destination_machinery
    )

    sim.logistics.settle_cargo_arrivals(flow.ready_day - 1)
    assert flow.id in sim.logistics.cargo_flows
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == pytest.approx(
        initial_destination_machinery
    )

    sim.logistics.settle_cargo_arrivals(flow.ready_day)
    assert flow.id not in sim.logistics.cargo_flows
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == pytest.approx(
        initial_destination_machinery + dispatched_amount
    )


def test_transport_capacity_uses_only_cargo_settled_at_tick_boundary():
    sim = build_game_application()._simulation
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.transport.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG,
        LEO,
        LUNAR_ORBIT,
        target_units=1,
        day=0,
    )
    sim.inventory.add(LUNAR_ORBIT, PROPELLANT, 10.0)
    leo_propellant = sim.inventory.available(LEO, PROPELLANT)
    if leo_propellant > 0:
        sim.inventory.consume_allocated(LEO, PROPELLANT, leo_propellant)

    _allow_external_transport(sim)
    inbound_lane = sim.logistics.create_lane(EARTH, LEO, 1.0, 5)
    outbound_lane = sim.logistics.create_lane(LEO, LUNAR_ORBIT, 1.0, 5)
    sim.inventory.add(EARTH, PROPELLANT, 1.0)
    inbound = ResourceDemand(
        EntityId("demand.propellant-inbound"),
        "test",
        EntityId("owner.propellant-inbound"),
        LEO,
        PROPELLANT,
        1.0,
        5,
        EARTH,
    )
    _advance_logistics(sim, 0, (inbound,))
    arriving = next(
        flow
        for flow in sim.logistics.cargo_flows.values()
        if flow.lane_id == inbound_lane
    )
    service_by_key = {
        row.key: row for row in sim.transport.transport_service_supplies(arriving.departure_day)
    }
    assert arriving.ready_day - arriving.departure_day == sum(
        service_by_key[key].latency_days for key in arriving.service_ids
    )
    sim.transport.external_services.clear()

    sim.inventory.add(LEO, MACHINERY, 1.0)
    outbound = _demand(
        1.0,
        demand_id="demand.boundary-propellant",
        destination=LUNAR_ORBIT,
        source=LEO,
    )

    # Movement/execution for day 2 does not perform boundary admission.
    _advance_logistics(sim, 2, (outbound,))
    assert sim.inventory.available(LEO, PROPELLANT) == pytest.approx(0.0)
    assert not any(
        flow.lane_id == outbound_lane and flow.demand_id == outbound.id
        for flow in sim.logistics.cargo_flows.values()
    )

    # Once day 2 boundary settlement runs, the arrival belongs to the physical
    # snapshot for day 2 and may support that tick's allocation.
    sim.logistics.settle_cargo_arrivals(2)
    assert sim.inventory.available(LEO, PROPELLANT) > 0
    _advance_logistics(sim, 2, (outbound,))
    assert any(
        flow.lane_id == outbound_lane and flow.demand_id == outbound.id
        for flow in sim.logistics.cargo_flows.values()
    )

def test_cargo_arrival_waits_for_destination_storage_admission():
    app = build_game_application()
    sim = app._simulation
    _allow_external_transport(sim)
    lane_id = sim.logistics.create_lane(EARTH, LEO, 1.0, 5)
    free_before = sim.inventory.free_capacity(LEO, MACHINERY)
    assert free_before is not None and free_before > 0
    sim.inventory.add(LEO, PRECISION_ELECTRONICS, free_before)
    assert sim.inventory.free_capacity(LEO, MACHINERY) == pytest.approx(0.0)

    source_before = sim.inventory.amount(EARTH, MACHINERY)
    destination_before = sim.inventory.amount(LEO, MACHINERY)
    demand = _demand(1.0, demand_id="demand.arrival-waiting")
    _advance_logistics(sim, 0, (demand,))
    flow = next(
        flow
        for flow in sim.logistics.cargo_flows.values()
        if flow.lane_id == lane_id and flow.demand_id == demand.id
    )
    assert sim.inventory.amount(EARTH, MACHINERY) == pytest.approx(source_before - 1.0)

    sim.logistics.settle_cargo_arrivals(flow.ready_day)
    assert flow.id in sim.logistics.cargo_flows
    assert flow.status.value == "arrival_waiting"
    assert flow.amount_t == pytest.approx(1.0)
    assert sim.inventory.amount(LEO, MACHINERY) == pytest.approx(destination_before)
    projected = next(item for item in app.query(GetCargoFlows()).items if item.id == str(flow.id))
    assert projected.admission_blockers
    assert any("storage" in blocker for blocker in projected.admission_blockers)

    sim.inventory.consume_allocated(LEO, PRECISION_ELECTRONICS, 1.0)
    sim.logistics.settle_cargo_arrivals(flow.ready_day + 1)
    assert flow.id not in sim.logistics.cargo_flows
    assert sim.inventory.amount(LEO, MACHINERY) == pytest.approx(destination_before + 1.0)


def test_dispatch_source_claim_competes_with_higher_priority_local_use():
    from space_idle.resource_claim import ResourceClaim

    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.logistics.create_lane(EARTH, LEO, 1.0, 3)
    sim.inventory.stock[(EARTH, MACHINERY)] = 1.0
    demand = _demand(1.0, demand_id="demand.source-competition")
    plan = sim.logistics.plan_capacity_logistics(sim.day, (demand,))
    cargo_claim = next(claim for claim in plan.claims if claim.owner_kind == "logistics_dispatch")
    local_claim = ResourceClaim(
        EntityId("claim.local-use"), EARTH, MACHINERY, 1.0, 5,
        "test_local_use", EntityId("owner.local-use"), "local_use",
    )

    funds = sim.external_economy.allocate(plan.spending_requests, sim.day)
    plan = sim.logistics.authorize_capacity_logistics(plan, funds, sim.day)
    allocations = allocate_resource_claims(plan.claims + (local_claim,), sim.inventory)
    services = _transport_service_allocations(sim, sim.day, plan)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        sim.day, plan, allocations, services
    )
    sim.logistics.advance_capacity_logistics(
        sim.day, plan, funds, execution,
    )

    assert allocations.allocated(local_claim.id) == pytest.approx(1.0)
    assert allocations.allocated(cargo_claim.id) == pytest.approx(0.0)
    assert not sim.logistics.cargo_flows
    assert sim.inventory.amount(EARTH, MACHINERY) == pytest.approx(1.0)
    sim.inventory.consume_allocated(EARTH, MACHINERY, allocations.allocated(local_claim.id))
    assert sim.inventory.amount(EARTH, MACHINERY) == pytest.approx(0.0)
