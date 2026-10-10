from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    ClearPopulationTarget, GetOperationalNode, PauseFacility, SetPopulationTarget,
    RequestPassengerTransfer, CancelPassengerTransfer, GetPassengerTransfers, GetPassengerTransferPreview,
    build_game_application,
)
from space_idle.app_contracts.population import PassengerCapacityChoice
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.site import evaluate_physical_site_requirements
from space_idle.population import PopulationRules


def test_population_life_support_and_resource_allocation_share_the_normal_day():
    app = build_game_application()
    sim = app._simulation
    initial_food = sim.inventory.amount(ids.EARTH, ids.FOOD)
    initial_water = sim.inventory.amount(ids.EARTH, ids.WATER)
    before = app.query(GetOperationalNode(str(ids.EARTH))).population
    assert before.current_count > 0
    assert before.life_support_required == before.current_count
    assert before.life_support_allocated == before.life_support_required
    assert before.housing_usable >= before.current_count
    assert sum(source.remaining_people for source in before.external_sources) > 0
    assert before.resource_demand_per_day

    sim.advance_days(1)
    after = app.query(GetOperationalNode(str(ids.EARTH))).population
    assert after.current_count == before.current_count
    assert after.deprivation_person_days == 0
    # Food is a normal Industry output, while inhabited Life Support consumes
    # an allocated Resource requirement exactly once.
    assert sim.inventory.amount(ids.EARTH, ids.FOOD) > initial_food
    empty_app = build_game_application()
    empty_app._simulation.population.groups.clear()
    empty_app._simulation.advance_days(1)
    assert sim.inventory.amount(ids.EARTH, ids.WATER) == pytest.approx(
        empty_app._simulation.inventory.amount(ids.EARTH, ids.WATER) - 0.06
    )

    farm = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == ids.FOOD_FARM)
    app.execute(PauseFacility(str(farm.id)))
    sim.inventory.stock[(ids.EARTH, ids.FOOD)] = 0.0
    population = sim.population
    sim.advance_days(1)
    group = population.groups_at(ids.EARTH)[0]
    assert group.deprivation == pytest.approx(1.0)
    assert population.crew_factor(group) < 1.0
    assert population.count_at(ids.EARTH) == before.current_count
    sim.advance_days(4)
    assert population.count_at(ids.EARTH) < before.current_count
    assert population.external_remaining == {source.id: source.remaining_people for source in before.external_sources}


def test_housing_is_physical_and_facility_removal_cannot_evict_people():
    app = build_game_application()
    sim = app._simulation
    housing = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == ids.EARTH_LIFE_SUPPORT)
    blockers = sim.projects.facility_lifecycle_registry.decommission_blockers(housing.id)
    assert any(row.code == 'population_housing' for row in blockers)
    before = sim.population.count_at(ids.EARTH)
    app.execute(PauseFacility(str(housing.id)))
    view = app.query(GetOperationalNode(str(ids.EARTH))).population
    assert view.housing_physical >= before
    assert view.housing_usable == 0
    assert view.life_support_allocated == 0
    sim.advance_days(1)
    assert sim.population.count_at(ids.EARTH) == before
    assert sim.population.groups_at(ids.EARTH)[0].deprivation > 0

    # An ambient oxygen provider is eligible by the physical atmosphere, not
    # by a planet ID; an artificial pressurized habitat supplies the alternative.
    ambient = sim.facilities.definitions[ids.EARTH_LIFE_SUPPORT]
    assert not evaluate_physical_site_requirements(
        ambient.operating_requirements, ids.EARTH, sim.day, sim.environment,
    )
    assert evaluate_physical_site_requirements(
        ambient.operating_requirements, ids.MOON_CELL_NEARSIDE_MARE, sim.day, sim.environment,
    )
    assert sim.facilities.definitions[ids.HABITAT].life_support is not None


