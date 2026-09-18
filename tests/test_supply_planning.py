from __future__ import annotations

from dataclasses import dataclass

import pytest

from space_idle import (
    GetCargoFlows, GetLogistics, GetProjects, PauseTransportAllocation,
    PlanBuild, ResumeTransportAllocation, build_game_application,
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
from space_idle.path_selection import select_tradeoff_path
from space_idle.supply import (
    SourceSelectionMode, SupplyRequirement, external_supply_requirements,
    resolve_local_supply,
)
from space_idle.shared import DefinitionId, EntityId
from space_idle.transport.models import PathPolicy


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


def _set_global_source_preference(sim, source=EARTH) -> EntityId:
    policy_id = sim.logistics.global_policy_id
    assert policy_id is not None
    sim.logistics.update_logistics_policy(
        policy_id,
        source_mode=SourceSelectionMode.PREFERRED,
        allowed_source_ids=None,
        preferred_source_id=source,
    )
    return policy_id


def _create_pinned_source_policy(sim, policy_id: str, source=EARTH) -> str:
    entity_id = EntityId(policy_id)
    sim.logistics.create_logistics_policy(
        entity_id, source_mode=SourceSelectionMode.PINNED, allowed_source_ids=(source,)
    )
    return str(entity_id)


def _owned_earth_leo_capacity(sim, units: int = 1):
    return sim.transport.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=units, day=sim.day
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
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=sim.day
    )
    tug = sim.transport.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG,
        LEO, LUNAR_ORBIT, target_units=1, day=sim.day
    )
    return launch, tug



@dataclass(frozen=True)
class _PathEdge:
    id: str
    source: str
    destination: str
    time: float
    propellant: float


def _selected_path_ids(edges: tuple[_PathEdge, ...], preference: PathPolicy) -> tuple[str, ...]:
    return tuple(
        edge.id
        for edge in select_tradeoff_path(
            "origin",
            "destination",
            outgoing=lambda node: tuple(edge for edge in edges if edge.source == node),
            edge_destination=lambda edge: edge.destination,
            edge_time=lambda edge: edge.time,
            edge_propellant=lambda edge: edge.propellant,
            edge_key=lambda edge: edge.id,
            preference=preference,
        )
    )


def test_canonical_path_preferences_choose_time_propellant_tradeoff_deterministically():
    edges = (
        _PathEdge("fast", "origin", "destination", 1.0, 10.0),
        _PathEdge("balanced", "origin", "destination", 2.0, 2.0),
        _PathEdge("efficient", "origin", "destination", 10.0, 1.0),
    )

    assert _selected_path_ids(edges, PathPolicy.FASTEST) == ("fast",)
    assert _selected_path_ids(edges, PathPolicy.LOWEST_PROPELLANT) == ("efficient",)
    assert _selected_path_ids(edges, PathPolicy.BALANCED) == ("balanced",)
    assert _selected_path_ids(tuple(reversed(edges)), PathPolicy.BALANCED) == ("balanced",)

def test_dynamic_supply_dispatch_uses_owned_route_and_pipeline_prevents_duplicate():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.stock[(LEO, MACHINERY)] = 0.0
    sim.inventory.stock[(EARTH, MACHINERY)] = 2.0
    _set_global_source_preference(sim, EARTH)
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

def test_supply_projection_exposes_transport_blockers_only_when_external_transport_is_needed():
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
            logistics_policy_id=_create_pinned_source_policy(sim, "logistics.policy.project-earth", EARTH),
        )
    ).created_id
    assert project_id is not None

    sim.advance_days(1)
    rows = [
        row for row in app.query(GetLogistics()).requirements
        if row.owner_id == project_id
    ]

    assert rows
    assert all(row.candidate_source_count == 1 for row in rows)
    assert all(row.stocked_source_count == 1 for row in rows)
    assert all(row.operational_source_count == 0 for row in rows)
    assert all(row.supply_state == "transport_blocked" for row in rows)
    assert all("no_transport_capacity" in row.blockers for row in rows)

    covered = [
        row for row in app.query(GetLogistics()).requirements
        if row.supply_state == "local_covered"
    ]
    assert covered
    assert all(not row.blockers for row in covered)


