import math

import pytest
from dataclasses import replace

from space_idle import GetFleet, build_game_application
from space_idle.content import base_ids as ids
from space_idle.shared import EntityId, SpatialNodeId
from space_idle.site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements
from space_idle.validation import validate_runtime_state
from space_idle.validation_support import ConfigurationError
from space_idle.supply import SupplyRoutingConstraintScope
from space_idle.transport.models import (
    DirectionalCapacity,
    FleetActivityRef,
    OperationSupportLocation,
    OperationSupportRequirement,
    ResourceSupportRequirement,
)


def _fleet_sim(count: int = 5):
    sim = build_game_application()._simulation
    # Core invariants must not depend on the provisional initial Fleet content.
    sim.transport.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = count
    return sim


def _capacity_for_units(
    transport, vehicle_definition_id, source_id, destination_id, units, *, day=0,
    movement_hard_constraint=None,
):
    return transport.transport_capacity_for_units(
        vehicle_definition_id, source_id, destination_id, units,
        day=day, movement_hard_constraint=movement_hard_constraint,
    )


def _create_transport_for_units(
    transport, vehicle_definition_id, source_id, destination_id, units, *, day=0, **kwargs
):
    return transport.create_transport_allocation(
        vehicle_definition_id, source_id, destination_id,
        target_capacity=_capacity_for_units(
            transport, vehicle_definition_id, source_id, destination_id, units, day=day,
            movement_hard_constraint=kwargs.get("movement_hard_constraint"),
        ),
        day=day, **kwargs,
    )


def _update_transport_units(transport, allocation_id, units, *, day=0, **kwargs):
    allocation = transport.transport_allocations[allocation_id]
    capacity = _capacity_for_units(
        transport, allocation.vehicle_definition_id, allocation.anchor_node_id,
        allocation.destination_id, units, day=day,
        movement_hard_constraint=allocation.movement_hard_constraint,
    )
    transport.update_transport_allocation(
        allocation_id, target_capacity=capacity, day=day, **kwargs
    )



def test_fleet_commitment_ownership_conservation_and_query_projection():
    app = build_game_application()
    sim = app._simulation
    lg = sim.transport
    lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = 5

    special_commitment_id = EntityId("commitment.special")
    special_owner = FleetActivityRef("test_mission", EntityId("mission.special"))
    lg.commit_fleet_units(
        special_commitment_id,
        special_owner,
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )
    allocation_id = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 3,
        day=sim.day,
    )

    allocation = lg.transport_allocations[allocation_id]
    transport_commitment = next(
        row for row in lg.fleet_commitment_snapshots()
        if row.owner_activity_ref == FleetActivityRef("transport_allocation", allocation_id)
    )
    assert transport_commitment.quantity == 3
    assert transport_commitment.vehicle_definition_id == allocation.vehicle_definition_id
    assert transport_commitment.operational_node_id == allocation.anchor_node_id
    assert lg.transport_active_units(allocation_id) == 3
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1

    view = app.query(GetFleet())
    pool = next(
        item for item in view.pools
        if item.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
        and item.operational_node_id == str(ids.LEO)
    )
    commitment = next(item for item in view.commitments if item.id == str(special_commitment_id))
    assert commitment.owner_activity_type == "test_mission"
    assert commitment.usage_kind == "other"
    assert commitment.quantity == 1
    assert pool.other_committed_units == 1
    assert (
        pool.free_units
        + pool.transport_units
        + pool.research_units
        + pool.survey_units
        + pool.exploration_units
        + pool.founding_units
        + pool.retirement_units
        + pool.other_committed_units
        + pool.relocating_units
        + pool.releasing_units
        == pool.total_units
    )

    final_commitment_id = EntityId("commitment.final-free-unit")
    lg.commit_fleet_units(
        final_commitment_id,
        FleetActivityRef("test_activity", EntityId("final-free-unit")),
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )
    with pytest.raises(ValueError, match="insufficient free fleet units"):
        lg.commit_fleet_units(
            EntityId("commitment.overcommit"),
            FleetActivityRef("test_activity", EntityId("overcommit")),
            ids.REUSABLE_ORBITAL_CARGO_TUG,
            ids.LEO,
            1,
        )
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 0


