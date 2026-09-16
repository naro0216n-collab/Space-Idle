from __future__ import annotations

import pytest

from space_idle import AdvanceTime, GetCargoFlows, GetLogistics, GetProjects, PlanBuild, build_game_application
from space_idle.content.base_game import (
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
from space_idle.resource_claim import ResourceClaim
from space_idle.supply import SupplyRequirement
from space_idle.shared import DefinitionId, EntityId
from tests._logistics_support import resolve_authorized_logistics


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


def _resolve_logistics(sim, day, requirements):
    plan = sim.logistics.plan_capacity_logistics(day, tuple(requirements))
    funds = sim.external_economy.allocate(plan.spending_requests, day)
    plan = sim.logistics.authorize_capacity_logistics(plan, funds, day)
    shared, transport, resources, _services = resolve_authorized_logistics(
        sim, day, plan
    )
    return plan, funds, resources, shared, transport


def _advance_logistics(sim, day, requirements):
    plan, funds, resources, _shared, execution = _resolve_logistics(
        sim, day, requirements
    )
    sim.logistics.advance_capacity_logistics(day, plan, funds, execution)
    return plan, resources, execution


def test_supply_requirement_dispatches_without_authoritative_lane():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    requirement = _requirement(1.0)

    _advance_logistics(sim, sim.day, (requirement,))

    flows = [row for row in sim.logistics.cargo_flows.values() if row.requirement_id == requirement.id]
    assert sum(row.amount_t for row in flows) == pytest.approx(1.0)
    assert all(row.source_id == EARTH and row.destination_id == LEO for row in flows)


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


def test_higher_priority_requirement_uses_shared_transport_capacity_first():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _allow_external_transport(sim)
    service_capacity = next(
        row.capacity_t_per_day
        for row in sim.transport.external_services.values()
        if row.display_name == "商業地表打上げ"
    )
    amount = service_capacity
    sim.inventory.add(EARTH, MACHINERY, amount * 2.0)
    high = _requirement(amount, requirement_id="supply.high", priority=5)
    low = _requirement(amount, requirement_id="supply.low", priority=2)

    _advance_logistics(sim, sim.day, (low, high))

    shipped = {high.id: 0.0, low.id: 0.0}
    for flow in sim.logistics.cargo_flows.values():
        if flow.requirement_id in shipped:
            shipped[flow.requirement_id] += flow.amount_t
    assert shipped[high.id] == pytest.approx(amount)
    assert shipped[low.id] == pytest.approx(0.0)


def test_same_priority_transport_capacity_is_progressive_max_min_and_registration_order_independent():
    def run(requirements):
        sim = build_game_application()._simulation
        sim.transport.transport_allocations.clear()
        _allow_external_transport(sim)
        service_capacity = next(
            row.capacity_t_per_day
            for row in sim.transport.external_services.values()
            if row.display_name == "商業地表打上げ"
        )
        sim.inventory.add(EARTH, MACHINERY, service_capacity * 4.0)
        planned, _funds, _resources, shared, _execution = _resolve_logistics(
            sim, sim.day, requirements
        )
        return service_capacity, {
            requirement.id: sum(
                shared.allocated(row.cargo_claim_id)
                for row in planned.dispatches
                if row.requirement.id == requirement.id
            )
            for requirement in requirements
        }

    first = _requirement(2.0, requirement_id="supply.same.a", priority=3)
    second = _requirement(2.0, requirement_id="supply.same.b", priority=3)
    capacity, forward = run((first, second))
    _capacity, reverse = run((second, first))

    assert forward == pytest.approx(reverse)
    assert forward[first.id] == pytest.approx(capacity / 2.0)
    assert forward[second.id] == pytest.approx(capacity / 2.0)


def test_external_transport_service_capacity_is_shared_across_supported_directions():
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
        priority=3,
    )
    inbound = _requirement(
        0.25,
        requirement_id="supply.external-shared.reverse",
        destination=LEO,
        source=LUNAR_ORBIT,
        priority=3,
    )

    plan, _funds, _resources, shared, _execution = _resolve_logistics(
        sim, sim.day, (outbound, inbound)
    )
    allocated = {
        requirement.id: sum(
            shared.allocated(row.cargo_claim_id)
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


def test_inbound_cargo_is_subtracted_from_requirement_and_not_dispatched_twice():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    requirement = _requirement(1.0, requirement_id="supply.pipeline")
    _advance_logistics(sim, sim.day, (requirement,))
    assert sim.logistics.cargo_flow_pipeline_t(requirement.id) == pytest.approx(1.0)

    second = sim.logistics.plan_capacity_logistics(sim.day + 1, (requirement,))
    assert not second.dispatches


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

    requirements = tuple(row for row in sim.projects.supplys(sim.day) if str(row.owner_id) == project_id)
    assert requirements and all(row.source_id == EARTH for row in requirements)
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert any(code in {"import_source", "import_transport_blocked"} for code, _ in project.blockers)

    _owned_earth_leo_capacity(sim)
    for row in requirements:
        sim.inventory.add(EARTH, row.resource_id, row.amount_t)
    _advance_logistics(sim, sim.day, requirements)
    generated = [row for row in sim.logistics.cargo_flows.values() if row.owner_id == EntityId(project_id)]
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
    _advance_logistics(sim, sim.day, (requirement,))
    flow = next(row for row in sim.logistics.cargo_flows.values() if row.requirement_id == requirement.id)
    assert flow.source_id == EARTH


def test_multistage_dispatch_freezes_current_and_downstream_service_conditions():
    sim = build_game_application()._simulation
    _allow_external_transport(sim)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    requirement = _requirement(
        1.0,
        requirement_id="supply.multistage",
        destination=LUNAR_ORBIT,
        source=EARTH,
    )
    raw = sim.logistics.plan_capacity_logistics(sim.day, (requirement,))
    dispatch = next(row for row in raw.dispatches if row.requirement.id == requirement.id)
    assert len(dispatch.path) > 1
    expected_services = tuple(edge.key for edge in dispatch.path)
    expected_destinations = tuple(edge.destination_id for edge in dispatch.path)
    expected_latency = sum(edge.latency_days for edge in dispatch.path)

    _advance_logistics(sim, sim.day, (requirement,))
    flow = next(row for row in sim.logistics.cargo_flows.values() if row.requirement_id == requirement.id)
    frozen_legs = (flow.leg,) + flow.remaining_legs
    assert tuple(leg.service_identity for leg in frozen_legs) == expected_services
    assert tuple(leg.destination_id for leg in frozen_legs) == expected_destinations
    assert sum(leg.latency_days for leg in frozen_legs) == expected_latency


def test_cargo_is_not_available_until_boundary_arrival_settlement():
    sim = build_game_application()._simulation
    _allow_external_transport(sim)
    resource = DefinitionId("test.resource.boundary-supply")
    sim.inventory.add(EARTH, resource, 1.0)
    before = sim.inventory.amount(LEO, resource)
    requirement = _requirement(
        1.0,
        requirement_id="supply.boundary",
        resource=resource,
    )
    _advance_logistics(sim, 0, (requirement,))
    flow = next(row for row in sim.logistics.cargo_flows.values() if row.requirement_id == requirement.id)

    dispatched = flow.amount_t
    ready_day = flow.first_arrival_day
    sim.logistics.prepare_cargo_arrivals(ready_day - 1)
    sim.logistics.settle_cargo_arrivals(ready_day - 1)
    assert sim.inventory.amount(LEO, resource) == pytest.approx(before)
    _settle_cargo_boundary(sim, ready_day)
    assert sim.inventory.amount(LEO, resource) == pytest.approx(before + dispatched)


def test_cargo_arrival_waits_for_inventory_admission():
    app = build_game_application()
    sim = app._simulation
    _allow_external_transport(sim)
    free = sim.inventory.free_capacity(LEO, MACHINERY)
    assert free is not None and free > 0
    sim.inventory.add(LEO, PRECISION_ELECTRONICS, free)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    requirement = _requirement(1.0, requirement_id="supply.arrival-waiting")

    _advance_logistics(sim, 0, (requirement,))
    flow = next(row for row in sim.logistics.cargo_flows.values() if row.requirement_id == requirement.id)
    ready_day = flow.first_arrival_day
    _settle_cargo_boundary(sim, ready_day)
    waiting = next(
        row for row in sim.logistics.arrival_waiting.values() if row.requirement_id == requirement.id
    )
    assert flow.id not in sim.logistics.cargo_flows
    projected = next(
        row for row in app.query(GetCargoFlows()).items if row.id == str(waiting.id)
    )
    assert projected.status == "arrival_waiting"
    assert any("storage" in blocker for blocker in projected.admission_blockers)

    sim.inventory.consume_allocated(LEO, PRECISION_ELECTRONICS, 1.0)
    _settle_cargo_boundary(sim, ready_day + 1)
    assert waiting.id not in sim.logistics.arrival_waiting


def test_dispatch_source_claim_competes_with_higher_priority_local_use():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.stock[(EARTH, MACHINERY)] = 1.0
    requirement = _requirement(1.0, requirement_id="supply.source-competition", priority=3)
    plan = sim.logistics.plan_capacity_logistics(sim.day, (requirement,))
    cargo_dispatch = next(
        row for row in plan.dispatches if row.requirement.id == requirement.id
    )
    local_claim = ResourceClaim(
        EntityId("claim.local-use"), EARTH, MACHINERY, 1.0, 5,
        "test_local_use", EntityId("owner.local-use"), "local_use",
    )

    funds = sim.external_economy.allocate(plan.spending_requests, sim.day)
    plan = sim.logistics.authorize_capacity_logistics(plan, funds, sim.day)
    shared, execution, _resources, _services = resolve_authorized_logistics(
        sim,
        sim.day,
        plan,
        static_intents=(sim._resource_claim_execution_bundle(local_claim),),
    )
    sim.logistics.advance_capacity_logistics(sim.day, plan, funds, execution)

    assert shared.allocated(local_claim.id) == pytest.approx(1.0)
    assert shared.allocated(cargo_dispatch.cargo_claim_id) == pytest.approx(0.0)
    assert not sim.logistics.cargo_flows


def test_locally_covered_requirement_does_not_report_unused_transport_blockers():
    app = build_game_application()
    covered = [
        row for row in app.query(GetLogistics()).requirements
        if row.supply_state == "local_covered"
    ]
    assert covered
    assert all(not row.blockers for row in covered)


def _settle_cargo_boundary(sim, day: int, *, allocate_transfer: bool = True):
    sim.logistics.prepare_cargo_arrivals(day)
    requests = sim.logistics.cargo_handoff_service_requests(day)
    allocations = direct_allocations = None
    if allocate_transfer and requests:
        allocations, direct_allocations = sim._allocate_boundary_handoff_services(requests)
    sim.logistics.settle_cargo_arrivals(day, allocations, direct_allocations)
    return allocations


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

    _advance_logistics(sim, 0, (requirement,))
    _advance_logistics(sim, 1, (requirement,))

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


def test_multistage_arrival_direct_handoff_preserves_logistics_ownership():
    sim = build_game_application()._simulation
    _allow_external_transport(sim)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.add(EARTH, MACHINERY, 0.1)
    requirement = _requirement(
        0.1,
        requirement_id="supply.direct-handoff",
        destination=LUNAR_ORBIT,
        source=EARTH,
    )

    _advance_logistics(sim, 0, (requirement,))
    first = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == requirement.id
    )
    assert first.remaining_legs
    handoff_node = first.destination_id
    stock_before = sim.inventory.amount(handoff_node, MACHINERY)
    ready_day = first.first_arrival_day

    _settle_cargo_boundary(sim, ready_day)

    assert not [
        row for row in sim.logistics.arrival_waiting.values()
        if row.requirement_id == requirement.id
    ]
    assert not [
        row for row in sim.logistics.handoff_staging.values()
        if row.requirement_id == requirement.id
    ]
    downstream = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == requirement.id
    )
    assert downstream.source_id == handoff_node
    assert sim.inventory.amount(handoff_node, MACHINERY) == pytest.approx(stock_before)


