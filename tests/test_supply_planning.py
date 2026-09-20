from __future__ import annotations

from dataclasses import dataclass

import pytest

from space_idle import (
    GetCargoFlows, GetLogistics, GetProjects, PauseTransportAllocation,
    PlanBuild, ResumeTransportAllocation, SetSupplyRoutingConstraint, build_game_application,
)
from space_idle.content.base_game import (
    CONSTRUCTION_EQUIPMENT,
    EARTH,
    LEO,
    LUNAR_ORBIT,
    MACHINERY,
    ORBITAL_LOGISTICS_NODE,
    PROPELLANT,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    WATER,
)
from space_idle.execution_requirements import (
    ExecutionRequirementBundle,
    ResourceRequirement,
    allocate_execution_requirements,
    resource_constraint,
)
from space_idle.inventory import InventoryBook
from space_idle.logistics_models import CargoFlowSegment, CargoServiceLeg
from space_idle.path_selection import select_canonical_path
from space_idle.supply import (
    SupplyRequirement, SupplyRoutingConstraintScope, external_supply_requirements,
    resolve_local_supply,
)
from space_idle.shared import DefinitionId, EntityId


def _requirement(
    amount_t: float,
    *,
    requirement_id: str = "supply.test",
    destination=LEO,
    resource=MACHINERY,
    priority: int = 3,
    forecast_requirement_day: int | None = None,
) -> SupplyRequirement:
    return SupplyRequirement(
        EntityId(requirement_id),
        "test",
        EntityId(f"owner.{requirement_id}"),
        destination,
        resource,
        amount_t,
        priority,
        forecast_requirement_day=forecast_requirement_day,
    )


def _capacity_for_units(sim, vehicle_definition_id, source_id, destination_id, units):
    return sim.transport.transport_capacity_for_units(
        vehicle_definition_id, source_id, destination_id, units, day=sim.day
    )


def _owned_earth_leo_capacity(sim, units: int = 1):
    return sim.transport.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO,
        target_capacity=_capacity_for_units(
            sim, REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, units
        ),
        day=sim.day,
    )


def _owned_multistage_capacity(sim):
    if not any(
        facility.definition_id == ORBITAL_LOGISTICS_NODE and facility.operational_node_id == LEO
        for facility in sim.facilities.facilities.values()
    ):
        sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    if not any(
        facility.definition_id == ORBITAL_LOGISTICS_NODE and facility.operational_node_id == LUNAR_ORBIT
        for facility in sim.facilities.facilities.values()
    ):
        sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.add(LEO, PROPELLANT, 10.0)
    sim.inventory.add(LUNAR_ORBIT, PROPELLANT, 10.0)
    launch = sim.transport.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO,
        target_capacity=_capacity_for_units(
            sim, REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, 1
        ),
        day=sim.day,
    )
    tug = sim.transport.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT,
        target_capacity=_capacity_for_units(
            sim, REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT, 1
        ),
        day=sim.day,
    )
    return launch, tug



@dataclass(frozen=True)
class _PathEdge:
    id: str
    source: str
    destination: str
    time: float
    propellant: float
    capacity: float = 1.0


def _selected_path_ids(edges: tuple[_PathEdge, ...]) -> tuple[str, ...]:
    return tuple(
        edge.id
        for edge in select_canonical_path(
            "origin",
            "destination",
            outgoing=lambda node: tuple(edge for edge in edges if edge.source == node),
            edge_destination=lambda edge: edge.destination,
            edge_time=lambda edge: edge.time,
            edge_propellant=lambda edge: edge.propellant,
            edge_capacity=lambda edge: edge.capacity,
            edge_key=lambda edge: edge.id,
        )
    )


def test_canonical_path_combines_operational_metrics_and_is_registration_order_independent():
    edges = (
        _PathEdge("fast", "origin", "destination", 1.0, 10.0),
        _PathEdge("balanced", "origin", "destination", 2.0, 2.0),
        _PathEdge("efficient", "origin", "destination", 10.0, 1.0),
    )

    assert _selected_path_ids(edges) == ("balanced",)
    assert _selected_path_ids(tuple(reversed(edges))) == ("balanced",)