def test_fleet_application_projection_separates_cross_domain_commitments():
    app = build_game_application()
    sim = app._simulation
    lg = sim.transport
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    node_id = ids.LEO
    lg.fleet_pool(vehicle_id, node_id).total_units = 8

    commitments = (
        ("research_provider_assignment", "research.assignment.test", 2),
        ("survey_provider_assignment", "survey.assignment.test", 1),
        ("scientific_exploration", "exploration.test", 1),
        ("founding", "founding.test", 1),
        ("test_activity", "other.test", 1),
    )
    for index, (activity_type, activity_id, quantity) in enumerate(commitments, start=1):
        lg.commit_fleet_units(
            EntityId(f"commitment.cross-domain.{index}"),
            FleetActivityRef(activity_type, EntityId(activity_id)),
            vehicle_id,
            node_id,
            quantity,
        )

    view = app.query(GetFleet())
    pool = next(
        item for item in view.pools
        if item.vehicle_definition_id == str(vehicle_id)
        and item.operational_node_id == str(node_id)
    )
    assert pool.free_units == 2
    assert pool.research_units == 2
    assert pool.survey_units == 1
    assert pool.exploration_units == 1
    assert pool.founding_units == 1
    assert pool.other_committed_units == 1

    usage_by_owner = {row.owner_activity_type: row.usage_kind for row in view.commitments}
    assert usage_by_owner["research_provider_assignment"] == "research"
    assert usage_by_owner["survey_provider_assignment"] == "survey"
    assert usage_by_owner["scientific_exploration"] == "scientific_exploration"
    assert usage_by_owner["founding"] == "founding"
    assert usage_by_owner["test_activity"] == "other"


def test_runtime_validation_enforces_fleet_commitment_owner_and_location_integrity():
    mismatched = _fleet_sim(1)
    transport = mismatched.transport
    allocation_id = _create_transport_for_units(
        transport, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 1,
        day=mismatched.day,
    )
    commitment = next(
        row for row in transport.fleet_commitments.values()
        if row.owner_activity_ref == FleetActivityRef("transport_allocation", allocation_id)
    )
    commitment.operational_node_id = ids.LUNAR_ORBIT
    with pytest.raises(ConfigurationError, match="transport Fleet commitment location mismatch"):
        validate_runtime_state(mismatched)

    orphaned_transport = _fleet_sim(1)
    transport = orphaned_transport.transport
    allocation_id = _create_transport_for_units(
        transport, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 1,
        day=orphaned_transport.day,
    )
    assert transport.transport_active_units(allocation_id) == 1
    del transport.transport_allocations[allocation_id]
    with pytest.raises(ConfigurationError, match="orphan Fleet commitment owner"):
        validate_runtime_state(orphaned_transport)

    external = _fleet_sim(1)
    transport = external.transport
    owner_id = EntityId("external.alpha")
    active_owners = {owner_id}
    transport.register_fleet_commitment_owner_resolver(
        "external_test_activity", lambda candidate: candidate in active_owners
    )
    transport.commit_fleet_units(
        EntityId("commitment.external.alpha"),
        FleetActivityRef("external_test_activity", owner_id),
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )
    validate_runtime_state(external)
    active_owners.clear()
    with pytest.raises(ConfigurationError, match="orphan Fleet commitment owner"):
        validate_runtime_state(external)






