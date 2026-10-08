from __future__ import annotations

from math import sqrt

from ..shared import DefinitionId
from ..spatial import AtmosphereField, EnvironmentResolver, PhysicalSurface, SpatialGraph
from ..transport import (
    AtmosphericEntryCapability,
    LandingCapability,
    OperationSupportLocation,
    OperationSupportRequirement,
    ResourceSupportRequirement,
    PoweredAscentCapability,
    SpaceflightCapability,
    SurfaceTransportCapability,
    TransportOperationKind,
    TransportOperationRequirement,
    TransportPerformanceProfile,
    VehicleDef,
    OperationAssetDisposition,
    VehicleMaintenanceSpec,
    VehicleProductionSpec,
    VehicleRetirementSpec,
)
from ..transport.movement import SpaceflightMovementRule, SurfaceAccessMovementRule, SurfaceTransportMovementRule
from . import base_ids as ids
from . import base_requirements as req

def build_surface_movement_rules() -> tuple[SurfaceTransportMovementRule, ...]:
    return (
        SurfaceTransportMovementRule(
            id=DefinitionId("base.movement.surface_transport"),
            display_name="地表輸送",
            operation=TransportOperationRequirement(TransportOperationKind.SURFACE_TRANSPORT, 0.0),
            gateway_capability_id="surface_distribution",
            transit_days=1,
        ),
    )


def build_surface_access_movement_rules(
    graph: SpatialGraph, environment: EnvironmentResolver,
) -> tuple[SurfaceAccessMovementRule, ...]:
    """Build one surface/space operation profile per physical surface.

    The existing Earth/Moon access Content retains its established profile.
    Additional bodies derive the orbital-access Delta-V scale from the *same*
    Body gravitational input used by Spatial transfer, and their atmosphere
    selects an entry or powered landing operation. No OD-specific routes or
    additional planet-specific Movement evaluators are registered.
    """
    baseline = (
        SurfaceAccessMovementRule(
            id=DefinitionId("base.movement.earth_surface_access"),
            display_name="地球地表アクセス",
            body_id=ids.EARTH_BODY,
            descent_operations=(
                TransportOperationRequirement(TransportOperationKind.ATMOSPHERIC_ENTRY, 0.0),
            ),
            ascent_operations=(
                TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 9.4),
            ),
            transit_days=2,
            gateway_capability_id="launch_operations",
            space_requirements=req.ORBIT_SITE,
            surface_requirements=req.ATMOSPHERIC_SURFACE_SITE,
        ),
        SurfaceAccessMovementRule(
            id=DefinitionId("base.movement.lunar_surface_access"),
            display_name="月面アクセス",
            body_id=ids.MOON,
            descent_operations=(
                TransportOperationRequirement(TransportOperationKind.LANDING, 1.9),
            ),
            ascent_operations=(
                TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 1.9),
            ),
            transit_days=3,
            gateway_capability_id="surface_distribution",
            space_requirements=req.ORBIT_SITE,
            surface_requirements=req.SURFACE_SITE,
        ),
    )
    derived: list[SurfaceAccessMovementRule] = []
    for body in sorted(graph.bodies.values(), key=lambda row: str(row.id)):
        if body.physical_surface is not PhysicalSurface.SOLID or body.id in (ids.EARTH_BODY, ids.MOON):
            continue
        gravity = body.representative_gravity_m_s2
        if gravity is None:
            continue  # Unknown physical input is not an artificial zero-gravity route.
        # Body definitions are physical subjects rather than Environment query
        # contexts. Read their statically owned BODY_GLOBAL facet directly.
        atmosphere = environment.static.body_facets.get((body.id, AtmosphereField))
        if atmosphere is None:
            continue  # The operation type cannot be selected without a known atmosphere.
        # Approximate powered access to a low orbit as 80% of local escape
        # speed. This is a Content operating assumption, not an ephemeris or
        # instant distance; Vehicle Delta-V and propellant share this one value.
        characteristic_delta_v = max(0.05, 0.8 * sqrt(2.0 * gravity * body.mean_radius_km * 1000.0) / 1000.0)
        has_dense_atmosphere = atmosphere.pressure_pa >= 50_000.0
        descent_kind = (
            TransportOperationKind.ATMOSPHERIC_ENTRY if has_dense_atmosphere
            else TransportOperationKind.LANDING
        )
        derived.append(SurfaceAccessMovementRule(
            id=DefinitionId(f"base.movement.{str(body.id).split('.')[-1]}_surface_access"),
            display_name=f"{body.display_name}地表アクセス",
            body_id=body.id,
            descent_operations=(TransportOperationRequirement(
                descent_kind, 0.0 if has_dense_atmosphere else characteristic_delta_v,
            ),),
            ascent_operations=(TransportOperationRequirement(
                TransportOperationKind.POWERED_ASCENT, characteristic_delta_v,
            ),),
            transit_days=2,
            space_requirements=req.ORBIT_SITE,
            surface_requirements=req.ATMOSPHERIC_SURFACE_SITE if has_dense_atmosphere else req.SURFACE_SITE,
        ))
    return baseline + tuple(derived)


