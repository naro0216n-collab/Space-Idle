from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import (
    build_game_application,
    AdvanceTime,
    ApplicationError,
    CreateLogisticsLane,
    GetLogistics,
    GetRoutes,
    GetVehicles,
    GetTransportPlans,
    ProduceVehicle,
    RefuelVehicle,
    SubmitCargo,
)
from space_idle.content.base_game import (
    DIRECT_LUNAR_SERVICE,
    EARTH,
    LEO,
    LEO_LUNAR_SERVICE,
    LUNAR_LANDING_SERVICE,
    LUNAR_ORBIT,
    MACHINERY,
    ORBITAL_LOGISTICS_NODE,
    PROPELLANT,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
    REUSABLE_SURFACE_CARGO_LANDER,
    SOUTH_POLAR_RIDGE,
    TECH_CISLUNAR_LOGISTICS,
    TECH_LUNAR_PROSPECTING,
    TECH_ORBITAL_OPERATIONS,
    MACHINERY,
    WATER,
)
from space_idle.logistics import (
    LandingCapability,
    PoweredAscentCapability,
    PathPolicy,
    SpaceflightCapability,
    TransportPerformanceProfile,
    VehicleDef,
    VehicleDisposition,
    VehicleMaintenanceSpec,
)
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import DefinitionId, EntityId, RouteId


def _unlock_lunar_transport(app) -> None:
    app._simulation.logistics.unlocked_technologies.update(
        {TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS, TECH_LUNAR_PROSPECTING}
    )


def test_one_vehicle_can_keep_cargo_onboard_through_a_waypoint_without_transfer_facility():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    assert not sim.facilities.all_at(LUNAR_ORBIT)

    definition_id = DefinitionId("test.vehicle.continuous_lunar_carrier")
    sim.logistics.vehicle_defs[definition_id] = VehicleDef(
        definition_id,
        "連続月輸送試験船",
        performance=TransportPerformanceProfile(
            dry_mass_t=4.0, payload_t=5.0,
            operation_capabilities=(SpaceflightCapability(5.0, 30), LandingCapability(2.1, 2.0, 1000.0)),
            default_disposition=VehicleDisposition.DESTINATION,
        ),
    )
    vehicle_id = sim.logistics.add_vehicle(definition_id, LEO)
    sim.inventory.add(LEO, MACHINERY, 1.0)

    first = RouteId("base.route.leo_lunar_orbit")
    second = RouteId("base.route.lunar_orbit_ridge")
    order_id = app.execute(
        SubmitCargo(
            str(LEO),
            str(SOUTH_POLAR_RIDGE),
            str(MACHINERY),
            1.0,
            100,
            (str(first), str(second)),
            ((str(first), str(definition_id)), (str(second), str(definition_id))),
        )
    ).created_id
    assert order_id is not None

    app.execute(AdvanceTime(5))
    mission = next(m for m in app.query(GetLogistics()).missions if m.order_id == order_id)
    vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.id == str(vehicle_id))
    assert mission.leg_index == 1 and mission.onboard and mission.status == "in_transit"
    assert vehicle.location_id is None and vehicle.transit_destination_id == str(SOUTH_POLAR_RIDGE)
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == 0.0

    app.execute(AdvanceTime(3))
    order = next(o for o in app.query(GetLogistics()).orders if o.id == order_id)
    vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.id == str(vehicle_id))
    assert order.delivered_t == pytest.approx(1.0)
    assert vehicle.location_id == str(SOUTH_POLAR_RIDGE)


