from __future__ import annotations

import pytest

from space_idle import GetCargoFlows, GetLogistics, GetProjects, PlanBuild, build_game_application
from space_idle.content.base_game import (
    CONSTRUCTION_EQUIPMENT,
    EARTH,
    LEO,
    LEO_LUNAR_SERVICE,
    LUNAR_ORBIT,
    MACHINERY,
    ORBITAL_LOGISTICS_NODE,
    PRECISION_ELECTRONICS,
    PROPELLANT,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    TECH_CISLUNAR_LOGISTICS,
    TECH_ORBITAL_OPERATIONS,
    WATER,
)
from space_idle.execution_requirements import (
    ExecutionRequirementBundle,
    ResourceRequirement,
    allocate_execution_requirements,
    resource_constraint,
)
from space_idle.supply import SupplyRequirement
from space_idle.shared import DefinitionId, EntityId


def _requirement(
    amount_t: float,
    *,
    requirement_id: str = "supply.test",
    destination=LEO,
    source=EARTH,
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
        source,
        forecast_requirement_day=forecast_requirement_day,
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


def test_dynamic_supply_dispatch_uses_owned_route_and_pipeline_prevents_duplicate():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.stock[(LEO, MACHINERY)] = 0.0
    sim.inventory.stock[(EARTH, MACHINERY)] = 2.0
    sim.logistics.set_supply_policy(LEO, MACHINERY, preferred_source_id=EARTH)
    target_id = sim.logistics.set_target_stock(LEO, MACHINERY, 1.0, 5)

    decision = sim.tick_decision_projection()
    dispatch = next(
        row for row in decision.plan.logistics.dispatches
        if row.requirement.owner_id == target_id
    )
    assert dispatch.source_id == EARTH
    assert dispatch.requirement.destination_id == LEO
    assert dispatch.path
    assert any(
        row.requirement.owner_id == target_id and amount == pytest.approx(1.0)
        for row, amount in decision.allocations.transport.executable_dispatches
    )

    sim.advance_days(1)
    flows = [
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    ]
    assert sum(row.amount_t for row in flows) == pytest.approx(1.0)
    assert sim.logistics.cargo_flow_pipeline_t(dispatch.requirement.id) == pytest.approx(1.0)

    next_day = sim.tick_decision_projection()
    assert not [
        row for row in next_day.plan.logistics.dispatches
        if row.requirement.owner_id == target_id
    ]

def test_supply_policy_selects_preferred_source_without_provisioning_transport():
    app = build_game_application()
    sim = app._simulation
    allocation_count = len(sim.transport.transport_allocations)
    sim.logistics.set_supply_policy(LEO, MACHINERY, preferred_source_id=EARTH)
    sim.logistics.set_target_stock(LEO, MACHINERY, 3.0, 4)

    view = app.query(GetLogistics())
    assert len(view.supply_policies) == 1
    assert view.supply_policies[0].preferred_source_id == str(EARTH)
    assert len(view.target_stocks) == 1
    assert any(row.resource_id == str(MACHINERY) for row in view.requirements)
    assert len(sim.transport.transport_allocations) == allocation_count


def test_external_transport_service_capacity_is_one_shared_pool_across_directions():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    sim.external_economy.register_service(LEO_LUNAR_SERVICE)
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(LEO_LUNAR_SERVICE,),
        day=sim.day,
    )
    sim.inventory.add(LEO, MACHINERY, 1.0)
    sim.inventory.add(LUNAR_ORBIT, MACHINERY, 1.0)
    outbound = _requirement(
        0.25,
        requirement_id="supply.external-shared.forward",
        destination=LUNAR_ORBIT,
        source=LEO,
    )
    inbound = _requirement(
        0.25,
        requirement_id="supply.external-shared.reverse",
        destination=LEO,
        source=LUNAR_ORBIT,
    )

    plan = sim.logistics.plan_capacity_logistics(sim.day, (outbound, inbound))
    bundles = sim.logistics.dispatch_execution_requirements(sim.day, plan)
    capacities = {
        key: float("inf")
        for bundle in bundles
        for key, _coefficient in bundle.coefficients()
    }
    capacities.update(sim.logistics.transport_capacity_pool_capacities(sim.day))
    allocation = allocate_execution_requirements(bundles, capacities)
    allocated = {
        requirement.id: sum(
            allocation.allocated(row.cargo_claim_id)
            for row in plan.dispatches
            if row.requirement.id == requirement.id
        )
        for requirement in (outbound, inbound)
    }

    assert sum(allocated.values()) == pytest.approx(0.25)
    assert allocated[outbound.id] == pytest.approx(0.125)
    assert allocated[inbound.id] == pytest.approx(0.125)

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