def test_recurring_supply_uses_latency_coverage_without_turning_pipeline_into_a_rate_cap():
    sim = build_game_application()._simulation
    allocation_id = _owned_earth_leo_capacity(sim)
    sim.inventory.stock[(LEO, MACHINERY)] = 0.0
    sim.inventory.stock[(EARTH, MACHINERY)] = 100.0
    requirement = SupplyRequirement(
        EntityId("supply.recurring-latency"), "test", EntityId("owner.recurring-latency"),
        LEO, MACHINERY, 2.0, 3, 2.0,
    )
    service = next(
        row for row in sim.transport.transport_service_supplies(sim.day)
        if row.allocation_id == allocation_id and row.direction == "forward"
    )

    active = sim.logistics.active_shipping_requirements(sim.day, (requirement,))
    assert active[0].amount_t == pytest.approx(2.0 * (service.latency_days + 1))

    sim.logistics.cargo_flows[EntityId("cargo.segment.recurring-test")] = CargoFlowSegment(
        id=EntityId("cargo.segment.recurring-test"), resource_id=MACHINERY, amount_t=2.0,
        source_id=EARTH, final_destination_id=LEO, requirement_id=requirement.id,
        owner_kind=requirement.owner_kind, owner_id=requirement.owner_id, priority=requirement.priority,
        leg=CargoServiceLeg(
            service.key, service.source_id, service.destination_id,
            service.latency_days, service.cycle_days, service.allocation_id, service.direction,
        ),
        remaining_legs=(), dispatch_start_day=sim.day, dispatch_end_day=sim.day + 1,
        dispatch_rate_t_per_day=2.0,
    )
    active_with_pipeline = sim.logistics.active_shipping_requirements(sim.day, (requirement,))
    plan = sim.logistics.plan_capacity_logistics(sim.day, active_with_pipeline)

    dispatch = next(row for row in plan.dispatches if row.requirement.id == requirement.id)
    assert dispatch.amount_t == pytest.approx(2.0 * service.latency_days)

def test_construction_supply_constraint_exposes_transport_blocker_and_recovers_with_owned_capacity():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update(
        sim.projects.recipes[ORBITAL_LOGISTICS_NODE].prerequisite_technologies
    )
    project_id = app.execute(
        PlanBuild(
            str(LEO),
            str(ORBITAL_LOGISTICS_NODE),
            priority=5,
            procurement_policy="immediate",
        )
    ).created_id
    assert project_id is not None
    app.execute(SetSupplyRoutingConstraint(
        destination_id=str(LEO), owner_kind="project", owner_id=project_id,
        source_node_id=str(EARTH),
    ))

    requirements = tuple(
        row for row in sim.projects.supplys(sim.day)
        if str(row.owner_id) == project_id
    )
    assert requirements
    assert all(
        sim.logistics.routing_constraint_for(row).source_node_id == EARTH
        for row in requirements
    )

    sim.advance_days(1)
    blocked_rows = [
        row for row in app.query(GetLogistics()).requirements
        if row.owner_id == project_id
    ]
    assert blocked_rows
    assert all(row.candidate_source_count == 1 for row in blocked_rows)
    assert all(row.stocked_source_count == 1 for row in blocked_rows)
    assert all(row.operational_source_count == 0 for row in blocked_rows)
    assert all(row.supply_state == "transport_blocked" for row in blocked_rows)
    assert all(
        any(blocker.code == "no_transport_capacity" for blocker in row.blockers)
        for row in blocked_rows
    )
    assert all(row.physical_movement_plan_ids for row in blocked_rows)
    for row in blocked_rows:
        plans = [
            sim.transport.require_movement_plan(plan_id)
            for plan_id in row.physical_movement_plan_ids
        ]
        assert all(plan.origin_id == EARTH and plan.destination_id == LEO for plan in plans)
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert any(
        blocker.code in {"logistics_source", "import_source", "import_transport_blocked"}
        for blocker in project.blockers
    )

    allocation_id = _owned_earth_leo_capacity(sim)
    for row in requirements:
        current = sim.inventory.amount(EARTH, row.resource_id)
        if current + 1e-9 < row.amount_t:
            sim.inventory.add(EARTH, row.resource_id, row.amount_t - current)

    app.execute(PauseTransportAllocation(str(allocation_id)))
    sim.advance_days(1)
    paused_requirements = [
        row for row in app.query(GetLogistics()).requirements
        if row.owner_id == project_id
    ]
    assert paused_requirements
    assert all(row.operational_source_count == 0 for row in paused_requirements)
    assert app.query(GetCargoFlows()).items == ()

    app.execute(ResumeTransportAllocation(str(allocation_id)))
    decision = sim.tick_decision_projection()
    assert [
        row for row, amount in decision.allocations.transport.executable_dispatches
        if str(row.requirement.owner_id) == project_id and amount > 0.0
    ]

    sim.advance_days(1)
    generated = [
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == EntityId(project_id)
    ]
    assert generated
    allocation = next(
        row for row in app.query(GetLogistics()).allocations
        if row.id == str(allocation_id)
    )
    assert not allocation.paused and allocation.used.forward_t_per_day > 0.0


