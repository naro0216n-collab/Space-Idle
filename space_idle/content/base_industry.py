from __future__ import annotations

from ..industry import ProcessSpec
from . import base_ids as ids


def build_process_specs() -> dict:
    return {
        ids.PROCESS_ELECTROLYSIS: ProcessSpec(ids.PROCESS_ELECTROLYSIS, "水電解", ids.ELECTROLYSIS_PLANT, {ids.WATER: 0.50}, {ids.OXYGEN: 0.44, ids.HYDROGEN: 0.055}),
        ids.PROCESS_PROPELLANT_BLEND: ProcessSpec(ids.PROCESS_PROPELLANT_BLEND, "化学推進剤調製", ids.PROPELLANT_PLANT, {ids.OXYGEN: 0.40, ids.HYDROGEN: 0.05}, {ids.PROPELLANT: 0.45}),
        ids.PROCESS_REGOLITH_SINTER: ProcessSpec(ids.PROCESS_REGOLITH_SINTER, "レゴリス焼結", ids.REGOLITH_SINTERING, {ids.REGOLITH: 1.0}, {ids.BULK_STRUCTURE: 0.8}),
        ids.PROCESS_ORE_PROCESS: ProcessSpec(ids.PROCESS_ORE_PROCESS, "鉱石処理", ids.ORE_PROCESSING, {ids.REGOLITH: 2.5}, {ids.METAL_FEEDSTOCK: 1.0}),
        ids.PROCESS_METALLURGY: ProcessSpec(ids.PROCESS_METALLURGY, "金属精錬", ids.METALLURGY, {ids.METAL_FEEDSTOCK: 2.0}, {ids.BULK_STRUCTURE: 1.8}),
        ids.PROCESS_STRUCTURAL_FABRICATION: ProcessSpec(ids.PROCESS_STRUCTURAL_FABRICATION, "構造部材加工", ids.FABRICATION_WORKSHOP, {ids.BULK_STRUCTURE: 0.65}, {ids.FABRICATED_STRUCTURE: 0.55}),
        ids.PROCESS_BASIC_MACHINING: ProcessSpec(ids.PROCESS_BASIC_MACHINING, "基礎機械加工", ids.MACHINE_SHOP, {ids.BULK_STRUCTURE: 0.4}, {ids.BASIC_MACHINE_PARTS: 0.25}),
        ids.PROCESS_HEAVY_EQUIPMENT: ProcessSpec(ids.PROCESS_HEAVY_EQUIPMENT, "建設機械組立", ids.HEAVY_EQUIPMENT_ASSEMBLY, {ids.BASIC_MACHINE_PARTS: 0.30, ids.PRECISION_ELECTRONICS: 0.05}, {ids.CONSTRUCTION_EQUIPMENT: 0.25}),
    }