def test_switching_transport_modes_requires_real_cargo_transfer_infrastructure():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    sim.inventory.add(LEO, MACHINERY, 1.0)

    first = RouteId("base.route.leo_lunar_orbit")
    second = RouteId("base.route.lunar_orbit_ridge")
    order_id = app.execute(
        SubmitCargo(
            str(LEO),
            str(SOUTH_POLAR_RIDGE),
            str(MACHINERY),
            1.0,
            100,
            (str(first), str(second)),
            ((str(first), str(LEO_LUNAR_SERVICE)), (str(second), str(LUNAR_LANDING_SERVICE))),
        )
    ).created_id
    assert order_id is not None

    app.execute(AdvanceTime(5))
    mission = next(m for m in app.query(GetLogistics()).missions if m.order_id == order_id)
    assert mission.status == "arrival_waiting"
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == 0.0

    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    app.execute(AdvanceTime(1))
    domain_order = next(order for oid, order in sim.logistics.orders.items() if str(oid) == order_id)
    # Arrived batches can now be staged for the next leg; later batches may
    # still be physically in flight because the external service has finite
    # daily capacity.
    assert sim.logistics.waiting.get((domain_order.id, 1), 0.0) > 0.0

    for _ in range(20):
        order = next(o for o in app.query(GetLogistics()).orders if o.id == order_id)
        if order.delivered_t >= order.amount_t - 1e-9:
            break
        app.execute(AdvanceTime(1))
    else:
        raise AssertionError("transferred cargo never completed the second leg")
    assert order.delivered_t == pytest.approx(1.0)


def test_refueling_requires_refueling_service_but_route_passage_does_not():
    app = build_game_application()
    sim = app._simulation
    tug = next(
        state for state in sim.logistics.vehicles.values()
        if state.definition_id == REUSABLE_ORBITAL_CARGO_TUG
    )
    sim.inventory.add(LEO, PROPELLANT, 4.0)

    with pytest.raises(ApplicationError, match="refueling infrastructure"):
        app.execute(RefuelVehicle(str(tug.id), 1.0))

    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    app.execute(RefuelVehicle(str(tug.id), 1.0))
    assert sim.logistics.vehicles[tug.id].propellant_t == pytest.approx(1.0)


def test_vehicle_production_consumes_industrial_inputs_and_creates_owned_asset_only_when_complete():
    app = build_game_application()
    sim = app._simulation
    before = len(sim.logistics.vehicles)
    definition = sim.logistics.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG]
    before_inputs = {resource_id: sim.inventory.amount(EARTH, resource_id) for resource_id, _ in definition.production.resources}

    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = next(pid for pid in sim.logistics.vehicle_production_projects if str(pid) == result.created_id)
    state = sim.logistics.vehicle_production_projects[production_id]
    assert len(sim.logistics.vehicles) == before
    assert state.phase.value == "awaiting_inputs"

    app.execute(AdvanceTime(1))
    assert state.phase.value == "building"
    for resource_id, amount in definition.production.resources:
        assert sim.inventory.amount(EARTH, resource_id) <= before_inputs[resource_id] - amount + 1e-9

    app.execute(AdvanceTime(int(definition.production.days) - 1))
    assert state.phase.value == "complete"
    assert state.completed_vehicle_id in sim.logistics.vehicles
    vehicle = sim.logistics.vehicles[state.completed_vehicle_id]
    assert vehicle.location_id == EARTH
    assert vehicle.status == "available"
    assert len(sim.logistics.vehicles) == before + 1


def test_spacecraft_waits_for_servicing_infrastructure_after_mission():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)

    definition_id = DefinitionId("test.vehicle.servicing_required")
    sim.logistics.vehicle_defs[definition_id] = VehicleDef(
        definition_id,
        "整備要求試験船",
        performance=TransportPerformanceProfile(
            dry_mass_t=3.0, payload_t=1.0,
            operation_capabilities=(SpaceflightCapability(5.0, 30),),
            default_disposition=VehicleDisposition.DESTINATION,
        ),
        maintenance=VehicleMaintenanceSpec("spacecraft_servicing", 2.0),
    )
    vehicle_id = sim.logistics.add_vehicle(definition_id, LEO)
    app.execute(__import__("space_idle").DispatchVehicle(str(vehicle_id), "base.route.leo_lunar_orbit"))
    app.execute(AdvanceTime(5))
    state = sim.logistics.vehicles[vehicle_id]
    assert state.location_id == LUNAR_ORBIT and state.status == "maintenance_wait"

    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)
    app.execute(AdvanceTime(1))
    assert sim.logistics.vehicles[vehicle_id].status == "turnaround"
    app.execute(AdvanceTime(2))
    assert sim.logistics.vehicles[vehicle_id].status == "available"


