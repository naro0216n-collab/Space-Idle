"""Resource-fueled generation shares the same finite allocation as every consumer."""
from datetime import datetime, timezone

import pytest

from space_idle import AdvanceTime, PauseFacility, ResumeFacility, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import DefinitionId


def test_fueled_generation_requires_both_operating_inputs_and_settles_stock(tmp_path):
    app = build_game_application()
    sim = app._simulation
    definition_id = DefinitionId('planned.facility.fusion_power_station')
    asset = sim.facilities.definitions[definition_id]
    assert asset.operating_resources_per_day
    reactor_id = sim.facilities.install(definition_id, ids.EARTH)
    from space_idle import GetOperationalNode
    facility_view = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).facilities
                         if row.id == str(reactor_id))
    assert dict(facility_view.operating_resources_per_day) == dict(asset.operating_resources_per_day)
    spec = sim.power.specs[definition_id]
    assert spec.generation.mw > spec.load_mw

    def projected():
        snapshot = sim.tick_decision_projection().allocations
        power = snapshot.power_by_location[ids.EARTH]
        return power.maintenance_factor_by_facility[reactor_id], power.generation_mw

    # No free generation without both upstream fuels, regardless of installed Capability.
    missing_factor, _ = projected()
    assert missing_factor == pytest.approx(0)
    sim.inventory.add(ids.EARTH, ids.FUSION_FUEL_ISOTOPES, 2.0)
    still_missing, _ = projected()
    assert still_missing == pytest.approx(0)
    sim.inventory.add(ids.EARTH, ids.HELIUM4_COOLANT, 2.0)
    active_factor, generation = projected()
    assert active_factor == pytest.approx(1)
    assert generation >= spec.generation.mw - 1e-8

    stock_before = {resource: sim.inventory.amount(ids.EARTH, resource)
                    for resource, _ in asset.operating_resources_per_day}
    app.execute(AdvanceTime(1))
    for resource, rate in asset.operating_resources_per_day:
        assert stock_before[resource] - sim.inventory.amount(ids.EARTH, resource) == pytest.approx(rate)

    app.execute(PauseFacility(str(reactor_id)))
    paused_stock = {resource: sim.inventory.amount(ids.EARTH, resource)
                    for resource, _ in asset.operating_resources_per_day}
    app.execute(AdvanceTime(1))
    for resource in paused_stock:
        assert sim.inventory.amount(ids.EARTH, resource) == pytest.approx(paused_stock[resource])
    app.execute(ResumeFacility(str(reactor_id)))
    file = tmp_path / 'fuel-power.json'
    save_game(app, file, saved_at=datetime(2026, 10, 16, tzinfo=timezone.utc))
    loaded, offline = load_game(file, build_game_application_for_load)
    assert offline is None
    assert capture_state(sim) == capture_state(loaded._simulation)
    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(sim) == capture_state(loaded._simulation)


