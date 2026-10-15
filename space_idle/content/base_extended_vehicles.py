"""Authored long-range spacecraft: physical payload, delta-V, fuel and acquisition.

These use the same fleet, reservation, propulsion, service and lifecycle domain
contracts as all other spacecraft; no instant Technology travel/unlock is added.
"""
from __future__ import annotations

from ..shared import DefinitionId
from ..transport import (
    VehicleDef, TransportPerformanceProfile, SpaceflightCapability,
    ResourceSupportRequirement, VehicleProductionSpec, VehicleRetirementSpec,
    VehicleMaintenanceSpec, PassengerAccommodation,
)
from . import base_ids as ids

# slug/name, mass t, payload t, delta-v km/s, propellant t per total t/dv,
# tank t, endurance d, production work d, production stocks t, technology,
# passenger seats, research/operation equipment capabilities.
_SHIPS = (
    ('industrial_local_shuttle', '非地球工業拠点連絡貨物艇', 10., 13., 5.0, .015, 5.5, 120., 9.,
     (('structural_components', 8.),('machinery', 4.),('precision_electronics', 2.)), ('X5-LOCAL-PROPELLANT',), 0, ('docking_interface',)),
    ('mineral_sample_returner', '鉱物分析・原料少量回収機', 4., 2., 7.0, .013, 1.5, 190., 6.,
     (('structural_components', 3.),('machinery', 2.),('precision_electronics', 2.)), ('RP-RESOURCE-CHAIN-10',), 0, ('sample_return_interface','optical_observation_instrument')),
    ('interplanetary_cargo_carrier', '高積載惑星間貨物船', 44., 120., 8.5, .0068, 26., 740., 28.,
     (('fabricated_structure', 38.),('machinery', 20.),('precision_electronics', 11.)), ('OD-06',), 0, ('docking_interface',)),
    ('electric_ore_freighter', '低推進剤高電力貨物船', 29., 84., 8.0, .0026, 9.0, 1100., 33.,
     (('fabricated_structure', 27.),('machinery', 18.),('thermal_control_assemblies', 8.)), ('PL-ELECTRIC-FREIGHT-HEAT',), 0, ('docking_interface',)),
    ('regional_personnel_ship', '惑星間有人定期便', 42., 32., 8.0, .008, 17., 600., 31.,
     (('fabricated_structure', 30.),('machinery', 19.),('precision_electronics', 12.)), ('OD-06',), 24, ('docking_interface','pressurized_crew_transport')),
    ('long_endurance_freighter', '深宇宙長期物資輸送船', 50., 70., 12.0, .0037, 18., 2800., 49.,
     (('fabricated_structure', 44.),('machinery', 29.),('hardened_electronics', 10.)), ('X7-LONG-DURATION-FLEET',), 0, ('docking_interface',)),
    ('extreme_system_relay_probe', '外惑星高放射線中継科学機', 12., 4., 13.0, .005, 4.0, 4200., 30.,
     (('radiation_shielding_panels', 7.),('hardened_electronics', 8.),('thermal_control_assemblies', 4.)), ('X7-DEEP-SPACE-RELAY',), 0, ('optical_observation_instrument','deep_space_relay')),
    ('multi_region_resource_carrier', '広域大質量補給船', 84., 290., 14.0, .002, 15., 4200., 80.,
     (('fabricated_structure', 75.),('machinery', 47.),('hardened_electronics', 22.)), ('PL-MULTIREGION-CARGO-CUSTODY',), 0, ('docking_interface',)),
    ('autonomous_replacement_barge', '自律設備更新ユニット搬送船', 36., 92., 15.0, .0022, 9., 5000., 55.,
     (('fabricated_structure', 33.),('machinery', 25.),('hardened_electronics', 17.)), ('X8-AUTONOMOUS-INFRASTRUCTURE',), 0, ('docking_interface','autonomous_equipment_servicing')),
)


def build_extended_vehicle_defs() -> tuple[VehicleDef, ...]:
    rows = []
    for slug, name, mass, payload, delta_v, fuel_rate, tank, endurance, days, stocks, technologies, seats, caps in _SHIPS:
        identity = DefinitionId('planned.vehicle.' + slug)
        supply = tuple((DefinitionId('base.resource.' + resource), amount) for resource, amount in stocks)
        passengers = PassengerAccommodation(
            seats=seats,
            life_support_person_days_per_day=float(seats),
            onboard_power_mw=seats * 0.15,
            power_mw_per_person=0.10 if seats else 0.0,
            net_resources_per_person_day=((ids.FOOD, .002),(ids.WATER,.003),(ids.OXYGEN,.002)) if seats else (),
        )
        rows.append(VehicleDef(
            id=identity, display_name=name,
            performance=TransportPerformanceProfile(
                dry_mass_t=mass, payload_t=payload,
                propellant_resource_id=ids.PROPELLANT,
                propellant_capacity_t=tank,
                propellant_t_per_total_t_per_km_s=fuel_rate,
                operation_capabilities=(SpaceflightCapability(delta_v),),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT,'vehicle_refueling','refueling_interface'),),
                endurance_days=endurance,
                generic_capabilities=('refueling_interface',) + caps,
            ),
            production=VehicleProductionSpec(
                service_type='vehicle_assembly',days=days,resources=supply,
                prerequisite_technologies=frozenset(DefinitionId(tech) for tech in technologies),
            ),
            retirement=VehicleRetirementSpec(
                service_type='vehicle_assembly',work_days_per_unit=days * .35,
                recovery_resources_per_unit=tuple((resource, amount*.46) for resource, amount in supply),
            ),
            maintenance=VehicleMaintenanceSpec(
                service_type='spacecraft_servicing', turnaround_days=max(1.0, days*.15),
                resources=((ids.BASIC_MACHINE_PARTS, .09),),
            ),
            passengers=passengers,
        ))
    return tuple(rows)