def test_population_targets_sources_and_deprivation_are_single_save_state(tmp_path):
    app = build_game_application()
    sim = app._simulation
    node = str(ids.EARTH)
    original = sim.population.count_at(ids.EARTH)
    source = app.query(GetOperationalNode(node)).population.external_sources[0]
    quota = source.max_acquisition_per_day
    first_remaining = source.remaining_people
    app.execute(SetPopulationTarget(node, original + quota + 3))
    assert sim.population.count_at(ids.EARTH) == original

    # Acceptance occurs only at the next physical Boundary, with a finite
    # external source and a common per-day acquisition quota.
    sim.advance_days(1)
    view = app.query(GetOperationalNode(node)).population
    assert view.current_count == original + quota
    assert view.target_unmet_count == 3
    assert view.external_sources[0].remaining_people == first_remaining - quota
    assert view.external_sources[0].available_today == 0
    assert view.target_local_receivable == 0
    assert sim.population.count_at(ids.EARTH) + sim.population.external_remaining[source.id] == original + first_remaining

    path = tmp_path / 'population.json'
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert loaded.query(GetOperationalNode(node)).population.external_sources[0].available_today == 0

    # A second canonical day replenishes only the quota, not the finite source.
    sim.advance_days(1)
    loaded._simulation.advance_days(1)
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert app.query(GetOperationalNode(node)).population.current_count == original + quota + 3
    assert sim.population.external_remaining[source.id] == first_remaining - quota - 3
    assert app.query(GetOperationalNode(node)).population.external_sources[0].available_today == quota - 3

    # Clearing the intent does not remove people; an inoperable provider also
    # blocks further intake rather than minting population against an empty bed.
    app.execute(ClearPopulationTarget(node))
    assert app.query(GetOperationalNode(node)).population.desired_count is None
    app.execute(SetPopulationTarget(node, original + quota + 6))
    housing = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == ids.EARTH_LIFE_SUPPORT)
    app.execute(PauseFacility(str(housing.id)))
    prior_count = sim.population.count_at(ids.EARTH)
    sim.advance_days(1)
    view = app.query(GetOperationalNode(node)).population
    assert view.current_count == prior_count
    assert view.target_unmet_count == 3
    assert 'housing_full' in view.target_blockers
    assert view.deprivation_person_days > 0
    assert sim.population.external_remaining[source.id] == first_remaining - quota - 3


