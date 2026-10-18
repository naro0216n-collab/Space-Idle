"""Fusion-fuel-limited freighter modeled through physical Fleet operations.

Fuel isotopes are an explicit Resource manufactured by Industry. All phases
of ownership and replenishment use the normal Transport/Fleet contracts;
this does not install a free reactor or enable external beam propulsion.
"""
from __future__ import annotations

from ..shared import DefinitionId
from ..transport import (
    SpaceflightCapability, TransportPerformanceProfile, ResourceSupportRequirement,
    OperationSupportRequirement, OperationSupportLocation, OperationServiceRequirement,
    VehicleDef, VehicleMaintenanceSpec, VehicleProductionSpec, VehicleRetirementSpec,
)
from . import base_ids as ids


def build_concept_vehicle_defs() -> tuple[VehicleDef, ...]:
    return (
        VehicleDef(
            id=DefinitionId('planned.vehicle.beamed_sail_cargo_probe'),
            display_name='位相合成ビーム帆貨物機',
            performance=TransportPerformanceProfile(
                dry_mass_t=7.5, payload_t=16.0,
                # Beamed acceleration supplies momentum externally; the ship
                # does not synthesize propellant or freely accelerate alone.
                operation_capabilities=(SpaceflightCapability(16.0),),
                operation_support_requirements=(
                    OperationSupportRequirement('spaceflight', OperationSupportLocation.ORIGIN,
                                                'phased_beam_emitter'),
                    OperationSupportRequirement('spaceflight', OperationSupportLocation.DESTINATION,
                                                'phased_beam_emitter'),
                ),
                operation_service_requirements=(
                    OperationServiceRequirement('spaceflight', OperationSupportLocation.ORIGIN,
                                                'beam_momentum_transfer', .017, max_distance_km=600000000.0),
                    OperationServiceRequirement('spaceflight', OperationSupportLocation.DESTINATION,
                                                'beam_momentum_transfer', .017, max_distance_km=600000000.0),
                ),
                generic_capabilities=('beam_sail_receiver', 'docking_interface'),
                endurance_days=10000.0,
            ),
            production=VehicleProductionSpec(
                service_type='vehicle_assembly', days=155.0,
                resources=((ids.FABRICATED_STRUCTURE, 39.0),
                           (ids.OPTICAL_INSTRUMENT_PACKAGES, 29.0),
                           (ids.HARDENED_ELECTRONICS, 17.0)),
                prerequisite_technologies=frozenset({DefinitionId('SF-BEAM-02'),
                                                    DefinitionId('SF-BEAM-03')}),
            ),
            maintenance=VehicleMaintenanceSpec(
                service_type='spacecraft_servicing', turnaround_days=11.0,
                resources=((ids.THERMAL_CONTROL_ASSEMBLIES, .15),),
            ),
            retirement=VehicleRetirementSpec(
                service_type='vehicle_assembly', work_days_per_unit=43.0,
                recovery_resources_per_unit=((ids.FABRICATED_STRUCTURE, 17.0),
                                             (ids.OPTICAL_INSTRUMENT_PACKAGES, 8.0)),
            ),
        ),
        VehicleDef(
            id=DefinitionId('planned.vehicle.fusion_freighter'),
            display_name='核融合燃料推進長距離貨物船',
            performance=TransportPerformanceProfile(
                dry_mass_t=92., payload_t=210.,
                # Propellant-rate models isotope fuel used per imparted delta-v.
                # This deliberately has a finite tank and requires physical
                # extraction/refining upstream of Fleet replenishment.
                propellant_resource_id=ids.FUSION_FUEL_ISOTOPES,
                propellant_capacity_t=22.,
                propellant_t_per_total_t_per_km_s=.00045,
                operation_capabilities=(SpaceflightCapability(28.),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.FUSION_FUEL_ISOTOPES, 'vehicle_refueling', 'fusion_fuel_fitting',
                ),),
                generic_capabilities=('fusion_fuel_fitting', 'docking_interface'),
                endurance_days=6500.,
            ),
            production=VehicleProductionSpec(
                service_type='vehicle_assembly', days=170.,
                resources=((ids.FABRICATED_STRUCTURE, 68.),
                           (ids.REFRACTORY_ALLOY, 39.),
                           (ids.HARDENED_ELECTRONICS, 25.)),
                prerequisite_technologies=frozenset({DefinitionId('SF-FUSION-03')}),
            ),
            maintenance=VehicleMaintenanceSpec(
                service_type='spacecraft_servicing', turnaround_days=22.,
                resources=((ids.THERMAL_CONTROL_ASSEMBLIES, .65),
                           (ids.REFRACTORY_ALLOY, .21)),
            ),
            retirement=VehicleRetirementSpec(
                service_type='vehicle_assembly', work_days_per_unit=60.,
                recovery_resources_per_unit=((ids.FABRICATED_STRUCTURE, 30.),
                                             (ids.REFRACTORY_ALLOY, 11.),
                                             (ids.HARDENED_ELECTRONICS, 6.)),
            ),
        ),
    )
