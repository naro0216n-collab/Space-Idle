import pytest
from dataclasses import FrozenInstanceError, replace

from space_idle import GetFleet, build_game_application
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content import base_ids as ids
from space_idle.shared import EntityId, RouteId, SpatialNodeId
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



def _transport_service_allocations(sim, day, plan):
    requests = sim.transport.transport_service_capacity_requests(day, plan.planned_usage)
    locations = sim._active_locations() | set(sim.graph.operational_node_ids())
    powers = {
        location_id: sim.power.snapshot(location_id, sim.facilities, day)
        for location_id in locations
    }
    return sim._allocate_tick_services(powers, requests)



def test_transport_fleet_commitment_is_owned_by_fleet_reservation():
    sim = _fleet_sim(2)
    lg = sim.transport
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=2,
        day=sim.day,
    )

    allocation = lg.transport_allocations[allocation_id]
    reservations = [
        row for row in lg.fleet_reservation_snapshots()
        if row.kind is FleetReservationKind.TRANSPORT and row.owner_id == allocation_id
    ]

    assert len(reservations) == 1
    assert reservations[0].units == 2
    assert reservations[0].vehicle_definition_id == allocation.vehicle_definition_id
    assert reservations[0].operational_node_id == allocation.anchor_node_id
    assert lg.fleet_pool_snapshot(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).transport_units == 2


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


def test_fleet_free_is_derived_from_exclusive_commitments():
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
    assert lg.transport_active_units(allocation_id) == 3
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 1


def test_adding_fleet_units_immediately_refills_existing_transport_target():
    sim = _fleet_sim(1)
    lg = sim.transport
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=2,
        day=sim.day,
    )
    assert lg.transport_active_units(allocation_id) == 1

    lg.add_fleet_units(
        ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, day=sim.day
    )

    assert lg.transport_active_units(allocation_id) == 2
    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 0


def test_releasing_fleet_reservation_immediately_refills_transport_target():
    sim = _fleet_sim(3)
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


def test_fleet_free_read_does_not_materialize_an_empty_pool():
    sim = build_base_simulation()
    lg = sim.transport
    before = dict(lg.fleet_pools)

    assert lg.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, SpatialNodeId("test.location.absent")) == 0
    assert lg.fleet_pools == before


def test_fleet_snapshot_read_does_not_materialize_an_empty_pool():
    sim = build_base_simulation()
    lg = sim.transport
    before = dict(lg.fleet_pools)

    snapshot = lg.fleet_pool_snapshot(
        ids.REUSABLE_ORBITAL_CARGO_TUG, SpatialNodeId("test.location.absent")
    )
    assert snapshot.total_units == 0
    assert snapshot.free_units == 0
    assert lg.fleet_pools == before


def test_fleet_reservation_queries_return_read_only_snapshots_in_stable_order():
    sim = _fleet_sim(3)
    lg = sim.transport
    later = EntityId("reservation.zeta")
    earlier = EntityId("reservation.alpha")
    for reservation_id, owner_id in (
        (later, EntityId("owner.zeta")),
        (earlier, EntityId("owner.alpha")),
    ):
        lg.reserve_fleet_units(
            reservation_id,
            owner_id,
            FleetReservationKind.OTHER,
            ids.REUSABLE_ORBITAL_CARGO_TUG,
            ids.LEO,
            1,
        )

    snapshots = lg.fleet_reservation_snapshots()
    assert tuple(row.id for row in snapshots) == (earlier, later)
    assert lg.fleet_reservation_snapshot(earlier) == snapshots[0]
    assert lg.fleet_reservation_snapshot(EntityId("reservation.missing")) is None
    with pytest.raises(FrozenInstanceError):
        snapshots[0].units = 2