def test_one_shot_passengers_conserve_people_fleet_and_onboard_resource_through_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN):
        sim.inventory.add(ids.LEO, resource, 1.0)
    origin = str(ids.EARTH)
    destination = str(ids.LEO)
    preview = app.query(GetPassengerTransferPreview(origin, destination, 3))
    dedicated = next(option for option in preview.options
                     if option.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE))
    assert dedicated.dispatchable_people == 3
    assert dedicated.travel_days > 0

    total = sum(group.count for group in sim.population.groups.values())
    free_before = sim.transport.fleet_free_units(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    result = app.execute(RequestPassengerTransfer(
        origin, destination, 3,
        capacity_source_constraint=PassengerCapacityChoice(
            dedicated_vehicle_definition_id=str(ids.REUSABLE_LAUNCH_VEHICLE), dedicated_units=1,
        ),
    ))
    sim.advance_days(1)
    row = app.query(GetPassengerTransfers()).items[0]
    assert (row.pending_count, row.transit_count, row.delivered_count) == (0, 3, 0)
    assert sim.transport.fleet_free_units(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH) == free_before - 1
    movement = next(iter(sim.transport.movement_executions.values()))
    total_loaded = sum(item.amount_t for item in movement.payload_resources)
    assert total_loaded > 0
    initial_holds = app.query(GetPassengerTransfers()).items[0].cargo_holds
    assert len(initial_holds) == 1
    assert initial_holds[0].owner_ref == f'movement:{movement.id}'
    assert initial_holds[0].physical_node_id is None
    assert sum(amount for _, amount in initial_holds[0].resources) == pytest.approx(total_loaded)
    from space_idle.analysis_observation import observe_state
    measured = observe_state(sim, resource_ids=frozenset((ids.WATER,))).metrics
    onboard = [row for row in measured if row.kind == 'movement_payload_resource'
               and row.context_id == f'movement:{movement.id}']
    assert sum(row.quantity for row in onboard) == pytest.approx(
        sum(payload.amount_t for payload in movement.payload_resources
            if payload.resource_id == ids.WATER))
    assert not any(row.kind == 'movement_payload_resource' for row in observe_state(
        sim, operational_node_ids=frozenset((ids.LEO,)),
        resource_ids=frozenset((ids.WATER,))).metrics)

    saved = tmp_path / 'passengers.json'
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_game(app, saved, saved_at=fixed_time)
    loaded, _ = load_game(saved, build_game_application_for_load, now=fixed_time)
    assert capture_state(loaded._simulation) == capture_state(sim)
    sim.advance_days(1)
    loaded._simulation.advance_days(1)
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert sim.population.count_at(ids.EARTH) == total - 3
    sim.advance_days(1)
    loaded._simulation.advance_days(1)
    assert capture_state(loaded._simulation) == capture_state(sim)
    result_row = app.query(GetPassengerTransfers()).items[0]
    assert (result_row.pending_count, result_row.transit_count, result_row.delivered_count) == (0, 0, 3)
    assert sum(group.count for group in sim.population.groups.values()) == total
    assert sim.transport.fleet_free_units(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH) == free_before
    assert not sim.transport.movement_executions
    # Crew is a common Service at the physical Node, not a globally pooled
    # headcount or a permanent worker assignment.  A crewed laboratory draws
    # that finite daily Service from arrivals.
    laboratory = next(facility for facility in sim.facilities.all_at(ids.LEO)
                      if facility.definition_id == ids.CREWED_ORBITAL_LABORATORY)
    bundle = next(bundle for bundle in sim.research.generation_execution_bundles({}, sim.day)
                  if bundle.owner_id == laboratory.id)
    assert any(req.service_type == 'crew' and req.constraint_node_id == ids.LEO
               for req in bundle.requirements if hasattr(req, 'service_type'))
    assert sim.population.service_capacity_supply_at(ids.LEO, 'crew', sim.facilities, sim.power, sim.day)[0] >= 3

    # Cancellation affects only people who have not embarked.
    other = app.execute(RequestPassengerTransfer(origin, destination, 2))
    app.execute(CancelPassengerTransfer(other.created_id))
    cancelled = next(item for item in app.query(GetPassengerTransfers()).items if item.id == other.created_id)
    assert (cancelled.pending_count, cancelled.delivered_count, cancelled.cancelled_count) == (0, 0, 2)


def test_transport_service_passengers_share_mass_and_seats_and_survive_reload(tmp_path):
    app = build_game_application()
    sim = app._simulation
    transport = sim.transport
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN):
        sim.inventory.add(ids.LEO, resource, 2.0)
    capacity = transport.transport_capacity_for_units(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=sim.day)
    allocation = transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
        target_capacity=capacity, day=sim.day)
    transport.advance_fleet_state(sim.day)
    options = app.query(GetPassengerTransferPreview(str(ids.EARTH), str(ids.LEO), 2)).options
    service = next(row for row in options if row.mode == 'service')
    assert service.dispatchable_people > 0
    assert str(allocation) in service.transport_allocation_ids
    initial_people = sum(group.count for group in sim.population.groups.values())
    result = app.execute(RequestPassengerTransfer(str(ids.EARTH), str(ids.LEO), 2))
    sim.advance_days(1)
    order = sim.population.transfer_orders[next(iter(sim.population.transfer_orders))]
    assert order.transit_count(sim.population.groups) > 0
    assert transport.passenger_service_transits
    assert sum(group.count for group in sim.population.groups.values()) == initial_people

    assert transport.transport_active_units(allocation) > 0
    path = tmp_path / 'service.json'
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_game(app, path, saved_at=stamp)
    restored, _ = load_game(path, build_game_application_for_load, now=stamp)
    assert capture_state(restored._simulation) == capture_state(sim)
    for _ in range(5):
        sim.advance_days(1)
        restored._simulation.advance_days(1)
        assert capture_state(restored._simulation) == capture_state(sim)
    assert order.delivered_count == 2
    assert sim.population.count_at(ids.LEO) >= 2
    assert sum(group.count for group in sim.population.groups.values()) == initial_people