def test_logistics_policy_selects_preferred_source_without_provisioning_transport():
    app = build_game_application()
    sim = app._simulation
    allocation_count = len(sim.transport.transport_allocations)
    _set_global_source_preference(sim, EARTH)
    sim.logistics.set_target_stock(LEO, MACHINERY, 3.0, 4)

    view = app.query(GetLogistics())
    assert len(view.logistics_policies) == 1
    assert view.logistics_policies[0].preferred_source_id == str(EARTH)
    assert view.logistics_policies[0].path_preference == "balanced"
    assert len(view.target_stocks) == 1
    assert any(row.resource_id == str(MACHINERY) for row in view.requirements)
    assert len(sim.transport.transport_allocations) == allocation_count


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
    sim.technology.completed.update(
        sim.projects.recipes[ORBITAL_LOGISTICS_NODE].prerequisite_technologies
    )
    project_id = app.execute(
        PlanBuild(
            str(LEO),
            str(ORBITAL_LOGISTICS_NODE),
            priority=3,
            procurement_policy="immediate",
            logistics_policy_id=_create_pinned_source_policy(sim, "logistics.policy.project-earth-2", EARTH),
        )
    ).created_id
    assert project_id is not None

    requirements = tuple(
        row for row in sim.projects.supplys(sim.day)
        if str(row.owner_id) == project_id
    )
    assert requirements
    assert all(
        sim.logistics.logistics_policy_for(row).allowed_source_ids == (EARTH,)
        for row in requirements
    )
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert any(code in {"logistics_source", "import_source", "import_transport_blocked"} for code, _ in project.blockers)

    allocation_id = _owned_earth_leo_capacity(sim)
    for row in requirements:
        sim.inventory.add(EARTH, row.resource_id, row.amount_t)

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


def test_missing_source_policy_blocks_multiple_viable_sources_instead_of_choosing_implicitly():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _owned_multistage_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    sim.inventory.add(LEO, MACHINERY, 1.0)
    sim.logistics.set_global_logistics_policy(None)
    requirement = _requirement(
        1.0, requirement_id="supply.ambiguous-source", destination=LUNAR_ORBIT, resource=MACHINERY
    )

    options = sim.logistics.supply_planning_options(requirement, sim.day)
    assert EARTH in options.stocked_source_ids and LEO in options.stocked_source_ids
    assert EARTH in options.operational_source_ids and LEO in options.operational_source_ids
    assert "logistics_policy:source_selection_required" in options.blockers
    assert not sim.logistics.plan_capacity_logistics(sim.day, (requirement,)).dispatches


def test_pinned_source_does_not_fallback_to_another_viable_source():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
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
    sim.transport.create_transport_allocation(
        REUSABLE_ORBITAL_CARGO_TUG, LEO, LUNAR_ORBIT, target_units=1, day=sim.day
    )
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    sim.inventory.add(LEO, MACHINERY, 1.0)
    sim.logistics.set_global_logistics_policy(None)
    requirement = _requirement(
        1.0, requirement_id="supply.pinned-no-fallback", destination=LUNAR_ORBIT, resource=MACHINERY
    )
    policy_id = EntityId("logistics.policy.pinned-earth-no-fallback")
    sim.logistics.create_logistics_policy(
        policy_id, source_mode=SourceSelectionMode.PINNED, allowed_source_ids=(EARTH,)
    )
    sim.logistics.register_policy_owner_resolver(
        "test", lambda owner_id: owner_id == requirement.owner_id
    )
    sim.logistics.assign_logistics_policy("test", requirement.owner_id, policy_id)

    options = sim.logistics.supply_planning_options(requirement, sim.day)
    assert options.candidate_source_ids == (EARTH,)
    assert not options.operational_source_ids
    assert not sim.logistics.plan_capacity_logistics(sim.day, (requirement,)).dispatches