def test_beamed_sail_cargo_requires_finite_powered_assistance_at_both_ends(tmp_path):
    """Physical beam acceleration competes in ordinary Cargo execution, not free Fleet propulsion."""
    from space_idle import SetTargetStock
    from space_idle.transport import DirectionalCapacity

    app = build_game_application()
    sim = app._simulation
    sail = DefinitionId('planned.vehicle.beamed_sail_cargo_probe')
    station = DefinitionId('planned.facility.phased_energy_array')
    emitter_ids = {}
    for node_id in (ids.LEO, ids.LUNAR_ORBIT):
        emitter_ids[node_id] = sim.facilities.install(station, node_id)
        sim.facilities.install(ids.ORBITAL_FISSION_POWER, node_id, level=500)
        sim.inventory.add(node_id, ids.THERMAL_CONTROL_ASSEMBLIES, 4.0)
    sim.transport.fleet_pool(sail, ids.LEO).total_units = 2
    sim.transport.create_transport_allocation(
        sail, ids.LEO, ids.LUNAR_ORBIT,
        target_capacity=DirectionalCapacity(2.0, 2.0), day=sim.day,
    )
    sim.inventory.add(ids.LEO, ids.STRUCTURAL_COMPONENTS, 5.0)
    app.execute(SetTargetStock(str(ids.LUNAR_ORBIT), str(ids.STRUCTURAL_COMPONENTS), 2.0))

    # Missing power-backed receiver suppresses a dispatch despite available
    # Vehicle units and stocked Cargo. The provider's nominal rate is not free.
    app.execute(PauseFacility(str(emitter_ids[ids.LUNAR_ORBIT])))
    constrained = sim.tick_decision_projection().allocations
    assert not constrained.transport.executable_dispatches
    app.execute(ResumeFacility(str(emitter_ids[ids.LUNAR_ORBIT])))
    enabled = sim.tick_decision_projection().allocations
    assert enabled.transport.executable_dispatches
    stock_before = {
        node_id: sim.inventory.amount(node_id, ids.THERMAL_CONTROL_ASSEMBLIES)
        for node_id in emitter_ids
    }
    app.execute(AdvanceTime(1))
    assert sim.logistics.cargo_flows
    for node_id in emitter_ids:
        assert sim.inventory.amount(node_id, ids.THERMAL_CONTROL_ASSEMBLIES) < stock_before[node_id]

    path = tmp_path / 'beam-cargo.json'
    save_game(app, path, saved_at=datetime(2026, 10, 16, tzinfo=timezone.utc))
    restored, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert capture_state(sim) == capture_state(restored._simulation)
    app.execute(AdvanceTime(1))
    restored.execute(AdvanceTime(1))
    assert capture_state(sim) == capture_state(restored._simulation)


def test_remote_power_transfer_is_lossy_finite_player_intent_and_durable(tmp_path):
    from space_idle import SetPowerLink, DeletePowerLink, GetOperationalNode

    app = build_game_application()
    sim = app._simulation
    transmitter = sim.facilities.install(DefinitionId('planned.facility.phased_energy_array'), ids.LEO)
    receiver = sim.facilities.install(DefinitionId('planned.facility.beamed_power_receiver'), ids.LUNAR_ORBIT)
    sim.facilities.install(ids.ORBITAL_FISSION_POWER, ids.LEO, level=500)
    for site in (ids.LEO, ids.LUNAR_ORBIT):
        sim.inventory.add(site, ids.THERMAL_CONTROL_ASSEMBLIES, 10)
    before = sim.tick_decision_projection().allocations.power_by_location
    app.execute(SetPowerLink(str(transmitter), str(receiver), 40.0))
    current = sim.tick_decision_projection().allocations.power_by_location
    transmitted = current[ids.LEO].exported_mw
    received = current[ids.LUNAR_ORBIT].imported_mw
    assert transmitted == pytest.approx(40)
    assert received == pytest.approx(transmitted * .75)
    assert before[ids.LEO].generation_mw - current[ids.LEO].generation_mw == pytest.approx(transmitted)
    assert current[ids.LUNAR_ORBIT].generation_mw - before[ids.LUNAR_ORBIT].generation_mw == pytest.approx(received)
    node_view = app.query(GetOperationalNode(str(ids.LUNAR_ORBIT)))
    assert node_view.power_imported_mw == pytest.approx(received)
    assert node_view.power_links

    path = tmp_path / 'remote-power.json'
    save_game(app, path, saved_at=datetime(2026, 10, 16, tzinfo=timezone.utc))
    restored, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert capture_state(sim) == capture_state(restored._simulation)
    app.execute(AdvanceTime(1))
    restored.execute(AdvanceTime(1))
    assert capture_state(sim) == capture_state(restored._simulation)
    app.execute(PauseFacility(str(transmitter)))
    paused = sim.tick_decision_projection().allocations.power_by_location
    assert paused[ids.LUNAR_ORBIT].imported_mw == pytest.approx(0)
    app.execute(ResumeFacility(str(transmitter)))
    app.execute(DeletePowerLink(str(transmitter), str(receiver)))
    assert sim.tick_decision_projection().allocations.power_by_location[ids.LUNAR_ORBIT].imported_mw == 0


