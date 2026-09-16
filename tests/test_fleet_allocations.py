import math

import pytest
from dataclasses import replace

from space_idle import GetFleet, build_game_application
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content import base_ids as ids
from space_idle.shared import EntityId, SpatialNodeId
from space_idle.site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements
from space_idle.validation import validate_runtime_state
from space_idle.validation_support import ConfigurationError
from space_idle.transport.models import (
    DirectionalCapacity,
    FleetReservationKind,
    OperationSupportLocation,
    OperationSupportRequirement,
    ResourceSupportRequirement,
    TransportControlMode,
)


def _fleet_sim(count: int = 5):
    sim = build_base_simulation()
    # Core invariants must not depend on the provisional initial Fleet content.
    sim.transport.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = count
    return sim



def test_fleet_commitments_are_reservation_owned_and_free_units_are_derived():
    sim = _fleet_sim(5)
    lg = sim.transport
    lg.reserve_fleet_units(
        EntityId("reservation.exploration"),
        EntityId("exploration.alpha"),
        FleetReservationKind.SCIENTIFIC_EXPLORATION,
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=3,
        day=sim.day,
    )

    allocation = lg.transport_allocations[allocation_id]
    reservation = next(
        row for row in lg.fleet_reservation_snapshots()
        if row.kind is FleetReservationKind.TRANSPORT and row.owner_id == allocation_id
    )
    assert reservation.units == 3
    assert reservation.vehicle_definition_id == allocation.vehicle_definition_id
    assert reservation.operational_node_id == allocation.anchor_node_id
    assert lg.transport_active_units(allocation_id) == 3
    assert lg.fleet_pool_snapshot(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).transport_units == 3
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1

def test_runtime_validation_rejects_transport_reservation_outside_allocation_contract():
    sim = _fleet_sim(1)
    lg = sim.transport
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=1,
        day=sim.day,
    )
    reservation = next(
        row for row in lg.fleet_reservations.values()
        if row.kind is FleetReservationKind.TRANSPORT and row.owner_id == allocation_id
    )
    reservation.operational_node_id = ids.LUNAR_ORBIT

    with pytest.raises(ConfigurationError, match="transport fleet reservation location mismatch"):
        validate_runtime_state(sim)


def test_transport_target_refills_immediately_when_fleet_availability_increases():
    sim = _fleet_sim(2)
    lg = sim.transport
    reservation_id = EntityId("reservation.special")
    lg.reserve_fleet_units(
        reservation_id,
        EntityId("mission.special"),
        FleetReservationKind.SPECIAL_MISSION,
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=3,
        day=sim.day,
    )
    assert lg.transport_active_units(allocation_id) == 1

    lg.add_fleet_units(ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, day=sim.day)
    assert lg.transport_active_units(allocation_id) == 2

    lg.release_fleet_reservation(reservation_id, day=sim.day)
    assert lg.transport_active_units(allocation_id) == 3
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 0

def test_fleet_query_exposes_other_exclusive_reservations_in_pool_balance():
    app = build_game_application()
    sim = app._simulation
    lg = sim.transport
    lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = 2
    reservation_id = EntityId("reservation.special.query")
    lg.reserve_fleet_units(
        reservation_id,
        EntityId("mission.special.query"),
        FleetReservationKind.SPECIAL_MISSION,
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        1,
    )

    row = next(
        item
        for item in app.query(GetFleet()).pools
        if item.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
        and item.operational_node_id == str(ids.LEO)
    )

    assert row.total_units == 2
    assert row.free_units == 1
    assert row.other_reserved_units == 1
    assert (
        row.free_units
        + row.transport_units
        + row.exploration_units
        + row.other_reserved_units
        + row.relocating_units
        + row.releasing_units
        == row.total_units
    )


