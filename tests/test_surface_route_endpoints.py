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
from space_idle.shared import DefinitionId, RouteId, SpatialNodeId
from space_idle.transport.surface_routes import derived_surface_access_route_id


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




def test_derived_surface_route_tracks_closest_access_cells_without_changing_route_identity():
    app = build_game_application()
    sim = app._simulation
    route_id = derived_surface_access_route_id(ids.SOUTH_POLAR_RIDGE, ids.NEARSIDE_MARE)

    sim.logistics.synchronize_surface_access_routes()
    before_count = len(sim.logistics.routes)
    before = sim.logistics.route_geometry(route_id)
    assert before.origin.surface_cell_id == ids.MOON_CELL_SOUTH_POLAR_RIDGE
    assert before.distance_km is not None

    sim.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)
    sim.logistics.synchronize_surface_access_routes()

    after = sim.logistics.route_geometry(route_id)
    assert len(sim.logistics.routes) == before_count
    assert after.origin.surface_cell_id == ids.MOON_CELL_EQUATORIAL_HIGHLANDS
    assert after.destination.surface_cell_id == ids.MOON_CELL_NEARSIDE_MARE
    assert after.distance_km is not None
    assert after.distance_km < before.distance_km

    plan = sim.logistics.transport_service_plan_for(
        ids.SURFACE_CARGO_HAULER, ids.SOUTH_POLAR_RIDGE, ids.NEARSIDE_MARE
    )
    assert plan.forward_path == (route_id,)
    assert plan.reverse_path == (
        derived_surface_access_route_id(ids.NEARSIDE_MARE, ids.SOUTH_POLAR_RIDGE),
    )


def test_player_founded_surface_location_receives_location_to_location_routes_without_cell_nodes():
    app = build_game_application()
    sim = app._simulation
    new_location_id = SpatialNodeId("player.location.farside")
    node_count_before = len(sim.graph.operational_node_ids())
    surface_cell_count = len(sim.graph.surface_cells)

    sim.graph.found_location(
        new_location_id,
        "Farside Test Location",
        ids.MOON,
        ids.MOON_CELL_FARSIDE_HIGHLANDS,
    )
    sim.logistics.synchronize_surface_access_routes()

    route_id = derived_surface_access_route_id(new_location_id, ids.NEARSIDE_MARE)
    route = sim.logistics.routes[route_id]
    geometry = sim.logistics.route_geometry(route_id)
    assert route.origin_id == new_location_id
    assert route.destination_id == ids.NEARSIDE_MARE
    assert geometry.origin.surface_cell_id == ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert geometry.destination.surface_cell_id == ids.MOON_CELL_NEARSIDE_MARE
    assert geometry.same_body_surface
    assert len(sim.graph.operational_node_ids()) == node_count_before + 1
    assert len(sim.graph.surface_cells) == surface_cell_count

    rows = app.query(
        GetRoutes(
            origin_id=str(new_location_id),
            destination_id=str(ids.NEARSIDE_MARE),
            include_modes=True,
        )
    ).items
    assert [row.id for row in rows] == [str(route_id)]
    surface_mode = next(
        mode for mode in rows[0].modes
        if mode.vehicle_definition_id == str(ids.SURFACE_CARGO_HAULER)
    )
    assert surface_mode.service_feasible


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


def test_derived_surface_route_is_rebuilt_after_save_load_for_persisted_allocation(tmp_path):
    from space_idle.persistence import load_game, save_game

    app = build_game_application()
    sim = app._simulation
    new_location_id = SpatialNodeId("player.location.persisted_surface_route")
    sim.graph.found_location(
        new_location_id,
        "Persisted Surface Route Test",
        ids.MOON,
        ids.MOON_CELL_FARSIDE_HIGHLANDS,
    )
    sim.logistics.synchronize_surface_access_routes()
    route_id = derived_surface_access_route_id(ids.SOUTH_POLAR_RIDGE, new_location_id)
    allocation_id = sim.logistics.create_transport_allocation(
        ids.SURFACE_CARGO_HAULER,
        ids.SOUTH_POLAR_RIDGE,
        new_location_id,
        target_units=1,
        path=(route_id,),
        day=sim.day,
    )

    path = tmp_path / "derived-surface-route.json"
    save_game(app, path)
    loaded, _ = load_game(path, build_game_application)
    loaded_sim = loaded._simulation
    loaded_sim.logistics.synchronize_surface_access_routes()

    assert route_id in loaded_sim.logistics.routes
    allocation = loaded_sim.logistics.transport_allocations[allocation_id]
    assert allocation.path == (route_id,)
    geometry = loaded_sim.logistics.route_geometry(route_id)
    assert geometry.origin.location_id == ids.SOUTH_POLAR_RIDGE
    assert geometry.destination.location_id == new_location_id
    assert geometry.same_body_surface