def test_competing_orders_share_arrival_space_and_service_transit_mortality_preserves_ownership(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    sim.population.initialize(ids.LEO, 7)  # One actual bed remains for both requests.
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN):
        sim.inventory.add(ids.LEO, resource, 2.0)
    capacity = sim.transport.transport_capacity_for_units(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=sim.day,
    )
    sim.transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
        target_capacity=capacity, day=sim.day,
    )
    sim.transport.advance_fleet_state(sim.day)
    for _ in range(2):
        app.execute(RequestPassengerTransfer(str(ids.EARTH), str(ids.LEO), 1))
    initial_total = sum(group.count for group in sim.population.groups.values())
    sim.advance_days(1)
    orders = tuple(sim.population.transfer_orders.values())
    on_board = sum(order.transit_count(sim.population.groups) for order in orders)
    assert on_board == 1  # Shared Housing admission pool, not one independent slot per Order.
    active = next(order for order in orders if order.in_transit_group_refs)
    for order in orders:
        if order is not active:
            app.execute(CancelPassengerTransfer(str(order.id)))

    # Make an actual onboard Life Support failure fatal. A dead Group cannot
    # remain as a manifest reference or silently become a new pending passenger.
    transit = next(iter(sim.transport.passenger_service_transits.values()))
    # Both Domain ownership directions must reconcile at a Save/Load boundary.
    # An Order still owning a person is invalid if Transport loses its manifest.
    from space_idle.population_domain import validate_runtime as validate_population_runtime
    passenger_manifest = transit.passenger_group_refs
    transit.passenger_group_refs = ()
    with pytest.raises(ValueError, match='matching Transport manifest'):
        validate_population_runtime(sim)
    transit.passenger_group_refs = passenger_manifest
    validate_population_runtime(sim)
    remaining_water = transit.onboard_resources[ids.WATER]
    destination_water = sim.inventory.amount(ids.LEO, ids.WATER)
    laboratory_spec = sim.facilities.definitions[ids.CREWED_ORBITAL_LABORATORY].life_support
    resident_water_per_day = sim.population.count_at(ids.LEO) * dict(laboratory_spec.net_resources)[ids.WATER]
    transit.onboard_resources[ids.FOOD] = 0.0
    sim.population.rules = PopulationRules(0.5, 100.0, 0.1, 4.0)
    sim.advance_days(1)
    assert active.deceased_count == 1
    assert (active.pending_count(sim.population.groups), active.transit_count(sim.population.groups),
            active.delivered_count, active.status(sim.population.groups)) == (0, 0, 0, 'completed')
    assert not sim.transport.passenger_service_transits
    assert sim.inventory.amount(ids.LEO, ids.WATER) == pytest.approx(destination_water - resident_water_per_day + remaining_water)
    assert sum(group.count for group in sim.population.groups.values()) == initial_total - 1
    sim.population.validate()

    path = tmp_path / 'passenger-deprivation.json'
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_game(app, path, saved_at=stamp)
    restored, _ = load_game(path, build_game_application_for_load, now=stamp)
    assert capture_state(restored._simulation) == capture_state(sim)