def test_provisioning_allocator_honors_priority_refill_and_registration_order_independence():
    refill_sim = _fleet_sim(2)
    refill = refill_sim.transport
    commitment_id = EntityId("commitment.special")
    refill.commit_fleet_units(
        commitment_id,
        FleetActivityRef("test_mission", EntityId("mission.special")),
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )
    refill_allocation = _create_transport_for_units(
        refill, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 3,
        day=refill_sim.day,
    )
    assert refill.transport_active_units(refill_allocation) == 1
    refill.add_fleet_units(ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, day=refill_sim.day)
    assert refill.transport_active_units(refill_allocation) == 2
    refill.release_fleet_commitment(commitment_id, day=refill_sim.day)
    assert refill.transport_active_units(refill_allocation) == 3
    assert refill.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 0

    sim = _fleet_sim(3)
    lg = sim.transport
    low = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 3,
        provisioning_priority=1, day=sim.day,
    )
    high = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 2,
        provisioning_priority=5, day=sim.day,
    )
    # No service has operated yet in this simulation day, so reprioritization is
    # a pure allocation edit and can be settled without a recovery delay.
    assert lg.allocation_required_units(low, sim.day) == 3
    assert lg.transport_active_units(low) == 1
    assert lg.transport_active_units(high) == 2
    assert not lg.fleet_releases
    snapshot = lg.transport_capacity_snapshot(low, day=sim.day)
    assert snapshot.required_units == 3
    assert snapshot.unfilled_units == 2
    assert "fleet_unfilled:2" in snapshot.blockers
    def active_by_destination(destinations):
        registration_sim = build_game_application()._simulation
        registration_logistics = registration_sim.transport
        target_id = SpatialNodeId("test.location.registration_order")
        registration_sim.graph.found_location(
            target_id, "Target", ids.MOON, ids.MOON_CELL_FARSIDE_HIGHLANDS
        )
        registration_sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, target_id)
        registration_sim.facilities.install(
            ids.SURFACE_DISTRIBUTION_HUB,
            target_id,
            site_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS,
        )
        registration_logistics.invalidate_movement_plans()
        registration_logistics.fleet_pool(
            ids.REUSABLE_SURFACE_CARGO_LANDER, ids.LUNAR_ORBIT
        ).total_units = 1
        actual = [
            ids.LEO if destination == "leo" else target_id
            for destination in destinations
        ]
        for destination in actual:
            _create_transport_for_units(
                registration_logistics, ids.REUSABLE_SURFACE_CARGO_LANDER,
                ids.LUNAR_ORBIT, destination, 1, provisioning_priority=3, day=0,
            )
        return {
            str(allocation.destination_id): registration_logistics.transport_active_units(
                allocation.id
            )
            for allocation in registration_logistics.transport_allocations.values()
        }

    assert active_by_destination(("leo", "surface")) == active_by_destination(
        ("surface", "leo")
    )

    def active_by_target(targets):
        registration_sim = _fleet_sim(2)
        registration_logistics = registration_sim.transport
        for target in targets:
            _create_transport_for_units(
                registration_logistics, ids.REUSABLE_ORBITAL_CARGO_TUG,
                ids.LEO, ids.LUNAR_ORBIT, target, provisioning_priority=3, day=0,
            )
        return {
            registration_logistics.allocation_required_units(allocation.id, 0):
                registration_logistics.transport_active_units(allocation.id)
            for allocation in registration_logistics.transport_allocations.values()
        }

    assert active_by_target((1, 2)) == active_by_target((2, 1)) == {1: 1, 2: 1}




