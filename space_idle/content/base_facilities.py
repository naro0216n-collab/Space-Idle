from __future__ import annotations

from ..facilities import FacilityDef, FacilityPlacementScope
from . import base_ids as ids
from . import base_requirements as req


def build_facility_definitions() -> dict:
    surface = req.SURFACE_ENV
    orbit = req.ORBIT_ENV
    definitions = {
        ids.EARTH_RESEARCH_LAB: FacilityDef(ids.EARTH_RESEARCH_LAB, "総合研究所", req._capabilities("research_lab"), surface, surface),
        ids.EARTH_OBSERVATION_SATELLITE: FacilityDef(ids.EARTH_OBSERVATION_SATELLITE, "地球観測衛星", (), orbit, orbit),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: FacilityDef(ids.MICROGRAVITY_EXPERIMENT_PLATFORM, "微小重力実験プラットフォーム", req._capabilities("research_lab"), orbit, orbit),
        ids.CREWED_ORBITAL_LABORATORY: FacilityDef(ids.CREWED_ORBITAL_LABORATORY, "有人軌道研究所", req._capabilities("research_lab"), orbit, orbit),
        ids.ROBOTIC_GEOLOGY_STATION: FacilityDef(ids.ROBOTIC_GEOLOGY_STATION, "ロボット地質調査ステーション", req._capabilities("research_lab", "surface_survey", "robotic_operations"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
        ids.SAMPLE_ANALYSIS_LABORATORY: FacilityDef(ids.SAMPLE_ANALYSIS_LABORATORY, "試料分析研究所", req._capabilities("research_lab"), surface, surface),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: FacilityDef(ids.VACUUM_REGOLITH_PROCESS_LABORATORY, "真空レゴリスプロセス研究所", req._capabilities("research_lab"), surface, req.VACUUM_SURFACE_ENV),
        ids.GRID_POWER_SUPPLY: FacilityDef(ids.GRID_POWER_SUPPLY, "外部電力網接続", req._capabilities("grid_power"), surface, surface),
        ids.ORBITAL_LOGISTICS_NODE: FacilityDef(ids.ORBITAL_LOGISTICS_NODE, "軌道物流・整備ノード", req._capabilities("cargo_transfer", "vehicle_refueling", "spacecraft_servicing"), orbit, orbit),
        ids.EARTH_LAUNCH_SUPPORT: FacilityDef(ids.EARTH_LAUNCH_SUPPORT, "打上げ・回収整備設備", req._capabilities("cargo_transfer", "vehicle_refueling", "launch_vehicle_servicing", "launch_operations"), surface, surface),
        ids.VEHICLE_ASSEMBLY_FACILITY: FacilityDef(ids.VEHICLE_ASSEMBLY_FACILITY, "宇宙輸送機製造・組立設備", req._capabilities("vehicle_assembly"), surface, surface),
        ids.ROBOTIC_SURVEY_PACKAGE: FacilityDef(ids.ROBOTIC_SURVEY_PACKAGE, "ロボット探査・初期建設パッケージ", req._capabilities("surface_survey", "base_construction", "robotic_operations", "spacecraft_servicing"), surface, surface),
        ids.SURFACE_POWER_GRID: FacilityDef(ids.SURFACE_POWER_GRID, "地表太陽光発電・配電設備", req._capabilities("power_grid"), surface, surface),
        ids.INDUSTRIAL_POWER_BLOCK: FacilityDef(ids.INDUSTRIAL_POWER_BLOCK, "核分裂電源ユニット", req._capabilities("industrial_power"), surface, surface),
        ids.CONSTRUCTION_YARD: FacilityDef(ids.CONSTRUCTION_YARD, "建設ヤード", req._capabilities("construction_yard"), surface, surface),
        ids.VOLATILE_EXTRACTOR: FacilityDef(ids.VOLATILE_EXTRACTOR, "揮発性物質抽出設備", req._capabilities("water_extraction"), surface, req.COLD_VOLATILE_SURFACE_ENV),
        ids.REGOLITH_HARVESTER: FacilityDef(ids.REGOLITH_HARVESTER, "レゴリス採掘設備", req._capabilities("regolith_excavation"), surface, surface),
        ids.WATER_STORAGE: FacilityDef(ids.WATER_STORAGE, "水貯蔵タンク", req._capabilities("water_storage"), surface, surface),
        ids.CRYOGENIC_STORAGE: FacilityDef(ids.CRYOGENIC_STORAGE, "極低温貯蔵設備", req._capabilities("cryogenic_storage", "vehicle_refueling"), surface, surface),
        ids.BULK_STORAGE: FacilityDef(ids.BULK_STORAGE, "バルク原料置場", req._capabilities("bulk_storage"), surface, surface),
        ids.CARGO_WAREHOUSE: FacilityDef(ids.CARGO_WAREHOUSE, "一般貨物倉庫", req._capabilities("cargo_storage"), surface, surface),
        ids.ELECTROLYSIS_PLANT: FacilityDef(ids.ELECTROLYSIS_PLANT, "工業電解設備", req._capabilities("industrial_electrolysis"), surface, surface),
        ids.PROPELLANT_PLANT: FacilityDef(ids.PROPELLANT_PLANT, "推進剤調製設備", req._capabilities("propellant_production"), surface, surface),
        ids.REGOLITH_SINTERING: FacilityDef(ids.REGOLITH_SINTERING, "レゴリス焼結設備", req._capabilities("sintering"), surface, surface),
        ids.ORE_PROCESSING: FacilityDef(ids.ORE_PROCESSING, "鉱石処理設備", req._capabilities("ore_processing"), surface, surface),
        ids.METALLURGY: FacilityDef(ids.METALLURGY, "金属精錬設備", req._capabilities("metallurgy"), surface, surface),
        ids.FABRICATION_WORKSHOP: FacilityDef(ids.FABRICATION_WORKSHOP, "構造材加工工場", req._capabilities("structural_fabrication"), surface, surface),
        ids.MACHINE_SHOP: FacilityDef(ids.MACHINE_SHOP, "機械工場", req._capabilities("basic_machine_shop"), surface, surface),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: FacilityDef(ids.HEAVY_EQUIPMENT_ASSEMBLY, "重機組立設備", req._capabilities("heavy_equipment_assembly"), surface, surface),
        ids.SURFACE_AGGREGATE_QUARRY: FacilityDef(ids.SURFACE_AGGREGATE_QUARRY, "露天骨材採掘場", req._capabilities("aggregate_extraction"), surface, surface, 0.10),
        ids.METAL_ORE_MINE: FacilityDef(ids.METAL_ORE_MINE, "露天金属鉱山", req._capabilities("metal_ore_extraction"), surface, surface, 0.10),
        ids.INDUSTRIAL_WATER_INTAKE: FacilityDef(ids.INDUSTRIAL_WATER_INTAKE, "工業用水取水・処理設備", req._capabilities("industrial_water_supply"), surface, surface, 0.08),
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: FacilityDef(ids.BASIC_STRUCTURAL_MATERIAL_PLANT, "基礎構造材工場", req._capabilities("basic_structural_material"), surface, surface, 0.09),
        ids.BASIC_MACHINERY_WORKS: FacilityDef(ids.BASIC_MACHINERY_WORKS, "基礎機械製作所", req._capabilities("basic_machinery_production"), surface, surface, 0.09),
    }
    # Maintenance rates are Content balance. Mature/general equipment uses a
    # modest baseline while deliberately inefficient opening industry carries
    # a higher burden above. No location identity participates in this rule.
    for definition_id, definition in tuple(definitions.items()):
        if definition.maintenance_fraction_per_year <= 1e-12:
            definitions[definition_id] = FacilityDef(
                definition.id, definition.display_name, definition.capability_supplies,
                definition.installation_environment, definition.operating_environment, 0.05,
                placement_scope=definition.placement_scope,
            )
    return definitions


def initial_facility_placements() -> tuple[tuple, ...]:
    return (
        (ids.EARTH_RESEARCH_LAB, ids.EARTH),
        (ids.EARTH_OBSERVATION_SATELLITE, ids.LEO),
        (ids.GRID_POWER_SUPPLY, ids.EARTH),
        (ids.EARTH_LAUNCH_SUPPORT, ids.EARTH),
        (ids.VEHICLE_ASSEMBLY_FACILITY, ids.EARTH),
        (ids.SURFACE_AGGREGATE_QUARRY, ids.EARTH),
        (ids.METAL_ORE_MINE, ids.EARTH),
        (ids.INDUSTRIAL_WATER_INTAKE, ids.EARTH),
        (ids.BASIC_STRUCTURAL_MATERIAL_PLANT, ids.EARTH),
        (ids.BASIC_MACHINERY_WORKS, ids.EARTH),
    )


def initial_facility_investments() -> dict:
    """Content-owned physical investment history for starting facilities."""
    S, M, E = ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS
    return {
        ids.EARTH_RESEARCH_LAB: {S: 12.0, M: 10.0, E: 8.0},
        ids.EARTH_OBSERVATION_SATELLITE: {S: 1.5, M: 1.0, E: 1.0},
        ids.GRID_POWER_SUPPLY: {S: 8.0, M: 6.0},
        ids.EARTH_LAUNCH_SUPPORT: {S: 10.0, M: 8.0, E: 2.0},
        ids.VEHICLE_ASSEMBLY_FACILITY: {S: 10.0, M: 10.0, E: 3.0},
        ids.SURFACE_AGGREGATE_QUARRY: {S: 5.0, M: 7.0},
        ids.METAL_ORE_MINE: {S: 6.0, M: 8.0},
        ids.INDUSTRIAL_WATER_INTAKE: {S: 5.0, M: 5.0},
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: {S: 8.0, M: 8.0},
        ids.BASIC_MACHINERY_WORKS: {S: 8.0, M: 10.0, E: 1.0},
    }
