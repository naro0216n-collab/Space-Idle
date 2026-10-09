from __future__ import annotations

from dataclasses import replace

from ..facilities import FacilityDef, FacilityPlacementScope, LifeSupportSpec
from . import base_ids as ids
from . import base_requirements as req


def build_facility_definitions() -> dict:
    surface = req.SURFACE_SITE
    orbit = req.ORBIT_SITE
    definitions = {
        ids.EARTH_RESEARCH_LAB: FacilityDef(ids.EARTH_RESEARCH_LAB, "総合研究所", req._capabilities("research_lab", "general_research_equipment"), surface, surface),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: FacilityDef(ids.MICROGRAVITY_EXPERIMENT_PLATFORM, "微小重力実験プラットフォーム", req._capabilities("research_lab", "microgravity_experiment_equipment"), orbit, orbit),
        ids.CREWED_ORBITAL_LABORATORY: FacilityDef(ids.CREWED_ORBITAL_LABORATORY, "有人軌道研究所", req._capabilities("research_lab", "crewed_orbital_research_equipment"), orbit, req.SiteRequirements(environment=req.LOW_RADIATION_ENV, spatial_classification_requirements=req.ORBIT_CLASSIFICATION)),
        ids.ROBOTIC_GEOLOGY_STATION: FacilityDef(ids.ROBOTIC_GEOLOGY_STATION, "ロボット地質調査ステーション", req._capabilities("research_lab", "robotic_geology_equipment", "surface_survey", "robotic_operations"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
        ids.SAMPLE_ANALYSIS_LABORATORY: FacilityDef(ids.SAMPLE_ANALYSIS_LABORATORY, "試料分析研究所", req._capabilities("research_lab", "sample_analysis_equipment"), surface, surface),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: FacilityDef(ids.VACUUM_REGOLITH_PROCESS_LABORATORY, "真空レゴリスプロセス研究所", req._capabilities("research_lab", "vacuum_regolith_research_equipment"), surface, req.VACUUM_SURFACE_SITE),
        ids.GRID_POWER_SUPPLY: FacilityDef(ids.GRID_POWER_SUPPLY, "外部電力網接続", req._capabilities("grid_power"), surface, surface),
        ids.ORBITAL_FISSION_POWER: FacilityDef(ids.ORBITAL_FISSION_POWER, "軌道核分裂電源", req._capabilities("orbital_power_supply"), orbit, orbit),
        ids.ORBITAL_LOGISTICS_NODE: FacilityDef(ids.ORBITAL_LOGISTICS_NODE, "軌道物流・整備ノード", req._capabilities("cargo_transfer", "vehicle_refueling", "spacecraft_servicing"), orbit, orbit, service_capacity_supplies=req._services(cargo_transfer=1.0, spacecraft_servicing=1.0)),
        ids.EARTH_LAUNCH_SUPPORT: FacilityDef(ids.EARTH_LAUNCH_SUPPORT, "打上げ・回収整備設備", req._capabilities("cargo_transfer", "vehicle_refueling", "launch_vehicle_servicing", "launch_operations", "surface_access_anchor"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL, service_capacity_supplies=req._services(cargo_transfer=1.0, launch_vehicle_servicing=1.0)),
        ids.VEHICLE_ASSEMBLY_FACILITY: FacilityDef(ids.VEHICLE_ASSEMBLY_FACILITY, "宇宙輸送機製造・組立設備", req._capabilities("vehicle_assembly"), surface, surface, service_capacity_supplies=req._services(vehicle_assembly=1.0)),
        ids.ROBOTIC_SURVEY_PACKAGE: FacilityDef(ids.ROBOTIC_SURVEY_PACKAGE, "ロボット探査・初期建設パッケージ", req._capabilities("surface_survey", "base_construction", "robotic_operations", "spacecraft_servicing", "cargo_transfer", "surface_access_anchor"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL, service_capacity_supplies=req._services(cargo_transfer=1.0, spacecraft_servicing=1.0)),
        ids.SURFACE_POWER_GRID: FacilityDef(ids.SURFACE_POWER_GRID, "地表太陽光発電・配電設備", req._capabilities("power_grid"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
        ids.INDUSTRIAL_POWER_BLOCK: FacilityDef(ids.INDUSTRIAL_POWER_BLOCK, "核分裂電源ユニット", req._capabilities("industrial_power"), surface, surface),
        ids.CONSTRUCTION_YARD: FacilityDef(ids.CONSTRUCTION_YARD, "建設ヤード", req._capabilities("construction_yard"), surface, surface),
        ids.VOLATILE_EXTRACTOR: FacilityDef(ids.VOLATILE_EXTRACTOR, "揮発性原料採取設備", req._capabilities("volatile_extraction"), surface, req.COLD_VOLATILE_SURFACE_SITE, extraction_capacity_t_per_day=6.0),
        ids.VOLATILE_PROCESSING: FacilityDef(ids.VOLATILE_PROCESSING, "揮発性成分回収設備", req._capabilities("volatile_processing"), surface, surface),
        ids.VACUUM_MINERAL_HARVESTER: FacilityDef(ids.VACUUM_MINERAL_HARVESTER, "真空粒状鉱物採掘設備", req._capabilities("granular_mineral_extraction"), surface, req.VACUUM_SURFACE_SITE, extraction_capacity_t_per_day=8.0),
        ids.WATER_STORAGE: FacilityDef(ids.WATER_STORAGE, "水貯蔵タンク", req._capabilities("water_storage"), surface, surface),
        ids.CRYOGENIC_STORAGE: FacilityDef(ids.CRYOGENIC_STORAGE, "極低温貯蔵設備", req._capabilities("cryogenic_storage", "vehicle_refueling"), surface, surface),
        ids.BULK_STORAGE: FacilityDef(ids.BULK_STORAGE, "バルク原料置場", req._capabilities("bulk_storage"), surface, surface),
        ids.CARGO_WAREHOUSE: FacilityDef(ids.CARGO_WAREHOUSE, "一般貨物倉庫", req._capabilities("cargo_storage"), surface, surface),
        ids.SURFACE_DISTRIBUTION_HUB: FacilityDef(
            ids.SURFACE_DISTRIBUTION_HUB,
            "地表物流・配給ハブ",
            req._capabilities("surface_distribution", "surface_access_anchor"),
            surface,
            surface,
            placement_scope=FacilityPlacementScope.SURFACE_CELL,
            service_capacity_supplies=req._services(surface_distribution=1.0),
        ),
        ids.ELECTROLYSIS_PLANT: FacilityDef(ids.ELECTROLYSIS_PLANT, "工業電解設備", req._capabilities("industrial_electrolysis"), surface, surface),
        ids.PROPELLANT_PLANT: FacilityDef(ids.PROPELLANT_PLANT, "推進剤調製設備", req._capabilities("propellant_production"), surface, surface),
        ids.MINERAL_SINTERING: FacilityDef(ids.MINERAL_SINTERING, "鉱物焼結設備", req._capabilities("mineral_sintering"), surface, surface),
        ids.ORE_PROCESSING: FacilityDef(ids.ORE_PROCESSING, "鉱石処理設備", req._capabilities("ore_processing"), surface, surface),
        ids.METALLURGY: FacilityDef(ids.METALLURGY, "金属精錬設備", req._capabilities("metallurgy"), surface, surface),
        ids.FABRICATION_WORKSHOP: FacilityDef(ids.FABRICATION_WORKSHOP, "構造材加工工場", req._capabilities("structural_fabrication"), surface, surface),
        ids.MACHINE_SHOP: FacilityDef(ids.MACHINE_SHOP, "機械工場", req._capabilities("basic_machine_shop", "precision_machining"), surface, surface),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: FacilityDef(ids.HEAVY_EQUIPMENT_ASSEMBLY, "重機組立設備", req._capabilities("heavy_equipment_assembly"), surface, surface),
        ids.MINERAL_QUARRY: FacilityDef(ids.MINERAL_QUARRY, "露天鉱物採掘場", req._capabilities("mineral_extraction"), surface, surface, 0.10, extraction_capacity_t_per_day=2.4),
        ids.METAL_ORE_MINE: FacilityDef(ids.METAL_ORE_MINE, "露天金属鉱山", req._capabilities("metal_ore_extraction"), surface, surface, 0.10, extraction_capacity_t_per_day=1.7),
        ids.INDUSTRIAL_WATER_INTAKE: FacilityDef(ids.INDUSTRIAL_WATER_INTAKE, "工業用水取水・処理設備", req._capabilities("industrial_water_supply"), surface, surface, 0.08, extraction_capacity_t_per_day=1.0),
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: FacilityDef(ids.BASIC_STRUCTURAL_MATERIAL_PLANT, "基礎構造材工場", req._capabilities("basic_structural_material"), surface, surface, 0.09),
        ids.BASIC_MACHINERY_WORKS: FacilityDef(ids.BASIC_MACHINERY_WORKS, "基礎機械製作所", req._capabilities("basic_machinery_production"), surface, surface, 0.09),
    }
    definitions[ids.FOOD_FARM] = FacilityDef(
        ids.FOOD_FARM, '閉鎖式食料栽培設備', req._capabilities('food_hydroponics'), installation_requirements=surface, operating_requirements=surface,
    )
    definitions[ids.CREWED_ORBITAL_LABORATORY] = replace(
        definitions[ids.CREWED_ORBITAL_LABORATORY], housing_capacity=8,
        life_support=LifeSupportSpec(8, ((ids.FOOD, 0.001), (ids.WATER, 0.002), (ids.OXYGEN, 0.003))),
    )
    # Maintenance rates are Content balance. Mature/general equipment uses a
    # modest baseline while deliberately inefficient opening industry carries
    # a higher burden above. No location identity participates in this rule.
    definitions[ids.HABITAT] = FacilityDef(
        ids.HABITAT, '与圧居住モジュール', housing_capacity=24,
        installation_requirements=surface, operating_requirements=surface,
        life_support=LifeSupportSpec(24, ((ids.FOOD, 0.001), (ids.WATER, 0.002), (ids.OXYGEN, 0.003))),
    )
    # Environmental eligibility and net replenishment are Content, not Core
    # exceptions keyed to the planet name.
    definitions[ids.EARTH_LIFE_SUPPORT] = FacilityDef(
        ids.EARTH_LIFE_SUPPORT, '地上居住・生活供給設備', housing_capacity=160,
        installation_requirements=req.BREATHABLE_SURFACE_SITE,
        operating_requirements=req.BREATHABLE_SURFACE_SITE,
        life_support=LifeSupportSpec(160, ((ids.FOOD, 0.001), (ids.WATER, 0.002))),
    )
    for definition_id, definition in tuple(definitions.items()):
        if definition.maintenance_fraction_per_year <= 1e-12:
            definitions[definition_id] = replace(definition, maintenance_fraction_per_year=0.05)
    definitions = {
        definition_id: replace(definition, decommission_recovery_fraction=0.5)
        for definition_id, definition in definitions.items()
    }
    return definitions