def test_transport_capacity_is_authoritative_and_required_units_are_derived():
    invalid_sim = build_game_application()._simulation
    invalid_transport = invalid_sim.transport
    before_allocations = dict(invalid_transport.transport_allocations)
    with pytest.raises(ValueError, match="reverse capacity target"):
        invalid_transport.create_transport_allocation(
            ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
            target_capacity=DirectionalCapacity(1.0, 1.0), day=invalid_sim.day,
        )
    assert invalid_transport.transport_allocations == before_allocations

    one_way_id = invalid_transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
        target_capacity=DirectionalCapacity(1.0, 0.0), day=invalid_sim.day,
    )
    before_one_way = replace(invalid_transport.transport_allocations[one_way_id])
    with pytest.raises(ValueError, match="reverse capacity target"):
        invalid_transport.update_transport_allocation(
            one_way_id, target_capacity=DirectionalCapacity(1.0, 1.0),
            day=invalid_sim.day,
        )
    assert invalid_transport.transport_allocations[one_way_id] == before_one_way

    capacity_sim = _fleet_sim(10)
    capacity_transport = capacity_sim.transport
    capacity_allocation_id = capacity_transport.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT,
        target_capacity=DirectionalCapacity(3.0, 3.0), day=capacity_sim.day,
    )
    plan = capacity_transport.derive_transport_service_plan(
        capacity_allocation_id, capacity_sim.day
    )
    target = capacity_transport.transport_allocations[capacity_allocation_id].target_capacity
    forward_units = math.ceil(
        target.forward_t_per_day / plan.nominal_per_unit.forward_t_per_day - 1e-12
    )
    reverse_units = math.ceil(
        target.reverse_t_per_day / plan.nominal_per_unit.reverse_t_per_day - 1e-12
    )
    expected = max(forward_units, reverse_units)
    assert capacity_transport.allocation_required_units(
        capacity_allocation_id, capacity_sim.day
    ) == expected
    assert expected < forward_units + reverse_units
    assert capacity_transport.transport_capacity_snapshot(
        capacity_allocation_id, day=capacity_sim.day
    ).required_units == expected

    convenience_sim = _fleet_sim(3)
    convenience_transport = convenience_sim.transport
    five_unit_capacity = convenience_transport.transport_capacity_for_units(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 5,
        day=convenience_sim.day,
    )
    convenience_id = convenience_transport.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT,
        target_capacity=five_unit_capacity, day=convenience_sim.day,
    )
    allocation = convenience_transport.transport_allocations[convenience_id]
    assert allocation.target_capacity == five_unit_capacity
    assert convenience_transport.allocation_required_units(
        convenience_id, convenience_sim.day
    ) == 5
    assert convenience_transport.transport_active_units(convenience_id) == 3
    with pytest.raises(ValueError, match="non-negative"):
        convenience_transport.transport_capacity_for_units(
            ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, -1,
            day=convenience_sim.day,
        )

    auto_plan = capacity_transport.derive_transport_service_plan(
        capacity_allocation_id, capacity_sim.day
    )
    incompatible_plan = capacity_transport.movement_plan_candidates(
        ids.EARTH, ids.LEO
    )[0]
    before_constraint = capacity_transport.transport_allocations[capacity_allocation_id]
    with pytest.raises(ValueError):
        capacity_transport.set_transport_movement_constraint(
            capacity_allocation_id, (incompatible_plan.id,), day=capacity_sim.day
        )
    after_constraint = capacity_transport.transport_allocations[capacity_allocation_id]
    assert after_constraint == before_constraint
    assert after_constraint.movement_hard_constraint is None
    assert capacity_transport.derive_transport_service_plan(
        capacity_allocation_id, capacity_sim.day
    ).forward_path == auto_plan.forward_path


def test_transport_pause_preserves_capacity_target_and_safely_releases_then_reprovisions():
    sim = _fleet_sim(2)
    lg = sim.transport
    allocation_id = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 2, day=0
    )
    allocation = lg.transport_allocations[allocation_id]
    target = allocation.target_capacity
    required = lg.allocation_required_units(allocation_id, 0)
    assert required == 2
    assert lg.transport_active_units(allocation_id) == 2

    allocation.last_operated_day = 2
    lg.update_transport_allocation(allocation_id, paused=True, day=3)
    paused = lg.transport_allocations[allocation_id]
    assert paused.paused
    assert paused.target_capacity == target
    assert lg.allocation_required_units(allocation_id, 3) == required
    assert lg.transport_active_units(allocation_id) == 0
    assert sum(
        lg.fleet_commitment_snapshot(row.fleet_commitment_id).quantity
        for row in lg.fleet_release_snapshots()
    ) == 2

    recovery_day = max(row.release_day for row in lg.fleet_releases.values())
    lg.advance_fleet_state(recovery_day)
    assert lg.transport_active_units(allocation_id) == 0
    assert not lg.fleet_releases

    lg.update_transport_allocation(allocation_id, paused=False, day=recovery_day)
    resumed = lg.transport_allocations[allocation_id]
    assert not resumed.paused
    assert resumed.target_capacity == target
    assert lg.transport_active_units(allocation_id) == required


