"""Finite industrial and biological operations from the research concept catalog.

Every output has an actual physical feed and a compatible installed process
interface. Electricity is charged to the operating Facility through Power.
"""
from __future__ import annotations

from ..industry import ProcessSpec
from ..shared import DefinitionId


def build_concept_process_specs() -> dict[DefinitionId, ProcessSpec]:
    # Ratios are provisional physical Content values, not fixed balance targets.
    # Inputs/outputs are tonnes per nominal process unit, at most three inputs.
    rows = (
        ('bioelectrochemical_mineral_recovery', '微生物浸出・電解金属回収', 'engineered_bioculture',
         {'metal_ore': 1.6, 'water': .55, 'carbon_nutrient_feedstock': .18},
         {'metal_feedstock': .83, 'water': .25}, ('VR-8-RESOURCE-CHAIN-01',)),
        ('brine_electrochemical_separation', '氷塩水の電気化学分離', 'industrial_volatile_fractionation',
         {'volatile_bearing_material': 1.4, 'water': .35},
         {'water': .95, 'mineral_feedstock': .22}, ('SYS-RSC-02',)),
        ('centrifugal_membrane_recycling', '遠心膜水再生', 'closed_cycle_water_recovery',
         {'volatile_bearing_material': .50, 'water': .35},
         {'water': .68, 'mineral_feedstock': .05}, ('PL-LARGE-HABITAT-RECYCLING',)),
        ('engineered_low_light_crops', '低光量改変作物栽培', 'controlled_nutrient_cultivation',
         {'water': .22, 'carbon_nutrient_feedstock': .32},
         {'food': .38, 'water': .05}, ('SYS-FOOD-04',)),
        ('engineered_nutrient_uptake_crops', '栄養吸収改変作物栽培', 'engineered_bioculture',
         {'water': .18, 'carbon_nutrient_feedstock': .26},
         {'food': .33, 'water': .06}, ('VR-8-PLANT-FOOD-01',)),
        ('functionally_graded_additive_fab', '傾斜組成積層成形', 'electromagnetic_levitation_founding',
         {'metal_feedstock': .62, 'ceramics_glass': .28, 'refractory_alloy': .17},
         {'fabricated_structure': .81}, ('MC-ADDITIVE-03',)),
        ('fusion_isotope_separation', '核融合燃料同位体分離', 'industrial_volatile_fractionation',
         {'hydrogen': 2.0, 'water': .12},
         {'fusion_fuel_isotopes': .065, 'hydrogen': 1.82}, ('SF-FUSION-04',)),
        ('laser_film_rework', '薄膜回路レーザー再加工', 'laser_film_rework',
         {'recovery_scrap': .9, 'precision_components': .16},
         {'precision_electronics': .53, 'metal_feedstock': .28}, ('VR-6-MICROELECTRONICS-01',)),
        ('laser_spectral_scrap_sorting', 'レーザー分光スクラップ選別', 'industrial_disassembly',
         {'recovery_scrap': 1.0},
         {'metal_feedstock': .41, 'refractory_alloy': .28}, ('PL-HIGH-VOLUME-RECOVERY-SORT',)),
        ('superfluid_helium_heat_transport', '超流動ヘリウム冷媒再生', 'cryogenic_coolant_reconditioning',
         {'helium4_coolant': .8, 'thermal_control_assemblies': .10},
         {'helium4_coolant': .76, 'recovery_scrap': .045}, ('VR-7-THERMAL-TRANSPORT-01',)),
        # Trace noble-gas separation requires a real volatile feed; a cryogenic
        # coolant cannot simply appear when the cooling technology is unlocked.
        ('helium4_volatile_recovery', '揮発性原料からのヘリウム回収', 'industrial_volatile_fractionation',
         {'volatile_bearing_material': 3.0},
         {'helium4_coolant': .018, 'water': 1.65}, ('VR-7-THERMAL-TRANSPORT-01',)),
    )
    result: dict[DefinitionId, ProcessSpec] = {}
    for slug, name, capability, inputs, outputs, tech in rows:
        identity = DefinitionId('planned.process.' + slug)
        result[identity] = ProcessSpec(
            identity, name, frozenset({capability}),
            {DefinitionId('base.resource.' + resource): quantity for resource, quantity in inputs.items()},
            {DefinitionId('base.resource.' + resource): quantity for resource, quantity in outputs.items()},
            frozenset(DefinitionId(item) for item in tech),
        )
    return result