def test_fleet_query_exposes_generic_other_reservations_without_hiding_commitments():
    app = build_game_application()
    sim = app._simulation
    lg = sim.transport
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    lg.fleet_pool(vehicle_id, ids.LEO).total_units = 2
    lg.reserve_fleet_units(
        EntityId("reservation.other"),
        EntityId("special.owner"),
        FleetReservationKind.OTHER,
        vehicle_id,
        ids.LEO,
        1,
    )

    row = next(
        item for item in app.query(GetFleet()).pools
        if item.vehicle_definition_id == str(vehicle_id)
        and item.operational_node_id == str(ids.LEO)
    )
    assert row.total_units == 2
    assert row.free_units == 1
    assert row.other_reserved_units == 1


def test_allocation_priority_is_deterministic_and_preserves_unfilled_target():
    sim = _fleet_sim(3)
    lg = sim.transport
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
    assert lg.transport_active_units(low) == 1
    assert lg.transport_active_units(high) == 2
    assert not lg.fleet_releases
    snapshot = lg.transport_capacity_snapshot(low, day=sim.day)
    assert snapshot.required_units == 3
    assert snapshot.unfilled_units == 2
    assert "fleet_unfilled:2" in snapshot.blockers


def test_capacity_mode_rejects_target_in_a_direction_without_nominal_service():
    sim = build_base_simulation()
    lg = sim.transport
    before_counter = lg._transport_allocation_counter
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
    assert lg._transport_allocation_counter == before_counter


def test_capacity_mode_update_rolls_back_an_unsupported_directional_target():
    sim = build_base_simulation()
    lg = sim.transport
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


def test_capacity_mode_uses_nominal_not_available_capacity_for_required_units():
    sim = _fleet_sim(8)
    lg = sim.transport
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
    lg = sim.transport
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
    lg = sim.transport
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        ids.LEO,
        ids.LUNAR_ORBIT,
        target_units=5,
        day=sim.day,
    )
    before = lg.transport_allocations[allocation_id]
    assert before.target_units == 5
    assert lg.transport_active_units(allocation_id) == 3
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
    lg = sim.transport
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
    assert relocation.arrival_day is None
    for row in plan.resource_requirements:
        assert lg.inventory.available(row.operational_node_id, row.resource_id) == pytest.approx(
            before[(row.operational_node_id, row.resource_id)]
        )

    sim.advance_days(1)
    relocation = lg.fleet_relocations[relocation_id]
    assert relocation.departure_day == 0
    assert relocation.arrival_day == plan.arrival_day
    for row in plan.resource_requirements:
        assert lg.inventory.available(row.operational_node_id, row.resource_id) == pytest.approx(
            before[(row.operational_node_id, row.resource_id)] - row.required_t
        )




def test_tick_boundary_cargo_arrival_can_fund_relocation_before_allocation():
    from space_idle.resource_claim import allocate_resource_claims
    from space_idle.resource_demand import ResourceDemand

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

    lane_id = sim.logistics.create_lane(ids.EARTH, ids.LEO, required, 100)
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=tuple(lg.external_services),
        day=sim.day,
    )
    sim.inventory.add(ids.EARTH, ids.PROPELLANT, required)
    demand = ResourceDemand(
        EntityId("demand.boundary-relocation-propellant"),
        "test",
        EntityId("owner.boundary-relocation-propellant"),
        ids.LEO,
        ids.PROPELLANT,
        required,
        100,
        ids.EARTH,
    )
    plan = sim.logistics.plan_capacity_logistics(0, (demand,))
    funds = sim.external_economy.allocate(plan.spending_requests, 0)
    plan = sim.logistics.authorize_capacity_logistics(plan, funds, 0)
    allocations = allocate_resource_claims(plan.claims, sim.inventory)
    services = _transport_service_allocations(sim, 0, plan)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        0, plan, allocations, services
    )
    sim.logistics.advance_capacity_logistics(
        0, plan, funds, execution
    )
    flow = next(
        row for row in sim.logistics.cargo_flows.values()
        if row.lane_id == lane_id and row.demand_id == demand.id
    )
    assert flow.ready_day > 0

    # Prevent the normal planner from creating another shipment while time moves
    # to the boundary where this seeded Cargo Flow becomes ready.
    sim.logistics.lanes[lane_id].paused = True
    lg.external_services.clear()
    sim.advance_to_day(flow.ready_day)
    assert relocation.departure_day is None
    assert sim.inventory.available(ids.LEO, ids.PROPELLANT) == pytest.approx(0.0)

    sim.advance_days(1)

    assert relocation.departure_day == flow.ready_day
    assert relocation.arrival_day == flow.ready_day + relocation.travel_days
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
            (CapabilityRequirement("research_lab", CapabilityRequirementState.ACTIVE),),
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
    lane_id = sim.logistics.create_lane(ids.LEO, ids.LUNAR_ORBIT, 1.0, 50)
    lane = next(row for row in sim.logistics.lane_snapshot((), sim.day).lanes if row.lane_id == lane_id)
    assert lane.effective_capacity_t_per_day == 0


