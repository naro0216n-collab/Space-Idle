import pytest
from dataclasses import replace

from space_idle import GetFleet, build_game_application
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content import base_ids as ids
from space_idle.shared import EntityId, RouteId
from space_idle.site import CapabilityRequirement, SiteRequirements
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
    sim.logistics.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = count
    return sim


def test_fleet_free_is_derived_from_exclusive_commitments():
    sim = _fleet_sim(5)
    lg = sim.logistics
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
    assert lg.transport_allocations[allocation_id].active_units == 3
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1


def test_allocation_priority_is_deterministic_and_preserves_unfilled_target():
    sim = _fleet_sim(3)
    lg = sim.logistics
    low = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        priority=10,
        target_units=3,
        day=sim.day,
    )
    high = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        priority=100,
        target_units=2,
        day=sim.day,
    )
    # No service has operated yet in this simulation day, so reprioritization is
    # a pure allocation edit and can be settled without a recovery delay.
    assert lg.transport_allocations[low].target_units == 3
    assert lg.transport_allocations[low].active_units == 1
    assert lg.transport_allocations[high].active_units == 2
    assert not lg.fleet_releases
    snapshot = lg.transport_capacity_snapshot(low, day=sim.day)
    assert snapshot.required_units == 3
    assert snapshot.unfilled_units == 2
    assert "fleet_unfilled:2" in snapshot.blockers


def test_capacity_mode_uses_nominal_not_available_capacity_for_required_units():
    sim = _fleet_sim(8)
    lg = sim.logistics
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        control_mode=TransportControlMode.CAPACITY,
        target_units=None,
        target_capacity=DirectionalCapacity(2.0, 1.0),
        day=sim.day,
    )
    plan = lg.derive_transport_service_plan(allocation_id, sim.day)
    expected = 2  # ceil(max(2/1.09..., 1/1.09...))
    assert plan.nominal_per_unit.forward_t_per_day > 1.0
    assert lg.allocation_required_units(allocation_id, sim.day) == expected
    snap = lg.transport_capacity_snapshot(allocation_id, day=sim.day)
    # Base content currently lacks the servicing/propellant needed at LEO, so
    # Available may be zero without changing the required fleet size.
    assert snap.required_units == expected


def test_bidirectional_capacity_does_not_add_directional_unit_requirements():
    sim = _fleet_sim(10)
    lg = sim.logistics
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        control_mode=TransportControlMode.CAPACITY,
        target_units=None,
        target_capacity=DirectionalCapacity(3.0, 3.0),
        day=sim.day,
    )
    plan = lg.derive_transport_service_plan(allocation_id, sim.day)
    per_unit = plan.nominal_per_unit.forward_t_per_day
    assert per_unit == plan.nominal_per_unit.reverse_t_per_day
    assert lg.allocation_required_units(allocation_id, sim.day) == 3


def test_units_capacity_mode_switch_preserves_unfilled_authoritative_target():
    sim = _fleet_sim(3)
    lg = sim.logistics
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=5,
        day=sim.day,
    )
    before = lg.transport_allocations[allocation_id]
    assert before.target_units == 5
    assert before.active_units == 3
    per_unit = lg.derive_transport_service_plan(allocation_id, sim.day).nominal_per_unit

    lg.change_transport_allocation_mode(
        allocation_id, TransportControlMode.CAPACITY, day=sim.day
    )
    converted = lg.transport_allocations[allocation_id]
    assert converted.target_units is None
    assert converted.target_capacity == DirectionalCapacity(
        per_unit.forward_t_per_day * 5,
        per_unit.reverse_t_per_day * 5,
    )
    assert lg.allocation_required_units(allocation_id, sim.day) == 5


def test_units_capacity_mode_switch_has_one_authoritative_target():
    sim = _fleet_sim(5)
    lg = sim.logistics
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=2,
        day=sim.day,
    )
    lg.change_transport_allocation_mode(
        allocation_id, TransportControlMode.CAPACITY, day=sim.day
    )
    allocation = lg.transport_allocations[allocation_id]
    assert allocation.target_units is None
    assert allocation.target_capacity is not None
    lg.change_transport_allocation_mode(
        allocation_id, TransportControlMode.UNITS, day=sim.day
    )
    allocation = lg.transport_allocations[allocation_id]
    assert allocation.target_capacity is None
    assert allocation.target_units == 2