def test_construction_source_constraint_is_visible_and_dispatches_when_capacity_exists():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update({TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS})
    sim.transport.external_services.clear()
    project_id = app.execute(
        PlanBuild(
            str(LEO),
            str(ORBITAL_LOGISTICS_NODE),
            priority=3,
            sourcing_policy="import_now",
            import_source_id=str(EARTH),
        )
    ).created_id
    assert project_id is not None

    requirements = tuple(
        row for row in sim.projects.supplys(sim.day)
        if str(row.owner_id) == project_id
    )
    assert requirements and all(row.source_id == EARTH for row in requirements)
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert any(code in {"import_source", "import_transport_blocked"} for code, _ in project.blockers)

    _owned_earth_leo_capacity(sim)
    for row in requirements:
        sim.inventory.add(EARTH, row.resource_id, row.amount_t)
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

def test_unconstrained_requirement_auto_selects_reachable_stocked_source():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, WATER, 1.0)
    requirement = _requirement(
        1.0,
        requirement_id="supply.auto-source",
        source=None,
        resource=WATER,
    )

    options = sim.logistics.supply_planning_options(requirement, sim.day)
    assert EARTH in options.stocked_source_ids
    plan = sim.logistics.plan_capacity_logistics(sim.day, (requirement,))
    dispatch = next(row for row in plan.dispatches if row.requirement.id == requirement.id)
    assert dispatch.source_id == EARTH

def test_multistage_dispatch_freezes_current_and_downstream_service_conditions():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.stock[(LUNAR_ORBIT, MACHINERY)] = 0.0
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    sim.logistics.set_supply_policy(LUNAR_ORBIT, MACHINERY, preferred_source_id=EARTH)
    target_id = sim.logistics.set_target_stock(LUNAR_ORBIT, MACHINERY, 1.0, 5)

    decision = sim.tick_decision_projection()
    dispatch = next(
        row for row in decision.plan.logistics.dispatches
        if row.requirement.owner_id == target_id
    )
    assert len(dispatch.path) > 1
    expected_services = tuple(edge.key for edge in dispatch.path)
    expected_destinations = tuple(edge.destination_id for edge in dispatch.path)
    expected_latency = sum(edge.latency_days for edge in dispatch.path)

    sim.advance_days(1)
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    frozen_legs = (flow.leg,) + flow.remaining_legs
    assert tuple(leg.service_identity for leg in frozen_legs) == expected_services
    assert tuple(leg.destination_id for leg in frozen_legs) == expected_destinations
    assert sum(leg.latency_days for leg in frozen_legs) == expected_latency

def test_cargo_is_not_available_until_boundary_arrival_settlement():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    resource = DefinitionId("test.resource.boundary-supply")
    sim.inventory.add(EARTH, resource, 1.0)
    before = sim.inventory.amount(LEO, resource)
    sim.logistics.set_supply_policy(LEO, resource, preferred_source_id=EARTH)
    target_id = sim.logistics.set_target_stock(LEO, resource, 1.0, 5)

    sim.advance_days(1)
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    dispatched = flow.amount_t
    ready_day = flow.first_arrival_day
    sim.advance_to_day(ready_day - 1)
    assert sim.inventory.amount(LEO, resource) == pytest.approx(before)

    sim.advance_days(1)
    assert sim.inventory.amount(LEO, resource) == pytest.approx(before + dispatched)

def test_cargo_arrival_waits_for_inventory_admission():
    app = build_game_application()
    sim = app._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    sim.inventory.stock[(LEO, MACHINERY)] = 0.0
    free = sim.inventory.free_capacity(LEO, MACHINERY)
    assert free is not None and free > 1.0
    sim.inventory.add(LEO, CONSTRUCTION_EQUIPMENT, free)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    sim.logistics.set_supply_policy(LEO, MACHINERY, preferred_source_id=EARTH)
    target_id = sim.logistics.set_target_stock(LEO, MACHINERY, 1.0, 5)

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
    assert any("storage" in blocker for blocker in projected.admission_blockers)

    sim.inventory.consume_allocated(LEO, CONSTRUCTION_EQUIPMENT, waiting.amount_t)
    sim.advance_days(1)
    assert waiting.id not in sim.logistics.arrival_waiting

def test_dispatch_source_requirement_competes_with_higher_priority_local_use():
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

def test_locally_covered_requirement_does_not_report_unused_transport_blockers():
    app = build_game_application()
    covered = [
        row for row in app.query(GetLogistics()).requirements
        if row.supply_state == "local_covered"
    ]
    assert covered
    assert all(not row.blockers for row in covered)