def test_multileg_operation_support_is_checked_at_actual_leg_endpoint():
    sim = _fleet_sim(1)
    lg = sim.transport
    vehicle_id = ids.REUSABLE_SURFACE_CARGO_LANDER
    target_id = __import__('space_idle.shared', fromlist=['SpatialNodeId']).SpatialNodeId("test.location.landing_support")
    sim.graph.found_location(target_id, "Target", ids.MOON, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, target_id)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, target_id, site_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS)
    lg.synchronize_surface_access_routes()
    landing_route = next(
        route_id for route_id, route in lg.routes.items()
        if route.origin_id == ids.LUNAR_ORBIT and route.destination_id == target_id
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
        path=(RouteId("base.route.leo_lunar_orbit"), landing_route), day=sim.day,
    )
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert snapshot.available.forward_t_per_day == 0
    assert f"infrastructure:{ids.LUNAR_ORBIT}:research_lab" in snapshot.limiting_factors


def test_relocation_keeps_units_exclusive_until_arrival():
    sim = _fleet_sim(3)
    lg = sim.transport
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
    sim.advance_days(1)
    assert lg.fleet_relocations[relocation_id].departure_day == 0
    lg.advance_fleet_state(4)
    assert relocation_id in lg.fleet_relocations
    lg.advance_fleet_state(5)
    assert relocation_id not in lg.fleet_relocations
    assert lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units == 1
    assert lg.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT).total_units == 2


def test_same_priority_allocation_result_does_not_depend_on_registration_order():
    def active_by_destination(destinations):
        sim = build_base_simulation()
        lg = sim.transport
        target_id = __import__('space_idle.shared', fromlist=['SpatialNodeId']).SpatialNodeId("test.location.registration_order")
        sim.graph.found_location(target_id, "Target", ids.MOON, ids.MOON_CELL_FARSIDE_HIGHLANDS)
        sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, target_id)
        sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, target_id, site_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS)
        lg.synchronize_surface_access_routes()
        lg.fleet_pool(ids.REUSABLE_SURFACE_CARGO_LANDER, ids.LUNAR_ORBIT).total_units = 1
        actual = [ids.LEO if d == "leo" else target_id for d in destinations]
        for destination in actual:
            lg.create_transport_allocation(
                ids.REUSABLE_SURFACE_CARGO_LANDER, ids.LUNAR_ORBIT, destination,
                priority=50, target_units=1, day=0,
            )
        return {str(a.destination_id): lg.transport_active_units(a.id) for a in lg.transport_allocations.values()}

    first = active_by_destination(("leo", "surface"))
    second = active_by_destination(("surface", "leo"))
    assert first == second


def test_same_priority_same_relation_with_different_targets_is_registration_order_independent():
    def active_by_target(targets):
        sim = _fleet_sim(2)
        lg = sim.transport
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
            allocation.target_units: lg.transport_active_units(allocation.id)
            for allocation in lg.transport_allocations.values()
        }

    assert active_by_target((1, 2)) == active_by_target((2, 1)) == {1: 1, 2: 1}


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
    lg = sim.transport
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
    assert release.operational_node_id == str(ids.LEO)
    assert release.units == 1
    assert release.release_day > sim.day
    assert release.remaining_days == release.release_day - sim.day


