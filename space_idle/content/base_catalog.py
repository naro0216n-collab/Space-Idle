from __future__ import annotations

from ..catalog import GameCatalog, ResourceDef
from . import base_ids as ids
from .base_ids import STRUCTURAL_COMPONENTS, MACHINERY, PRECISION_ELECTRONICS, BULK_STRUCTURE, FABRICATED_STRUCTURE, BASIC_MACHINE_PARTS, CONSTRUCTION_EQUIPMENT, MINERAL_FEEDSTOCK, VOLATILE_BEARING_MATERIAL, CERAMICS_GLASS, PRECISION_COMPONENTS, METAL_FEEDSTOCK, METAL_ORE, WATER, OXYGEN, HYDROGEN, PROPELLANT, THERMAL_CONTROL_ASSEMBLIES, RADIATION_SHIELDING_PANELS, OPTICAL_INSTRUMENT_PACKAGES, FOOD

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
        THERMAL_CONTROL_ASSEMBLIES: ResourceDef(THERMAL_CONTROL_ASSEMBLIES, "ヒートパイプ・放熱器モジュール", category="equipment"),
        RADIATION_SHIELDING_PANELS: ResourceDef(RADIATION_SHIELDING_PANELS, "積層放射線遮蔽パネル", category="equipment"),
        OPTICAL_INSTRUMENT_PACKAGES: ResourceDef(OPTICAL_INSTRUMENT_PACKAGES, "光学観測・精密追尾モジュール", category="equipment"),
        FOOD: ResourceDef(FOOD, "食料"),
        ids.CARBON_NUTRIENT_FEEDSTOCK: ResourceDef(ids.CARBON_NUTRIENT_FEEDSTOCK, "炭素・栄養塩調整原料", category="bulk"),
        ids.REFRACTORY_ALLOY: ResourceDef(ids.REFRACTORY_ALLOY, "耐熱・耐腐食工業合金", category="bulk"),
        ids.HARDENED_ELECTRONICS: ResourceDef(ids.HARDENED_ELECTRONICS, "耐放射線・極低温制御電子モジュール"),
        ids.RECOVERY_SCRAP: ResourceDef(ids.RECOVERY_SCRAP, "使用済み合金・機械回収材", category="bulk"),
        ids.HELIUM4_COOLANT: ResourceDef(ids.HELIUM4_COOLANT, "ヘリウム4冷媒", storage_pool_key="cryogenic"),
        ids.FUSION_FUEL_ISOTOPES: ResourceDef(ids.FUSION_FUEL_ISOTOPES, "分離核融合燃料同位体", storage_pool_key="cryogenic"),
        WATER: ResourceDef(WATER, "水"),
        OXYGEN: ResourceDef(OXYGEN, "酸素", storage_pool_key="cryogenic"),
        HYDROGEN: ResourceDef(HYDROGEN, "水素", storage_pool_key="cryogenic"),
        PROPELLANT: ResourceDef(PROPELLANT, "化学推進剤", storage_pool_key="cryogenic"),
    }
    return GameCatalog(resources)
