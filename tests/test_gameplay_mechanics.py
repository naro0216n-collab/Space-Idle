from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    CreateLogisticsLane,
    CreateTransportAllocation,
    GetCargoFlows,
    GetFleet,
    GetLogistics,
    GetLogisticsLanes,
    GetProjects,
    GetRoutes,
    PauseLogisticsLane,
    PlanBuild,
    ResumeLogisticsLane,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.logistics import PoweredAscentCapability, TransportPerformanceProfile, VehicleDef
from space_idle.shared import DefinitionId, RouteId
from space_idle.spatial import AtmosphereField, GravityField


def test_transport_fleet_investment_is_explicit_and_lane_demand_does_not_resize_it():
    app = build_game_application()
    before = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.location_id == str(ids.EARTH)
    )
    assert before.total_units == 1 and before.free_units == 1
    assert app.query(GetLogistics()).allocations == ()

    app.execute(CreateLogisticsLane(str(ids.EARTH), str(ids.LEO), 100.0, priority=100))
    after_lane = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.location_id == str(ids.EARTH)
    )
    assert after_lane.free_units == 1

    app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        control_mode="units", target_units=1, priority=50,
    ))
    allocated = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.location_id == str(ids.EARTH)
    )
    assert allocated.transport_units == 1 and allocated.free_units == 0


def test_paused_lane_keeps_project_demand_visible_without_dispatching_cargo_flow():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update({ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS})
    app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        control_mode="units", target_units=1, priority=100,
    ))
    lane_id = app.execute(CreateLogisticsLane(
        str(ids.EARTH), str(ids.LEO), 20.0, priority=100
    )).created_id
    assert lane_id is not None
    project_id = app.execute(PlanBuild(
        str(ids.LEO), str(ids.ORBITAL_LOGISTICS_NODE), priority=100,
        sourcing_policy="import_now", import_source_id=str(ids.EARTH),
    )).created_id
    assert project_id is not None

    app.execute(PauseLogisticsLane(lane_id))
    app.execute(AdvanceTime(1))
    demands = [row for row in app.query(GetLogistics()).demands if row.owner_id == project_id]
    assert demands and all(row.operational_lane_count == 0 for row in demands)
    assert app.query(GetCargoFlows()).items == ()

    app.execute(ResumeLogisticsLane(lane_id))
    app.execute(AdvanceTime(1))
    assert app.query(GetCargoFlows()).items
    lane = next(row for row in app.query(GetLogisticsLanes()).items if row.id == lane_id)
    assert not lane.paused and lane.used_t > 0


def test_vehicle_route_eligibility_is_derived_from_operation_capability_not_vehicle_name():
    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.earth_leo")
    route = sim.logistics.routes[route_id]

    route_view = app.query(GetRoutes(route_id=str(route_id), include_modes=True)).items[0]
    lander_mode = next(mode for mode in route_view.modes if mode.id == str(ids.REUSABLE_SURFACE_CARGO_LANDER))
    assert not lander_mode.service_feasible
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
            endurance_days=30.0,
            operation_capabilities=(
                PoweredAscentCapability(route.delta_v_km_s + 1.0, gravity + 1.0, pressure + 1000.0),
            ),
        ),
    )
    sim.logistics.add_fleet_units(definition_id, 1, ids.EARTH)
    assert not sim.logistics.vehicle_route_failures(route_id, definition_id, sim.day)
    mode = next(
        row for row in app.query(GetRoutes(route_id=str(route_id), include_modes=True)).items[0].modes
        if row.id == str(definition_id)
    )
    assert mode.fleet_total_units == 1
    assert mode.nominal_capacity.forward_t_per_day > 0


def test_capacity_mode_target_is_not_auto_increased_by_lane_demand():
    app = build_game_application()
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        control_mode="capacity", target_forward_t_per_day=1.0,
        target_reverse_t_per_day=0.0, priority=70,
    )).created_id
    assert allocation_id is not None
    app.execute(CreateLogisticsLane(str(ids.EARTH), str(ids.LEO), 100.0, priority=100))
    allocation = next(row for row in app.query(GetLogistics()).allocations if row.id == allocation_id)
    assert allocation.target_capacity.forward_t_per_day == pytest.approx(1.0)
    assert allocation.required_units == 1