def test_lane_capacity_recognizes_onboard_handoff_even_with_transfer_infrastructure():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    # LEO can transfer cargo, but the selected physical plan also permits the
    # onward lander to be integrated at Earth and separated in LEO. Projection
    # must not require that lander or its fuel to be pre-positioned at LEO.
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    onward_id = sim.logistics.add_vehicle(REUSABLE_SURFACE_CARGO_LANDER, EARTH)
    onward_def = sim.logistics.vehicle_defs[REUSABLE_SURFACE_CARGO_LANDER]
    sim.logistics.vehicles[onward_id].propellant_t = onward_def.propellant_capacity_t
    assert sim.inventory.amount(LEO, PROPELLANT) == pytest.approx(0.0)

    first = "base.route.earth_leo"
    second = "base.route.leo_ridge"
    lane_id = app.execute(CreateLogisticsLane(
        str(EARTH),
        str(SOUTH_POLAR_RIDGE),
        10.0,
        100,
        (first, second),
        ((first, str(REUSABLE_LAUNCH_VEHICLE)),
         (second, str(REUSABLE_SURFACE_CARGO_LANDER))),
        "lowest_cost",
    )).created_id
    assert lane_id is not None
    lane = next(row for row in app.query(GetLogistics()).lanes if row.id == lane_id)
    assert lane.effective_capacity_t_per_day > 0
    assert not any("propellant" in blocker for blocker in lane.blockers)

    demand = ResourceDemand(
        EntityId("demand.test.onboard_handoff"),
        "test",
        EntityId("test.owner"),
        SOUTH_POLAR_RIDGE,
        MACHINERY,
        1.0,
        100,
        EARTH,
    )
    sim.logistics.advance_automation(sim.day, (demand,))
    sim.logistics.advance_day(sim.day)
    order = next(row for row in sim.logistics.orders.values() if row.demand_id == demand.id)
    mission = next(row for row in sim.logistics.missions.values() if row.order_id == order.id)
    assert mission.handoff_vehicle_id == onward_id
    assert mission.onboard


def test_automatic_path_does_not_assume_unowned_vehicle_definitions_exist_as_capacity():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    sim.logistics.external_services.pop(DIRECT_LUNAR_SERVICE)
    sim.logistics.external_services.pop(LEO_LUNAR_SERVICE)
    sim.logistics.external_services.pop(LUNAR_LANDING_SERVICE)
    sim.logistics.vehicles = {
        vid: state for vid, state in sim.logistics.vehicles.items()
        if state.location_id == EARTH
    }

    with pytest.raises(ValueError, match="no route path"):
        sim.logistics.find_path(EARTH, SOUTH_POLAR_RIDGE, sim.day, PathPolicy.FASTEST)


def test_transport_plan_query_exposes_end_to_end_policy_choices():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.inventory.add(LEO, PROPELLANT, 20.0)
    # Make direct commercial service deliberately premium in this test. This
    # validates policy behavior without freezing production balance constants.
    sim.logistics.external_services[DIRECT_LUNAR_SERVICE] = replace(
        sim.logistics.external_services[DIRECT_LUNAR_SERVICE], cost_musd_per_t=30.0
    )

    plans = app.query(GetTransportPlans(str(EARTH), str(SOUTH_POLAR_RIDGE)))
    by_policy = {row.policy: row for row in plans.options}
    assert {"fastest", "lowest_cost", "lowest_propellant"}.issubset(by_policy)
    assert by_policy["fastest"].path == ("base.route.earth_ridge_direct",)
    assert by_policy["lowest_cost"].path != by_policy["fastest"].path
    assert by_policy["lowest_cost"].estimated_cost_musd_per_t < by_policy["fastest"].estimated_cost_musd_per_t


