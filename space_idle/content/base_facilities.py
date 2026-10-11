from __future__ import annotations

from dataclasses import replace

from ..facilities import FacilityDef, FacilityPlacementScope, LifeSupportSpec
from . import base_ids as ids
from . import base_requirements as req


def build_facility_definitions() -> dict:
    surface = req.SURFACE_SITE
    orbit = req.ORBIT_SITE
    definitions = {
        ids.ORBITAL_CONSTRUCTION_PLATFORM: FacilityDef(
            ids.ORBITAL_CONSTRUCTION_PLATFORM, "軌道上ロボット施工プラットフォーム",
            req._capabilities("robotic_orbital_construction"), orbit, orbit,
        ),
        ids.ORBITAL_SOLAR_ARRAY: FacilityDef(
            ids.ORBITAL_SOLAR_ARRAY, "軌道上太陽電池アレイ",
            req._capabilities("orbital_solar_generation"), orbit, orbit,
        ),
        ids.TRACKING_ORBITAL_SOLAR_ARRAY: FacilityDef(
            ids.TRACKING_ORBITAL_SOLAR_ARRAY, "軌道追尾式多接合太陽電池アレイ",
            req._capabilities("orbital_solar_generation"), orbit, orbit,
        ),
        ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER: FacilityDef(
            ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER, "軌道高出力核分裂電源",
            req._capabilities("orbital_power_supply", "fission_reactor_control_instrumentation"), orbit, orbit,
        ),
        ids.ORBITAL_PROPELLANT_DEPOT: FacilityDef(
            ids.ORBITAL_PROPELLANT_DEPOT, "軌道上推進剤貯蔵・補給所",
            req._capabilities("vehicle_refueling", "cryogenic_storage", "orbital_fuel_transfer"),
            orbit, orbit, service_capacity_supplies=req._services(spacecraft_servicing=0.3),
        ),
        ids.ORBITAL_MATERIALS_WORKSHOP: FacilityDef(
            ids.ORBITAL_MATERIALS_WORKSHOP, "軌道トラス加工・精密工作モジュール",
            req._capabilities("structural_fabrication", "basic_machine_shop", "precision_machining"),
            orbit, orbit, process_throughput_per_day=2.5,
        ),
        ids.NUCLEAR_THERMAL_TEST_STAND: FacilityDef(
            ids.NUCLEAR_THERMAL_TEST_STAND, "核熱推進模擬炉心・水素流動試験設備",
            req._capabilities("nuclear_thermal_flow_test_equipment", "research_lab"),
            req.SiteRequirements(), req.SiteRequirements(),
        ),
        ids.PLASMA_PROPULSION_TEST_MODULE: FacilityDef(
            ids.PLASMA_PROPULSION_TEST_MODULE, "高電圧プラズマ推進器・真空試験モジュール",
            req._capabilities("plasma_propulsion_test_instrumentation", "research_lab"),
            orbit, orbit,
        ),
        ids.ORBITAL_HEAVY_CARGO_TERMINAL: FacilityDef(
            ids.ORBITAL_HEAVY_CARGO_TERMINAL, "大型貨物係留・移載ターミナル",
            req._capabilities("cargo_transfer", "spacecraft_servicing", "vehicle_refueling", "orbital_fuel_transfer"),
            orbit, orbit, service_capacity_supplies=req._services(cargo_transfer=4.0, spacecraft_servicing=2.0),
        ),
        ids.ORBITAL_ASSEMBLY_YARD: FacilityDef(
            ids.ORBITAL_ASSEMBLY_YARD, "軌道上宇宙機組立ヤード",
            req._capabilities("vehicle_assembly", "robotic_orbital_assembly"), orbit, orbit,
            service_capacity_supplies=req._services(vehicle_assembly=1.4),
        ),
        # Reuse the exact production Process used at surface greenhouses. The
        # orbital installation needs pressurized rooting equipment and active
        # environmental control; it does not create a second Food economy.
        ids.ORBITAL_HYDROPONICS: FacilityDef(
            ids.ORBITAL_HYDROPONICS, "軌道閉鎖環境水耕栽培ユニット",
            req._capabilities("food_hydroponics"), orbit, orbit,
            process_throughput_per_day=1.6,
        ),
        # A separate gas-generation skid allows the same water electrolysis
        # Process to feed crew Oxygen and hydrogen-propellant operations in
        # orbit. Its Power/maintenance and inventory are not implicit buffs.
        ids.ORBITAL_WATER_ELECTROLYSIS: FacilityDef(
            ids.ORBITAL_WATER_ELECTROLYSIS, "軌道水電解・ガス分離モジュール",
            req._capabilities("industrial_electrolysis"), orbit, orbit,
            process_throughput_per_day=2.1,
        ),
        # Physically powered data/knowledge retention capacity, rather than a
        # second lab that also generates RP. A distant science campaign needs
        # Research admission headroom but does not automatically create it.
        ids.RESEARCH_DATA_ARCHIVE: FacilityDef(
            ids.RESEARCH_DATA_ARCHIVE, "宇宙探査研究データ保存・受入アーカイブ",
            req._capabilities("research_data_retention"),
            req.SiteRequirements(), req.SiteRequirements(),
        ),
        # Material testing needs a physical beamline and calibrated strain
        # instruments rather than a generic research throughput multiplier.
        ids.MATERIALS_FATIGUE_BEAMLINE: FacilityDef(
            ids.MATERIALS_FATIGUE_BEAMLINE, "複合熱・放射線材料疲労試験施設",
            req._capabilities("research_lab", "material_fatigue_beamline"),
            surface, surface, maintenance_fraction_per_year=0.085,
        ),
        # An unmanned orbital thermal/vacuum laboratory provides experiments
        # inaccessible to the surface beamline, with power and cooling demand.
        ids.ORBITAL_THERMAL_VACUUM_LAB: FacilityDef(
            ids.ORBITAL_THERMAL_VACUUM_LAB, "軌道熱真空・二相流実験モジュール",
            req._capabilities("research_lab", "orbital_thermal_vacuum_calorimetry"),
            orbit, orbit, maintenance_fraction_per_year=0.09,
        ),
        # Life-science research requires an inhabited, operating closed-loop
        # habitat. Research RP consumes real local crew capacity, not a free
        # laboratory-wide research buff or a separate Crew owner.
        ids.BIOREGENERATIVE_BIOMEDICAL_LAB: FacilityDef(
            ids.BIOREGENERATIVE_BIOMEDICAL_LAB, "閉鎖生態・宇宙生体曝露解析施設",
            req._capabilities("research_lab", "bioregenerative_biomedical_research"),
            req.SiteRequirements(), req.SiteRequirements(),
            maintenance_fraction_per_year=0.09,
        ),
        ids.ORBITAL_HABITAT: FacilityDef(
            ids.ORBITAL_HABITAT, "軌道居住・生命維持モジュール",
            req._capabilities("pressurized_habitation"), orbit, orbit, housing_capacity=18,
            life_support=LifeSupportSpec(18, ((ids.FOOD, 0.001), (ids.WATER, 0.002), (ids.OXYGEN, 0.003))),
        ),
        ids.PROPULSION_TEST_FACILITY: FacilityDef(
            ids.PROPULSION_TEST_FACILITY, "ロケット推進系試験場",
            req._capabilities("propulsion_test_equipment", "research_lab"), surface, surface,
        ),
        ids.DEEP_SPACE_TRACKING_ARRAY: FacilityDef(
            ids.DEEP_SPACE_TRACKING_ARRAY, "深宇宙通信・測距アンテナ群",
            req._capabilities("deep_space_tracking_equipment", "research_lab"), surface, surface,
        ),
        ids.SURFACE_ROVER_SERVICE_DEPOT: FacilityDef(
            ids.SURFACE_ROVER_SERVICE_DEPOT, "地表探査車整備・充填拠点",
            req._capabilities("rover_maintenance"), surface, surface,
            service_capacity_supplies=req._services(surface_vehicle_servicing=1.2),
        ),
        ids.GENERAL_RESEARCH_LAB: FacilityDef(ids.GENERAL_RESEARCH_LAB, "総合研究所", req._capabilities("research_lab", "general_research_equipment"), surface, surface),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: FacilityDef(ids.MICROGRAVITY_EXPERIMENT_PLATFORM, "微小重力実験プラットフォーム", req._capabilities("research_lab", "microgravity_experiment_equipment"), orbit, orbit),
        ids.CREWED_ORBITAL_LABORATORY: FacilityDef(ids.CREWED_ORBITAL_LABORATORY, "有人軌道研究所", req._capabilities("research_lab", "crewed_orbital_research_equipment"), orbit, req.SiteRequirements(environment=req.LOW_RADIATION_ENV, spatial_classification_requirements=req.ORBIT_CLASSIFICATION)),
        ids.ROBOTIC_GEOLOGY_STATION: FacilityDef(ids.ROBOTIC_GEOLOGY_STATION, "ロボット地質調査ステーション", req._capabilities("research_lab", "robotic_geology_equipment", "surface_survey", "robotic_operations"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
        ids.SAMPLE_ANALYSIS_LABORATORY: FacilityDef(ids.SAMPLE_ANALYSIS_LABORATORY, "試料分析研究所", req._capabilities("research_lab", "sample_analysis_equipment"), surface, surface),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: FacilityDef(ids.VACUUM_REGOLITH_PROCESS_LABORATORY, "真空レゴリスプロセス研究所", req._capabilities("research_lab", "vacuum_regolith_research_equipment"), surface, req.VACUUM_SURFACE_SITE),
        ids.GRID_POWER_SUPPLY: FacilityDef(
            ids.GRID_POWER_SUPPLY, "外部電力網接続", req._capabilities("grid_power"),
            req.EXTERNAL_GRID_SITE, req.EXTERNAL_GRID_SITE,
            placement_scope=FacilityPlacementScope.SURFACE_CELL,
        ),
        ids.ORBITAL_FISSION_POWER: FacilityDef(ids.ORBITAL_FISSION_POWER, "軌道核分裂電源", req._capabilities("orbital_power_supply", "fission_reactor_control_instrumentation"), orbit, orbit),
        ids.ORBITAL_LOGISTICS_NODE: FacilityDef(ids.ORBITAL_LOGISTICS_NODE, "軌道物流・整備ノード", req._capabilities("cargo_transfer", "vehicle_refueling", "spacecraft_servicing"), orbit, orbit, service_capacity_supplies=req._services(cargo_transfer=1.0, spacecraft_servicing=1.0)),
        ids.SURFACE_LAUNCH_SUPPORT: FacilityDef(ids.SURFACE_LAUNCH_SUPPORT, "打上げ・回収整備設備", req._capabilities("cargo_transfer", "vehicle_refueling", "launch_vehicle_servicing", "launch_operations", "surface_access_anchor"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL, service_capacity_supplies=req._services(cargo_transfer=1.0, launch_vehicle_servicing=1.0)),
        ids.CARGO_LAUNCH_INTEGRATION_PAD: FacilityDef(
            ids.CARGO_LAUNCH_INTEGRATION_PAD, "貨物ロケット地上統合・再使用整備射場",
            req._capabilities("cargo_transfer", "vehicle_refueling", "launch_vehicle_servicing",
                              "launch_operations", "surface_access_anchor"),
            surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL,
            service_capacity_supplies=req._services(cargo_transfer=2.5,
                                                     launch_vehicle_servicing=2.2),
        ),
        ids.VEHICLE_ASSEMBLY_FACILITY: FacilityDef(ids.VEHICLE_ASSEMBLY_FACILITY, "宇宙輸送機製造・組立設備", req._capabilities("vehicle_assembly"), surface, surface, service_capacity_supplies=req._services(vehicle_assembly=1.0)),
        ids.ROBOTIC_SURVEY_PACKAGE: FacilityDef(ids.ROBOTIC_SURVEY_PACKAGE, "ロボット探査・初期建設パッケージ", req._capabilities("surface_survey", "robotic_prospecting_kit", "base_construction", "robotic_operations", "spacecraft_servicing", "cargo_transfer", "surface_access_anchor"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL, service_capacity_supplies=req._services(cargo_transfer=1.0, spacecraft_servicing=1.0)),
        ids.SURFACE_POWER_GRID: FacilityDef(ids.SURFACE_POWER_GRID, "地表太陽光発電・配電設備", req._capabilities("power_grid"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
        ids.INDUSTRIAL_POWER_BLOCK: FacilityDef(ids.INDUSTRIAL_POWER_BLOCK, "核分裂電源ユニット", req._capabilities("industrial_power", "fission_reactor_control_instrumentation"), surface, surface),
        ids.CONSTRUCTION_YARD: FacilityDef(ids.CONSTRUCTION_YARD, "建設ヤード", req._capabilities("construction_yard"), surface, surface),
        ids.VOLATILE_EXTRACTOR: FacilityDef(
            ids.VOLATILE_EXTRACTOR, "揮発性原料採取設備",
            req._capabilities("volatile_extraction"),
            req.COLD_VOLATILE_SURFACE_SITE, req.COLD_VOLATILE_SURFACE_SITE,
            placement_scope=FacilityPlacementScope.SURFACE_CELL,
            extraction_capacity_t_per_day=6.0,
        ),
        ids.VOLATILE_PROCESSING: FacilityDef(ids.VOLATILE_PROCESSING, "揮発性成分回収設備", req._capabilities("volatile_processing"), surface, surface),
        ids.VACUUM_MINERAL_HARVESTER: FacilityDef(ids.VACUUM_MINERAL_HARVESTER, "真空粒状鉱物採掘設備", req._capabilities("granular_mineral_extraction"), surface, req.VACUUM_SURFACE_SITE, extraction_capacity_t_per_day=8.0),
        ids.WATER_STORAGE: FacilityDef(ids.WATER_STORAGE, "水貯蔵タンク", req._capabilities("water_storage"), surface, surface),
        ids.CRYOGENIC_STORAGE: FacilityDef(ids.CRYOGENIC_STORAGE, "極低温貯蔵設備", req._capabilities("cryogenic_storage", "vehicle_refueling"), surface, surface),
        ids.BULK_STORAGE: FacilityDef(ids.BULK_STORAGE, "バルク原料置場", req._capabilities("bulk_storage"), surface, surface),
        ids.CARGO_WAREHOUSE: FacilityDef(ids.CARGO_WAREHOUSE, "一般貨物倉庫", req._capabilities("cargo_storage"), surface, surface),
        ids.VACUUM_CARGO_HANDLING_TERMINAL: FacilityDef(
            ids.VACUUM_CARGO_HANDLING_TERMINAL,
            "低圧地表貨物係留・着陸船整備ターミナル",
            req._capabilities("surface_distribution", "surface_access_anchor", "cargo_transfer",
                              "spacecraft_servicing", "vehicle_refueling"),
            req.VACUUM_SURFACE_SITE, req.VACUUM_SURFACE_SITE,
            placement_scope=FacilityPlacementScope.SURFACE_CELL,
            service_capacity_supplies=req._services(surface_distribution=3.5,
                                                     cargo_transfer=3.0,
                                                     spacecraft_servicing=2.4),
        ),
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
        ids.CRYOGENIC_PROPELLANT_TERMINAL: FacilityDef(
            ids.CRYOGENIC_PROPELLANT_TERMINAL, "極低温推進剤液化・充填ターミナル",
            req._capabilities("propellant_production", "cryogenic_storage", "vehicle_refueling"),
            surface, surface, process_throughput_per_day=4.5,
        ),
        ids.MINERAL_SINTERING: FacilityDef(ids.MINERAL_SINTERING, "鉱物焼結設備", req._capabilities("mineral_sintering"), surface, surface),
        ids.ORE_PROCESSING: FacilityDef(ids.ORE_PROCESSING, "鉱石処理設備", req._capabilities("ore_processing"), surface, surface),
        ids.METALLURGY: FacilityDef(ids.METALLURGY, "金属精錬設備", req._capabilities("metallurgy"), surface, surface),
        ids.FABRICATION_WORKSHOP: FacilityDef(ids.FABRICATION_WORKSHOP, "構造材加工工場", req._capabilities("structural_fabrication"), surface, surface),
        ids.MACHINE_SHOP: FacilityDef(ids.MACHINE_SHOP, "機械工場", req._capabilities("basic_machine_shop", "precision_machining"), surface, surface),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: FacilityDef(ids.HEAVY_EQUIPMENT_ASSEMBLY, "重機組立設備", req._capabilities("heavy_equipment_assembly"), surface, surface),
        ids.MINERAL_QUARRY: FacilityDef(ids.MINERAL_QUARRY, "露天鉱物採掘場", req._capabilities("mineral_extraction"), surface, surface, 0.10, extraction_capacity_t_per_day=2.4),
        ids.METAL_ORE_MINE: FacilityDef(ids.METAL_ORE_MINE, "露天金属鉱山", req._capabilities("metal_ore_extraction"), surface, surface, 0.10, extraction_capacity_t_per_day=1.7),
        # These industrial assets use ordinary Extraction/Process interfaces.
        # Their measured throughput, energy and investment differ; their names
        # describe installed physical functions rather than a generic tier.
        ids.AUTONOMOUS_ORE_MINE: FacilityDef(
            ids.AUTONOMOUS_ORE_MINE, "自律掘削・鉱石搬送鉱山",
            req._capabilities("metal_ore_extraction"), surface, surface,
            extraction_capacity_t_per_day=8.0,
        ),
        ids.CONTINUOUS_ORE_CONCENTRATOR: FacilityDef(
            ids.CONTINUOUS_ORE_CONCENTRATOR, "多段破砕・品位選別プラント",
            req._capabilities("ore_processing"), surface, surface,
            process_throughput_per_day=3.5,
        ),
        ids.CONTINUOUS_REDUCTION_FURNACE: FacilityDef(
            ids.CONTINUOUS_REDUCTION_FURNACE, "原料組成制御型還元精錬炉",
            req._capabilities("metallurgy"), surface, surface,
            process_throughput_per_day=3.0,
        ),
        ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE: FacilityDef(
            ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE, "自動寸法補正構造材加工工場",
            req._capabilities("structural_fabrication"), surface, surface,
            process_throughput_per_day=4.0,
        ),
        ids.INDUSTRIAL_MACHINERY_ASSEMBLY: FacilityDef(
            ids.INDUSTRIAL_MACHINERY_ASSEMBLY, "産業機械モジュール組立工場",
            req._capabilities("industrial_machinery_assembly"), surface, surface,
            process_throughput_per_day=2.2,
        ),
        ids.MICROELECTRONICS_FAB: FacilityDef(
            ids.MICROELECTRONICS_FAB, "薄膜回路・電子モジュール製造工場",
            req._capabilities("microelectronics_fabrication"), surface, surface,
            process_throughput_per_day=1.6,
        ),
        ids.MOLTEN_OXIDE_ELECTROLYZER: FacilityDef(
            ids.MOLTEN_OXIDE_ELECTROLYZER, "溶融酸化物電解製錬設備",
            req._capabilities("molten_oxide_electrolysis"),
            surface, surface,
            process_throughput_per_day=2.0,
        ),
        ids.INDUSTRIAL_WATER_INTAKE: FacilityDef(ids.INDUSTRIAL_WATER_INTAKE, "工業用水取水・処理設備", req._capabilities("industrial_water_supply"), surface, surface, 0.08, extraction_capacity_t_per_day=1.0),
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: FacilityDef(ids.BASIC_STRUCTURAL_MATERIAL_PLANT, "基礎構造材工場", req._capabilities("basic_structural_material"), surface, surface, 0.09),
        ids.BASIC_MACHINERY_WORKS: FacilityDef(ids.BASIC_MACHINERY_WORKS, "基礎機械製作所", req._capabilities("basic_machinery_production"), surface, surface, 0.09),
    }
    # The physical recirculation hardware is installed after its Research and
    # construction investment. These modules can be transported as real cargo
    # to any operational site with enough Power and maintenance, rather than
    # being licensed by a planet name or a scenario-only subsidy.
    definitions[ids.BIOREGENERATIVE_GROWTH_MODULE] = FacilityDef(
        ids.BIOREGENERATIVE_GROWTH_MODULE, "再生養液・閉鎖環境栽培モジュール",
        req._capabilities("food_hydroponics", "recirculating_hydroponics"),
        process_throughput_per_day=1.8, maintenance_fraction_per_year=0.075,
    )
    definitions[ids.VOLATILE_FRACTIONATION_PLANT] = FacilityDef(
        ids.VOLATILE_FRACTIONATION_PLANT, "多段揮発成分分留・凝縮装置",
        req._capabilities("volatile_processing", "multistage_volatile_fractionation"),
        process_throughput_per_day=2.2, maintenance_fraction_per_year=0.075,
    )
    # Distinct installed pressure/atmosphere and water-reclamation hardware.
    # Lower *net* demand reflects internal closed-cycle recovery, not a new
    # Resource source or a free technological change to existing habitats.
    definitions[ids.CLOSED_CYCLE_HABITAT] = FacilityDef(
        ids.CLOSED_CYCLE_HABITAT, "閉鎖水循環・大気再生居住区",
        req._capabilities("pressurized_habitation", "closed_cycle_life_support"),
        housing_capacity=48, maintenance_fraction_per_year=0.085,
        life_support=LifeSupportSpec(48, ((ids.FOOD, 0.001),
                                        (ids.WATER, 0.00040),
                                        (ids.OXYGEN, 0.0014))),
    )
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
    definitions[ids.BREATHABLE_SURFACE_LIFE_SUPPORT] = FacilityDef(
        ids.BREATHABLE_SURFACE_LIFE_SUPPORT, '地上居住・生活供給設備', housing_capacity=160,
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
