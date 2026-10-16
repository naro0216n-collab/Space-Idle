"""Individually specified material equipment from the eight-stage concept catalog.

These definitions participate in ordinary construction, power, maintenance,
industry and capability allocation. Advanced cross-node energy transfer and
assisted movement are not represented by local Capability supplies alone.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..facilities import FacilityDef, FacilityPlacementScope, LifeSupportSpec
from ..power import PowerSpec, SolarGeneration, FixedGeneration
from ..projects import ConstructionRecipe, BuildResourceRequirement, ConstructionProviderSpec
from ..shared import DefinitionId
from ..site import SiteRequirements
from .asset_content import FacilityAsset
from . import base_requirements as req
from . import base_ids as ids


@dataclass(frozen=True)
class ConceptEquipment:
    slug: str
    name: str
    technologies: tuple[str, ...]
    materials: tuple[tuple[str, float], ...]
    work: float
    capabilities: tuple[str, ...]
    power_load_mw: float
    throughput: float = 0.0
    services: tuple[tuple[str, float], ...] = ()
    construction_tpd: float = 0.0
    solar_mw: float = 0.0
    housing: int = 0
    orbital: bool = False
    site_independent: bool = False
    fixed_generation_mw: float = 0.0
    beam_transmit_mw: float = 0.0
    beam_receive_mw: float = 0.0
    operating_resources_per_day: tuple[tuple[str, float], ...] = ()


# Material requirements are tonnes per installed unit, never a stage-based
# generic multiplier. Construction, maintenance and operating capacities have
# distinct physical meanings. Concept equipment with unsupported remote-power
# and kinetic-transfer semantics is intentionally not advertised here.
_EQUIPMENT = (
    ConceptEquipment('adaptive_optical_relay', '適応光学通信中継器', ('DENS-036',),
        (('optical_instrument_packages', 16), ('hardened_electronics', 6), ('thermal_control_assemblies', 9)),
        84, ('adaptive_optical_tracking', 'deep_space_relay'), 4.6, orbital=True),
    ConceptEquipment('beam_array_thermal_qualification', '光ビーム送信器熱試験設備', ('SF-BEAM-05',),
        (('optical_instrument_packages', 12), ('thermal_control_assemblies', 20), ('refractory_alloy', 11)),
        130, ('beamed_array_thermal_test',), 23),
    ConceptEquipment('cooperative_orbital_assembly', '自由浮遊協調組立セル', ('VR-6-AUTONOMY-ROBOTICS-02',),
        (('machinery', 15), ('precision_components', 13), ('fabricated_structure', 17)),
        110, ('robotic_orbital_construction', 'orbital_precision_module_fabrication'),
        6.5, throughput=4.0, construction_tpd=8.0, orbital=True),
    ConceptEquipment('electromagnetic_mass_driver', '電磁貨物射出設備', ('SF-MASS-01',),
        (('refractory_alloy', 64), ('fabricated_structure', 70), ('thermal_control_assemblies', 31)),
        365, ('mass_driver_launch_interface',), 90.0,
        services=(('mass_driver_launch', 38.0),),
        operating_resources_per_day=(('thermal_control_assemblies', .012),)),
    ConceptEquipment('kinetic_cargo_receiver', '射出貨物捕捉設備', ('SF-MASS-02',),
        (('fabricated_structure', 72), ('machinery', 44), ('hardened_electronics', 28)),
        340, ('kinetic_capture_interface',), 32.0,
        services=(('kinetic_cargo_capture', 40.0),), orbital=True,
        operating_resources_per_day=(('thermal_control_assemblies', .015),)),
    ConceptEquipment('momentum_exchange_tether', '運動量交換テザーハブ',
        ('SF-TETHER-01', 'SF-TETHER-02', 'SF-TETHER-03', 'SF-TETHER-04'),
        (('refractory_alloy', 92), ('fabricated_structure', 145), ('hardened_electronics', 41)),
        710, ('tether_catch_release_interface',), 85.0,
        services=(('tether_momentum_exchange', 22.0),), orbital=True,
        operating_resources_per_day=(('thermal_control_assemblies', .035),)),
    ConceptEquipment('phased_energy_array', '位相合成ビーム送信設備',
        ('SF-BEAM-01', 'SF-BEAM-03', 'SF-BEAM-04'),
        (('optical_instrument_packages', 92), ('refractory_alloy', 73), ('thermal_control_assemblies', 86)),
        690, ('phased_beam_emitter',), 210.0,
        services=(('beam_momentum_transfer', 18.0),), site_independent=True,
        beam_transmit_mw=65.0,
        operating_resources_per_day=(('thermal_control_assemblies', .02),)),
    ConceptEquipment('beamed_power_receiver', '指向性光電力受信設備',
        ('VR-8-SOLAR-POWER-01', 'X8-DISTRIBUTED-POWER'),
        (('optical_instrument_packages', 58), ('thermal_control_assemblies', 65), ('hardened_electronics', 33)),
        430, ('directed_light_receiving_aperture',), 8.0, orbital=True,
        beam_receive_mw=50.0),
    ConceptEquipment('engineered_bioculture_containment', '合成微生物封じ込め設備', ('SF-BIO-01',),
        (('fabricated_structure', 8), ('precision_electronics', 7), ('thermal_control_assemblies', 5)),
        90, ('bioculture_containment',), 5.0),
    ConceptEquipment('engineered_bioculture_reactor', '合成微生物閉鎖培養槽', ('EC-06', 'EC-07', 'EC-08', 'SF-BIO-01'),
        (('fabricated_structure', 9), ('machinery', 11), ('precision_electronics', 6)),
        95, ('engineered_bioculture', 'bioculture_containment', 'controlled_nutrient_cultivation'), 8.0, throughput=3.0),
    ConceptEquipment('fusion_power_station', '核融合燃料循環・熱回収発電施設', ('SF-FUSION-04',),
        (('refractory_alloy', 78), ('radiation_shielding_panels', 52), ('thermal_control_assemblies', 66)),
        540, ('fusion_thermal_generation', 'fusion_fuel_handling'), 36.0,
        fixed_generation_mw=210.0,
        operating_resources_per_day=(('fusion_fuel_isotopes', .18), ('helium4_coolant', .025))),
    ConceptEquipment('high_field_magnet_testbed', '高磁場コイル試験装置', ('SF-MAGNET-01',),
        (('refractory_alloy', 10), ('thermal_control_assemblies', 12), ('hardened_electronics', 7)),
        108, ('high_field_magnetic_testing',), 16.0),
    ConceptEquipment('industrial_habitat', '産業居住施設', ('SYS-LIFE-01', 'SYS-HAB-02'),
        (('fabricated_structure', 38), ('machinery', 14), ('precision_electronics', 11)),
        150, ('pressurized_habitation', 'closed_cycle_life_support'), 5.5, housing=90),
    ConceptEquipment('magnetic_particle_shield', '部分磁気粒子遮蔽設備', ('SF-SHIELD-01', 'SF-SHIELD-02'),
        (('refractory_alloy', 15), ('thermal_control_assemblies', 13), ('hardened_electronics', 12)),
        165, ('magnetic_particle_shielding',), 30.0),
    ConceptEquipment('orbital_magnetic_foundry', '電磁浮遊軌道鋳造設備', ('X6-ORBITAL-MANUFACTURING', 'PL-SPACE-BASED-HEAVY-FAB'),
        (('refractory_alloy', 21), ('machinery', 18), ('thermal_control_assemblies', 11)),
        140, ('electromagnetic_levitation_founding', 'metallurgy'), 18.0, throughput=7.0, orbital=True),
    ConceptEquipment('orbital_modular_thinfilm_array', '軌道組立式薄膜発電面', ('VR-6-SOLAR-POWER-01', 'VR-7-SOLAR-POWER-01'),
        (('fabricated_structure', 23), ('precision_electronics', 9), ('optical_instrument_packages', 5)),
        112, ('orbital_solar_generation',), 1.2, solar_mw=42.0, orbital=True),
    ConceptEquipment('phase_change_habitat_cooling', '相変化蓄熱型居住冷却設備', ('PL-REGENERATIVE-HABITAT-THERMAL',),
        (('thermal_control_assemblies', 17), ('machinery', 7), ('ceramics_glass', 12)),
        112, ('phase_change_thermal_control', 'industrial_heat_exchange', 'cryogenic_coolant_reconditioning'), 3.5),
    ConceptEquipment('reconfigurable_rad_hard_computer', '再構成型耐照射制御計算機', ('SYS-COMP-03', 'VR-7-MICROELECTRONICS-01'),
        (('hardened_electronics', 14), ('thermal_control_assemblies', 5), ('precision_components', 9)),
        126, ('verified_remote_control', 'radiation_hardened_computation'), 8.5),
    ConceptEquipment('recovery_microelectronics_fab', '循環型電子回路精製・製造', ('VR-8-MICROELECTRONICS-02',),
        (('hardened_electronics', 16), ('machinery', 22), ('thermal_control_assemblies', 12)),
        185, ('laser_film_rework', 'circular_microelectronics_fabrication'), 16.0, throughput=11.0),
    ConceptEquipment('rotating_habitat', '回転式居住区', ('SF-GRAV-01', 'SF-GRAV-02', 'SF-GRAV-03'),
        (('fabricated_structure', 70), ('machinery', 35), ('hardened_electronics', 14)),
        260, ('rotating_habitat_support', 'pressurized_habitation', 'closed_cycle_life_support', 'closed_cycle_water_recovery'),
        19.0, housing=240, orbital=True),
    ConceptEquipment('superconducting_dc_bus', '低温超伝導直流母線', ('VR-6-STORAGE-DISTRIBUTION-01', 'SYS-POWER-05'),
        (('thermal_control_assemblies', 18), ('refractory_alloy', 11), ('precision_electronics', 8)),
        135, ('superconducting_power_distribution',), 8.5),
    ConceptEquipment('variable_emissivity_radiator', '可変放射率熱放散設備', ('PL-EXTERIOR-THERMAL-RADIATOR',),
        (('thermal_control_assemblies', 18), ('refractory_alloy', 8), ('precision_electronics', 5)),
        96, ('variable_emissivity_cooling', 'industrial_heat_exchange'), 2.3),
)


def build_concept_facility_assets() -> tuple[FacilityAsset, ...]:
    rows = []
    for row in _EQUIPMENT:
        identity = DefinitionId('planned.facility.' + row.slug)
        site = (SiteRequirements() if row.site_independent else
                req.ORBIT_SITE if row.orbital else req.SURFACE_SITE)
        definition = FacilityDef(
            identity, row.name, req._capabilities(*row.capabilities),
            site, site, maintenance_fraction_per_year=.07,
            decommission_recovery_fraction=.42,
            service_capacity_supplies=req._services(**dict(row.services)),
            housing_capacity=row.housing,
            life_support=(LifeSupportSpec(row.housing, ((ids.FOOD, .001), (ids.WATER, .002), (ids.OXYGEN, .003)))
                          if row.housing else None),
            process_throughput_per_day=row.throughput,
            operating_resources_per_day=tuple(
                (DefinitionId('base.resource.' + resource), rate)
                for resource, rate in row.operating_resources_per_day
            ),
        )
        recipes = tuple(BuildResourceRequirement(DefinitionId('base.resource.' + item), quantity)
                        for item, quantity in row.materials)
        rows.append(FacilityAsset(
            definition=definition,
            construction=ConstructionRecipe(
                identity, recipes, row.work, site,
                frozenset(DefinitionId(t) for t in row.technologies),
            ),
            power=PowerSpec(
                (SolarGeneration(row.solar_mw / .62, 1361.0) if row.solar_mw
                 else FixedGeneration(row.fixed_generation_mw) if row.fixed_generation_mw else None),
                row.power_load_mw,
                standby_load_mw=.12 * row.power_load_mw,
                beam_transmit_capacity_mw=row.beam_transmit_mw,
                beam_receive_capacity_mw=row.beam_receive_mw,
            ),
            construction_provider=ConstructionProviderSpec(identity, row.construction_tpd)
                if row.construction_tpd else None,
        ))
    return tuple(rows)