def test_external_transport_service_is_capability_based_not_bound_to_one_route():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    service = sim.logistics.external_services[LUNAR_LANDING_SERVICE]
    assert not hasattr(service, "route_id")
    for suffix in ("ridge", "cold_trap", "nearside"):
        route_id = RouteId(f"base.route.lunar_orbit_{suffix}")
        assert not sim.logistics.service_route_failures(route_id, service.id, sim.day)


def test_launch_carrier_can_handoff_onboard_spacecraft_without_leo_cargo_transfer():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    # Put an onward spacecraft at the original departure node so the launch
    # carrier can carry it as payload and release it in LEO.
    onward_id = sim.logistics.add_vehicle(REUSABLE_SURFACE_CARGO_LANDER, EARTH)
    onward_def = sim.logistics.vehicle_defs[REUSABLE_SURFACE_CARGO_LANDER]
    sim.logistics.vehicles[onward_id].propellant_t = onward_def.propellant_capacity_t

    first = RouteId("base.route.earth_leo")
    second = RouteId("base.route.leo_ridge")
    leo_machinery_before = sim.inventory.amount(LEO, MACHINERY)
    order_id = app.execute(
        SubmitCargo(
            str(EARTH), str(SOUTH_POLAR_RIDGE), str(MACHINERY), 1.0, 100,
            (str(first), str(second)),
            ((str(first), str(REUSABLE_LAUNCH_VEHICLE)),
             (str(second), str(REUSABLE_SURFACE_CARGO_LANDER))),
        )
    ).created_id
    assert order_id is not None

    app.execute(AdvanceTime(1))
    mission = next(m for m in app.query(GetLogistics()).missions if m.order_id == order_id)
    assert mission.leg_index == 0
    assert mission.handoff_vehicle_id == str(onward_id)
    assert mission.onboard
    # The order remains physically onboard during the handoff path. Ambient LEO
    # inventory may exist for other systems (for example facility maintenance),
    # so verify that this 1 t cargo was not deposited into node inventory.
    assert sim.inventory.amount(LEO, MACHINERY) <= leo_machinery_before + 1e-9

    app.execute(AdvanceTime(1))
    mission = next(m for m in app.query(GetLogistics()).missions if m.order_id == order_id)
    assert mission.leg_index == 1
    assert mission.vehicle_id == str(onward_id)
    assert mission.handoff_vehicle_id is None
    assert mission.onboard
    assert sim.inventory.amount(LEO, MACHINERY) <= leo_machinery_before + 1e-9

    app.execute(AdvanceTime(7))
    order = next(o for o in app.query(GetLogistics()).orders if o.id == order_id)
    assert order.delivered_t == pytest.approx(1.0)
    assert sim.logistics.vehicles[onward_id].location_id == SOUTH_POLAR_RIDGE


def test_automatic_planner_can_use_onboard_spacecraft_for_later_leg_without_prepositioning():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    sim.logistics.external_services.clear()
    # Remove all initially pre-positioned spacecraft. Keep the launch carrier
    # and add one onward spacecraft at Earth as its payload.
    launch_ids = {
        vid for vid, state in sim.logistics.vehicles.items()
        if state.definition_id == REUSABLE_LAUNCH_VEHICLE and state.location_id == EARTH
    }
    sim.logistics.vehicles = {vid: sim.logistics.vehicles[vid] for vid in launch_ids}
    onward_id = sim.logistics.add_vehicle(REUSABLE_SURFACE_CARGO_LANDER, EARTH)
    onward_def = sim.logistics.vehicle_defs[REUSABLE_SURFACE_CARGO_LANDER]
    sim.logistics.vehicles[onward_id].propellant_t = onward_def.propellant_capacity_t

    path = sim.logistics.find_path(EARTH, SOUTH_POLAR_RIDGE, sim.day, PathPolicy.FASTEST)
    assert path == (RouteId("base.route.earth_leo"), RouteId("base.route.leo_ridge"))
    plan = sim.logistics._automatic_mode_plan(path, sim.day, PathPolicy.FASTEST)
    assert plan == {
        path[0]: str(REUSABLE_LAUNCH_VEHICLE),
        path[1]: str(REUSABLE_SURFACE_CARGO_LANDER),
    }