def test_population_target_dispatch_uses_finite_service_capacity_without_creating_orders(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN):
        sim.inventory.add(ids.LEO, resource, 2.0)
    capacity = sim.transport.transport_capacity_for_units(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=sim.day,
    )
    sim.transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
        target_capacity=capacity, day=sim.day,
    )
    sim.transport.advance_fleet_state(sim.day)
    app.execute(SetPopulationTarget(str(ids.LEO), 2))
    people = sum(group.count for group in sim.population.groups.values())
    sources = sum(sim.population.external_remaining.values())
    sim.advance_days(1)
    transits = list(sim.transport.passenger_service_transits.values())
    assert transits and all(transit.order_id is None for transit in transits)
    dispatched = sum(sum(sim.population.groups[ref].count for ref in transit.passenger_group_refs)
                     for transit in transits)
    assert 0 < dispatched <= 2
    assert not sim.population.transfer_orders
    assert sum(sim.population.external_remaining.values()) == sources - dispatched
    assert sum(group.count for group in sim.population.groups.values()) == people + dispatched
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    path = tmp_path / 'auto-target.json'
    save_game(app, path, saved_at=stamp)
    restored, _ = load_game(path, build_game_application_for_load, now=stamp)
    assert capture_state(restored._simulation) == capture_state(sim)
    for _ in range(8):
        sim.advance_days(1)
        restored._simulation.advance_days(1)
        assert capture_state(restored._simulation) == capture_state(sim)
    assert sim.population.count_at(ids.LEO) == 2
    assert not sim.transport.passenger_service_transits
    assert not sim.population.transfer_orders
    assert sum(group.count for group in sim.population.groups.values()) + sum(sim.population.external_remaining.values()) == people + sources


def test_population_target_prefers_available_owned_surplus_then_finite_external_people():
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN):
        sim.inventory.add(ids.LEO, resource, 3.0)
    capacity = sim.transport.transport_capacity_for_units(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=sim.day,
    )
    sim.transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
        target_capacity=capacity, day=sim.day,
    )
    sim.transport.advance_fleet_state(sim.day)
    current = sim.population.count_at(ids.EARTH)
    app.execute(SetPopulationTarget(str(ids.EARTH), current - 1))
    app.execute(SetPopulationTarget(str(ids.LEO), 2))
    demands = sim.population._automatic_passenger_demands(sim.day)
    owned = [row for row in demands if row.source_external_provider_id is None]
    external = [row for row in demands if row.source_external_provider_id is not None]
    assert sum(row.requested_count for row in owned) == 1
    assert sum(row.requested_count for row in external) == 1
    initial_total = (sum(group.count for group in sim.population.groups.values())
                     + sum(sim.population.external_remaining.values()))
    sim.advance_days(1)
    assert sim.population.count_at(ids.EARTH) >= current - 1
    assert (sum(group.count for group in sim.population.groups.values())
            + sum(sim.population.external_remaining.values())) == initial_total
    assert all(group.activity_commitment_ref is None
               for group in sim.population.groups.values())

