from __future__ import annotations

from ..shared import RouteId
from ..logistics import (
    ExternalTransportServiceDef,
    LandingCapability,
    LogisticsService,
    OperationSupportLocation,
    OperationSupportRequirement,
    ResourceSupportRequirement,
    PoweredAscentCapability,
    RouteDef,
    SpaceflightCapability,
    TransportOperationKind,
    TransportOperationRequirement,
    TransportPerformanceProfile,
    VehicleDef,
    OperationAssetDisposition,
    VehicleMaintenanceSpec,
    VehicleProductionSpec,
)
from . import base_ids as ids
from . import base_requirements as req


def build_route_definitions() -> dict:
    routes = {
        RouteId("base.route.earth_leo"): RouteDef(
            id=RouteId("base.route.earth_leo"), origin_id=ids.EARTH, destination_id=ids.LEO, transit_days=2,
            operations=(TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 9.4),),
            display_name="地球地表→低軌道", origin_requirements=req.SURFACE_SITE, destination_requirements=req.ORBIT_SITE,
        ),
        RouteId("base.route.leo_lunar_orbit"): RouteDef(
            id=RouteId("base.route.leo_lunar_orbit"), origin_id=ids.LEO, destination_id=ids.LUNAR_ORBIT, transit_days=5,
            operations=(TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 4.1),),
            display_name="低軌道→月周回軌道",
            origin_requirements=req.ORBIT_SITE, destination_requirements=req.ORBIT_SITE,
        ),
        RouteId("base.route.lunar_orbit_leo"): RouteDef(
            id=RouteId("base.route.lunar_orbit_leo"), origin_id=ids.LUNAR_ORBIT, destination_id=ids.LEO, transit_days=5,
            operations=(TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 4.1),),
            display_name="月周回軌道→低軌道",
            origin_requirements=req.ORBIT_SITE, destination_requirements=req.ORBIT_SITE,
        ),
    }
    for suffix, surface, label in (
        ("ridge", ids.SOUTH_POLAR_RIDGE, "南極高地"),
        ("cold_trap", ids.POLAR_COLD_TRAP, "極域永久影"),
        ("nearside", ids.NEARSIDE_MARE, "表側海地域"),
    ):
        routes[RouteId(f"base.route.lunar_orbit_{suffix}")] = RouteDef(
            id=RouteId(f"base.route.lunar_orbit_{suffix}"), origin_id=ids.LUNAR_ORBIT, destination_id=surface, transit_days=3,
            operations=(TransportOperationRequirement(TransportOperationKind.LANDING, 1.9),),
            display_name=f"月周回軌道→{label}",
            origin_requirements=req.ORBIT_SITE, destination_requirements=req.SURFACE_SITE,
        )
        routes[RouteId(f"base.route.{suffix}_lunar_orbit")] = RouteDef(
            id=RouteId(f"base.route.{suffix}_lunar_orbit"), origin_id=surface, destination_id=ids.LUNAR_ORBIT, transit_days=3,
            operations=(TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 1.9),),
            display_name=f"{label}→月周回軌道",
            origin_requirements=req.SURFACE_SITE, destination_requirements=req.ORBIT_SITE,
        )
        routes[RouteId(f"base.route.leo_{suffix}")] = RouteDef(
            id=RouteId(f"base.route.leo_{suffix}"), origin_id=ids.LEO, destination_id=surface, transit_days=7,
            operations=(
                TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 4.1),
                TransportOperationRequirement(TransportOperationKind.LANDING, 1.9),
            ),
            display_name=f"低軌道→{label}直行",
            origin_requirements=req.ORBIT_SITE, destination_requirements=req.SURFACE_SITE,
        )
        routes[RouteId(f"base.route.{suffix}_leo")] = RouteDef(
            id=RouteId(f"base.route.{suffix}_leo"), origin_id=surface, destination_id=ids.LEO, transit_days=7,
            operations=(
                TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 1.9),
                TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 4.1),
            ),
            display_name=f"{label}→低軌道直行",
            origin_requirements=req.SURFACE_SITE, destination_requirements=req.ORBIT_SITE,
        )
        routes[RouteId(f"base.route.earth_{suffix}_direct")] = RouteDef(
            id=RouteId(f"base.route.earth_{suffix}_direct"), origin_id=ids.EARTH, destination_id=surface, transit_days=8,
            operations=(
                TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 9.4),
                TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 3.2),
                TransportOperationRequirement(TransportOperationKind.LANDING, 1.9),
            ),
            display_name=f"地球地表→{label}直行ミッション",
            origin_requirements=req.SURFACE_SITE, destination_requirements=req.SURFACE_SITE,
        )
    return routes