def test_power_link_competition_cannot_invent_or_reexport_energy():
    from space_idle import SetPowerLink

    app = build_game_application()
    sim = app._simulation
    sender = DefinitionId('planned.facility.phased_energy_array')
    receiver_def = DefinitionId('planned.facility.beamed_power_receiver')
    first = sim.facilities.install(sender, ids.LEO)
    second = sim.facilities.install(sender, ids.LUNAR_ORBIT)
    lunar_receiver = sim.facilities.install(receiver_def, ids.LUNAR_ORBIT)
    earth_receiver = sim.facilities.install(receiver_def, ids.EARTH)
    sim.facilities.install(ids.ORBITAL_FISSION_POWER, ids.LEO, level=500)
    for node in (ids.LEO, ids.LUNAR_ORBIT, ids.EARTH):
        sim.inventory.add(node, ids.THERMAL_CONTROL_ASSEMBLIES, 20)
    app.execute(SetPowerLink(str(first), str(lunar_receiver), 60))
    # Even with an incoming 45 MW the Lunar emitter cannot retransmit
    # if its *local* solar generation cannot cover its 210 MW active load.
    app.execute(SetPowerLink(str(second), str(earth_receiver), 60))
    snapshots = sim.tick_decision_projection().allocations.power_by_location
    assert snapshots[ids.LEO].exported_mw == pytest.approx(60)
    assert snapshots[ids.LUNAR_ORBIT].imported_mw == pytest.approx(45)
    assert snapshots[ids.LUNAR_ORBIT].exported_mw == pytest.approx(0)
    assert snapshots[ids.EARTH].imported_mw == pytest.approx(0)


def test_fixed_mass_driver_freight_uses_two_finite_services_without_fleet_and_survives_save(tmp_path):
    """Surface launch/orbital capture transfers owned Cargo, not invented vehicles."""
    from space_idle import (
        SetInfrastructureFreightLink, DeleteInfrastructureFreightLink,
        SetTargetStock, GetOperationalNode,
    )
    app = build_game_application()
    sim = app._simulation
    emitter = sim.facilities.install(
        DefinitionId('planned.facility.electromagnetic_mass_driver'), ids.EARTH,
    )
    catcher = sim.facilities.install(
        DefinitionId('planned.facility.kinetic_cargo_receiver'), ids.LEO,
    )
    sim.facilities.install(ids.ORBITAL_FISSION_POWER, ids.LEO, level=500)
    sim.inventory.add(ids.EARTH, ids.THERMAL_CONTROL_ASSEMBLIES, 10.0)
    sim.inventory.add(ids.LEO, ids.THERMAL_CONTROL_ASSEMBLIES, 10.0)
    sim.inventory.add(ids.EARTH, ids.STRUCTURAL_COMPONENTS, 12.0)
    fleet_before = capture_state(sim)['transport']['fleet_pools']
    result = app.execute(SetInfrastructureFreightLink(
        'planned.operation.mass_driver_freight', str(emitter), str(catcher), 2.0,
    ))
    assert result.created_id
    link_id = result.created_id
    assert any(row[0] == link_id for row in
               app.query(GetOperationalNode(str(ids.EARTH))).infrastructure_links)
    app.execute(SetTargetStock(str(ids.LEO), str(ids.STRUCTURAL_COMPONENTS), 2.0))
    planned = sim.tick_decision_projection().allocations.transport.executable_dispatches
    assert any(any(leg.allocation_id == link_id for leg in dispatch.path)
               for dispatch, amount in planned if amount > 0)
    source_before = sim.inventory.amount(ids.EARTH, ids.THERMAL_CONTROL_ASSEMBLIES)
    dest_before = sim.inventory.amount(ids.LEO, ids.THERMAL_CONTROL_ASSEMBLIES)
    app.execute(AdvanceTime(1))
    assert sim.inventory.amount(ids.EARTH, ids.THERMAL_CONTROL_ASSEMBLIES) < source_before
    assert sim.inventory.amount(ids.LEO, ids.THERMAL_CONTROL_ASSEMBLIES) < dest_before
    assert sim.logistics.arrival_waiting or sim.logistics.cargo_flows
    assert capture_state(sim)['transport']['fleet_pools'] == fleet_before

    path = tmp_path / 'fixed-freight.json'
    save_game(app, path, saved_at=datetime(2026, 10, 16, tzinfo=timezone.utc))
    restored, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert capture_state(sim) == capture_state(restored._simulation)
    app.execute(AdvanceTime(1))
    restored.execute(AdvanceTime(1))
    assert capture_state(sim) == capture_state(restored._simulation)
    app.execute(DeleteInfrastructureFreightLink(link_id))
    assert link_id not in app._simulation.transport.infrastructure_links


