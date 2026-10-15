"""Finite material transformations for the extended research/industrial catalog.

Quantities are authored Content calibration inputs (tonnes per nominal process unit),
not technology-wide multipliers. The installed Facility and its Power determine
whether a process may operate, and the ordinary Industry allocator owns inventory.
"""
from __future__ import annotations

from ..industry import ProcessSpec
from ..shared import DefinitionId


def build_extended_process_specs() -> dict[DefinitionId, ProcessSpec]:
    # Process ID, name, equipment interface, finite inputs/outputs, Technology.
    # No process creates a resource without a material feedstock.
    rows = (
        ('carbon_nutrient_recovery', '揮発性原料からの炭素・栄養塩調整', 'carbon_nutrient_separation',
         {'volatile_bearing_material': 0.70, 'water': 0.30}, {'carbon_nutrient_feedstock': 0.52, 'water': 0.16}, 'PL-PLANT-FOOD-04'),
        ('controlled_closed_crop', '炭素・養液循環型食料生産', 'controlled_nutrient_cultivation',
         {'water': 0.18, 'carbon_nutrient_feedstock': 0.40}, {'food': 0.36, 'water': 0.12}, 'PL-PLANT-FOOD-04'),
        ('pilot_regolith_sintering', '現地粉体圧縮・焼結試験', 'pilot_regolith_sintering',
         {'mineral_feedstock': 1.10}, {'ceramics_glass': 0.61}, 'X4-SINTER-BUILD'),
        ('continuous_mineral_beneficiation', '連続破砕・複合原料選別', 'continuous_mineral_separation',
         {'metal_ore': 2.80, 'mineral_feedstock': 0.50}, {'metal_feedstock': 1.45, 'mineral_feedstock': 0.20}, 'RP-RESOURCE-CHAIN-10'),
        ('refractory_alloy_refining', '耐熱合金の高温溶解・調質', 'high_temperature_alloy_furnace',
         {'metal_feedstock': 1.40, 'ceramics_glass': 0.35}, {'refractory_alloy': 1.14}, 'X5-THERMAL-REFINING'),
        ('industrial_exchange_parts', '耐熱精密交換部品加工', 'industrial_exchange_machining',
         {'basic_machine_parts': 0.60, 'refractory_alloy': 0.50, 'precision_electronics': 0.15}, {'precision_components': 0.82}, 'X5-PRECISION-FABRICATION'),
        ('bulk_volatile_fractionation', '工業規模多段揮発原料分留', 'industrial_volatile_fractionation',
         {'volatile_bearing_material': 2.50}, {'water': 1.55}, 'X5-LOCAL-PROPELLANT'),
        ('continuous_electrolysis', '連続水電解と生成ガス分離', 'continuous_electrolysis',
         {'water': 1.00}, {'oxygen': 0.84, 'hydrogen': 0.10}, 'X5-LOCAL-PROPELLANT'),
        ('industrial_propellant_blend', '工業推進剤混合・冷却', 'industrial_propellant_processing',
         {'oxygen': 0.80, 'hydrogen': 0.10}, {'propellant': 0.86}, 'X5-LOCAL-PROPELLANT'),
        ('orbital_precision_modules', '真空組立用精密モジュール加工', 'orbital_precision_module_fabrication',
         {'precision_components': 0.60, 'refractory_alloy': 0.40, 'precision_electronics': 0.24}, {'machinery': 0.94}, 'X6-ORBITAL-MANUFACTURING'),
        ('industrial_scrap_recovery', '設備分解・使用済み部品選別', 'industrial_disassembly',
         {'machinery': 0.90, 'refractory_alloy': 0.25}, {'recovery_scrap': 0.72, 'basic_machine_parts': 0.12}, 'X6-INTERPLANETARY-REPAIR'),
        ('scrap_refining', '合金回収材の再溶解・再製材', 'recovered_alloy_refining',
         {'recovery_scrap': 1.0}, {'refractory_alloy': 0.62, 'metal_feedstock': 0.14}, 'X6-ORBITAL-MANUFACTURING'),
        ('hardened_control_electronics', '遮蔽・耐熱制御モジュール組立', 'hardened_electronics_fabrication',
         {'precision_electronics': 0.80, 'radiation_shielding_panels': 0.18, 'refractory_alloy': 0.26}, {'hardened_electronics': 0.58}, 'X7-RADIATION-HARDENED-COMPONENTS'),
        ('low_sun_insulated_modules', '低温断熱・防護機器モジュール', 'cryogenic_protected_fabrication',
         {'refractory_alloy': 0.80, 'thermal_control_assemblies': 0.55, 'hardened_electronics': 0.20}, {'machinery': 1.01}, 'X7-DELAY-TOLERANT-AUTONOMY'),
        ('circular_precision_manufacturing', '回収合金の精密再加工・部品再製造', 'circular_precision_remanufacturing',
         {'recovery_scrap': 0.90, 'precision_components': 0.25, 'hardened_electronics': 0.18}, {'precision_components': 0.51, 'machinery': 0.32}, 'X8-CIRCULAR-MANUFACTURING'),
        ('earth_primary_billet_casting', '一次鉱石の低効率地金鋳造', 'metallurgy',
         {'metal_ore': 2.00}, {'metal_feedstock': 0.55}, None),
        ('earth_basic_electronics', '鉱物薄膜・基礎電子機器組立', 'earth_basic_electronics',
         {'metal_ore': 0.60, 'mineral_feedstock': 0.80, 'water': 0.10}, {'precision_electronics': 0.12}, 'PL-EARTH-PRECISION-PARTS'),
        ('earth_basic_precision_components', '初期精密加工と組立', 'basic_machine_shop',
         {'basic_machine_parts': 0.45, 'precision_electronics': 0.08}, {'precision_components': 0.28}, 'PL-EARTH-PRECISION-PARTS'),
        ('earth_kiln_ceramics', '低効率鉱物焼成', 'mineral_sintering',
         {'mineral_feedstock': 1.40}, {'ceramics_glass': 0.52}, None),
        ('earth_electrolysis_basic', '初期水電解・分離', 'industrial_electrolysis',
         {'water': 0.60}, {'oxygen': 0.49, 'hydrogen': 0.06}, None),
    )
    result = {}
    for name, label, capability, inputs, outputs, technology in rows:
        identity = DefinitionId('planned.process.' + name)
        result[identity] = ProcessSpec(
            identity, label, frozenset({capability}),
            {DefinitionId('base.resource.' + key): value for key, value in inputs.items()},
            {DefinitionId('base.resource.chemical_propellant' if key == 'propellant' else 'base.resource.' + key): value for key, value in outputs.items()},
            frozenset({DefinitionId(technology)}) if technology else frozenset(),
        )
    return result
