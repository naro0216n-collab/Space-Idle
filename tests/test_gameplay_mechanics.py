from __future__ import annotations


from space_idle import (
    GetMovementPlans,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.transport import PoweredAscentCapability, TransportPerformanceProfile, VehicleDef
from space_idle.shared import DefinitionId
from space_idle.spatial import AtmosphereField, GravityField


def test_vehicle_movement_eligibility_is_derived_from_operation_capability_not_vehicle_name():
    app = build_game_application()
    sim = app._simulation
    plan = min(sim.transport.movement_plan_candidates(ids.EARTH, ids.LEO), key=lambda row: str(row.id))

    movement_plan_view = app.query(GetMovementPlans(movement_plan_id=str(plan.id), include_modes=True)).items[0]
    lander_mode = next(mode for mode in movement_plan_view.modes if mode.id == str(ids.REUSABLE_SURFACE_CARGO_LANDER))
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
        row for row in app.query(GetMovementPlans(movement_plan_id=str(plan.id), include_modes=True)).items[0].modes
        if row.id == str(definition_id)
    )
    assert mode.fleet_total_units == 1
    assert mode.nominal_capacity.forward_t_per_day > 0