def test_turnaround_can_require_real_service_funds_and_replacement_materials():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LUNAR_ORBIT)

    definition_id = DefinitionId("test.vehicle.maintenance_inputs")
    sim.logistics.vehicle_defs[definition_id] = VehicleDef(
        definition_id,
        "整備資材要求試験船",
        performance=TransportPerformanceProfile(
            dry_mass_t=2.0, payload_t=1.0,
            operation_capabilities=(SpaceflightCapability(5.0, 30),),
            default_disposition=VehicleDisposition.DESTINATION,
        ),
        maintenance=VehicleMaintenanceSpec("spacecraft_servicing", 2.0, 0.25, ((MACHINERY, 0.5),)),
    )
    vehicle_id = sim.logistics.add_vehicle(definition_id, LEO)
    app.execute(__import__("space_idle").DispatchVehicle(str(vehicle_id), "base.route.leo_lunar_orbit"))
    app.execute(AdvanceTime(5))
    state = sim.logistics.vehicles[vehicle_id]
    assert state.status == "maintenance_wait"
    funds_while_waiting = sim.account.funds_musd

    sim.inventory.add(LUNAR_ORBIT, MACHINERY, 0.5)
    app.execute(AdvanceTime(1))
    state = sim.logistics.vehicles[vehicle_id]
    assert state.status == "turnaround"
    assert sim.inventory.amount(LUNAR_ORBIT, MACHINERY) == pytest.approx(0.0)
    assert sim.account.funds_musd == pytest.approx(funds_while_waiting - 0.25)

    app.execute(AdvanceTime(2))
    assert sim.logistics.vehicles[vehicle_id].status == "available"


def test_operation_support_is_vehicle_specific_not_a_route_gate_for_external_service():
    from space_idle import GetLocation, PauseFacility
    from space_idle.content.base_game import EARTH_LAUNCH_SUPPORT, EARTH_LEO_LAUNCH_SERVICE

    app = build_game_application()
    launch_support_id = next(
        row.id for row in app.query(GetLocation(str(EARTH))).facilities
        if row.definition_id == str(EARTH_LAUNCH_SUPPORT)
    )
    app.execute(PauseFacility(launch_support_id))

    route = next(row for row in app.query(GetLogistics()).routes if row.id == "base.route.earth_leo")
    owned = next(mode for mode in route.modes if mode.id == str(REUSABLE_LAUNCH_VEHICLE))
    external = next(mode for mode in route.modes if mode.id == str(EARTH_LEO_LAUNCH_SERVICE))
    assert not owned.usable_now
    assert any("operation_support:powered_ascent:origin:launch_operations" in blocker for blocker in owned.blockers)
    assert external.usable_now


def test_cargo_transfer_can_handoff_directly_without_intermediate_storage():
    app = build_game_application()
    sim = app._simulation
    _unlock_lunar_transport(app)
    sim.facilities.install(ORBITAL_LOGISTICS_NODE, LEO)
    sim.inventory.add(LEO, PROPELLANT, 20.0)
    sim.logistics.external_services[DIRECT_LUNAR_SERVICE] = replace(
        sim.logistics.external_services[DIRECT_LUNAR_SERVICE], cost_musd_per_t=30.0
    )

    order_id = app.execute(SubmitCargo(
        str(EARTH), str(SOUTH_POLAR_RIDGE), str(WATER), 1.0, 100,
        path_policy="lowest_cost",
    )).created_id
    assert order_id is not None
    order = next(row for row in app.query(GetLogistics()).orders if row.id == order_id)
    assert order.path == ("base.route.earth_leo", "base.route.leo_ridge")

    app.execute(AdvanceTime(2))
    mission = next(m for m in app.query(GetLogistics()).missions if m.order_id == order_id)
    assert mission.leg_index == 1 and mission.status == "in_transit"
    assert sim.inventory.amount(LEO, WATER) == 0.0
    domain_order = next(o for oid, o in sim.logistics.orders.items() if str(oid) == order_id)
    assert sim.logistics.waiting.get((domain_order.id, 1), 0.0) == 0.0