def test_unchanged_daily_dispatches_extend_one_cargo_flow_segment():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    launch_capacity = next(
        row.capacity_t_per_day
        for row in sim.transport.external_services.values()
        if row.display_name == "商業地表打上げ"
    )
    sim.inventory.add(EARTH, MACHINERY, launch_capacity * 3.0)
    requirement = _requirement(
        launch_capacity * 3.0,
        requirement_id="supply.segment-compression",
    )

    for day in (0, 1):
        raw = sim.logistics.plan_capacity_logistics(day, (requirement,))
        funds = sim.external_economy.allocate(raw.spending_requests, day)
        plan = sim.logistics.authorize_capacity_logistics(raw, funds, day)
        bundles = sim.logistics.dispatch_execution_requirements(day, plan)
        capacities = {
            key: float("inf")
            for bundle in bundles
            for key, _coefficient in bundle.coefficients()
        }
        capacities.update(sim.logistics.transport_capacity_pool_capacities(day))
        shared = allocate_execution_requirements(bundles, capacities)
        execution = sim.logistics.build_capacity_logistics_execution(
            day, plan, shared, ()
        )
        sim.logistics.advance_capacity_logistics(day, plan, funds, execution)

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

@pytest.mark.parametrize(
    "direct_handoff",
    (True, False),
    ids=("logistics_owned_direct", "inventory_staged_reload"),
)
def test_multistage_handoff_ownership_transition(direct_handoff):
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    if direct_handoff:
        sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    resource = CONSTRUCTION_EQUIPMENT
    sim.inventory.stock[(LUNAR_ORBIT, resource)] = 0.0
    sim.inventory.add(EARTH, resource, 0.1)
    sim.logistics.set_supply_policy(LUNAR_ORBIT, resource, preferred_source_id=EARTH)
    target_id = sim.logistics.set_target_stock(LUNAR_ORBIT, resource, 0.1, 5)

    sim.advance_days(1)
    first = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    assert first.remaining_legs
    handoff_node = first.destination_id
    stock_before = sim.inventory.amount(handoff_node, resource)
    sim.advance_to_day(first.first_arrival_day)

    assert not [
        row for row in sim.logistics.arrival_waiting.values()
        if row.owner_id == target_id
    ]
    staging_rows = [
        row for row in sim.logistics.handoff_staging.values()
        if row.owner_id == target_id
    ]
    if direct_handoff:
        assert staging_rows == []
        downstream = next(
            row for row in sim.logistics.cargo_flows.values()
            if row.owner_id == target_id
        )
        assert downstream.source_id == handoff_node
        assert sim.inventory.amount(handoff_node, resource) == pytest.approx(stock_before)
        return

    assert len(staging_rows) == 1
    staging = staging_rows[0]
    assert sim.inventory.amount(handoff_node, resource) == pytest.approx(
        stock_before + staging.amount_t
    )
    assert sim.inventory.reserved_for(
        staging.reservation_owner_id, handoff_node, resource
    ) == pytest.approx(staging.amount_t)

    sim.facilities.install(ORBITAL_LOGISTICS_NODE, handoff_node)
    sim.refresh_storage()
    sim.advance_days(1)

    assert staging.id not in sim.logistics.handoff_staging
    assert sim.inventory.amount(handoff_node, resource) == pytest.approx(stock_before)
    downstream = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.owner_id == target_id
    )
    assert downstream.source_id == handoff_node

def test_arrival_waiting_reduces_reusable_transport_capacity_until_cleared():
    sim = build_game_application()._simulation
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.refresh_storage()
    allocation_id = _owned_earth_leo_capacity(sim)
    baseline = sim.logistics.current_transport_capacity_snapshot(allocation_id, day=0)
    cargo = DefinitionId("test.resource.backpressure-cargo")
    filler = DefinitionId("test.resource.backpressure-filler")
    sim.inventory.register_storage_class(cargo, "general_cargo")
    sim.inventory.register_storage_class(filler, "general_cargo")
    free = sim.inventory.free_capacity(LEO, cargo)
    assert free is not None and free > 1.0
    sim.inventory.add(LEO, filler, free)
    sim.inventory.add(EARTH, cargo, 1.0)
    sim.logistics.set_supply_policy(LEO, cargo, preferred_source_id=EARTH)
    target_id = sim.logistics.set_target_stock(LEO, cargo, 1.0, 5)

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

    blocked = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=ready_day
    )
    assert blocked.available.forward_t_per_day < baseline.available.forward_t_per_day
    assert "arrival_backpressure" in blocked.limiting_factors

    sim.inventory.consume_allocated(LEO, filler, waiting.amount_t)
    sim.advance_days(1)
    assert waiting.id not in sim.logistics.arrival_waiting
    restored = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=ready_day + 1
    )
    assert restored.available.forward_t_per_day == pytest.approx(
        baseline.available.forward_t_per_day
    )
    assert "arrival_backpressure" not in restored.limiting_factors