def test_relocation_plan_is_the_execution_contract_for_eligibility_allocation_time_and_resources():
    sim = _fleet_sim(1)
    lg = sim.transport
    with pytest.raises(ValueError, match="refueling|resource"):
        lg.relocate_fleet(
            ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, ids.LUNAR_ORBIT, day=0
        )

    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.stock[(ids.LEO, ids.PROPELLANT)] = 0.0
    sim.inventory.stock[(ids.LUNAR_ORBIT, ids.PROPELLANT)] = 0.0

    plan = lg.fleet_relocation_plan(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        1,
        ids.LEO,
        ids.LUNAR_ORBIT,
        day=sim.day,
    )
    assert plan.path
    assert plan.blockers
    assert all(blocker.startswith("resource:") for blocker in plan.blockers)
    assert plan.travel_days > 0
    assert plan.arrival_day == sim.day + plan.travel_days
    assert plan.resource_requirements

    relocation_id = lg.relocate_fleet(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        1,
        ids.LEO,
        ids.LUNAR_ORBIT,
        day=sim.day,
    )
    relocation = lg.fleet_relocations[relocation_id]
    assert relocation.movement_execution_id is None
    for row in plan.resource_requirements:
        assert lg.inventory.available(row.operational_node_id, row.resource_id) == pytest.approx(
            row.available_t
        )

    sim.advance_days(1)
    assert relocation.movement_execution_id is None
    for row in plan.resource_requirements:
        assert lg.inventory.available(row.operational_node_id, row.resource_id) == pytest.approx(
            row.available_t
        )

    for row in plan.resource_requirements:
        missing = max(0.0, row.required_t - lg.inventory.available(
            row.operational_node_id, row.resource_id
        ))
        if missing > 0.0:
            sim.inventory.add(row.operational_node_id, row.resource_id, missing)
    before_departure = {
        (row.operational_node_id, row.resource_id): lg.inventory.available(
            row.operational_node_id, row.resource_id
        )
        for row in plan.resource_requirements
    }
    departure_day = sim.day
    sim.advance_days(1)

    assert relocation.movement_execution_id is not None
    execution = lg.movement_executions[relocation.movement_execution_id]
    assert execution.started_day == departure_day
    assert execution.latency_days == plan.travel_days
    assert execution.completion_day == departure_day + plan.travel_days
    for row in plan.resource_requirements:
        assert lg.inventory.available(row.operational_node_id, row.resource_id) == pytest.approx(
            before_departure[(row.operational_node_id, row.resource_id)] - row.required_t
        )


def test_tick_boundary_cargo_arrival_can_fund_relocation_before_allocation():
    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.refresh_storage()
    sim.inventory.stock[(ids.LEO, ids.PROPELLANT)] = 0.0

    relocation_id = lg.relocate_fleet(
        ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, ids.LUNAR_ORBIT, day=0
    )
    relocation = lg.fleet_relocations[relocation_id]
    required = sum(
        need.required_t
        for need in relocation.resource_needs
        if need.operational_node_id == ids.LEO and need.resource_id == ids.PROPELLANT
    )
    assert required > 0.0

    _create_transport_for_units(
        lg, ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 1, day=sim.day
    )
    sim.inventory.add(ids.EARTH, ids.PROPELLANT, required)

    decision = sim.tick_decision_projection()
    dispatch = next(
        row for row, amount in decision.allocations.transport.executable_dispatches
        if row.requirement.owner_kind == "fleet_relocation"
        and row.requirement.owner_id == relocation_id
        and row.requirement.resource_id == ids.PROPELLANT
        and amount > 0.0
    )
    sim.advance_days(1)
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.requirement_id == dispatch.requirement.id
    )
    ready_day = flow.first_arrival_day
    assert ready_day > 0

    sim.advance_to_day(ready_day)
    assert relocation.movement_execution_id is None
    assert sim.inventory.available(ids.LEO, ids.PROPELLANT) == pytest.approx(required)

    for _ in range(8):
        sim.advance_days(1)
        if relocation.movement_execution_id is not None:
            break

    assert relocation.movement_execution_id is not None
    execution = lg.movement_executions[relocation.movement_execution_id]
    assert execution.started_day >= ready_day
    assert execution.completion_day == execution.started_day + execution.latency_days
    assert flow.id not in sim.logistics.cargo_flows