def build_spaceflight_movement_rules() -> tuple[SpaceflightMovementRule, ...]:
    # 384,400 km / 76,880 km/day = 5 characteristic days for the baseline
    # Earth-Moon anchors. New bodies reuse this profile from their own Spatial
    # transport geometry rather than adding OD-specific definitions.
    return (
        SpaceflightMovementRule(
            id=DefinitionId("base.movement.spaceflight"),
            display_name="宇宙航行",
            operation_type=TransportOperationKind.SPACEFLIGHT,
            characteristic_speed_km_per_day=76_880.0,
            minimum_transit_days=1,
        ),
    )


def build_vehicle_definitions() -> dict:
    """Owned base-game fleets are constrained only by physical requirements."""
    return {
        ids.REUSABLE_LAUNCH_VEHICLE: VehicleDef(
            id=ids.REUSABLE_LAUNCH_VEHICLE,
            display_name="再使用型打上げヴィークル",
            performance=TransportPerformanceProfile(
                dry_mass_t=80.0, payload_t=25.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=45.0,
                propellant_t_per_total_t_per_km_s=0.040,
                operation_capabilities=(PoweredAscentCapability(10.0, 10.0, 110000.0, 400.0, OperationAssetDisposition.ORIGIN),),
                operation_support_requirements=(OperationSupportRequirement(TransportOperationKind.POWERED_ASCENT, OperationSupportLocation.ORIGIN, "launch_operations"),),
                resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                endurance_days=14.0,
                generic_capabilities=("refueling_interface",),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=10.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 20.0), (ids.MACHINERY, 8.0), (ids.PRECISION_ELECTRONICS, 2.0)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=5.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 10.0), (ids.MACHINERY, 4.0), (ids.PRECISION_ELECTRONICS, 1.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="launch_vehicle_servicing", turnaround_days=5.0),
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
                service_type="vehicle_assembly", days=4.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 4.0), (ids.MACHINERY, 2.0), (ids.PRECISION_ELECTRONICS, 1.0)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=2.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 2.0), (ids.MACHINERY, 1.0), (ids.PRECISION_ELECTRONICS, 0.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
        ),
        ids.DEEP_SPACE_FREIGHTER: VehicleDef(
            id=ids.DEEP_SPACE_FREIGHTER,
            display_name="長距離軌道間貨物船",
            performance=TransportPerformanceProfile(
                dry_mass_t=12.0, payload_t=16.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=18.0,
                propellant_t_per_total_t_per_km_s=0.008,
                operation_capabilities=(SpaceflightCapability(35.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=30_000.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=18.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 12.0),
                           (ids.MACHINERY, 5.0), (ids.PRECISION_ELECTRONICS, 4.0)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=8.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 6.0),
                                            (ids.MACHINERY, 2.5), (ids.PRECISION_ELECTRONICS, 2.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=8.0),
        ),
        ids.INTERPLANETARY_LANDER: VehicleDef(
            id=ids.INTERPLANETARY_LANDER,
            display_name="惑星間地表輸送機",
            performance=TransportPerformanceProfile(
                dry_mass_t=8.0, payload_t=8.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=13.0,
                propellant_t_per_total_t_per_km_s=0.012,
                operation_capabilities=(
                    SpaceflightCapability(25.0),
                    PoweredAscentCapability(9.0, 12.0, 500_000.0, 500.0),
                    LandingCapability(9.0, 12.0, 500_000.0, 500.0),
                    AtmosphericEntryCapability(500_000.0, 500.0, 40.0),
                ),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=2_000.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=12.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 8.0),
                           (ids.MACHINERY, 3.0), (ids.PRECISION_ELECTRONICS, 3.0)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=6.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 4.0),
                                            (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 1.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=6.0),
        ),
        ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT: VehicleDef(
            id=ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT,
            display_name="月周回資源観測宇宙機",
            performance=TransportPerformanceProfile(
                dry_mass_t=2.5, payload_t=0.5,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=1.0,
                propellant_t_per_total_t_per_km_s=0.018,
                operation_capabilities=(SpaceflightCapability(5.0),),
                resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                endurance_days=180.0,
                generic_capabilities=("survey_sensor", "docking_interface", "refueling_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=3.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 1.2), (ids.MACHINERY, 0.8), (ids.PRECISION_ELECTRONICS, 1.5)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.6), (ids.MACHINERY, 0.4), (ids.PRECISION_ELECTRONICS, 0.75)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
        ),
        ids.DEEP_SPACE_PROBE: VehicleDef(
            id=ids.DEEP_SPACE_PROBE,
            display_name="長距離無人探査機",
            performance=TransportPerformanceProfile(
                dry_mass_t=3.0, payload_t=1.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=3.0,
                propellant_t_per_total_t_per_km_s=0.015,
                operation_capabilities=(SpaceflightCapability(20.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=20_000.0,
                generic_capabilities=("survey_sensor", "docking_interface", "refueling_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=14.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 7.0), (ids.MACHINERY, 3.0),
                           (ids.PRECISION_ELECTRONICS, 5.0)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=5.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.0),
                                             (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 2.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=5.0),
        ),
        ids.SURFACE_CARGO_HAULER: VehicleDef(
            id=ids.SURFACE_CARGO_HAULER,
            display_name="地表貨物輸送車",
            performance=TransportPerformanceProfile(
                dry_mass_t=4.0, payload_t=12.0,
                operation_capabilities=(SurfaceTransportCapability(180.0),),
                endurance_days=120.0,
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=2.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 1.5), (ids.MACHINERY, 1.0), (ids.PRECISION_ELECTRONICS, 0.25)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.75), (ids.MACHINERY, 0.5), (ids.PRECISION_ELECTRONICS, 0.125)),
            ),
            maintenance=VehicleMaintenanceSpec(turnaround_days=0.25),
        ),
        ids.REUSABLE_SURFACE_CARGO_LANDER: VehicleDef(
            id=ids.REUSABLE_SURFACE_CARGO_LANDER,
            display_name="再使用型地表貨物宇宙船",
            performance=TransportPerformanceProfile(
                dry_mass_t=5.0, payload_t=6.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=3.0,
                propellant_t_per_total_t_per_km_s=0.030,
                operation_capabilities=(SpaceflightCapability(5.0), PoweredAscentCapability(2.1, 2.0, 1000.0, 420.0), LandingCapability(2.1, 2.0, 1000.0, 420.0)),
                resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                endurance_days=30.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=3.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 2.5), (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 0.8)),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 1.25), (ids.MACHINERY, 0.75), (ids.PRECISION_ELECTRONICS, 0.4)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
        ),
    }