def test_relocation_requires_operational_support_and_propellant():
    sim = _fleet_sim(1)
    lg = sim.logistics
    try:
        lg.relocate_fleet(
            ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, ids.LUNAR_ORBIT, day=0
        )
    except ValueError as exc:
        assert "refueling" in str(exc) or "resource" in str(exc)
    else:
        raise AssertionError("relocation unexpectedly ignored operational requirements")


def test_resource_support_uses_definition_capability_instead_of_magic_refueling_id():
    sim = _fleet_sim(1)
    lg = sim.logistics
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
    lg = sim.logistics
    lg.external_services.clear()
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

    route_id = RouteId("base.route.leo_lunar_orbit")
    route = lg.routes[route_id]
    lg.routes[route_id] = replace(
        route,
        origin_requirements=SiteRequirements(
            route.origin_requirements.environment,
            (CapabilityRequirement("research_lab", 0.01, "available"),),
        ),
    )
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
    lane_id = lg.create_lane(ids.LEO, ids.LUNAR_ORBIT, 1.0, 50)
    lane = next(row for row in lg.lane_snapshot((), sim.day).lanes if row.lane_id == lane_id)
    assert lane.effective_capacity_t_per_day == 0


def test_multileg_operation_support_is_checked_at_actual_leg_endpoint():
    sim = _fleet_sim(1)
    lg = sim.logistics
    vehicle_id = ids.REUSABLE_SURFACE_CARGO_LANDER
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
                    "landing", OperationSupportLocation.ORIGIN, "cargo_transfer"
                ),
            ),
        ),
    )
    lg.fleet_pool(vehicle_id, ids.LEO).total_units = 1
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    allocation_id = lg.create_transport_allocation(
        vehicle_id,
        ids.LEO,
        ids.SOUTH_POLAR_RIDGE,
        target_units=1,
        path=(
            RouteId("base.route.leo_lunar_orbit"),
            RouteId("base.route.lunar_orbit_ridge"),
        ),
        day=sim.day,
    )
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=sim.day)

    assert snapshot.available.forward_t_per_day == 0
    assert f"infrastructure:{ids.LUNAR_ORBIT}:cargo_transfer" in snapshot.limiting_factors


def test_relocation_keeps_units_exclusive_until_arrival():
    sim = _fleet_sim(3)
    lg = sim.logistics
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 10.0)
    relocation_id = lg.relocate_fleet(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        2,
        ids.LEO,
        ids.LUNAR_ORBIT,
        day=0,
    )
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1
    lg.advance_fleet_state(4)
    assert relocation_id in lg.fleet_relocations
    lg.advance_fleet_state(5)
    assert relocation_id not in lg.fleet_relocations
    assert lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units == 1
    assert lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT).total_units == 2


def test_same_priority_allocation_result_does_not_depend_on_registration_order():
    def active_by_destination(destinations):
        sim = build_base_simulation()
        lg = sim.logistics
        lg.fleet_pool(ids.REUSABLE_SURFACE_CARGO_LANDER, ids.LEO).total_units = 1
        for destination in destinations:
            lg.create_transport_allocation(
                ids.REUSABLE_SURFACE_CARGO_LANDER,
                ids.LEO,
                destination,
                priority=50,
                target_units=1,
                day=0,
            )
        return {
            allocation.destination_id: allocation.active_units
            for allocation in lg.transport_allocations.values()
        }

    first = active_by_destination((ids.LUNAR_ORBIT, ids.SOUTH_POLAR_RIDGE))
    second = active_by_destination((ids.SOUTH_POLAR_RIDGE, ids.LUNAR_ORBIT))
    assert first == second