def test_provisioning_allocator_honors_priority_and_is_registration_order_independent():
    sim = _fleet_sim(3)
    lg = sim.transport
    low = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        provisioning_priority=1,
        target_units=3,
        day=sim.day,
    )
    high = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        provisioning_priority=5,
        target_units=2,
        day=sim.day,
    )
    # No service has operated yet in this simulation day, so reprioritization is
    # a pure allocation edit and can be settled without a recovery delay.
    assert lg.transport_allocations[low].target_units == 3
    assert lg.transport_active_units(low) == 1
    assert lg.transport_active_units(high) == 2
    assert not lg.fleet_releases
    snapshot = lg.transport_capacity_snapshot(low, day=sim.day)
    assert snapshot.required_units == 3
    assert snapshot.unfilled_units == 2
    assert "fleet_unfilled:2" in snapshot.blockers
    def active_by_destination(destinations):
        registration_sim = build_base_simulation()
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
            registration_logistics.create_transport_allocation(
                ids.REUSABLE_SURFACE_CARGO_LANDER,
                ids.LUNAR_ORBIT,
                destination,
                provisioning_priority=3,
                target_units=1,
                day=0,
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
            registration_logistics.create_transport_allocation(
                ids.REUSABLE_ORBITAL_CARGO_TUG,
                ids.LEO,
                ids.LUNAR_ORBIT,
                provisioning_priority=3,
                target_units=target,
                day=0,
            )
        return {
            allocation.target_units: registration_logistics.transport_active_units(
                allocation.id
            )
            for allocation in registration_logistics.transport_allocations.values()
        }

    assert active_by_target((1, 2)) == active_by_target((2, 1)) == {1: 1, 2: 1}


def test_capacity_mode_rejects_unsupported_directional_target_without_mutation():
    sim = build_base_simulation()
    lg = sim.transport
    before_allocations = dict(lg.transport_allocations)

    with pytest.raises(ValueError, match="reverse capacity target"):
        lg.create_transport_allocation(
            ids.REUSABLE_LAUNCH_VEHICLE,
            ids.EARTH,
            ids.LEO,
            control_mode=TransportControlMode.CAPACITY,
            target_units=None,
            target_capacity=DirectionalCapacity(1.0, 1.0),
            day=sim.day,
        )
    assert lg.transport_allocations == before_allocations

    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE,
        ids.EARTH,
        ids.LEO,
        control_mode=TransportControlMode.CAPACITY,
        target_units=None,
        target_capacity=DirectionalCapacity(1.0, 0.0),
        day=sim.day,
    )
    before = replace(lg.transport_allocations[allocation_id])
    with pytest.raises(ValueError, match="reverse capacity target"):
        lg.update_transport_allocation(
            allocation_id,
            target_capacity=DirectionalCapacity(1.0, 1.0),
            day=sim.day,
        )
    assert lg.transport_allocations[allocation_id] == before


def test_transport_control_modes_preserve_authoritative_target_and_derive_required_units():
    capacity_sim = _fleet_sim(10)
    capacity_logistics = capacity_sim.transport
    capacity_allocation_id = capacity_logistics.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        control_mode=TransportControlMode.CAPACITY,
        target_units=None,
        target_capacity=DirectionalCapacity(3.0, 3.0),
        day=capacity_sim.day,
    )
    plan = capacity_logistics.derive_transport_service_plan(
        capacity_allocation_id, capacity_sim.day
    )
    target = capacity_logistics.transport_allocations[
        capacity_allocation_id
    ].target_capacity
    assert target is not None
    forward_units = math.ceil(
        target.forward_t_per_day / plan.nominal_per_unit.forward_t_per_day - 1e-12
    )
    reverse_units = math.ceil(
        target.reverse_t_per_day / plan.nominal_per_unit.reverse_t_per_day - 1e-12
    )
    expected = max(forward_units, reverse_units)
    required = capacity_logistics.allocation_required_units(
        capacity_allocation_id, capacity_sim.day
    )
    assert required == expected
    assert required < forward_units + reverse_units
    assert capacity_logistics.transport_capacity_snapshot(
        capacity_allocation_id, day=capacity_sim.day
    ).required_units == expected

    units_sim = _fleet_sim(3)
    units_logistics = units_sim.transport
    units_allocation_id = units_logistics.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=5,
        day=units_sim.day,
    )
    before = units_logistics.transport_allocations[units_allocation_id]
    assert before.target_units == 5
    assert units_logistics.transport_active_units(units_allocation_id) == 3
    per_unit = units_logistics.derive_transport_service_plan(
        units_allocation_id, units_sim.day
    ).nominal_per_unit

    units_logistics.change_transport_allocation_mode(
        units_allocation_id, TransportControlMode.CAPACITY, day=units_sim.day
    )
    converted = units_logistics.transport_allocations[units_allocation_id]
    assert converted.target_units is None
    assert converted.target_capacity == DirectionalCapacity(
        per_unit.forward_t_per_day * 5,
        per_unit.reverse_t_per_day * 5,
    )
    assert units_logistics.allocation_required_units(
        units_allocation_id, units_sim.day
    ) == 5

def test_relocation_requires_operational_support_and_propellant():
    sim = _fleet_sim(1)
    lg = sim.transport
    try:
        lg.relocate_fleet(
            ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, ids.LUNAR_ORBIT, day=0
        )
    except ValueError as exc:
        assert "refueling" in str(exc) or "resource" in str(exc)
    else:
        raise AssertionError("relocation unexpectedly ignored operational requirements")