def test_resource_support_uses_definition_capability_instead_of_magic_refueling_id():
    sim = _fleet_sim(1)
    lg = sim.transport
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    definition = lg.vehicle_defs[vehicle_id]
    lg.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(
            definition.performance,
            resource_support_requirements=(
                ResourceSupportRequirement(
                    ids.PROPELLANT,
                    "spacecraft_servicing",
                    "refueling_interface",
                ),
            ),
        ),
    )
    node_definition = sim.facilities.definitions[ids.ORBITAL_LOGISTICS_NODE]
    sim.facilities.definitions[ids.ORBITAL_LOGISTICS_NODE] = replace(
        node_definition,
        capability_supplies=tuple(
            supply
            for supply in node_definition.capability_supplies
            if supply.id != "vehicle_refueling"
        ),
    )
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 10.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 10.0)

    allocation_id = _create_transport_for_units(
        lg, vehicle_id, ids.LEO, ids.LUNAR_ORBIT, 1, day=sim.day
    )
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=sim.day)

    assert snapshot.available.forward_t_per_day > 0
    assert not any("vehicle_refueling" in value for value in snapshot.limiting_factors)


def test_service_plan_blocker_zeroes_available_capacity_consistently_with_execution():
    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

    lg.spaceflight_movement_rules = tuple(
        replace(
            row,
            origin_requirements=SiteRequirements(
                row.origin_requirements.environment,
                (CapabilityRequirement("research_lab", CapabilityRequirementState.ACTIVE),),
            ),
        )
        if row.operation_type == "spaceflight"
        else row
        for row in lg.spaceflight_movement_rules
    )
    lg.invalidate_movement_plans()
    allocation_id = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 1,
        day=sim.day,
    )

    plan = lg.derive_transport_service_plan(allocation_id, sim.day)
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=sim.day)

    assert plan.nominal_per_unit.forward_t_per_day > 0
    assert lg.allocation_required_units(allocation_id, sim.day) == 1
    assert any("research_lab" in blocker for blocker in plan.blockers)
    assert snapshot.nominal.forward_t_per_day > 0
    assert snapshot.available.forward_t_per_day == 0
    assert snapshot.available.reverse_t_per_day == 0
    constrained = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=sim.day
    )
    assert constrained.available.forward_t_per_day == 0


def test_multileg_operation_support_is_checked_at_actual_leg_endpoint():
    sim = _fleet_sim(1)
    lg = sim.transport
    vehicle_id = ids.REUSABLE_SURFACE_CARGO_LANDER
    target_id = SpatialNodeId("test.location.landing_support")
    sim.graph.found_location(target_id, "Target", ids.MOON, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, target_id)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, target_id, site_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS)
    landing_plan = min(
        (
            plan for plan in lg.movement_plan_candidates(ids.LUNAR_ORBIT, target_id)
            if tuple(operation.operation_type for operation in plan.operations) == ("landing",)
        ),
        key=lambda row: str(row.id),
    )
    definition = lg.vehicle_defs[vehicle_id]
    lg.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(
            definition.performance,
            propellant_resource_id=None,
            propellant_capacity_t=0.0,
            propellant_t_per_total_t_per_km_s=0.0,
            resource_support_requirements=(),
            operation_support_requirements=(
                OperationSupportRequirement(
                    "landing", OperationSupportLocation.ORIGIN, "research_lab"
                ),
            ),
        ),
    )
    lg.fleet_pool(vehicle_id, ids.LEO).total_units = 1
    sim.facilities.install(ids.MICROGRAVITY_EXPERIMENT_PLATFORM, ids.LEO)
    movement_constraint = (
        min(
            (
                plan for plan in lg.movement_plan_candidates(ids.LEO, ids.LUNAR_ORBIT)
                if tuple(operation.operation_type for operation in plan.operations) == ("spaceflight",)
            ),
            key=lambda row: str(row.id),
        ).id,
        landing_plan.id,
    )
    allocation_id = _create_transport_for_units(
        lg, vehicle_id, ids.LEO, target_id, 1,
        movement_hard_constraint=movement_constraint, day=sim.day,
    )
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert snapshot.available.forward_t_per_day == 0
    assert f"infrastructure:{ids.LUNAR_ORBIT}:research_lab" in snapshot.limiting_factors