def test_same_priority_same_relation_with_different_targets_is_registration_order_independent():
    def active_by_target(targets):
        sim = _fleet_sim(2)
        lg = sim.logistics
        for target in targets:
            lg.create_transport_allocation(
                ids.REUSABLE_ORBITAL_CARGO_TUG,
                ids.LEO,
                ids.LUNAR_ORBIT,
                priority=50,
                target_units=target,
                day=0,
            )
        return {
            allocation.target_units: allocation.active_units
            for allocation in lg.transport_allocations.values()
        }

    assert active_by_target((1, 2)) == active_by_target((2, 1)) == {1: 1, 2: 1}


def test_releasing_uses_remaining_cycle_time_not_a_new_full_cycle():
    sim = _fleet_sim(2)
    lg = sim.logistics
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=2,
        day=0,
    )
    allocation = lg.transport_allocations[allocation_id]
    cycle_days = int(__import__('math').ceil(lg.derive_transport_service_plan(allocation_id, 0).cycle_days))
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


def test_fleet_query_exposes_releasing_units_and_recovery_time():
    app = build_game_application()
    sim = app._simulation
    lg = sim.logistics
    lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = 2
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=2,
        day=0,
    )
    allocation = lg.transport_allocations[allocation_id]
    allocation.last_operated_day = 2
    sim.day = 3
    lg.update_transport_allocation(allocation_id, target_units=1, day=sim.day)

    fleet = app.query(GetFleet())
    assert len(fleet.releases) == 1
    release = fleet.releases[0]
    assert release.allocation_id == str(allocation_id)
    assert release.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    assert release.location_id == str(ids.LEO)
    assert release.units == 1
    assert release.release_day > sim.day
    assert release.remaining_days == release.release_day - sim.day


def test_fleet_query_filters_transitional_state_with_pool_scope():
    app = build_game_application()
    sim = app._simulation
    lg = sim.logistics
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
    assert [row.allocation_id for row in leo.releases] == [str(allocation_id)]

    lunar_orbit = app.query(GetFleet(str(ids.LUNAR_ORBIT), str(vehicle_id)))
    assert [row.id for row in lunar_orbit.relocations] == [str(relocation_id)]
    assert lunar_orbit.releases == ()

    earth = app.query(GetFleet(str(ids.EARTH), str(vehicle_id)))
    assert earth.relocations == ()
    assert earth.releases == ()


def test_bidirectional_service_resource_use_counts_empty_return_not_loaded_return():
    sim = _fleet_sim(1)
    lg = sim.logistics
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
    actual = {(loc, rid): amount for loc, rid, amount in snapshot.operational_resource_demand}
    assert actual == pytest.approx(expected)
    assert snapshot.utilization == pytest.approx(1.0)


def test_resource_limited_available_capacity_uses_nominal_cycle_utilization():
    sim = _fleet_sim(1)
    lg = sim.logistics
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT,
        target_units=1, day=0,
    )
    plan = lg.derive_transport_service_plan(allocation_id, 0)
    empty = {(loc, rid): amount for loc, rid, amount in plan.resource_t_per_empty_cycle_day}
    forward_increment = {
        (loc, rid): amount
        for loc, rid, amount in plan.resource_t_per_forward_payload_increment_day
    }
    forward_full = {
        key: empty.get(key, 0.0) + forward_increment.get(key, 0.0)
        for key in set(empty) | set(forward_increment)
    }
    for (location_id, resource_id), amount in forward_full.items():
        sim.inventory.add(location_id, resource_id, amount / 2.0)

    available = lg.transport_capacity_snapshot(allocation_id, day=0)
    assert available.available.forward_t_per_day == pytest.approx(
        available.nominal.forward_t_per_day / 2.0
    )
    used = DirectionalCapacity(available.available.forward_t_per_day, 0.0)
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=0, used=used)
    assert snapshot.utilization == pytest.approx(0.5)
    actual = {(loc, rid): amount for loc, rid, amount in snapshot.operational_resource_demand}
    assert actual == pytest.approx({key: amount / 2.0 for key, amount in forward_full.items()})
