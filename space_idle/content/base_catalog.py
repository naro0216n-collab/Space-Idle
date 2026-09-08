from __future__ import annotations

from ..catalog import GameCatalog, ResourceDef
from .base_ids import STRUCTURAL_COMPONENTS, MACHINERY, PRECISION_ELECTRONICS, BULK_STRUCTURE, FABRICATED_STRUCTURE, BASIC_MACHINE_PARTS, CONSTRUCTION_EQUIPMENT, REGOLITH, METAL_FEEDSTOCK, WATER, OXYGEN, HYDROGEN, PROPELLANT

def build_base_catalog() -> GameCatalog:
    resources = {
        STRUCTURAL_COMPONENTS: ResourceDef(STRUCTURAL_COMPONENTS, "高性能構造部材"),
        MACHINERY: ResourceDef(MACHINERY, "機械類"),
        PRECISION_ELECTRONICS: ResourceDef(PRECISION_ELECTRONICS, "精密電子機器"),
        BULK_STRUCTURE: ResourceDef(BULK_STRUCTURE, "基礎構造材", category="bulk"),
        FABRICATED_STRUCTURE: ResourceDef(FABRICATED_STRUCTURE, "加工構造部材", category="bulk"),
        BASIC_MACHINE_PARTS: ResourceDef(BASIC_MACHINE_PARTS, "基礎機械部品", category="bulk"),
        CONSTRUCTION_EQUIPMENT: ResourceDef(CONSTRUCTION_EQUIPMENT, "建設機械", category="equipment"),
        REGOLITH: ResourceDef(REGOLITH, "レゴリス", category="bulk"),
        METAL_FEEDSTOCK: ResourceDef(METAL_FEEDSTOCK, "金属原料", category="bulk"),
        WATER: ResourceDef(WATER, "水"), OXYGEN: ResourceDef(OXYGEN, "酸素"), HYDROGEN: ResourceDef(HYDROGEN, "水素"),
        PROPELLANT: ResourceDef(PROPELLANT, "化学推進剤"),
    }
    return GameCatalog(resources)