def test_future_high_priority_requirement_does_not_preempt_current_requirement_before_lead_time():
    sim = build_game_application()._simulation
    allocation_id = _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 10.0)
    current = _requirement(1.0, requirement_id="supply.current", priority=2)
    future = _requirement(
        1.0,
        requirement_id="supply.future",
        priority=5,
        forecast_requirement_day=100,
    )

    plan = sim.logistics.plan_capacity_logistics(sim.day, (future, current))
    planned_ids = {row.requirement.id for row in plan.dispatches}
    assert current.id in planned_ids
    assert future.id not in planned_ids

    latency = sim.transport.derive_transport_service_plan(
        allocation_id, sim.day
    ).forward_latency_days
    due_day = future.forecast_requirement_day - latency
    due = sim.logistics.plan_capacity_logistics(due_day, (future,))
    assert any(row.requirement.id == future.id for row in due.dispatches)


def test_auto_source_selection_and_hard_source_constraint_have_no_preference_fallback():
    auto = build_game_application()._simulation
    auto.transport.transport_allocations.clear()
    _owned_multistage_capacity(auto)
    auto.inventory.add(EARTH, MACHINERY, 1.0)
    auto.inventory.add(LEO, MACHINERY, 1.0)
    requirement = _requirement(
        1.0, requirement_id="supply.auto-source",
        destination=LUNAR_ORBIT, resource=MACHINERY,
    )

    options = auto.logistics.supply_planning_options(requirement, auto.day)
    assert {EARTH, LEO}.issubset(set(options.stocked_source_ids))
    assert {EARTH, LEO}.issubset(set(options.operational_source_ids))
    assert options.selected_source_id in {EARTH, LEO}
    assert options.selected_transport_allocation_ids
    assert not options.blockers
    first = auto.logistics.plan_capacity_logistics(auto.day, (requirement,)).dispatches[0]
    assert options.selected_transport_allocation_ids == tuple(
        dict.fromkeys(edge.allocation_id for edge in first.path)
    )

    reordered = build_game_application()._simulation
    reordered.transport.transport_allocations.clear()
    _owned_multistage_capacity(reordered)
    reordered.inventory.add(LEO, MACHINERY, 1.0)
    reordered.inventory.add(EARTH, MACHINERY, 1.0)
    same = _requirement(
        1.0, requirement_id="supply.auto-source",
        destination=LUNAR_ORBIT, resource=MACHINERY,
    )
    second = reordered.logistics.plan_capacity_logistics(reordered.day, (same,)).dispatches[0]
    assert second.source_id == first.source_id
    assert tuple(edge.key for edge in second.path) == tuple(edge.key for edge in first.path)

    constrained = build_game_application()._simulation
    constrained.transport.transport_allocations.clear()
    if not any(
        facility.definition_id == ORBITAL_LOGISTICS_NODE
        and facility.operational_node_id == LEO
        for facility in constrained.facilities.facilities.values()
    ):
        constrained.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    if not any(
        facility.definition_id == ORBITAL_LOGISTICS_NODE
        and facility.operational_node_id == LUNAR_ORBIT
        for facility in constrained.facilities.facilities.values()
    ):
        constrained.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    constrained.refresh_storage()
    constrained.inventory.add(LEO, PROPELLANT, 10.0)
    constrained.transport.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT,
        target_capacity=_capacity_for_units(
            constrained, REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT, 1
        ),
        day=constrained.day,
    )
    constrained.inventory.add(EARTH, MACHINERY, 1.0)
    constrained.inventory.add(LEO, MACHINERY, 1.0)
    hard = _requirement(
        1.0, requirement_id="supply.hard-source-no-fallback",
        destination=LUNAR_ORBIT, resource=MACHINERY,
    )
    constrained.logistics.set_supply_routing_constraint(
        SupplyRoutingConstraintScope(destination_id=LUNAR_ORBIT, resource_id=MACHINERY),
        source_node_id=EARTH,
    )

    blocked = constrained.logistics.supply_planning_options(hard, constrained.day)
    assert blocked.candidate_source_ids == (EARTH,)
    assert not blocked.operational_source_ids
    assert "routing_constraint:path_unavailable" in blocked.blockers
    assert not constrained.logistics.plan_capacity_logistics(
        constrained.day, (hard,)
    ).dispatches


