from __future__ import annotations

import math

from space_idle import GetRoutes, build_game_application
from space_idle.content import base_ids as ids
from space_idle.logistics import (
    ExternalTransportServiceDef,
    OperationAssetDisposition,
    RouteDef,
    RouteEndpoint,
    SurfaceTransportCapability,
    TransportOperationKind,
    TransportOperationRequirement,
    TransportPerformanceProfile,
    VehicleDef,
)
from space_idle.persistence import load_game, save_game
from space_idle.shared import DefinitionId, RouteId, SpatialNodeId
from space_idle.transport.surface_routes import (
    DERIVED_SURFACE_ACCESS_ROUTE_PREFIX,
    DERIVED_SURFACE_ORBIT_ROUTE_PREFIX,
)


def _location_with_gateway(sim, name: str, cell_id):
    location_id = SpatialNodeId(f"test.location.{name}")
    sim.graph.found_location(location_id, name, ids.MOON, cell_id)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, location_id)
    gateway_id = sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        location_id,
        site_cell_id=cell_id,
    )
    sim.logistics.synchronize_surface_access_routes()
    return location_id, gateway_id


def _route_between(sim, origin, destination, prefix=DERIVED_SURFACE_ACCESS_ROUTE_PREFIX):
    matches = [
        route_id for route_id, route in sim.logistics.routes.items()
        if str(route_id).startswith(prefix)
        and route.origin_id == origin and route.destination_id == destination
    ]
    assert len(matches) == 1
    return matches[0]


def _surface_route(route_id: str, origin, origin_cell, destination, destination_cell) -> RouteDef:
    return RouteDef(
        RouteId(route_id),
        RouteEndpoint(origin, access_cell_id=origin_cell),
        RouteEndpoint(destination, access_cell_id=destination_cell),
        transit_days=99,
        operations=(TransportOperationRequirement(TransportOperationKind.SURFACE_TRANSPORT),),
        display_name=route_id,
    )


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


def test_derived_surface_route_uses_real_gateway_facility_cells():
    sim = build_game_application()._simulation
    a, a_gateway = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, b_gateway = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)

    route_id = _route_between(sim, a, b)
    route = sim.logistics.routes[route_id]
    geometry = sim.logistics.route_geometry(route_id)

    assert route.origin.surface_interface_id == a_gateway
    assert route.destination.surface_interface_id == b_gateway
    assert geometry.origin.surface_cell_id == ids.MOON_CELL_SOUTH_POLAR_RIDGE
    assert geometry.destination.surface_cell_id == ids.MOON_CELL_NEARSIDE_MARE
    assert geometry.same_body_surface
    assert geometry.distance_km is not None and geometry.distance_km > 0


def test_gateway_position_changes_route_geometry_without_changing_location_identity():
    sim = build_game_application()._simulation
    a, gateway = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    before_id = _route_between(sim, a, b)
    before = sim.logistics.route_geometry(before_id)

    sim.graph.develop_surface_cell(a, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(a, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)
    sim.facilities.facilities[gateway].site_cell_id = ids.MOON_CELL_EQUATORIAL_HIGHLANDS
    sim.logistics.synchronize_surface_access_routes()

    after_id = _route_between(sim, a, b)
    after = sim.logistics.route_geometry(after_id)
    assert before.origin.node_id == after.origin.node_id == a
    assert after.origin.surface_cell_id == ids.MOON_CELL_EQUATORIAL_HIGHLANDS
    assert after.distance_km is not None and before.distance_km is not None
    assert after.distance_km < before.distance_km
    # Physical endpoint identity is part of derived Route identity; moving the same
    # gateway Facility keeps its entity id, so the Route id remains stable.
    assert after_id == before_id


def test_surface_transport_latency_uses_endpoint_distance_and_vehicle_speed():
    sim = build_game_application()._simulation
    a, _ = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_POLAR_COLD_TRAP)
    vehicle = _surface_vehicle("test.vehicle.surface", speed_km_per_day=25.0)
    sim.logistics.vehicle_defs[vehicle.id] = vehicle
    forward_id = _route_between(sim, a, b)
    reverse_id = _route_between(sim, b, a)
    forward = sim.logistics.routes[forward_id]

    distance = sim.logistics.route_geometry(forward_id).distance_km
    assert distance is not None
    expected_days = max(1, math.ceil(distance / 25.0))
    assert sim.logistics.performance_route_transit_days(forward, vehicle.performance) == expected_days
    plan = sim.logistics.transport_service_plan_for(vehicle.id, a, b, path=(forward_id,))
    assert plan.feasible
    assert plan.forward_latency_days == expected_days
    assert plan.reverse_path == (reverse_id,)