def test_fixed_infrastructure_requires_correct_endpoints_and_excludes_passengers():
    from space_idle import SetInfrastructureFreightLink, GetOperationalNode
    app = build_game_application()
    sim = app._simulation
    emitter = sim.facilities.install(
        DefinitionId('planned.facility.electromagnetic_mass_driver'), ids.EARTH,
    )
    catcher = sim.facilities.install(
        DefinitionId('planned.facility.kinetic_cargo_receiver'), ids.LEO,
    )
    from space_idle import ApplicationError
    with pytest.raises(ApplicationError):
        app.execute(SetInfrastructureFreightLink(
            'planned.operation.tether_transfer', str(emitter), str(catcher), 1,
        ))
    app.execute(SetInfrastructureFreightLink(
        'planned.operation.mass_driver_freight', str(emitter), str(catcher), 1,
    ))
    with pytest.raises(ValueError, match="no path"):
        sim.logistics.passenger_service_path(ids.EARTH, ids.LEO, sim.day)
    assert any(row[0] == 'planned.operation.tether_transfer'
               for row in app.query(GetOperationalNode(str(ids.EARTH))).infrastructure_methods)


def test_tether_installation_moves_finite_cargo_between_same_body_orbital_nodes():
    """An additional operational orbit is ordinary World Content, not a Core exception."""
    from space_idle import SetTargetStock, SetInfrastructureFreightLink
    from space_idle.spatial import OperationalNodeState

    app = build_game_application()
    sim = app._simulation
    target = ids.EARTH_TRANSFER_ORBIT
    assert target in sim.graph.nodes and not sim.graph.has_operational_node(target)
    sim.graph.add_operational_node(OperationalNodeState(target))
    tether = DefinitionId('planned.facility.momentum_exchange_tether')
    origin = sim.facilities.install(tether, ids.LEO)
    catcher = sim.facilities.install(tether, target)
    for node in (ids.LEO, target):
        sim.facilities.install(ids.ORBITAL_FISSION_POWER, node, level=100)
        sim.inventory.add(node, ids.THERMAL_CONTROL_ASSEMBLIES, 10)
    sim.inventory.add(ids.LEO, ids.STRUCTURAL_COMPONENTS, 3)
    link = app.execute(SetInfrastructureFreightLink(
        'planned.operation.tether_transfer', str(origin), str(catcher), 2,
    )).created_id
    assert link
    app.execute(SetTargetStock(str(target), str(ids.STRUCTURAL_COMPONENTS), 1))
    assert any(any(edge.allocation_id == link for edge in dispatch.path)
               for dispatch, _ in sim.tick_decision_projection().allocations.transport.executable_dispatches)
    app.execute(AdvanceTime(1))
    assert any(segment.leg.allocation_id == link for segment in sim.logistics.cargo_flows.values())
    sim.advance_days(5)
    assert any(waiting.node_id == target and waiting.amount_t > 0
               for waiting in sim.logistics.arrival_waiting.values())
    # A new orbit has no implicit storage; arrival remains physically owned
    # rather than being inserted into Inventory for free.
    assert sim.inventory.amount(target, ids.STRUCTURAL_COMPONENTS) == 0


