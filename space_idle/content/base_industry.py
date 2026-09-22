from __future__ import annotations

from ..industry import ProcessSpec
from . import base_ids as ids


def build_process_specs() -> dict:
    return {
        ids.PROCESS_ELECTROLYSIS: ProcessSpec(ids.PROCESS_ELECTROLYSIS, "水電解", ids.ELECTROLYSIS_PLANT, {ids.WATER: 0.50}, {ids.OXYGEN: 0.44, ids.HYDROGEN: 0.055}),
        ids.PROCESS_PROPELLANT_BLEND: ProcessSpec(ids.PROCESS_PROPELLANT_BLEND, "化学推進剤調製", ids.PROPELLANT_PLANT, {ids.OXYGEN: 0.40, ids.HYDROGEN: 0.05}, {ids.PROPELLANT: 0.45}),
        ids.PROCESS_MINERAL_SINTER: ProcessSpec(ids.PROCESS_MINERAL_SINTER, "鉱物原料焼結", ids.MINERAL_SINTERING, {ids.MINERAL_FEEDSTOCK: 1.0}, {ids.CERAMICS_GLASS: 0.8}),
        ids.PROCESS_VOLATILE_WATER_RECOVERY: ProcessSpec(ids.PROCESS_VOLATILE_WATER_RECOVERY, "揮発性成分回収", ids.VOLATILE_PROCESSING, {ids.VOLATILE_BEARING_MATERIAL: 1.0}, {ids.WATER: 0.35}),
        ids.PROCESS_ORE_PROCESS: ProcessSpec(ids.PROCESS_ORE_PROCESS, "鉱石処理", ids.ORE_PROCESSING, {ids.METAL_ORE: 2.5}, {ids.METAL_FEEDSTOCK: 1.0}),
        ids.PROCESS_METALLURGY: ProcessSpec(ids.PROCESS_METALLURGY, "金属精錬", ids.METALLURGY, {ids.METAL_FEEDSTOCK: 2.0}, {ids.BULK_STRUCTURE: 1.8}),
        ids.PROCESS_STRUCTURAL_FABRICATION: ProcessSpec(ids.PROCESS_STRUCTURAL_FABRICATION, "構造部材加工", ids.FABRICATION_WORKSHOP, {ids.BULK_STRUCTURE: 0.65}, {ids.FABRICATED_STRUCTURE: 0.55}),
        ids.PROCESS_BASIC_MACHINING: ProcessSpec(ids.PROCESS_BASIC_MACHINING, "基礎機械加工", ids.MACHINE_SHOP, {ids.BULK_STRUCTURE: 0.4}, {ids.BASIC_MACHINE_PARTS: 0.25}),
        ids.PROCESS_PRECISION_COMPONENTS: ProcessSpec(ids.PROCESS_PRECISION_COMPONENTS, "精密部品加工", ids.MACHINE_SHOP, {ids.BASIC_MACHINE_PARTS: 0.30, ids.PRECISION_ELECTRONICS: 0.05}, {ids.PRECISION_COMPONENTS: 0.22}),
        ids.PROCESS_HEAVY_EQUIPMENT: ProcessSpec(ids.PROCESS_HEAVY_EQUIPMENT, "建設機械組立", ids.HEAVY_EQUIPMENT_ASSEMBLY, {ids.BASIC_MACHINE_PARTS: 0.30, ids.PRECISION_ELECTRONICS: 0.05}, {ids.CONSTRUCTION_EQUIPMENT: 0.25}),
        # Deliberately low-throughput opening industry. These are ordinary
        # ProcessSpecs and can operate at any site where their facility and
        # inputs are available; Earth is only their initial Content placement.
        ids.PROCESS_BASIC_STRUCTURAL_MATERIAL: ProcessSpec(
            ids.PROCESS_BASIC_STRUCTURAL_MATERIAL, "基礎構造部材製造",
            ids.BASIC_STRUCTURAL_MATERIAL_PLANT,
            {ids.MINERAL_FEEDSTOCK: 1.20, ids.METAL_ORE: 0.40},
            {ids.STRUCTURAL_COMPONENTS: 0.30},
        ),
        ids.PROCESS_BASIC_MACHINERY: ProcessSpec(
            ids.PROCESS_BASIC_MACHINERY, "基礎機械製造",
            ids.BASIC_MACHINERY_WORKS,
            {ids.METAL_ORE: 0.70, ids.STRUCTURAL_COMPONENTS: 0.20},
            {ids.MACHINERY: 0.16},
        ),
    }
