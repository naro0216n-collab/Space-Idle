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
from space_idle.shared import DefinitionId, RouteId


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
        DefinitionId(vehicle_id),
        vehicle_id,
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


def test_surface_route_geometry_uses_access_cells_not_location_core_cells():
    app = build_game_application()
    sim = app._simulation

    # Expand the south-polar Location toward the equator without changing its core cell.
    sim.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)

    core_route = _surface_route(
        "test.route.core",
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        ids.NEARSIDE_MARE,
        ids.MOON_CELL_NEARSIDE_MARE,
    )
    access_route = _surface_route(
        "test.route.access",
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
        ids.NEARSIDE_MARE,
        ids.MOON_CELL_NEARSIDE_MARE,
    )
    sim.logistics.routes[core_route.id] = core_route
    sim.logistics.routes[access_route.id] = access_route

    core_geometry = sim.logistics.route_geometry(core_route.id)
    access_geometry = sim.logistics.route_geometry(access_route.id)

    assert core_geometry.same_body_surface
    assert access_geometry.same_body_surface
    assert access_geometry.distance_km is not None
    assert core_geometry.distance_km is not None
    assert access_geometry.distance_km < core_geometry.distance_km
    assert access_geometry.origin.surface_cell_id == ids.MOON_CELL_EQUATORIAL_HIGHLANDS
    assert access_geometry.origin.location_id == ids.SOUTH_POLAR_RIDGE


def test_surface_transport_latency_and_service_plan_derive_from_endpoint_distance_and_vehicle_speed():
    app = build_game_application()
    sim = app._simulation
    vehicle = _surface_vehicle("test.vehicle.surface", speed_km_per_day=25.0)
    forward = _surface_route(
        "test.route.ridge_cold_trap",
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        ids.POLAR_COLD_TRAP,
        ids.MOON_CELL_POLAR_COLD_TRAP,
    )
    reverse = _surface_route(
        "test.route.cold_trap_ridge",
        ids.POLAR_COLD_TRAP,
        ids.MOON_CELL_POLAR_COLD_TRAP,
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_SOUTH_POLAR_RIDGE,
    )
    sim.logistics.vehicle_defs[vehicle.id] = vehicle
    sim.logistics.routes[forward.id] = forward
    sim.logistics.routes[reverse.id] = reverse

    distance = sim.logistics.route_geometry(forward.id).distance_km
    assert distance is not None
    expected_days = max(1, math.ceil(distance / 25.0))
    assert expected_days != forward.transit_days
    assert sim.logistics.performance_route_transit_days(forward, vehicle.performance) == expected_days

    plan = sim.logistics.transport_service_plan_for(
        vehicle.id,
        ids.SOUTH_POLAR_RIDGE,
        ids.POLAR_COLD_TRAP,
        path=(forward.id,),
    )
    assert plan.feasible
    assert plan.forward_latency_days == expected_days
    assert plan.reverse_latency_days == expected_days
    assert tuple(leg.transit_days for leg in plan.legs) == (expected_days, expected_days)




def test_fastest_path_uses_endpoint_geometry_when_locations_have_multiple_access_cells():
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)

    vehicle = _surface_vehicle("test.vehicle.pathing", speed_km_per_day=200.0)
    sim.logistics.vehicle_defs[vehicle.id] = vehicle
    routes = (
        _surface_route(
            "test.route.path.core.forward", ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_RIDGE,
            ids.NEARSIDE_MARE, ids.MOON_CELL_NEARSIDE_MARE,
        ),
        _surface_route(
            "test.route.path.access.forward", ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
            ids.NEARSIDE_MARE, ids.MOON_CELL_NEARSIDE_MARE,
        ),
        _surface_route(
            "test.route.path.core.reverse", ids.NEARSIDE_MARE, ids.MOON_CELL_NEARSIDE_MARE,
            ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        ),
        _surface_route(
            "test.route.path.access.reverse", ids.NEARSIDE_MARE, ids.MOON_CELL_NEARSIDE_MARE,
            ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
        ),
    )
    for route in routes:
        sim.logistics.routes[route.id] = route

    plan = sim.logistics.transport_service_plan_for(
        vehicle.id, ids.SOUTH_POLAR_RIDGE, ids.NEARSIDE_MARE
    )

    assert plan.forward_path == (RouteId("test.route.path.access.forward"),)
    assert plan.reverse_path == (RouteId("test.route.path.access.reverse"),)

def test_external_surface_service_latency_uses_endpoint_geometry():
    app = build_game_application()
    sim = app._simulation
    route = _surface_route(
        "test.route.external_surface",
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        ids.POLAR_COLD_TRAP,
        ids.MOON_CELL_POLAR_COLD_TRAP,
    )
    service_id = DefinitionId("test.service.surface")
    service = ExternalTransportServiceDef(
        service_id,
        "Surface Carrier",
        5.0,
        0.2,
        TransportPerformanceProfile(
            dry_mass_t=3.0,
            payload_t=8.0,
            operation_capabilities=(SurfaceTransportCapability(40.0),),
        ),
    )
    sim.logistics.routes[route.id] = route
    sim.logistics.external_services[service_id] = service

    distance = sim.logistics.route_geometry(route.id).distance_km
    assert distance is not None
    expected_days = max(1, math.ceil(distance / 40.0))
    row = app.query(GetRoutes(route_id=str(route.id), include_modes=True)).items[0]
    mode = next(item for item in row.modes if item.id == str(service_id))

    assert mode.service_feasible
    assert mode.forward_latency_days == expected_days
    assert mode.forward_latency_days != route.transit_days

def test_surface_transport_distance_limit_is_a_physical_route_blocker():
    app = build_game_application()
    sim = app._simulation
    route = _surface_route(
        "test.route.surface_limit",
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        ids.NEARSIDE_MARE,
        ids.MOON_CELL_NEARSIDE_MARE,
    )
    sim.logistics.routes[route.id] = route
    geometry_distance = sim.logistics.route_geometry(route.id).distance_km
    assert geometry_distance is not None and geometry_distance > 1.0

    vehicle = _surface_vehicle(
        "test.vehicle.short_range",
        speed_km_per_day=100.0,
        max_distance_km=geometry_distance / 2.0,
    )
    sim.logistics.vehicle_defs[vehicle.id] = vehicle

    failures = sim.logistics.vehicle_route_physical_failures(route.id, vehicle.id)
    assert any("surface_transport:distance:" in failure for failure in failures)


def test_route_query_exposes_resolved_physical_endpoints_and_surface_distance():
    app = build_game_application()
    sim = app._simulation
    route = _surface_route(
        "test.route.query_geometry",
        ids.SOUTH_POLAR_RIDGE,
        ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        ids.POLAR_COLD_TRAP,
        ids.MOON_CELL_POLAR_COLD_TRAP,
    )
    sim.logistics.routes[route.id] = route

    row = app.query(GetRoutes(route_id=str(route.id), include_modes=False)).items[0]

    assert row.origin_id == str(ids.SOUTH_POLAR_RIDGE)
    assert row.destination_id == str(ids.POLAR_COLD_TRAP)
    assert row.origin_endpoint.surface_cell_id == str(ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    assert row.destination_endpoint.surface_cell_id == str(ids.MOON_CELL_POLAR_COLD_TRAP)
    assert row.same_body_surface
    assert row.distance_km is not None and row.distance_km > 0.0