def test_routing_constraint_preserves_any_referenced_transport_link_until_cleared():
    """A hard routing decision outlives neither Fleet nor fixed-infrastructure deletion."""
    from space_idle import (
        ApplicationError, ClearSupplyRoutingConstraint, CreateTransportAllocation,
        DeleteInfrastructureFreightLink, DeleteTransportAllocation,
        SetInfrastructureFreightLink, SetSupplyRoutingConstraint,
    )
    from space_idle.transport import DirectionalCapacity

    app = build_game_application()
    sim = app._simulation
    emitter = sim.facilities.install(DefinitionId('planned.facility.electromagnetic_mass_driver'), ids.EARTH)
    catcher = sim.facilities.install(DefinitionId('planned.facility.kinetic_cargo_receiver'), ids.LEO)
    fixed = app.execute(SetInfrastructureFreightLink(
        'planned.operation.mass_driver_freight', str(emitter), str(catcher), 1.0,
    )).created_id
    mobile = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=1.0, target_reverse_t_per_day=0.0,
    )).created_id

    for link_id, delete in ((fixed, DeleteInfrastructureFreightLink(fixed)),
                            (mobile, DeleteTransportAllocation(mobile))):
        routing = SetSupplyRoutingConstraint(
            str(ids.LEO), resource_id=str(ids.STRUCTURAL_COMPONENTS),
            required_transport_allocation_ids=(link_id,),
        )
        app.execute(routing)
        with pytest.raises(ApplicationError, match='clear Supply Routing constraints'):
            app.execute(delete)
        assert link_id in (sim.transport.infrastructure_links if link_id == fixed
                           else sim.transport.transport_allocations)
        app.execute(ClearSupplyRoutingConstraint(str(ids.LEO),
                                               resource_id=str(ids.STRUCTURAL_COMPONENTS)))
        app.execute(delete)
    assert not sim.logistics.routing_constraints


def test_new_orbital_context_uses_existing_scoped_player_founding_options():
    """New transport endpoints stay physical World context until player-founded."""
    from space_idle import GetNonSurfaceFoundingOptions

    app = build_game_application()
    sim = app._simulation
    assert ids.EARTH_TRANSFER_ORBIT in sim.graph.nodes
    assert not sim.graph.has_operational_node(ids.EARTH_TRANSFER_ORBIT)
    view = app.query(GetNonSurfaceFoundingOptions(
        str(ids.EARTH_BODY), founding_context_id=str(ids.EARTH_TRANSFER_ORBIT),
    ))
    target = next(row for row in view.contexts
                  if row.spatial_node_id == str(ids.EARTH_TRANSFER_ORBIT))
    assert not target.operational
    assert any(option.can_plan and not option.blockers and option.transit_days is not None
               for option in target.foundation_options)


def test_assisted_one_shot_movement_does_not_advertise_an_unsettled_fleet_action():
    """Fleet commands cannot start free beam-powered Movement outside Cargo allocation."""
    from space_idle import ApplicationError, GetFleetRelocationPreview, RelocateFleet

    app = build_game_application()
    sim = app._simulation
    vehicle = DefinitionId('planned.vehicle.beamed_sail_cargo_probe')
    sim.transport.fleet_pool(vehicle, ids.LEO).total_units = 1
    view = app.query(GetFleetRelocationPreview(str(vehicle), 1, str(ids.LEO), str(ids.LUNAR_ORBIT)))
    assert not view.feasible
    assert any('operation_service' in row.code for row in view.blockers)
    with pytest.raises(ApplicationError, match='operation_service'):
        app.execute(RelocateFleet(str(vehicle), 1, str(ids.LEO), str(ids.LUNAR_ORBIT)))
    assert sim.transport.fleet_free_units(vehicle, ids.LEO) == 1