def build_external_transport_services() -> dict:
    launch = TransportPerformanceProfile(
        dry_mass_t=100.0, payload_t=30.0,
        operation_capabilities=(PoweredAscentCapability(10.2, 11.0, 120000.0),),
    )
    orbital = TransportPerformanceProfile(
        dry_mass_t=12.0, payload_t=20.0,
        operation_capabilities=(SpaceflightCapability(6.0),),
        endurance_days=120.0,
    )
    lander = TransportPerformanceProfile(
        dry_mass_t=7.0, payload_t=8.0,
        operation_capabilities=(PoweredAscentCapability(2.5, 2.5, 2000.0), LandingCapability(2.5, 2.5, 2000.0)),
    )
    direct = TransportPerformanceProfile(
        dry_mass_t=120.0, payload_t=18.0,
        operation_capabilities=(PoweredAscentCapability(10.2, 11.0, 120000.0), SpaceflightCapability(5.0), LandingCapability(2.5, 2.5, 2000.0)),
        endurance_days=30.0,
    )
    return {
        ids.EARTH_LEO_LAUNCH_SERVICE: ExternalTransportServiceDef(ids.EARTH_LEO_LAUNCH_SERVICE, "商業地表打上げ", 1.6, 4.0, launch, origin_requirements=req.ATMOSPHERIC_SURFACE_SITE, destination_requirements=req.ORBIT_SITE),
        ids.LEO_LUNAR_SERVICE: ExternalTransportServiceDef(ids.LEO_LUNAR_SERVICE, "商業軌道間輸送", 0.25, 5.0, orbital, origin_requirements=req.ORBIT_SITE, destination_requirements=req.ORBIT_SITE),
        ids.LUNAR_LANDING_SERVICE: ExternalTransportServiceDef(ids.LUNAR_LANDING_SERVICE, "商業真空地表着陸輸送", 0.20, 3.5, lander, origin_requirements=req.ORBIT_SITE, destination_requirements=req.VACUUM_SURFACE_SITE),
        ids.DIRECT_LUNAR_SERVICE: ExternalTransportServiceDef(ids.DIRECT_LUNAR_SERVICE, "商業地球―真空地表直行輸送", 0.12, 11.0, direct, origin_requirements=req.ATMOSPHERIC_SURFACE_SITE, destination_requirements=req.VACUUM_SURFACE_SITE),
    }


def build_vehicle_definitions() -> dict:
    """Owned base-game fleets are physical assets, not recurring money sinks.

    Their operation is constrained by vehicle performance, propellant, support
    infrastructure, turnaround time, production capacity, and material inputs.
    Monetary settlement remains on ExternalTransportServiceDef for commercial
    services and may still be used by other optional content.
    """
    return {
        ids.REUSABLE_LAUNCH_VEHICLE: VehicleDef(
            id=ids.REUSABLE_LAUNCH_VEHICLE,
            display_name="再使用型打上げヴィークル",
            performance=TransportPerformanceProfile(
                dry_mass_t=80.0, payload_t=25.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=45.0,
                propellant_t_per_total_t_per_km_s=0.040,
                operation_capabilities=(PoweredAscentCapability(10.0, 10.0, 110000.0, OperationAssetDisposition.ORIGIN),),
                operation_support_requirements=(OperationSupportRequirement(TransportOperationKind.POWERED_ASCENT, OperationSupportLocation.ORIGIN, "launch_operations"),),
                resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                endurance_days=14.0,
                generic_capabilities=("refueling_interface",),
            ),
            production=VehicleProductionSpec(
                capability_id="vehicle_assembly", days=10.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 20.0), (ids.MACHINERY, 8.0), (ids.PRECISION_ELECTRONICS, 2.0)),
            ),
            maintenance=VehicleMaintenanceSpec(capability_id="launch_vehicle_servicing", turnaround_days=5.0),
        ),
        ids.REUSABLE_ORBITAL_CARGO_TUG: VehicleDef(
            id=ids.REUSABLE_ORBITAL_CARGO_TUG,
            display_name="再使用型軌道間貨物船",
            performance=TransportPerformanceProfile(
                dry_mass_t=8.0, payload_t=12.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=4.0,
                propellant_t_per_total_t_per_km_s=0.020,
                operation_capabilities=(SpaceflightCapability(5.0),),
                resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                endurance_days=60.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                capability_id="vehicle_assembly", days=4.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 4.0), (ids.MACHINERY, 2.0), (ids.PRECISION_ELECTRONICS, 1.0)),
            ),
            maintenance=VehicleMaintenanceSpec(capability_id="spacecraft_servicing", turnaround_days=1.0),
        ),
        ids.REUSABLE_SURFACE_CARGO_LANDER: VehicleDef(
            id=ids.REUSABLE_SURFACE_CARGO_LANDER,
            display_name="再使用型地表貨物宇宙船",
            performance=TransportPerformanceProfile(
                dry_mass_t=5.0, payload_t=6.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=3.0,
                propellant_t_per_total_t_per_km_s=0.030,
                operation_capabilities=(SpaceflightCapability(5.0), PoweredAscentCapability(2.1, 2.0, 1000.0), LandingCapability(2.1, 2.0, 1000.0)),
                resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                endurance_days=30.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                capability_id="vehicle_assembly", days=3.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 2.5), (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 0.8)),
            ),
            maintenance=VehicleMaintenanceSpec(capability_id="spacecraft_servicing", turnaround_days=1.0),
        ),
    }


def initial_vehicle_deployments() -> tuple[tuple, ...]:
    return (
        (ids.REUSABLE_LAUNCH_VEHICLE, 1, ids.EARTH),
        (ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO),
        (ids.REUSABLE_SURFACE_CARGO_LANDER, 1, ids.LEO),
    )