def test_multistage_cargo_lifecycle_freezes_service_conditions_and_preserves_ownership_until_final_arrival():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _owned_multistage_capacity(sim)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    resource = CONSTRUCTION_EQUIPMENT
    sim.inventory.stock[(LUNAR_ORBIT, resource)] = 0.0
    sim.inventory.add(EARTH, resource, 0.1)
    target_id = sim.logistics.set_target_stock(LUNAR_ORBIT, resource, 0.1, 5)
    sim.logistics.set_supply_routing_constraint(
        SupplyRoutingConstraintScope(destination_id=LUNAR_ORBIT, resource_id=resource),
        source_node_id=EARTH,
    )

    decision = sim.tick_decision_projection()
    dispatch = next(
        row for row in decision.plan.logistics.dispatches
        if row.requirement.owner_id == target_id
    )
    assert dispatch.source_id == EARTH
    assert dispatch.requirement.destination_id == LUNAR_ORBIT
    assert len(dispatch.path) > 1
    assert any(
        row.requirement.owner_id == target_id and amount == pytest.approx(0.1)
        for row, amount in decision.allocations.transport.executable_dispatches
    )
    expected_services = tuple(edge.key for edge in dispatch.path)
    expected_destinations = tuple(edge.destination_id for edge in dispatch.path)
    expected_latency = sum(edge.latency_days for edge in dispatch.path)
    destination_before = sim.inventory.amount(LUNAR_ORBIT, resource)

    sim.advance_days(1)
    first = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    frozen_legs = (first.leg,) + first.remaining_legs
    assert tuple(leg.service_identity for leg in frozen_legs) == expected_services
    assert tuple(leg.destination_id for leg in frozen_legs) == expected_destinations
    assert sum(leg.latency_days for leg in frozen_legs) == expected_latency
    dispatched = first.amount_t
    assert sim.logistics.cargo_flow_pipeline_t(dispatch.requirement.id) == pytest.approx(dispatched)
    next_day = sim.tick_decision_projection()
    assert not [
        row for row in next_day.plan.logistics.dispatches
        if row.requirement.owner_id == target_id
    ]

    handoff_node = first.destination_id
    handoff_stock_before = sim.inventory.amount(handoff_node, resource)
    sim.advance_to_day(first.first_arrival_day)

    assert not [
        row for row in sim.logistics.arrival_waiting.values()
        if row.owner_id == target_id
    ]
    downstream = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    assert downstream.source_id == handoff_node
    assert sim.inventory.amount(handoff_node, resource) == pytest.approx(handoff_stock_before)
    assert sim.inventory.amount(LUNAR_ORBIT, resource) == pytest.approx(destination_before)

    sim.advance_to_day(downstream.first_arrival_day - 1)
    assert sim.inventory.amount(LUNAR_ORBIT, resource) == pytest.approx(destination_before)

    sim.advance_days(1)
    assert sim.inventory.amount(LUNAR_ORBIT, resource) == pytest.approx(
        destination_before + dispatched
    )
    assert not [
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    ]