def test_fleet_query_filters_transitional_state_with_pool_scope():
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
    assert [row.allocation_id for row in leo.releases] == [str(allocation_id)]

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
    actual = {(loc, rid): amount for loc, rid, amount in snapshot.operational_resource_demand}
    assert actual == pytest.approx(expected)
    assert snapshot.utilization == pytest.approx(1.0)


def test_resource_limited_available_capacity_uses_shared_allocation_and_nominal_utilization():
    from space_idle.resource_claim import allocate_resource_claims
    from space_idle.resource_demand import ResourceDemand

    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    allocation_id = lg.create_transport_allocation(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT,
        target_units=1, day=0,
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
        stocked = sim.inventory.available(location_id, resource_id)
        if stocked > 0:
            sim.inventory.consume_allocated(location_id, resource_id, stocked)
        sim.inventory.add(location_id, resource_id, amount / 2.0)

    lane_id = sim.logistics.create_lane(
        ids.LEO, ids.LUNAR_ORBIT, physical.nominal.forward_t_per_day, 100
    )
    cargo_amount = physical.nominal.forward_t_per_day
    sim.inventory.add(ids.LEO, ids.MACHINERY, cargo_amount)
    demand = ResourceDemand(
        EntityId("demand.shared-transport-resource"),
        "test",
        EntityId("owner.shared-transport-resource"),
        ids.LUNAR_ORBIT,
        ids.MACHINERY,
        cargo_amount,
        100,
        ids.LEO,
    )
    raw = sim.logistics.plan_capacity_logistics(0, (demand,))
    funds = sim.external_economy.allocate(raw.spending_requests, 0)
    logistics_plan = sim.logistics.authorize_capacity_logistics(raw, funds, 0)
    resources = allocate_resource_claims(logistics_plan.claims, sim.inventory)
    services = _transport_service_allocations(sim, 0, logistics_plan)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        0, logistics_plan, resources, services
    )
    available = sim.logistics.current_transport_capacity_snapshot(
        allocation_id,
        day=0,
        execution_allocation=execution,
    )
    assert available.available.forward_t_per_day == pytest.approx(
        available.nominal.forward_t_per_day / 2.0
    )
    assert any(
        value.startswith("resource_allocation:")
        for value in available.limiting_factors
    )

    used = DirectionalCapacity(available.available.forward_t_per_day, 0.0)
    snapshot = lg.transport_capacity_snapshot(allocation_id, day=0, used=used)
    assert snapshot.utilization == pytest.approx(0.5)
    actual = {
        (loc, rid): amount
        for loc, rid, amount in snapshot.operational_resource_demand
    }
    assert actual == pytest.approx(
        {key: amount / 2.0 for key, amount in forward_full.items()}
    )
    assert lane_id in sim.logistics.lanes


def test_relocation_waits_for_shared_resource_claim_allocation_before_departure():
    from space_idle.resource_claim import allocate_resource_claims

    sim = _fleet_sim(1)
    lg = sim.transport
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.stock[(ids.LEO, ids.PROPELLANT)] = 0.0

    relocation_id = lg.relocate_fleet(
        ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, ids.LUNAR_ORBIT, day=0
    )
    relocation = lg.fleet_relocations[relocation_id]
    claims = lg.fleet_relocation_resource_claims(0)
    assert claims
    empty = allocate_resource_claims(claims, sim.inventory)
    lg.advance_fleet_relocations(empty, 0)
    assert relocation.departure_day is None

    required = sum(
        need.required_t for need in relocation.resource_needs
        if need.operational_node_id == ids.LEO and need.resource_id == ids.PROPELLANT
    )
    sim.inventory.add(ids.LEO, ids.PROPELLANT, required)
    funded = allocate_resource_claims(lg.fleet_relocation_resource_claims(0), sim.inventory)
    lg.advance_fleet_relocations(funded, 0)

    assert relocation.departure_day == 0
    assert relocation.arrival_day == relocation.travel_days
    assert sim.inventory.amount(ids.LEO, ids.PROPELLANT) == pytest.approx(0.0)