def test_relocation_plan_is_the_execution_contract_for_time_and_resources():
    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

    plan = lg.fleet_relocation_plan(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        1,
        ids.LEO,
        ids.LUNAR_ORBIT,
        day=sim.day,
    )
    assert plan.feasible
    assert plan.path
    assert plan.travel_days > 0
    assert plan.arrival_day == sim.day + plan.travel_days
    assert plan.resource_requirements
    before = {
        (row.operational_node_id, row.resource_id): row.available_t
        for row in plan.resource_requirements
    }

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
            before[(row.operational_node_id, row.resource_id)]
        )

    sim.advance_days(1)
    relocation = lg.fleet_relocations[relocation_id]
    assert relocation.movement_execution_id is not None
    execution = lg.movement_executions[relocation.movement_execution_id]
    assert execution.started_day == 0
    assert execution.completion_day == plan.arrival_day
    for row in plan.resource_requirements:
        assert lg.inventory.available(row.operational_node_id, row.resource_id) == pytest.approx(
            before[(row.operational_node_id, row.resource_id)] - row.required_t
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

    lg.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, target_units=1, day=sim.day
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

    allocation_id = lg.create_transport_allocation(
        vehicle_id, ids.LEO, ids.LUNAR_ORBIT, target_units=1, day=sim.day
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
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=1,
        day=sim.day,
    )

    plan = lg.derive_transport_service_plan(allocation_id, sim.day)
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=sim.day)

    assert plan.nominal_per_unit.forward_t_per_day > 0
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
    allocation_id = lg.create_transport_allocation(
        vehicle_id, ids.LEO, target_id, target_units=1,
        path=(
            min(
                (
                    plan for plan in lg.movement_plan_candidates(ids.LEO, ids.LUNAR_ORBIT)
                    if tuple(operation.operation_type for operation in plan.operations) == ("spaceflight",)
                ),
                key=lambda row: str(row.id),
            ).id,
            landing_plan.id,
        ),
        day=sim.day,
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
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1
    sim.advance_days(1)
    relocation = lg.fleet_relocations[relocation_id]
    assert relocation.movement_execution_id is not None
    execution = lg.movement_executions[relocation.movement_execution_id]
    assert execution.started_day == 0
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
    assert lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO
    ).total_units == source_before - 2
    assert lg.fleet_pool(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT
    ).total_units == destination_before + 2


def test_releasing_uses_remaining_cycle_time_not_a_new_full_cycle():
    sim = _fleet_sim(2)
    lg = sim.transport
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=2,
        day=0,
    )
    allocation = lg.transport_allocations[allocation_id]
    cycle_days = int(math.ceil(lg.derive_transport_service_plan(allocation_id, 0).cycle_days))
    allocation.last_operated_day = 2
    lg.update_transport_allocation(allocation_id, target_units=1, day=3)
    release = next(iter(lg.fleet_releases.values()))
    assert release.release_day == 2 + cycle_days

    # If the last operated cycle has already completed, reducing the target
    # frees the unit immediately instead of starting an artificial new cycle.
    lg.advance_fleet_state(release.release_day)
    allocation.last_operated_day = 2
    lg.update_transport_allocation(allocation_id, target_units=0, day=release.release_day)
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

    allocation_id = lg.create_transport_allocation(
        vehicle_id, ids.LEO, ids.LUNAR_ORBIT, target_units=2, day=0
    )
    lg.transport_allocations[allocation_id].last_operated_day = 2
    sim.day = 3
    lg.update_transport_allocation(allocation_id, target_units=1, day=sim.day)
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
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT,
        target_units=1, day=0,
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
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=1,
        day=0,
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
    sim.logistics.set_supply_policy(
        ids.LUNAR_ORBIT, ids.MACHINERY, preferred_source_id=ids.LEO
    )
    target_id = sim.logistics.set_target_stock(
        ids.LUNAR_ORBIT, ids.MACHINERY, cargo_amount, 5
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
    assert decision.allocations.execution.allocated(dispatch.cargo_claim_id) == pytest.approx(
        cargo_amount / 2.0
    )
    assert decision.allocations.resources.allocated(dispatch.cargo_claim_id) == pytest.approx(
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

def test_relocation_waits_for_common_execution_allocation_before_departure():
    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.stock[(ids.LEO, ids.PROPELLANT)] = 0.0

    relocation_id = lg.relocate_fleet(
        ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, ids.LUNAR_ORBIT, day=sim.day
    )
    relocation = lg.fleet_relocations[relocation_id]
    required = sum(
        need.required_t for need in relocation.resource_needs
        if need.operational_node_id == ids.LEO and need.resource_id == ids.PROPELLANT
    )
    assert required > 0.0

    # Exercise the canonical daily allocation path rather than the retired
    # ResourceClaim-only allocator.  Without common execution allocation the
    # relocation remains pending and consumes nothing.
    sim.advance_days(1)
    assert relocation.movement_execution_id is None
    assert sim.inventory.amount(ids.LEO, ids.PROPELLANT) == pytest.approx(0.0)

    sim.inventory.add(ids.LEO, ids.PROPELLANT, required)
    departure_day = sim.day
    sim.advance_days(1)

    assert relocation.movement_execution_id is not None
    execution = lg.movement_executions[relocation.movement_execution_id]
    assert execution.started_day == departure_day
    assert execution.completion_day == departure_day + execution.latency_days
    assert sim.inventory.amount(ids.LEO, ids.PROPELLANT) == pytest.approx(0.0)
