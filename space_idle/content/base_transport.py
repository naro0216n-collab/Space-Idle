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
    PassengerAccommodation,
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
    """Build surface access for every solid Body from physical World conditions.

    Vehicle and gateway eligibility use one ordinary Movement contract; named
    planets are not privileged and no per-origin/destination table exists.
    """
    rules: list[SurfaceAccessMovementRule] = []
    for body in sorted(graph.bodies.values(), key=lambda row: str(row.id)):
        if body.physical_surface is not PhysicalSurface.SOLID:
            continue
        gravity = body.representative_gravity_m_s2
        if gravity is None:
            continue  # Unknown physical input is not an artificial zero-gravity route.
        # Body definitions are physical subjects rather than Environment query
        # contexts. Read their statically owned BODY_GLOBAL facet directly.
        atmosphere = environment.static.body_facets.get((body.id, AtmosphereField))
        if atmosphere is None:
            continue  # The operation type cannot be selected without a known atmosphere.
        # Surface-to-low-orbit demand is an approximation of local escape speed.
        # Vehicle Delta-V and propellant share this one Content-derived value.
        has_dense_atmosphere = atmosphere.pressure_pa >= 50_000.0
        # Atmospheric launch requires additional ascent margin beyond a vacuum
        # ascent. Both cases derive from the same Body physics, without named
        # planet surface-access exceptions.
        ascent_factor = 0.84 if has_dense_atmosphere else 0.8
        characteristic_delta_v = max(0.05, ascent_factor * sqrt(2.0 * gravity * body.mean_radius_km * 1000.0) / 1000.0)
        descent_kind = (
            TransportOperationKind.ATMOSPHERIC_ENTRY if has_dense_atmosphere
            else TransportOperationKind.LANDING
        )
        rules.append(SurfaceAccessMovementRule(
            id=DefinitionId(f"base.movement.surface_access.{body.id}"),
            display_name=f"{body.display_name}地表アクセス",
            body_id=body.id,
            descent_operations=(TransportOperationRequirement(
                descent_kind, 0.0 if has_dense_atmosphere else characteristic_delta_v,
            ),),
            ascent_operations=(TransportOperationRequirement(
                TransportOperationKind.POWERED_ASCENT, characteristic_delta_v,
            ),),
            transit_days=2,
            gateway_capability_id="launch_operations" if has_dense_atmosphere else "surface_distribution",
            space_requirements=req.ORBIT_SITE,
            surface_requirements=req.ATMOSPHERIC_SURFACE_SITE if has_dense_atmosphere else req.SURFACE_SITE,
        ))
    return tuple(rules)


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
        ids.CREW_TRANSFER_SPACECRAFT: VehicleDef(
            id=ids.CREW_TRANSFER_SPACECRAFT,
            display_name="軌道間有人輸送船",
            performance=TransportPerformanceProfile(
                dry_mass_t=9.0, payload_t=3.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=5.0,
                propellant_t_per_total_t_per_km_s=0.018,
                operation_capabilities=(SpaceflightCapability(7.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=120.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=9.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 6.0), (ids.MACHINERY, 3.5), (ids.PRECISION_ELECTRONICS, 3.0)),
                prerequisite_technologies=frozenset({ids.LS_ATMOSPHERE_WATER_WASTE_01, ids.research_id("GN-NAVIGATION-04")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=4.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.0), (ids.MACHINERY, 1.75), (ids.PRECISION_ELECTRONICS, 1.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=3.0),
            passengers=PassengerAccommodation(
                seats=12, life_support_person_days_per_day=12, onboard_power_mw=1.5,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
            ),
        ),
        ids.ROBOTIC_SURFACE_PROSPECTOR: VehicleDef(
            id=ids.ROBOTIC_SURFACE_PROSPECTOR,
            display_name="自律地表地質探査車",
            performance=TransportPerformanceProfile(
                dry_mass_t=0.9, payload_t=0.2,
                operation_capabilities=(SurfaceTransportCapability(45.0),),
                endurance_days=360.0,
                generic_capabilities=("surface_survey", "robotic_prospecting_sensor"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=3.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 0.9), (ids.MACHINERY, 0.6), (ids.PRECISION_ELECTRONICS, 1.2)),
                prerequisite_technologies=frozenset({ids.research_id("SM-SURFACE-MOBILITY-02"), ids.SS_SENSING_04}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.45), (ids.MACHINERY, 0.3), (ids.PRECISION_ELECTRONICS, 0.6)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="surface_vehicle_servicing", turnaround_days=1.0),
        ),
        ids.PRESSURIZED_SURFACE_ROVER: VehicleDef(
            id=ids.PRESSURIZED_SURFACE_ROVER,
            display_name="与圧有人地表探査車",
            performance=TransportPerformanceProfile(
                dry_mass_t=6.0, payload_t=1.0,
                operation_capabilities=(SurfaceTransportCapability(110.0),),
                endurance_days=90.0,
                generic_capabilities=("surface_mobility",),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=8.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 5.0), (ids.MACHINERY, 3.0), (ids.PRECISION_ELECTRONICS, 2.0)),
                prerequisite_technologies=frozenset({ids.LS_ATMOSPHERE_WATER_WASTE_01, ids.research_id("SM-SURFACE-MOBILITY-04")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=3.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 2.5), (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 1.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="surface_vehicle_servicing", turnaround_days=2.0),
            passengers=PassengerAccommodation(
                seats=6, life_support_person_days_per_day=6, onboard_power_mw=0.8,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
            ),
        ),
        ids.RADAR_MAPPING_ORBITER: VehicleDef(
            id=ids.RADAR_MAPPING_ORBITER,
            display_name="合成開口レーダー地質探査衛星",
            performance=TransportPerformanceProfile(
                dry_mass_t=3.0, payload_t=0.8,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=1.2,
                propellant_t_per_total_t_per_km_s=0.018,
                operation_capabilities=(SpaceflightCapability(6.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=800.0,
                generic_capabilities=("radar_sounder", "docking_interface", "refueling_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=6.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 2.8), (ids.MACHINERY, 1.4), (ids.PRECISION_ELECTRONICS, 3.0)),
                prerequisite_technologies=frozenset({ids.research_id("SS-SENSING-06"), ids.research_id("GN-NAVIGATION-03")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=2.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 1.4), (ids.MACHINERY, 0.7), (ids.PRECISION_ELECTRONICS, 1.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=2.0),
        ),
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
                prerequisite_technologies=frozenset({ids.research_id("CH-COMBUSTION-01"), ids.research_id("GN-NAVIGATION-01")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=5.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 10.0), (ids.MACHINERY, 4.0), (ids.PRECISION_ELECTRONICS, 1.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="launch_vehicle_servicing", turnaround_days=5.0),
            passengers=PassengerAccommodation(
                seats=6, life_support_person_days_per_day=6, onboard_power_mw=0.6,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
            ),
        ),
        ids.MODULAR_CARGO_LAUNCHER: VehicleDef(
            id=ids.MODULAR_CARGO_LAUNCHER,
            display_name="モジュール集成型貨物打上げ機",
            performance=TransportPerformanceProfile(
                dry_mass_t=160.0, payload_t=52.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=105.0,
                propellant_t_per_total_t_per_km_s=0.021,
                operation_capabilities=(PoweredAscentCapability(
                    10.0, 10.0, 110000.0, 450.0, OperationAssetDisposition.ORIGIN,
                ),),
                operation_support_requirements=(OperationSupportRequirement(
                    TransportOperationKind.POWERED_ASCENT,
                    OperationSupportLocation.ORIGIN, "launch_operations",
                ),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=14.0,
                generic_capabilities=("refueling_interface",),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=24.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 42.0),
                           (ids.MACHINERY, 18.0), (ids.PRECISION_ELECTRONICS, 6.0)),
                prerequisite_technologies=frozenset({
                    ids.research_id("CH-COMBUSTION-09"),
                    ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09"),
                    ids.research_id("GN-NAVIGATION-06"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=12.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 21.0),
                                             (ids.MACHINERY, 9.0),
                                             (ids.PRECISION_ELECTRONICS, 3.0)),
            ),
            maintenance=VehicleMaintenanceSpec(
                service_type="launch_vehicle_servicing", turnaround_days=8.0,
            ),
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
                prerequisite_technologies=frozenset({ids.research_id("CH-COMBUSTION-06"), ids.research_id("GN-NAVIGATION-04")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=2.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 2.0), (ids.MACHINERY, 1.0), (ids.PRECISION_ELECTRONICS, 0.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
            passengers=PassengerAccommodation(
                seats=4, life_support_person_days_per_day=4, onboard_power_mw=0.4,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
            ),
        ),
        ids.HEAVY_ORBITAL_FREIGHTER: VehicleDef(
            id=ids.HEAVY_ORBITAL_FREIGHTER,
            display_name="大型軌道間モジュール貨物船",
            performance=TransportPerformanceProfile(
                dry_mass_t=22.0, payload_t=44.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=28.0,
                propellant_t_per_total_t_per_km_s=0.011,
                operation_capabilities=(SpaceflightCapability(14.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=520.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=20.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 26.0),
                           (ids.MACHINERY, 11.0), (ids.PRECISION_ELECTRONICS, 5.0)),
                prerequisite_technologies=frozenset({
                    ids.LM_LOGISTICS_MAINTENANCE_13,
                    ids.MC_MANUFACTURING_CONSTRUCTION_05,
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=9.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 13.0),
                                             (ids.MACHINERY, 5.5), (ids.PRECISION_ELECTRONICS, 2.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=7.0),
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
                prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-06"), ids.research_id("CO-RF-COMMUNICATIONS-04")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=8.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 6.0),
                                            (ids.MACHINERY, 2.5), (ids.PRECISION_ELECTRONICS, 2.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=8.0),
            passengers=PassengerAccommodation(
                seats=8, life_support_person_days_per_day=8, onboard_power_mw=0.8,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
            ),
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
                prerequisite_technologies=frozenset({ids.research_id("EDL-EDL-08")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=6.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 4.0),
                                            (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 1.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=6.0),
            passengers=PassengerAccommodation(
                seats=4, life_support_person_days_per_day=4, onboard_power_mw=0.4,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
            ),
        ),
        ids.ORBITAL_OBSERVATION_SPACECRAFT: VehicleDef(
            id=ids.ORBITAL_OBSERVATION_SPACECRAFT,
            display_name="自律軌道観測宇宙機",
            performance=TransportPerformanceProfile(
                dry_mass_t=2.0, payload_t=0.3,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=0.8,
                propellant_t_per_total_t_per_km_s=0.018,
                operation_capabilities=(SpaceflightCapability(5.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=180.0,
                generic_capabilities=("optical_observation_instrument", "docking_interface", "refueling_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=3.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 1.5),
                           (ids.MACHINERY, 1.0), (ids.PRECISION_ELECTRONICS, 1.0)),
                prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-01"), ids.SS_SENSING_01}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.75),
                                            (ids.MACHINERY, 0.5), (ids.PRECISION_ELECTRONICS, 0.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
        ),
        ids.ORBITAL_RESOURCE_MAPPING_SPACECRAFT: VehicleDef(
            id=ids.ORBITAL_RESOURCE_MAPPING_SPACECRAFT,
            display_name="軌道分光資源マッピング衛星",
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
                prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-02"), DefinitionId("SS-SENSING-01")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.6), (ids.MACHINERY, 0.4), (ids.PRECISION_ELECTRONICS, 0.75)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
        ),
        # Electric propulsion consumes locally manufactured liquid hydrogen,
        # not a fictitious interchangeable Chemical Propellant stock. The
        # additional onboard electrical plant trades dry mass and slower
        # transit for considerably less reaction mass at high Delta-V.
        ids.HALL_ELECTRIC_CARGO_TUG: VehicleDef(
            id=ids.HALL_ELECTRIC_CARGO_TUG,
            display_name="ホール電気推進軌道間貨物船",
            performance=TransportPerformanceProfile(
                dry_mass_t=13.0, payload_t=14.0, transit_time_multiplier=2.4,
                propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=3.2,
                propellant_t_per_total_t_per_km_s=0.0025,
                operation_capabilities=(SpaceflightCapability(30.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=4000.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=16.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 13.0),
                           (ids.MACHINERY, 5.5), (ids.PRECISION_ELECTRONICS, 8.0)),
                prerequisite_technologies=frozenset({
                    ids.research_id("EP-PLASMA-THRUSTERS-06"),
                    ids.research_id("GN-NAVIGATION-06"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=8.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 6.5),
                                             (ids.MACHINERY, 2.75), (ids.PRECISION_ELECTRONICS, 4.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=6.0),
        ),
        ids.ION_PROPULSION_SCIENCE_PROBE: VehicleDef(
            id=ids.ION_PROPULSION_SCIENCE_PROBE,
            display_name="グリッド式イオン推進深宇宙探査機",
            performance=TransportPerformanceProfile(
                dry_mass_t=4.5, payload_t=1.1, transit_time_multiplier=2.0,
                propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=1.2,
                propellant_t_per_total_t_per_km_s=0.0017,
                operation_capabilities=(SpaceflightCapability(45.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=30000.0,
                generic_capabilities=("survey_sensor", "docking_interface", "refueling_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=12.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 6.0),
                           (ids.MACHINERY, 3.0), (ids.PRECISION_ELECTRONICS, 6.0)),
                prerequisite_technologies=frozenset({
                    ids.research_id("EP-PLASMA-THRUSTERS-04"),
                    ids.research_id("EP-PLASMA-THRUSTERS-07"),
                    ids.research_id("SS-SENSING-01"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=5.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.0),
                                             (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 3.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=4.0),
        ),
        # Hydrogen flows through an onboard reactor-heated nozzle. Its high
        # thrust keeps travel time close to chemical propulsion, unlike the
        # low-thrust electric tug, while the reactor/thermal hardware raises
        # manufacturing material, maintenance and Research commitments.
        ids.NUCLEAR_THERMAL_CARGO_SHIP: VehicleDef(
            id=ids.NUCLEAR_THERMAL_CARGO_SHIP,
            display_name="水素核熱推進・惑星間貨物輸送船",
            performance=TransportPerformanceProfile(
                dry_mass_t=28.0, payload_t=40.0, transit_time_multiplier=1.05,
                propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=22.0,
                propellant_t_per_total_t_per_km_s=0.005,
                operation_capabilities=(SpaceflightCapability(38.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=17000.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=26.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 23.0),
                           (ids.MACHINERY, 13.0), (ids.PRECISION_ELECTRONICS, 8.0)),
                prerequisite_technologies=frozenset({
                    ids.research_id("NT-NUCLEAR-THERMAL-04"),
                    ids.research_id("FP-REACTOR-POWER-03"),
                    ids.research_id("MC-MANUFACTURING-CONSTRUCTION-05"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=11.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 11.5),
                                             (ids.MACHINERY, 6.5), (ids.PRECISION_ELECTRONICS, 4.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=9.0),
        ),
        ids.NUCLEAR_THERMAL_CREW_SHIP: VehicleDef(
            id=ids.NUCLEAR_THERMAL_CREW_SHIP,
            display_name="核熱推進・有人深宇宙航行船",
            performance=TransportPerformanceProfile(
                dry_mass_t=33.0, payload_t=25.0, transit_time_multiplier=1.12,
                propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=15.0,
                propellant_t_per_total_t_per_km_s=0.0045,
                operation_capabilities=(SpaceflightCapability(50.0),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=12000.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=38.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 31.0),
                           (ids.MACHINERY, 17.0), (ids.PRECISION_ELECTRONICS, 13.0)),
                prerequisite_technologies=frozenset({
                    ids.research_id("NT-NUCLEAR-THERMAL-07"),
                    ids.research_id("LS-ATMOSPHERE-WATER-WASTE-05"),
                    ids.research_id("HB-HABITATION-PROTECTION-04"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=16.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 15.5),
                                             (ids.MACHINERY, 8.5), (ids.PRECISION_ELECTRONICS, 6.5)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=12.0),
            passengers=PassengerAccommodation(
                seats=10, life_support_person_days_per_day=10, onboard_power_mw=2.0,
                power_mw_per_person=0.14,
                net_resources_per_person_day=((ids.FOOD, 0.002),
                                              (ids.WATER, 0.003), (ids.OXYGEN, 0.002)),
            ),
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
                prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-06"), ids.research_id("SS-SENSING-01"), ids.research_id("CO-RF-COMMUNICATIONS-04")}),
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
                prerequisite_technologies=frozenset({ids.research_id("SM-SURFACE-MOBILITY-01")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.75), (ids.MACHINERY, 0.5), (ids.PRECISION_ELECTRONICS, 0.125)),
            ),
            maintenance=VehicleMaintenanceSpec(turnaround_days=0.25),
        ),
        ids.REUSABLE_SURFACE_CARGO_LANDER: VehicleDef(
            id=ids.REUSABLE_SURFACE_CARGO_LANDER,
            display_name="小型再使用着陸貨物艇",
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
                prerequisite_technologies=frozenset({ids.research_id("CH-COMBUSTION-01"), ids.research_id("EDL-EDL-06")}),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=1.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 1.25), (ids.MACHINERY, 0.75), (ids.PRECISION_ELECTRONICS, 0.4)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
        ),
        # Compact low-gravity round-trip ferry: reduced per-leg propellant
        # relative to the multi-body throttleable lander, but a lower thrust
        # envelope and a distinct maintenance/production investment.
        ids.LOW_GRAVITY_CARGO_FERRY: VehicleDef(
            id=ids.LOW_GRAVITY_CARGO_FERRY,
            display_name="低重力往復貨物フェリー",
            performance=TransportPerformanceProfile(
                dry_mass_t=7.0, payload_t=8.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=5.0,
                propellant_t_per_total_t_per_km_s=0.015,
                operation_capabilities=(
                    SpaceflightCapability(4.5),
                    PoweredAscentCapability(2.3, 2.8, 900.0, 410.0),
                    LandingCapability(2.3, 2.8, 900.0, 410.0),
                ),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=45.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=7.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 6.5),
                           (ids.MACHINERY, 4.0), (ids.PRECISION_ELECTRONICS, 3.1)),
                prerequisite_technologies=frozenset({
                    ids.research_id("CH-COMBUSTION-08"),
                    ids.research_id("LM-LOGISTICS-MAINTENANCE-14"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=2.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.25),
                                             (ids.MACHINERY, 2.0),
                                             (ids.PRECISION_ELECTRONICS, 1.55)),
            ),
            maintenance=VehicleMaintenanceSpec(
                service_type="spacecraft_servicing", turnaround_days=1.8,
            ),
        ),
        ids.THROTTLEABLE_CARGO_LANDER: VehicleDef(
            id=ids.THROTTLEABLE_CARGO_LANDER,
            display_name="推力可変式地表アクセス貨物艇",
            performance=TransportPerformanceProfile(
                dry_mass_t=9.0, payload_t=10.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=11.0,
                propellant_t_per_total_t_per_km_s=0.021,
                operation_capabilities=(
                    SpaceflightCapability(9.0),
                    PoweredAscentCapability(4.5, 5.0, 1500.0, 440.0),
                    LandingCapability(4.5, 5.0, 1500.0, 440.0),
                ),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=75.0,
                generic_capabilities=("refueling_interface", "docking_interface"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=8.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 6.0),
                           (ids.MACHINERY, 4.0), (ids.PRECISION_ELECTRONICS, 2.2)),
                prerequisite_technologies=frozenset({
                    ids.research_id("CH-COMBUSTION-08"),
                    ids.research_id("EDL-EDL-08"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=3.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.0),
                                             (ids.MACHINERY, 2.0),
                                             (ids.PRECISION_ELECTRONICS, 1.1)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=3.5),
        ),
    }