def test_vehicle_production_progress_pauses_when_assembly_capability_is_unavailable():
    from space_idle import GetLocation, PauseFacility, ResumeFacility
    from space_idle.content.base_game import VEHICLE_ASSEMBLY_FACILITY

    app = build_game_application()
    sim = app._simulation
    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    production_id = next(pid for pid in sim.logistics.vehicle_production_projects if str(pid) == result.created_id)
    state = sim.logistics.vehicle_production_projects[production_id]
    factory_id = next(
        row.id for row in app.query(GetLocation(str(EARTH))).facilities
        if row.definition_id == str(VEHICLE_ASSEMBLY_FACILITY)
    )
    definition = sim.logistics.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG]
    app.execute(PauseFacility(factory_id))
    app.execute(AdvanceTime(2))
    assert state.progress_days == pytest.approx(0.0)
    assert state.phase.value == "awaiting_inputs"
    demands = {
        demand.resource_id: demand
        for demand in sim.logistics.vehicle_production_resource_demands(sim.day)
        if demand.owner_id == production_id
    }
    for resource_id, amount in definition.production.resources:
        demand = demands[resource_id]
        assert sim.inventory.reserved_for(demand.id, EARTH, resource_id) == pytest.approx(amount)
    app.execute(ResumeFacility(factory_id))
    app.execute(AdvanceTime(int(definition.production.days)))
    assert state.phase.value == "complete"
    assert state.completed_vehicle_id in sim.logistics.vehicles


def test_vehicle_eligibility_is_derived_from_physical_ascent_capability_not_concept_name():
    from space_idle.spatial import AtmosphereField, GravityField

    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.earth_leo")
    route = sim.logistics.routes[route_id]

    route_view = app.query(GetRoutes(route_id=str(route_id), include_modes=True)).items[0]
    lander_mode = next(
        mode for mode in route_view.modes if mode.id == str(REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert not lander_mode.usable_now
    assert any("operation:powered_ascent" in blocker for blocker in lander_mode.blockers)

    gravity = sim.environment.require(route.origin_id, GravityField).local_acceleration_m_s2
    pressure = sim.environment.require(route.origin_id, AtmosphereField).pressure_pa
    definition_id = DefinitionId("test.vehicle.integrated_spacecraft")
    sim.logistics.vehicle_defs[definition_id] = VehicleDef(
        id=definition_id,
        display_name="統合型試験宇宙船",
        performance=TransportPerformanceProfile(
            dry_mass_t=10.0,
            payload_t=2.0,
            operation_capabilities=(
                PoweredAscentCapability(route.delta_v_km_s + 1.0, gravity + 1.0, pressure + 1000.0),
            ),
            default_disposition=VehicleDisposition.DESTINATION,
        ),
    )
    vehicle_id = sim.logistics.add_vehicle(definition_id, EARTH)
    assert not sim.logistics.vehicle_route_failures(route_id, definition_id, sim.day)

    order_id = app.execute(
        SubmitCargo(
            str(EARTH),
            str(LEO),
            str(WATER),
            1.0,
            100,
            (str(route_id),),
            ((str(route_id), str(definition_id)),),
        )
    ).created_id
    assert order_id
    app.execute(AdvanceTime(2))
    vehicle = next(v for v in app.query(GetVehicles()).items if v.id == str(vehicle_id))
    assert vehicle.location_id == str(LEO)