@pytest.mark.parametrize('dedicated', [False, True])
def test_arrived_passengers_disembark_before_leftover_stock_is_admitted(tmp_path, monkeypatch, dedicated):
    """Arrival holding retains actual cargo/Fleet without holding already admitted people."""
    app = build_game_application()
    sim = app._simulation
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN):
        sim.inventory.add(ids.LEO, resource, 2.0)
    if not dedicated:
        capacity = sim.transport.transport_capacity_for_units(
            ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=sim.day,
        )
        sim.transport.create_transport_allocation(
            ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO,
            target_capacity=capacity, day=sim.day,
        )
        sim.transport.advance_fleet_state(sim.day)
    app.execute(RequestPassengerTransfer(
        str(ids.EARTH), str(ids.LEO), 1,
        capacity_source_constraint=(PassengerCapacityChoice(
            dedicated_vehicle_definition_id=str(ids.REUSABLE_LAUNCH_VEHICLE), dedicated_units=1,
        ) if dedicated else None),
    ))
    sim.advance_days(1)
    order = next(iter(sim.population.transfer_orders.values()))
    assert order.transit_count(sim.population.groups) == 1
    transit = (next(iter(sim.transport.movement_executions.values())) if dedicated
               else next(iter(sim.transport.passenger_service_transits.values())))
    # Model an already-loaded surplus from the same finite Inventory.  A
    # normal transfer carries just its planned life-support demand, but the
    # arrival boundary must also conserve legitimate leftover onboard Stock.
    surplus = 0.01
    sim.inventory.stock[(ids.EARTH, ids.WATER)] -= surplus
    if dedicated:
        from space_idle.transport.models import MovementExecutionPayloadResource
        transit.payload_resources = tuple(
            MovementExecutionPayloadResource(row.resource_id, row.amount_t + (surplus if row.resource_id == ids.WATER else 0))
            for row in transit.payload_resources
        )
    else:
        transit.onboard_resources[ids.WATER] += surplus
        from space_idle.analysis_observation import observe_state
        onboard = [row for row in observe_state(sim, resource_ids=frozenset((ids.WATER,))).metrics
                   if row.kind == 'passenger_service_onboard_resource']
        assert len(onboard) == 1
        assert onboard[0].context_id == f'passenger_transit:{transit.id}'
        assert onboard[0].quantity == pytest.approx(transit.onboard_resources[ids.WATER])
        assert not any(row.kind == 'passenger_service_onboard_resource' for row in observe_state(
            sim, operational_node_ids=frozenset((ids.LEO,)),
            resource_ids=frozenset((ids.WATER,))).metrics)
    arrival = transit.completion_day if dedicated else transit.arrival_day
    recovery_node = (ids.EARTH if dedicated else ids.LEO)
    previous_admit = sim.inventory.can_admit_resources
    monkeypatch.setattr(sim.inventory, 'can_admit_resources',
                        lambda node, resources: False if node == recovery_node else previous_admit(node, resources))
    while sim.day < arrival:
        sim.advance_days(1)
    assert order.delivered_count == 1
    assert not order.in_transit_group_refs
    assert sim.population.count_at(ids.LEO) >= 1
    if dedicated:
        assert not sim.transport.movement_executions
        commitment = sim.transport.fleet_commitments[sim.population._passenger_commitment_id(order.id)]
        assert commitment.operational_node_id == recovery_node
        assert sum(commitment.onboard_resources.values()) > 0
    else:
        still_held = next(iter(sim.transport.passenger_service_transits.values()))
        assert not still_held.passenger_group_refs
        assert sum(still_held.onboard_resources.values()) > 0

    holds = next(row for row in app.query(GetPassengerTransfers()).items
                 if row.id == str(order.id)).cargo_holds
    assert len(holds) == 1
    assert holds[0].physical_node_id == str(recovery_node)
    assert 'storage_admission_unavailable' in holds[0].blockers
    assert sum(amount for _, amount in holds[0].resources) >= surplus - 1e-9

    saved = tmp_path / 'unloaded-after-disembark.json'
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_game(app, saved, saved_at=stamp)
    restored, _ = load_game(saved, build_game_application_for_load, now=stamp)
    assert capture_state(restored._simulation) == capture_state(sim)
    monkeypatch.setattr(sim.inventory, 'can_admit_resources', previous_admit)
    from space_idle.analysis_execution import observe_canonical_day
    stock_before = {(str(node), str(resource)): quantity
                    for (node, resource), quantity in sim.inventory.stock.items()}
    with observe_canonical_day(sim) as trace:
        sim.advance_days(1)
    restored._simulation.advance_days(1)
    assert capture_state(restored._simulation) == capture_state(sim)
    # Unloading real onboard Resource is one known custody source, not a
    # second production event or an unexplained Inventory inflow. Both the
    # dedicated Fleet and aggregate passenger-service routes use the same
    # authoritative Inventory settlement and observation contract.
    activity_prefix = 'fleet_provisions_recovery:' if dedicated else 'passenger_service_arrival:'
    source_prefix = 'fleet_commitment:' if dedicated else 'passenger_transit:'
    unloaded = [flow for flow in trace.activity_flows()
                if flow.activity_id.startswith(activity_prefix)
                and flow.resource_id == str(ids.WATER)]
    assert unloaded
    assert all(flow.source_owner.startswith(source_prefix)
               and flow.destination_owner == f'inventory:{recovery_node}'
               for flow in unloaded)
    assert sum(row.quantity_t for row in unloaded) >= surplus - 1e-9
    stock_after = {(str(node), str(resource)): quantity
                   for (node, resource), quantity in sim.inventory.stock.items()}
    assert all(abs(row['unattributed_delta_t']) < 1e-7
               for row in trace.reconcile(stock_before, stock_after))
    assert not sim.transport.passenger_service_transits
    assert not next(row for row in app.query(GetPassengerTransfers()).items
                    if row.id == str(order.id)).cargo_holds
    assert sim.population._passenger_commitment_id(order.id) not in sim.transport.fleet_commitments


