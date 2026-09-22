from __future__ import annotations

from ..catalog import GameCatalog, ResourceDef
from .base_ids import STRUCTURAL_COMPONENTS, MACHINERY, PRECISION_ELECTRONICS, BULK_STRUCTURE, FABRICATED_STRUCTURE, BASIC_MACHINE_PARTS, CONSTRUCTION_EQUIPMENT, MINERAL_FEEDSTOCK, VOLATILE_BEARING_MATERIAL, CERAMICS_GLASS, PRECISION_COMPONENTS, METAL_FEEDSTOCK, METAL_ORE, WATER, OXYGEN, HYDROGEN, PROPELLANT

def build_base_catalog() -> GameCatalog:
    resources = {
        STRUCTURAL_COMPONENTS: ResourceDef(STRUCTURAL_COMPONENTS, "高性能構造部材"),
        MACHINERY: ResourceDef(MACHINERY, "機械類"),
        PRECISION_ELECTRONICS: ResourceDef(PRECISION_ELECTRONICS, "精密電子機器"),
        BULK_STRUCTURE: ResourceDef(BULK_STRUCTURE, "基礎構造材", category="bulk"),
        FABRICATED_STRUCTURE: ResourceDef(FABRICATED_STRUCTURE, "加工構造部材", category="bulk"),
        BASIC_MACHINE_PARTS: ResourceDef(BASIC_MACHINE_PARTS, "基礎機械部品", category="bulk"),
        CONSTRUCTION_EQUIPMENT: ResourceDef(CONSTRUCTION_EQUIPMENT, "建設機械", category="equipment"),
        MINERAL_FEEDSTOCK: ResourceDef(MINERAL_FEEDSTOCK, "鉱物原料", category="bulk"),
        VOLATILE_BEARING_MATERIAL: ResourceDef(VOLATILE_BEARING_MATERIAL, "揮発性成分含有原料", category="bulk"),
        CERAMICS_GLASS: ResourceDef(CERAMICS_GLASS, "セラミックス／ガラス", category="bulk"),
        PRECISION_COMPONENTS: ResourceDef(PRECISION_COMPONENTS, "精密部品"),
        METAL_FEEDSTOCK: ResourceDef(METAL_FEEDSTOCK, "金属原料", category="bulk"),
                METAL_ORE: ResourceDef(METAL_ORE, "金属鉱石", category="bulk"),
        WATER: ResourceDef(WATER, "水"),
        OXYGEN: ResourceDef(OXYGEN, "酸素", storage_pool_key="cryogenic"),
        HYDROGEN: ResourceDef(HYDROGEN, "水素", storage_pool_key="cryogenic"),
        PROPELLANT: ResourceDef(PROPELLANT, "化学推進剤", storage_pool_key="cryogenic"),
    }
    return GameCatalog(resources)