def test_scenario_global_policy_auto_selects_reachable_stocked_source():
    sim = build_game_application()._simulation
    _owned_earth_leo_capacity(sim)
    sim.inventory.add(EARTH, WATER, 1.0)
    requirement = _requirement(
        1.0,
        requirement_id="supply.auto-source",
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
    _owned_multistage_capacity(sim)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.stock[(LUNAR_ORBIT, MACHINERY)] = 0.0
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    _set_global_source_preference(sim, EARTH)
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
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.refresh_storage()
    _owned_earth_leo_capacity(sim)
    resource = DefinitionId("test.resource.boundary-supply")
    sim.inventory.add(EARTH, resource, 1.0)
    before = sim.inventory.amount(LEO, resource)
    _set_global_source_preference(sim, EARTH)
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
    assert sim.inventory.amount(LEO, resource) >= before
    for _ in range(8):
        if sim.inventory.amount(LEO, resource) >= before + dispatched - 1e-9:
            break
        sim.advance_days(1)
    assert sim.inventory.amount(LEO, resource) == pytest.approx(before + dispatched)

def test_cargo_arrival_waits_for_inventory_admission():
    app = build_game_application()
    sim = app._simulation
    sim.transport.transport_allocations.clear()
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.refresh_storage()
    _owned_earth_leo_capacity(sim)
    sim.inventory.stock[(LEO, MACHINERY)] = 0.0
    free = sim.inventory.admission_state(LEO, MACHINERY).admission_capacity_t
    assert free is not None and free > 1.0
    sim.inventory.add(LEO, CONSTRUCTION_EQUIPMENT, free)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    _set_global_source_preference(sim, EARTH)
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
    for _ in range(8):
        sim.advance_days(1)
        if waiting.id not in sim.logistics.arrival_waiting:
            break
    assert waiting.id not in sim.logistics.arrival_waiting

def test_supply_resource_competition_respects_priority_reservations_and_order_independence():
    inventory = InventoryBook()
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

def test_multistage_boundary_handoff_preserves_logistics_ownership():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _owned_multistage_capacity(sim)
    resource = CONSTRUCTION_EQUIPMENT
    sim.inventory.stock[(LUNAR_ORBIT, resource)] = 0.0
    sim.inventory.add(EARTH, resource, 0.1)
    _set_global_source_preference(sim, EARTH)
    target_id = sim.logistics.set_target_stock(LUNAR_ORBIT, resource, 0.1, 5)

    sim.advance_days(1)
    first = next(row for row in sim.logistics.cargo_flows.values() if row.owner_id == target_id)
    assert first.remaining_legs
    handoff_node = first.destination_id
    stock_before = sim.inventory.amount(handoff_node, resource)
    sim.advance_to_day(first.first_arrival_day)

    assert not [row for row in sim.logistics.arrival_waiting.values() if row.owner_id == target_id]
    downstream = next(row for row in sim.logistics.cargo_flows.values() if row.owner_id == target_id)
    assert downstream.source_id == handoff_node
    assert sim.inventory.amount(handoff_node, resource) == pytest.approx(stock_before)


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
    free = sim.inventory.admission_state(LEO, cargo).admission_capacity_t
    assert free is not None and free > 1.0
    sim.inventory.add(LEO, filler, free)
    sim.inventory.add(EARTH, cargo, 1.0)
    _set_global_source_preference(sim, EARTH)
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


def test_logistics_policy_source_handoff_and_service_constraints_are_hard_limits():
    sim = build_game_application()._simulation
    sim.transport.transport_allocations.clear()
    _owned_multistage_capacity(sim)
    sim.inventory.add(EARTH, MACHINERY, 2.0)
    sim.inventory.add(LEO, MACHINERY, 2.0)
    requirement = _requirement(
        1.0,
        requirement_id="supply.policy-hard-path",
        destination=LUNAR_ORBIT,
        resource=MACHINERY,
    )
    policy_id = EntityId("logistics.policy.hard-path")
    sim.logistics.create_logistics_policy(
        policy_id,
        source_mode=SourceSelectionMode.ALLOW_ANY,
        allowed_source_ids=(EARTH,),
        allowed_handoff_ids=(LEO,),
    )
    sim.logistics.set_global_logistics_policy(policy_id)

    initial_path = sim.logistics.supply_service_path(requirement, EARTH, sim.day)
    assert len(initial_path) == 2
    assert initial_path[0].destination_id == LEO
    options = sim.logistics.supply_planning_options(requirement, sim.day)
    assert options.candidate_source_ids == (EARTH,)
    assert options.operational_source_ids == (EARTH,)

    sim.logistics.update_logistics_policy(policy_id, allowed_handoff_ids=())
    blocked = sim.logistics.supply_planning_options(requirement, sim.day)
    assert not blocked.operational_source_ids
    assert "logistics_policy:path_constraint_unavailable" in blocked.blockers
    assert not sim.logistics.plan_capacity_logistics(sim.day, (requirement,)).dispatches

    sim.logistics.update_logistics_policy(
        policy_id,
        allowed_handoff_ids=(LEO,),
        allowed_service_ids=(initial_path[0].key,),
    )
    service_blocked = sim.logistics.supply_planning_options(requirement, sim.day)
    assert not service_blocked.operational_source_ids
    assert "logistics_policy:path_constraint_unavailable" in service_blocked.blockers

    sim.logistics.update_logistics_policy(
        policy_id,
        allowed_service_ids=tuple(edge.key for edge in initial_path),
    )
    restored = sim.logistics.supply_planning_options(requirement, sim.day)
    assert restored.operational_source_ids == (EARTH,)
    dispatch = sim.logistics.plan_capacity_logistics(sim.day, (requirement,)).dispatches[0]
    assert dispatch.source_id == EARTH
    assert tuple(edge.key for edge in dispatch.path) == tuple(edge.key for edge in initial_path)