def test_supply_resource_competition_respects_priority_reservations_and_order_independence():
    inventory = InventoryBook()
    inventory.set_capacity_snapshot({(EARTH, "default"): 10.0}, {(EARTH, "default"): 10.0})
    inventory.add(EARTH, MACHINERY, 5.0)
    high = _requirement(
        4.0, requirement_id="supply.local.high", destination=EARTH, priority=5
    )
    low = _requirement(
        4.0, requirement_id="supply.local.low", destination=EARTH, priority=3
    )
    resolutions = resolve_local_supply((low, high), inventory)
    by_id = {row.requirement.id: row for row in resolutions}
    assert by_id[high.id].local_supply_t == pytest.approx(4.0)
    assert by_id[high.id].external_required_t == pytest.approx(0.0)
    assert by_id[low.id].local_supply_t == pytest.approx(1.0)
    assert by_id[low.id].external_required_t == pytest.approx(3.0)
    assert inventory.reserved == {}

    constrained = InventoryBook()
    constrained.set_capacity_snapshot({(EARTH, "default"): 10.0}, {(EARTH, "default"): 10.0})
    constrained.add(EARTH, MACHINERY, 2.0)
    first = _requirement(
        3.0, requirement_id="supply.equal.a", destination=EARTH, priority=3
    )
    second = _requirement(
        3.0, requirement_id="supply.equal.b", destination=EARTH, priority=3
    )
    forward = external_supply_requirements((first, second), constrained)
    reverse = external_supply_requirements((second, first), constrained)
    assert forward == reverse
    assert [(row.id, row.amount_t) for row in forward] == [
        (first.id, pytest.approx(2.0)),
        (second.id, pytest.approx(2.0)),
    ]
    assert constrained.reserved == {}

    reserved = InventoryBook()
    reserved.set_capacity_snapshot({(EARTH, "default"): 10.0}, {(EARTH, "default"): 10.0})
    reserved.add(EARTH, MACHINERY, 5.0)
    reserved.reserve(EntityId("project.supply"), EARTH, MACHINERY, 4.0)
    other = _requirement(
        3.0, requirement_id="supply.reserved.other", destination=EARTH, priority=3
    )
    resolution = resolve_local_supply((other,), reserved)[0]
    assert resolution.local_supply_t == pytest.approx(1.0)
    assert resolution.external_required_t == pytest.approx(2.0)

    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.stock[(EARTH, MACHINERY)] = 1.0
    requirement = _requirement(
        1.0,
        requirement_id="supply.source-competition",
        priority=3,
    )
    plan = sim.logistics.plan_capacity_logistics(sim.day, (requirement,))
    cargo_bundle = next(
        row for row in sim.logistics.dispatch_execution_requirements(sim.day, plan)
        if row.owner_id == requirement.owner_id
    )
    local_bundle = ExecutionRequirementBundle(
        id=EntityId("execution.local-use"),
        owner_kind="test_local_use",
        owner_id=EntityId("owner.local-use"),
        purpose="local_use",
        operational_node_id=EARTH,
        requested_execution=1.0,
        priority=5,
        requirements=(ResourceRequirement(MACHINERY, 1.0),),
    )
    capacities = {
        key: float("inf")
        for bundle in (cargo_bundle, local_bundle)
        for key, _coefficient in bundle.coefficients()
    }
    capacities[resource_constraint(EARTH, MACHINERY)] = 1.0
    allocation = allocate_execution_requirements(
        (cargo_bundle, local_bundle), capacities
    )

    assert allocation.allocated(local_bundle.id) == pytest.approx(1.0)
    assert allocation.allocated(cargo_bundle.id) == pytest.approx(0.0)


def test_unchanged_daily_dispatches_extend_one_cargo_flow_segment():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    allocation_id = _owned_earth_leo_capacity(sim)
    launch_capacity = sim.transport.transport_capacity_snapshot(
        allocation_id, day=sim.day
    ).available.forward_t_per_day
    assert launch_capacity > 0.0
    sim.inventory.add(EARTH, MACHINERY, launch_capacity * 3.0)
    requirement = _requirement(
        launch_capacity * 3.0,
        requirement_id="supply.segment-compression",
    )

    for day in (0, 1):
        plan = sim.logistics.plan_capacity_logistics(day, (requirement,))
        bundles = sim.logistics.dispatch_execution_requirements(day, plan)
        capacities = {
            key: float("inf")
            for bundle in bundles
            for key, _coefficient in bundle.coefficients()
        }
        capacities.update(sim.logistics.allocation_pool_capacities(day))
        shared = allocate_execution_requirements(bundles, capacities)
        execution = sim.logistics.build_capacity_logistics_execution(
            day, plan, shared, ()
        )
        sim.logistics.advance_capacity_logistics(day, plan, execution)

    flows = [
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == requirement.id
    ]
    assert len(flows) == 1
    segment = flows[0]
    assert segment.dispatch_start_day == 0
    assert segment.dispatch_end_day == 2
    assert segment.dispatch_rate_t_per_day == pytest.approx(launch_capacity)
    assert segment.amount_t == pytest.approx(launch_capacity * 2.0)