def test_relocation_keeps_units_exclusive_until_arrival():
    sim = _fleet_sim(3)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 10.0)
    source_before = lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO
    ).total_units
    destination_before = lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT
    ).total_units
    relocation_id = lg.relocate_fleet(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        2,
        ids.LEO,
        ids.LUNAR_ORBIT,
        day=0,
    )
    relocation = lg.fleet_relocations[relocation_id]
    commitment_id = relocation.fleet_commitment_id
    commitment = lg.fleet_commitment_snapshot(commitment_id)
    assert commitment is not None
    assert commitment.owner_activity_ref == FleetActivityRef("fleet_relocation", relocation_id)
    assert commitment.quantity == 2
    assert commitment.operational_node_id == ids.LEO
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1
    sim.advance_days(1)
    relocation = lg.fleet_relocations[relocation_id]
    assert relocation.movement_execution_id is not None
    execution = lg.movement_executions[relocation.movement_execution_id]
    assert execution.started_day == 0
    moving_commitment = lg.fleet_commitment_snapshot(commitment_id)
    assert moving_commitment is not None
    assert moving_commitment.operational_node_id is None
    assert moving_commitment.movement_execution_id == execution.id
    assert execution.fleet_commitment_id == commitment_id
    assert lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO
    ).total_units == source_before - 2
    assert lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT
    ).total_units == destination_before
    lg.advance_fleet_state(execution.completion_day - 1)
    assert relocation_id in lg.fleet_relocations
    lg.advance_fleet_state(execution.completion_day)
    assert relocation_id not in lg.fleet_relocations
    assert lg.fleet_commitment_snapshot(commitment_id) is None
    assert lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO
    ).total_units == source_before - 2
    assert lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT
    ).total_units == destination_before + 2


def test_releasing_uses_remaining_cycle_time_not_a_new_full_cycle():
    sim = _fleet_sim(2)
    lg = sim.transport
    allocation_id = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 2, day=0,
    )
    allocation = lg.transport_allocations[allocation_id]
    cycle_days = int(math.ceil(lg.derive_transport_service_plan(allocation_id, 0).cycle_days))
    allocation.last_operated_day = 2
    _update_transport_units(lg, allocation_id, 1, day=3)
    release = next(iter(lg.fleet_releases.values()))
    assert release.release_day == 2 + cycle_days

    # If the last operated cycle has already completed, reducing the target
    # frees the unit immediately instead of starting an artificial new cycle.
    lg.advance_fleet_state(release.release_day)
    allocation.last_operated_day = 2
    _update_transport_units(lg, allocation_id, 0, day=release.release_day)
    assert not lg.fleet_releases
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 2


def test_fleet_query_exposes_and_scopes_transitional_state():
    app = build_game_application()
    sim = app._simulation
    lg = sim.transport
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    lg.fleet_pool(vehicle_id, ids.LEO).total_units = 3
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

    allocation_id = _create_transport_for_units(
        lg, vehicle_id, ids.LEO, ids.LUNAR_ORBIT, 2, day=0
    )
    lg.transport_allocations[allocation_id].last_operated_day = 2
    sim.day = 3
    _update_transport_units(lg, allocation_id, 1, day=sim.day)
    relocation_id = lg.relocate_fleet(
        vehicle_id, 1, ids.LEO, ids.LUNAR_ORBIT, day=sim.day
    )

    leo = app.query(GetFleet(str(ids.LEO), str(vehicle_id)))
    assert [row.id for row in leo.relocations] == [str(relocation_id)]
    assert len(leo.releases) == 1
    release = leo.releases[0]
    assert release.allocation_id == str(allocation_id)
    assert release.vehicle_definition_id == str(vehicle_id)
    assert release.operational_node_id == str(ids.LEO)
    assert release.units == 1
    assert release.release_day > sim.day
    assert release.remaining_days == release.release_day - sim.day

    lunar_orbit = app.query(GetFleet(str(ids.LUNAR_ORBIT), str(vehicle_id)))
    assert [row.id for row in lunar_orbit.relocations] == [str(relocation_id)]
    assert lunar_orbit.releases == ()

    earth = app.query(GetFleet(str(ids.EARTH), str(vehicle_id)))
    assert earth.relocations == ()
    assert earth.releases == ()


