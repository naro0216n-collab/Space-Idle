from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    CreateTransportAllocation,
    GetCargoFlows,
    GetFleet,
    GetLogistics,
    GetProjects,
    GetRoutes,
    PauseTransportAllocation,
    PlanBuild,
    SetTargetStock,
    ResumeTransportAllocation,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.transport import PoweredAscentCapability, TransportPerformanceProfile, VehicleDef
from space_idle.shared import DefinitionId
from space_idle.spatial import AtmosphereField, GravityField


def test_transport_fleet_investment_is_explicit_and_supply_demand_does_not_resize_it():
    app = build_game_application()
    before = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.operational_node_id == str(ids.EARTH)
    )
    assert before.total_units > 0
    assert before.free_units == before.total_units
    assert app.query(GetLogistics()).allocations == ()

    app.execute(SetTargetStock(str(ids.LEO), str(ids.MACHINERY), 100.0, priority=5))
    after_supply = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.operational_node_id == str(ids.EARTH)
    )
    assert after_supply.free_units == before.free_units

    app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        control_mode="units", target_units=1, provisioning_priority=3,
    ))
    allocated = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.operational_node_id == str(ids.EARTH)
    )
    assert allocated.transport_units == 1
    assert allocated.free_units == before.free_units - 1


def test_paused_transport_capacity_keeps_supply_requirement_visible_without_dispatching_cargo_flow():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update({ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS})
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        control_mode="units", target_units=1, provisioning_priority=5,
    )).created_id
    assert allocation_id is not None
    project_id = app.execute(PlanBuild(
        str(ids.LEO), str(ids.ORBITAL_LOGISTICS_NODE), priority=5,
        sourcing_policy="import_now", import_source_id=str(ids.EARTH),
    )).created_id
    assert project_id is not None

    app.execute(PauseTransportAllocation(allocation_id))
    app.execute(AdvanceTime(1))
    requirements = [row for row in app.query(GetLogistics()).requirements if row.owner_id == project_id]
    assert requirements and all(row.operational_source_count == 0 for row in requirements)
    assert app.query(GetCargoFlows()).items == ()

    app.execute(ResumeTransportAllocation(allocation_id))
    app.execute(AdvanceTime(1))
    assert app.query(GetCargoFlows()).items
    allocation = next(row for row in app.query(GetLogistics()).allocations if row.id == allocation_id)
    assert not allocation.paused and allocation.used.forward_t_per_day > 0


def test_vehicle_route_eligibility_is_derived_from_operation_capability_not_vehicle_name():
    app = build_game_application()
    sim = app._simulation
    plan = sim.transport.movement_plan_candidates(ids.EARTH, ids.LEO)[0]

    route_view = app.query(GetRoutes(route_id=str(plan.id), include_modes=True)).items[0]
    lander_mode = next(mode for mode in route_view.modes if mode.id == str(ids.REUSABLE_SURFACE_CARGO_LANDER))
    assert not lander_mode.service_feasible
    assert any("operation:powered_ascent" in blocker for blocker in lander_mode.blockers)

    origin_context = sim.transport.movement_geometry(plan.id).origin.environment_context_id
    gravity = sim.environment.require(origin_context, GravityField).local_acceleration_m_s2
    pressure = sim.environment.require(origin_context, AtmosphereField).pressure_pa
    definition_id = DefinitionId("test.vehicle.integrated_spacecraft")
    sim.transport.vehicle_defs[definition_id] = VehicleDef(
        id=definition_id,
        display_name="統合型試験宇宙船",
        performance=TransportPerformanceProfile(
            dry_mass_t=10.0,
            payload_t=2.0,
            endurance_days=30.0,
            operation_capabilities=(
                PoweredAscentCapability(plan.delta_v_km_s + 1.0, gravity + 1.0, pressure + 1000.0),
            ),
        ),
    )
    sim.transport.add_fleet_units(definition_id, 1, ids.EARTH)
    assert not sim.transport.vehicle_movement_failures(plan.id, definition_id, sim.day)
    mode = next(
        row for row in app.query(GetRoutes(route_id=str(plan.id), include_modes=True)).items[0].modes
        if row.id == str(definition_id)
    )
    assert mode.fleet_total_units == 1
    assert mode.nominal_capacity.forward_t_per_day > 0


def test_capacity_mode_target_is_not_auto_increased_by_supply_demand():
    app = build_game_application()
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        control_mode="capacity", target_forward_t_per_day=1.0,
        target_reverse_t_per_day=0.0, provisioning_priority=4,
    )).created_id
    assert allocation_id is not None
    before = next(row for row in app.query(GetLogistics()).allocations if row.id == allocation_id)

    app.execute(SetTargetStock(str(ids.LEO), str(ids.MACHINERY), 100.0, priority=5))
    after = next(row for row in app.query(GetLogistics()).allocations if row.id == allocation_id)

    assert after.target_capacity == before.target_capacity
    assert after.required_units == before.required_units
