from __future__ import annotations

from ..industry import ProcessSpec
from ..shared import DefinitionId
from . import base_ids as ids


def build_process_specs() -> dict:
    return {
        ids.PROCESS_FOOD_PRODUCTION: ProcessSpec(
            ids.PROCESS_FOOD_PRODUCTION, '食料水耕生産', frozenset({"food_hydroponics"}),
            {ids.WATER: 0.18}, {ids.FOOD: 0.36},
        ),
        ids.PROCESS_ELECTROLYSIS: ProcessSpec(ids.PROCESS_ELECTROLYSIS, "水電解", frozenset({"industrial_electrolysis"}), {ids.WATER: 0.50}, {ids.OXYGEN: 0.44, ids.HYDROGEN: 0.055}),
        ids.PROCESS_PROPELLANT_BLEND: ProcessSpec(ids.PROCESS_PROPELLANT_BLEND, "化学推進剤調製", frozenset({"propellant_production"}), {ids.OXYGEN: 0.40, ids.HYDROGEN: 0.05}, {ids.PROPELLANT: 0.45}),
        ids.PROCESS_MINERAL_SINTER: ProcessSpec(ids.PROCESS_MINERAL_SINTER, "鉱物原料焼結", frozenset({"mineral_sintering"}), {ids.MINERAL_FEEDSTOCK: 1.0}, {ids.CERAMICS_GLASS: 0.8}, frozenset({DefinitionId("MC-MANUFACTURING-CONSTRUCTION-10")})),
        ids.PROCESS_VOLATILE_WATER_RECOVERY: ProcessSpec(ids.PROCESS_VOLATILE_WATER_RECOVERY, "揮発性成分回収", frozenset({"volatile_processing"}), {ids.VOLATILE_BEARING_MATERIAL: 1.0}, {ids.WATER: 0.35}),
        ids.PROCESS_ORE_PROCESS: ProcessSpec(ids.PROCESS_ORE_PROCESS, "鉱石処理", frozenset({"ore_processing"}), {ids.METAL_ORE: 2.5}, {ids.METAL_FEEDSTOCK: 1.0}),
        ids.PROCESS_METALLURGY: ProcessSpec(ids.PROCESS_METALLURGY, "金属精錬", frozenset({"metallurgy"}), {ids.METAL_FEEDSTOCK: 2.0}, {ids.BULK_STRUCTURE: 1.8}),
        # Explicit alternative operations on the same physical metallurgical
        # interface: recovered gas costs finite water, while variable-feed
        # operation substitutes common mineral stock for metal feedstock.
        # Completing Research never silently changes an existing plant's recipe.
        ids.PROCESS_METALLURGY_BYPRODUCT_RECOVERY: ProcessSpec(
            ids.PROCESS_METALLURGY_BYPRODUCT_RECOVERY, "精錬副生成ガス回収",
            frozenset({"metallurgy"}),
            {ids.METAL_FEEDSTOCK: 2.0, ids.WATER: 0.20},
            {ids.BULK_STRUCTURE: 1.8, ids.OXYGEN: 0.10},
            frozenset({ids.RP_RESOURCE_CHAIN_14}),
        ),
        ids.PROCESS_METALLURGY_VARIABLE_FEED: ProcessSpec(
            ids.PROCESS_METALLURGY_VARIABLE_FEED, "組成変動対応複合原料精錬",
            frozenset({"metallurgy"}),
            {ids.METAL_FEEDSTOCK: 1.5, ids.MINERAL_FEEDSTOCK: 0.8},
            {ids.BULK_STRUCTURE: 1.6},
            frozenset({ids.RP_RESOURCE_CHAIN_15}),
        ),
        ids.PROCESS_STRUCTURAL_FABRICATION: ProcessSpec(ids.PROCESS_STRUCTURAL_FABRICATION, "構造部材加工", frozenset({"structural_fabrication"}), {ids.BULK_STRUCTURE: 0.65}, {ids.FABRICATED_STRUCTURE: 0.55}),
        ids.PROCESS_BASIC_MACHINING: ProcessSpec(ids.PROCESS_BASIC_MACHINING, "基礎機械加工", frozenset({"basic_machine_shop"}), {ids.BULK_STRUCTURE: 0.4}, {ids.BASIC_MACHINE_PARTS: 0.25}),
        ids.PROCESS_PRECISION_COMPONENTS: ProcessSpec(ids.PROCESS_PRECISION_COMPONENTS, "精密部品加工", frozenset({"basic_machine_shop", "precision_machining"}), {ids.BASIC_MACHINE_PARTS: 0.30, ids.PRECISION_ELECTRONICS: 0.05}, {ids.PRECISION_COMPONENTS: 0.22}),
        ids.PROCESS_HEAVY_EQUIPMENT: ProcessSpec(ids.PROCESS_HEAVY_EQUIPMENT, "建設機械組立", frozenset({"heavy_equipment_assembly"}), {ids.BASIC_MACHINE_PARTS: 0.30, ids.PRECISION_ELECTRONICS: 0.05}, {ids.CONSTRUCTION_EQUIPMENT: 0.25}),
        # Deliberately low-throughput opening industry. These are ordinary
        # ProcessSpecs and can operate at any site where their facility and
        # inputs are available; Earth is only their initial Content placement.
        ids.PROCESS_BASIC_STRUCTURAL_MATERIAL: ProcessSpec(
            ids.PROCESS_BASIC_STRUCTURAL_MATERIAL, "基礎構造部材製造",
            frozenset({"basic_structural_material"}),
            {ids.MINERAL_FEEDSTOCK: 1.20, ids.METAL_ORE: 0.40},
            {ids.STRUCTURAL_COMPONENTS: 0.30},
        ),
        ids.PROCESS_BASIC_MACHINERY: ProcessSpec(
            ids.PROCESS_BASIC_MACHINERY, "基礎機械製造",
            frozenset({"basic_machinery_production"}),
            {ids.METAL_ORE: 0.70, ids.STRUCTURAL_COMPONENTS: 0.20},
            {ids.MACHINERY: 0.16},
        ),
    }