def test_bidirectional_service_resource_use_counts_empty_return_not_loaded_return():
    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)
    allocation_id = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 1, day=0,
    )
    plan = lg.derive_transport_service_plan(allocation_id, 0)
    nominal = lg.transport_capacity_snapshot(allocation_id, day=0).nominal
    used = DirectionalCapacity(nominal.forward_t_per_day, 0.0)
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=0, used=used)

    empty = {(loc, rid): amount for loc, rid, amount in plan.resource_t_per_empty_cycle_day}
    forward_increment = {
        (loc, rid): amount
        for loc, rid, amount in plan.resource_t_per_forward_payload_increment_day
    }
    expected = {
        key: empty.get(key, 0.0) + forward_increment.get(key, 0.0)
        for key in set(empty) | set(forward_increment)
    }
    actual = {(loc, rid): amount for loc, rid, amount in snapshot.operational_supply}
    assert actual == pytest.approx(expected)
    assert snapshot.utilization == pytest.approx(1.0)


def test_resource_limited_available_capacity_uses_shared_allocation_and_nominal_utilization():
    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.refresh_storage()
    allocation_id = _create_transport_for_units(
        lg, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 1, day=0,
    )
    service_plan = lg.derive_transport_service_plan(allocation_id, 0)
    physical = lg.transport_capacity_snapshot(allocation_id, day=0)
    empty = {
        (loc, rid): amount
        for loc, rid, amount in service_plan.resource_t_per_empty_cycle_day
    }
    forward_increment = {
        (loc, rid): amount
        for loc, rid, amount in service_plan.resource_t_per_forward_payload_increment_day
    }
    forward_full = {
        key: empty.get(key, 0.0) + forward_increment.get(key, 0.0)
        for key in set(empty) | set(forward_increment)
    }
    for (location_id, resource_id), amount in forward_full.items():
        sim.inventory.stock[(location_id, resource_id)] = amount / 2.0

    cargo_amount = physical.nominal.forward_t_per_day
    sim.inventory.stock[(ids.LUNAR_ORBIT, ids.MACHINERY)] = 0.0
    sim.inventory.stock[(ids.LEO, ids.MACHINERY)] = cargo_amount
    target_id = sim.logistics.set_target_stock(
        ids.LUNAR_ORBIT, ids.MACHINERY, cargo_amount, 5
    )
    sim.logistics.set_supply_routing_constraint(
        SupplyRoutingConstraintScope(
            destination_id=ids.LUNAR_ORBIT,
            owner_kind="target_stock",
            owner_id=EntityId(str(target_id)),
            resource_id=ids.MACHINERY,
        ),
        source_node_id=ids.LEO,
    )

    decision = sim.tick_decision_projection()
    dispatch, executable = next(
        (row, amount)
        for row, amount in decision.allocations.transport.executable_dispatches
        if row.requirement.owner_id == target_id
    )
    available = sim.logistics.current_transport_capacity_snapshot(
        allocation_id,
        day=0,
        execution_allocation=decision.allocations.transport,
    )
    assert available.available.forward_t_per_day == pytest.approx(
        available.nominal.forward_t_per_day / 2.0
    )
    assert any(
        value.startswith("resource_allocation:")
        for value in available.limiting_factors
    )
    assert decision.allocations.execution.allocated(dispatch.cargo_execution_id) == pytest.approx(
        cargo_amount / 2.0
    )
    assert decision.allocations.resources.allocated(dispatch.cargo_execution_id) == pytest.approx(
        cargo_amount / 2.0
    )
    assert executable == pytest.approx(cargo_amount / 2.0)

    used = DirectionalCapacity(available.available.forward_t_per_day, 0.0)
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=0, used=used)
    assert snapshot.utilization == pytest.approx(0.5)
    actual = {
        (loc, rid): amount
        for loc, rid, amount in snapshot.operational_supply
    }
    assert actual == pytest.approx(
        {key: amount / 2.0 for key, amount in forward_full.items()}
    )