def test_passenger_intermediate_service_handoff_waits_in_real_cabin_and_preserves_people(monkeypatch):
    from types import SimpleNamespace
    from space_idle.population import ExternalPopulationSourceDefinition
    from space_idle.transport.models import PassengerAccommodation, PassengerServiceLeg, PassengerServiceTransit
    from space_idle.shared import EntityId, DefinitionId

    app = build_game_application()
    sim = app._simulation
    pop = sim.population
    source = pop.groups_at(ids.EARTH)[0]
    passenger = pop._split_group(source, 1)
    transit_id = EntityId('test.passenger.legchain')
    pop.move_group_to_execution(passenger.id, transit_id)
    cabin = PassengerAccommodation(2, 0.1, 2.0, 2.0, 0.05, ((ids.WATER, 0.01),))
    allocation = EntityId('test.passenger.allocation')
    first = PassengerServiceLeg('first', allocation, ids.EARTH, ids.LEO, 1, cabin, 0.15)
    second = PassengerServiceLeg('second', allocation, ids.LEO, ids.EARTH, 1, cabin, 0.15)
    pop.inventory.consume_allocated(ids.EARTH, ids.WATER, 0.03)
    transit = PassengerServiceTransit(transit_id, None, (passenger.id,), (first, second), sim.day,
                                     sim.day, {ids.WATER: 0.03})
    sim.transport.passenger_service_transits[transit_id] = transit
    monkeypatch.setattr(sim.transport, 'transport_service_supplies', lambda day: ())
    pop.settle_transit_arrivals(sim.day + 1)
    assert transit.handoff_wait_days == [1]
    assert transit.active_leg(sim.day + 2) == first
    assert pop.groups[passenger.id].position.ref == str(transit_id)
    assert transit.onboard_resources[ids.WATER] == pytest.approx(0.02)

    supply = SimpleNamespace(key='second', source_id=ids.LEO, destination_id=ids.EARTH,
                             capacity_t_per_day=0.2)
    monkeypatch.setattr(sim.transport, 'transport_service_supplies', lambda day: (supply,))
    pop.settle_transit_arrivals(sim.day + 2)
    assert transit.handoff_wait_days == [1]
    assert transit.active_leg(sim.day + 3) == second
    pop.settle_transit_arrivals(sim.day + 3)
    assert transit_id not in sim.transport.passenger_service_transits
    assert pop.count_at(ids.EARTH) == 30
    assert pop.groups[passenger.id].position.ref == str(ids.EARTH)
    assert pop.inventory.amount(ids.EARTH, ids.WATER) > 0


def test_external_population_eligibility_is_derived_from_existing_research():
    from space_idle.population import ExternalPopulationSourceDefinition
    app = build_game_application()
    sim = app._simulation
    pop = sim.population
    source_id = next(iter(pop.external_definitions))
    before = pop.external_definitions[source_id]
    tech = next(iter(sim.research.definitions))
    pop.external_definitions[source_id] = ExternalPopulationSourceDefinition(
        before.id, before.operational_node_id, before.initial_people,
        before.max_acquisition_per_day, (tech,),
    )
    completed = tech in sim.technology.completed
    if completed:
        sim.technology.completed.remove(tech)
    assert pop.external_available(source_id, sim.day) == 0
    sim.technology.completed.add(tech)
    assert pop.external_available(source_id, sim.day) > 0