def test_player_founded_location_gets_orbit_routes_only_after_real_gateway_exists():
    sim = build_game_application()._simulation
    location_id = SpatialNodeId("test.location.farside")
    sim.graph.found_location(location_id, "Farside", ids.MOON, ids.MOON_CELL_FARSIDE_HIGHLANDS)
    sim.logistics.synchronize_surface_access_routes()
    assert not any(
        str(route_id).startswith(DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
        and location_id in {route.origin_id, route.destination_id}
        for route_id, route in sim.logistics.routes.items()
    )

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        location_id,
        site_cell_id=ids.MOON_CELL_FARSIDE_HIGHLANDS,
    )
    sim.logistics.synchronize_surface_access_routes()
    down = _route_between(sim, ids.LUNAR_ORBIT, location_id, DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
    up = _route_between(sim, location_id, ids.LUNAR_ORBIT, DERIVED_SURFACE_ORBIT_ROUTE_PREFIX)
    assert sim.logistics.route_geometry(down).destination.surface_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert sim.logistics.route_geometry(up).origin.surface_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS


def test_surface_interface_projection_and_availability_follow_gateway_facility():
    app = build_game_application()
    sim = app._simulation
    a, gateway = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    route_id = _route_between(sim, a, b)

    row = app.query(GetRoutes(route_id=str(route_id), include_modes=False)).items[0]
    assert row.origin_endpoint.locator_kind == "surface_interface"
    assert row.origin_endpoint.locator_id == str(gateway)
    assert row.origin_endpoint.surface_cell_id == str(ids.MOON_CELL_SOUTH_POLAR_RIDGE)

    sim.facilities.pause(gateway)
    blocked = app.query(GetRoutes(route_id=str(route_id), include_modes=False)).items[0]
    assert not blocked.available
    assert any(item.startswith("origin:interface:manual_pause:") for item in blocked.blockers)


def test_surface_transport_distance_limit_is_physical_blocker():
    sim = build_game_application()._simulation
    a, _ = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    route_id = _route_between(sim, a, b)
    distance = sim.logistics.route_geometry(route_id).distance_km
    assert distance is not None and distance > 1
    vehicle = _surface_vehicle("test.vehicle.short", speed_km_per_day=100, max_distance_km=distance / 2)
    sim.logistics.vehicle_defs[vehicle.id] = vehicle
    assert any("surface_transport:distance:" in f for f in sim.logistics.vehicle_route_physical_failures(route_id, vehicle.id))


def test_derived_surface_route_is_rebuilt_after_save_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    a, _ = _location_with_gateway(sim, "a", ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    b, _ = _location_with_gateway(sim, "b", ids.MOON_CELL_NEARSIDE_MARE)
    route_id = _route_between(sim, a, b)

    path = tmp_path / "derived-route.json"
    save_game(app, path)
    loaded, _ = load_game(path, build_game_application)
    assert route_id in loaded._simulation.logistics.routes
    geometry = loaded._simulation.logistics.route_geometry(route_id)
    assert geometry.origin.node_id == a
    assert geometry.destination.node_id == b