def test_multistage_external_arrival_can_unload_to_inventory_reservation_then_reload():
    sim = build_game_application()._simulation
    _allow_external_transport(sim)
    # No local transfer capability exists at the first handoff yet.  The
    # external carrier can unload its delivered Cargo, but cannot provide the
    # subsequent Inventory-owned reload.
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.add(EARTH, MACHINERY, 0.1)
    requirement = _requirement(
        0.1,
        requirement_id="supply.unload-handoff",
        destination=LUNAR_ORBIT,
        source=EARTH,
    )

    _advance_logistics(sim, 0, (requirement,))
    first = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == requirement.id
    )
    assert first.remaining_legs
    handoff_node = first.destination_id
    stock_before = sim.inventory.amount(handoff_node, MACHINERY)
    ready_day = first.first_arrival_day

    _settle_cargo_boundary(sim, ready_day)

    staging = next(
        row for row in sim.logistics.handoff_staging.values()
        if row.requirement_id == requirement.id
    )
    assert not [
        row for row in sim.logistics.arrival_waiting.values()
        if row.requirement_id == requirement.id
    ]
    assert sim.inventory.amount(handoff_node, MACHINERY) == pytest.approx(
        stock_before + staging.amount_t
    )
    assert sim.inventory.reserved_for(
        staging.reservation_owner_id, handoff_node, MACHINERY
    ) == pytest.approx(staging.amount_t)

    # Once local handling infrastructure exists, the Inventory-owned Cargo can
    # consume local transfer capacity, reload, and continue downstream.
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, handoff_node)
    sim.refresh_storage()
    _settle_cargo_boundary(sim, ready_day + 1)

    assert staging.id not in sim.logistics.handoff_staging
    assert sim.inventory.amount(handoff_node, MACHINERY) == pytest.approx(stock_before)
    downstream = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == requirement.id
    )
    assert downstream.source_id == handoff_node


