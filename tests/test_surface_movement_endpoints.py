from __future__ import annotations

import math

from space_idle import GetMovementPlans, build_game_application
from space_idle.content import base_ids as ids
from space_idle.transport import (
    MovementEndpoint,
    OperationAssetDisposition,
    SurfaceTransportCapability,
    TransportPerformanceProfile,
    VehicleDef,
)
from space_idle.persistence import load_game, save_game
from space_idle.shared import CelestialBodyId, DefinitionId, SpatialNodeId
from space_idle.spatial import (
    CelestialBodyDef,
    CharacteristicTransportGeometry,
    OperationalNodeState,
    SpatialNodeDef,
    SpatialNodeKind,
)
from space_idle.transport.endpoints import resolve_movement_endpoint


def _location_with_gateway(sim, name: str, cell_id):
    location_id = SpatialNodeId(f"test.location.{name}")
    sim.graph.found_location(location_id, name, ids.MOON, cell_id)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, location_id)
    gateway_id = sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        location_id,
        site_cell_id=cell_id,
    )
    sim.transport.invalidate_movement_plans()
    return location_id, gateway_id


def _plan_between(sim, origin, destination):
    plans = sim.transport.movement_plan_candidates(origin, destination)
    assert len(plans) == 1
    return plans[0]


def _surface_vehicle(vehicle_id: str, *, speed_km_per_day: float, max_distance_km: float | None = None) -> VehicleDef:
    return VehicleDef(
        DefinitionId(vehicle_id), vehicle_id,
        TransportPerformanceProfile(
            dry_mass_t=4.0,
            payload_t=10.0,
            operation_capabilities=(
                SurfaceTransportCapability(
                    speed_km_per_day,
                    max_distance_km=max_distance_km,
                    asset_disposition=OperationAssetDisposition.DESTINATION,
                ),
            ),
            endurance_days=100.0,
        ),
    )


def test_surface_movement_plan_uses_real_gateway_facility_cells():
    sim = build_game_application()._simulation
    a, a_gateway = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, b_gateway = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)

    plan = _plan_between(sim, a, b)
    geometry = sim.transport.movement_geometry(plan.id)

    assert plan.origin.surface_interface_id == a_gateway
    assert plan.destination.surface_interface_id == b_gateway
    assert geometry.origin.surface_cell_id == ids.MOON_CELL_SOUTH_POLAR_RIDGE
    assert geometry.destination.surface_cell_id == ids.MOON_CELL_NEARSIDE_MARE
    assert geometry.same_body_surface
    assert geometry.distance_km is not None and geometry.distance_km > 0


def test_gateway_position_changes_movement_geometry_without_changing_location_identity():
    sim = build_game_application()._simulation
    a, gateway = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    before_plan = _plan_between(sim, a, b)
    before = sim.transport.movement_geometry(before_plan.id)

    sim.graph.develop_surface_cell(a, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(a, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)
    sim.facilities.facilities[gateway].site_cell_id = ids.MOON_CELL_EQUATORIAL_HIGHLANDS
    sim.transport.invalidate_movement_plans()

    after_plan = _plan_between(sim, a, b)
    after = sim.transport.movement_geometry(after_plan.id)
    assert before.origin.node_id == after.origin.node_id == a
    assert after.origin.surface_cell_id == ids.MOON_CELL_EQUATORIAL_HIGHLANDS
    assert after.distance_km is not None and before.distance_km is not None
    assert after.distance_km < before.distance_km
    # Plan identity follows the stable endpoint interface identity; its geometry
    # is re-derived from the gateway's current Surface Cell.
    assert after_plan.id == before_plan.id


def test_surface_transport_latency_uses_endpoint_distance_and_vehicle_speed():
    sim = build_game_application()._simulation
    a, _ = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_POLAR_COLD_TRAP)
    vehicle = _surface_vehicle("test.vehicle.surface", speed_km_per_day=25.0)
    sim.transport.vehicle_defs[vehicle.id] = vehicle
    forward = _plan_between(sim, a, b)
    reverse = _plan_between(sim, b, a)

    distance = sim.transport.movement_geometry(forward.id).distance_km
    assert distance is not None
    expected_days = max(1, math.ceil(distance / 25.0))
    assert sim.transport.performance_movement_transit_days(forward, vehicle.performance) == expected_days
    service = sim.transport.transport_service_plan_for(vehicle.id, a, b, path=(forward.id,))
    assert service.feasible
    assert service.forward_latency_days == expected_days
    assert service.reverse_path == (reverse.id,)


def test_player_founded_location_gets_orbit_movement_only_after_real_gateway_exists():
    sim = build_game_application()._simulation
    location_id = SpatialNodeId("test.location.farside")
    sim.graph.found_location(location_id, "Farside", ids.MOON, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    sim.transport.invalidate_movement_plans()
    assert not sim.transport.movement_plan_candidates(ids.LUNAR_ORBIT, location_id)
    assert not sim.transport.movement_plan_candidates(location_id, ids.LUNAR_ORBIT)

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        location_id,
        site_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS,
    )
    sim.transport.invalidate_movement_plans()
    down = _plan_between(sim, ids.LUNAR_ORBIT, location_id)
    up = _plan_between(sim, location_id, ids.LUNAR_ORBIT)
    assert sim.transport.movement_geometry(down.id).destination.surface_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert sim.transport.movement_geometry(up.id).origin.surface_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS


def test_surface_interface_projection_and_availability_follow_gateway_facility():
    app = build_game_application()
    sim = app._simulation
    a, gateway = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    plan = _plan_between(sim, a, b)

    row = app.query(GetMovementPlans(movement_plan_id=str(plan.id), include_modes=False)).items[0]
    assert row.origin_endpoint.locator_kind == "surface_interface"
    assert row.origin_endpoint.locator_id == str(gateway)
    assert row.origin_endpoint.surface_cell_id == str(ids.MOON_CELL_SOUTH_POLAR_RIDGE)

    sim.facilities.pause(gateway)
    blocked = app.query(GetMovementPlans(movement_plan_id=str(plan.id), include_modes=False)).items[0]
    assert not blocked.available
    assert any(item.startswith("origin:interface:manual_pause:") for item in blocked.blockers)


def test_surface_transport_distance_limit_is_physical_blocker():
    sim = build_game_application()._simulation
    a, _ = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    plan = _plan_between(sim, a, b)
    distance = sim.transport.movement_geometry(plan.id).distance_km
    assert distance is not None and distance > 1
    vehicle = _surface_vehicle("test.vehicle.short", speed_km_per_day=100, max_distance_km=distance / 2)
    sim.transport.vehicle_defs[vehicle.id] = vehicle
    assert any(
        "surface_transport:distance:" in failure
        for failure in sim.transport.vehicle_movement_physical_failures(plan.id, vehicle.id)
    )


def test_movement_plan_is_rederived_after_save_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    a, _ = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    plan = _plan_between(sim, a, b)

    path = tmp_path / "movement-plan.json"
    save_game(app, path)
    loaded, _ = load_game(path, build_game_application)
    loaded_plan = _plan_between(loaded._simulation, a, b)
    assert loaded_plan.id == plan.id
    geometry = loaded._simulation.transport.movement_geometry(loaded_plan.id)
    assert geometry.origin.node_id == a
    assert geometry.destination.node_id == b


def test_physical_target_endpoint_uses_surface_cell_without_operational_node():
    sim = build_game_application()._simulation
    endpoint = MovementEndpoint(physical_target_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS)

    resolved = resolve_movement_endpoint(endpoint, sim.facilities)
    plans = sim.transport.movement_plans_to_physical_target(
        ids.LUNAR_ORBIT, ids.MOON_CELL_FARSIDE_HIGHLANDS
    )

    assert resolved.node_id is None
    assert resolved.locator_kind == "physical_target"
    assert resolved.surface_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert resolved.environment_context_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert ids.MOON_CELL_FARSIDE_HIGHLANDS not in sim.graph.operational_node_states
    assert len(plans) == 1
    assert plans[0].destination.operational_node_id is None
    assert plans[0].destination.physical_target_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert plans[0].relation.destination_context_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert plans[0].relation.characteristic_distance_km == 0.0
    assert tuple(op.operation_type for op in plans[0].operations) == ("landing",)
    assert not sim.transport.movement_plan_failures(plans[0].id, sim.day)



def test_distinct_non_surface_nodes_with_same_anchor_still_get_movement_candidate():
    sim = build_game_application()._simulation
    extra_orbit = SpatialNodeId("test.node.colocated_lunar_orbit")
    lunar_geometry = sim.graph.bodies[ids.MOON].system_local_transport_geometry
    sim.graph.add(SpatialNodeDef(
        extra_orbit,
        "Co-located Lunar Orbit",
        ids.SOL_SYSTEM,
        lunar_geometry,
        body_id=ids.MOON,
        kind=SpatialNodeKind.ORBITAL,
    ))
    sim.graph.add_operational_node(OperationalNodeState(extra_orbit))

    plans = sim.transport.movement_plan_candidates(ids.LUNAR_ORBIT, extra_orbit)

    assert len(plans) == 1
    assert plans[0].relation.characteristic_distance_km == 0.0
    assert tuple(op.operation_type for op in plans[0].operations) == ("spaceflight",)


def test_new_celestial_body_uses_spatial_geometry_without_pairwise_movement_definition():
    sim = build_game_application()._simulation
    body_id = CelestialBodyId("test.body.new")
    extra_orbit = SpatialNodeId("test.node.new_body_orbit")
    geometry = CharacteristicTransportGeometry(
        (1_000_000.0, 0.0, 0.0),
        (6.0, 0.0, 0.0),
    )
    sim.graph.add_body(CelestialBodyDef(
        body_id, "New Body", 1000.0, ids.SOL_SYSTEM, geometry
    ))
    sim.graph.add(SpatialNodeDef(
        extra_orbit,
        "New Body Orbit",
        ids.SOL_SYSTEM,
        geometry,
        body_id=body_id,
        kind=SpatialNodeKind.ORBITAL,
    ))
    sim.graph.add_operational_node(OperationalNodeState(extra_orbit))

    plans = sim.transport.movement_plan_candidates(ids.LEO, extra_orbit)

    assert len(plans) == 1
    plan = plans[0]
    assert plan.origin.operational_node_id == ids.LEO
    assert plan.destination.operational_node_id == extra_orbit
    assert plan.relation.characteristic_distance_km == 1_000_000.0
    assert plan.relation.characteristic_delta_v_km_s == 6.0
    assert tuple(op.operation_type for op in plan.operations) == ("spaceflight",)
    assert plan.operations[0].delta_v_km_s == 6.0