def test_arrival_waiting_exposes_admission_blocker_and_backpressures_transport_until_cleared():
    app = build_game_application()
    sim = app._simulation
    sim.transport.transport_allocations.clear()
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.refresh_storage()
    allocation_id = _owned_earth_leo_capacity(sim)
    baseline = sim.logistics.current_transport_capacity_snapshot(allocation_id, day=0)

    cargo = WATER
    filler = CONSTRUCTION_EQUIPMENT
    free = sim.inventory.admission_state(LEO, cargo).admission_capacity_t
    assert free is not None and free > 1.0
    sim.inventory.add(LEO, filler, free)
    sim.inventory.add(EARTH, cargo, 1.0)
    target_id = sim.logistics.set_target_stock(LEO, cargo, 1.0, 5)
    sim.logistics.set_supply_routing_constraint(
        SupplyRoutingConstraintScope(destination_id=LEO, resource_id=cargo),
        source_node_id=EARTH,
    )

    sim.advance_days(1)
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    ready_day = flow.first_arrival_day
    sim.advance_to_day(ready_day)
    waiting = next(
        row for row in sim.logistics.arrival_waiting.values()
        if row.owner_id == target_id
    )
    assert flow.id not in sim.logistics.cargo_flows

    projected = next(
        row for row in app.query(GetCargoFlows()).items if row.id == str(waiting.id)
    )
    assert projected.status == "arrival_waiting"
    assert any(blocker.kind == "storage" or "storage" in blocker.code for blocker in projected.admission_blockers)

    blocked = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=ready_day
    )
    assert blocked.available.forward_t_per_day < baseline.available.forward_t_per_day
    assert "arrival_backpressure" in blocked.limiting_factors

    sim.inventory.consume_allocated(LEO, filler, waiting.amount_t)
    for _ in range(8):
        sim.advance_days(1)
        if waiting.id not in sim.logistics.arrival_waiting:
            break
    assert waiting.id not in sim.logistics.arrival_waiting
    restored = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=sim.day
    )
    assert restored.available.forward_t_per_day == pytest.approx(
        baseline.available.forward_t_per_day
    )
    assert "arrival_backpressure" not in restored.limiting_factors


def test_routing_via_and_transport_allocation_constraints_are_hard_limits():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    launch, tug = _owned_multistage_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    requirement = _requirement(
        1.0, requirement_id="supply.hard-route",
        destination=LUNAR_ORBIT, resource=MACHINERY,
    )
    scope = SupplyRoutingConstraintScope(
        destination_id=LUNAR_ORBIT, resource_id=MACHINERY
    )
    sim.logistics.set_supply_routing_constraint(
        scope, source_node_id=EARTH, required_via_node_ids=(LEO,),
        required_transport_allocation_ids=(launch, tug),
    )

    initial_path = sim.logistics.supply_service_path(requirement, EARTH, sim.day)
    assert len(initial_path) == 2
    assert initial_path[0].destination_id == LEO
    assert {edge.allocation_id for edge in initial_path} == {launch, tug}
    options = sim.logistics.supply_planning_options(requirement, sim.day)
    assert options.operational_source_ids == (EARTH,)

    sim.transport.update_transport_allocation(tug, paused=True, day=sim.day)
    blocked = sim.logistics.supply_planning_options(requirement, sim.day)
    assert not blocked.operational_source_ids
    assert "routing_constraint:path_unavailable" in blocked.blockers
    assert not sim.logistics.plan_capacity_logistics(sim.day, (requirement,)).dispatches

    sim.transport.update_transport_allocation(tug, paused=False, day=sim.day)
    restored = sim.logistics.supply_planning_options(requirement, sim.day)
    assert restored.operational_source_ids == (EARTH,)
    dispatch = sim.logistics.plan_capacity_logistics(sim.day, (requirement,)).dispatches[0]
    assert dispatch.source_id == EARTH
    assert tuple(edge.key for edge in dispatch.path) == tuple(edge.key for edge in initial_path)


def test_supply_dispatch_requires_player_owned_transport_capacity_without_spending_market_funds():
    from space_idle import GetWorld

    app = build_game_application()
    sim = app._simulation
    sim.inventory.stock[(LEO, CONSTRUCTION_EQUIPMENT)] = 0.0
    sim.inventory.add(EARTH, CONSTRUCTION_EQUIPMENT, 2.0)
    target_id = sim.logistics.set_target_stock(LEO, CONSTRUCTION_EQUIPMENT, 1.0, 5)
    sim.transport.transport_allocations.clear()
    before_funds = app.query(GetWorld()).funds_musd

    sim.advance_days(1)
    assert app.query(GetWorld()).funds_musd == before_funds
    assert not [
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    ]

    _owned_earth_leo_capacity(sim)
    sim.advance_days(1)
    assert app.query(GetWorld()).funds_musd == before_funds
    assert any(
        row.owner_id == target_id
        for row in sim.logistics.cargo_flows.values()
    )