def test_arrival_waiting_reduces_reusable_transport_capacity_until_cleared():
    sim = build_game_application()._simulation
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.refresh_storage()
    allocation_id = _owned_earth_leo_capacity(sim)
    baseline = sim.logistics.current_transport_capacity_snapshot(allocation_id, day=0)
    free = sim.inventory.free_capacity(LEO, MACHINERY)
    assert free is not None and free > 1.0
    sim.inventory.add(LEO, PRECISION_ELECTRONICS, free)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    requirement = _requirement(1.0, requirement_id="supply.backpressure")

    _advance_logistics(sim, 0, (requirement,))
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == requirement.id
    )
    ready_day = flow.first_arrival_day
    _settle_cargo_boundary(sim, ready_day)
    waiting = next(
        row for row in sim.logistics.arrival_waiting.values()
        if row.requirement_id == requirement.id
    )

    blocked = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=ready_day
    )
    assert blocked.available.forward_t_per_day < baseline.available.forward_t_per_day
    assert "arrival_backpressure" in blocked.limiting_factors

    sim.inventory.consume_allocated(LEO, PRECISION_ELECTRONICS, waiting.amount_t)
    _settle_cargo_boundary(sim, ready_day + 1)
    assert waiting.id not in sim.logistics.arrival_waiting
    restored = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=ready_day + 1
    )
    assert restored.available.forward_t_per_day == pytest.approx(
        baseline.available.forward_t_per_day
    )
