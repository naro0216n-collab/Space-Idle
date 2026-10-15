"""Standard physical-asset Content: one typed entry per Facility/Vehicle.

Facility acquisition, operation and physical capacities are authored together.
Other Content remains in its respective domain-oriented module.
"""
from __future__ import annotations
from dataclasses import replace
from ..facilities import FacilityDef, FacilityPlacementScope, LifeSupportSpec
from .asset_content import FacilityAsset
from . import base_ids as ids
from .base_extended_assets import build_extended_facility_assets
from .base_concept_assets import build_concept_facility_assets
from .base_extended_vehicles import build_extended_vehicle_defs
from .base_concept_vehicles import build_concept_vehicle_defs
from . import base_requirements as req
from ..projects import ConstructionProviderSpec, ConstructionRecipe, FacilityDecommissionRecipe, FacilityUpgradeRecipe, BuildResourceRequirement
from ..site import SiteRequirements
from ..power import FixedGeneration, PowerSpec, SolarGeneration
from ..storage import StorageProviderSpec
from ..shared import DefinitionId
from ..transport import AtmosphericEntryCapability, LandingCapability, OperationSupportLocation, OperationSupportRequirement, ResourceSupportRequirement, PoweredAscentCapability, SpaceflightCapability, SurfaceTransportCapability, TransportOperationKind, TransportPerformanceProfile, VehicleDef, OperationAssetDisposition, VehicleMaintenanceSpec, VehicleProductionSpec, VehicleRetirementSpec, PassengerAccommodation


def build_base_assets() -> tuple[tuple[FacilityAsset, ...], tuple[VehicleDef, ...]]:
    """Single authoritative authored asset list, used by normal Composition."""
    surface = req.SURFACE_SITE
    orbit = req.ORBIT_SITE
    facilities = (
        # THERMAL_HARDWARE_ASSEMBLY
        FacilityAsset(
            definition=FacilityDef(
                        ids.THERMAL_HARDWARE_ASSEMBLY, "ヒートパイプ封止・放熱器組立工場",
                        req._capabilities("heat_pipe_radiator_assembly"),
                        req.SiteRequirements(), req.SiteRequirements(),
                        process_throughput_per_day=1.8,
                    ),
            construction=ConstructionRecipe(
                        ids.THERMAL_HARDWARE_ASSEMBLY,
                        (req._structure_resource(14.0), req._machinery_resource(12.0),
                         req._electronics_resource(5.0)), 65.0, req.SiteRequirements(),
                        frozenset({ids.research_id("TH-THERMAL-TRANSPORT-03")}),
                    ),
            power=PowerSpec(None, 1.35, standby_load_mw=0.09),
        ),
        # SHIELDING_PANEL_FABRICATION
        FacilityAsset(
            definition=FacilityDef(
                        ids.SHIELDING_PANEL_FABRICATION, "積層鉱物放射線遮蔽パネル工場",
                        req._capabilities("graded_radiation_shielding"),
                        req.SiteRequirements(), req.SiteRequirements(),
                        process_throughput_per_day=2.5,
                    ),
            construction=ConstructionRecipe(
                        ids.SHIELDING_PANEL_FABRICATION,
                        (req._structure_resource(17.0), req._machinery_resource(10.0),
                         req._electronics_resource(3.0)), 58.0, req.SiteRequirements(),
                        frozenset({ids.research_id("HB-HABITATION-PROTECTION-04")}),
                    ),
            power=PowerSpec(None, 0.85, standby_load_mw=0.07),
        ),
        # OPTICAL_INSTRUMENT_INTEGRATION
        FacilityAsset(
            definition=FacilityDef(
                        ids.OPTICAL_INSTRUMENT_INTEGRATION, "光学計測器芯出し・組立工場",
                        req._capabilities("precision_optical_alignment"),
                        req.SiteRequirements(), req.SiteRequirements(),
                        process_throughput_per_day=1.3,
                    ),
            construction=ConstructionRecipe(
                        ids.OPTICAL_INSTRUMENT_INTEGRATION,
                        (req._structure_resource(9.0), req._machinery_resource(15.0),
                         req._electronics_resource(12.0)), 78.0, req.SiteRequirements(),
                        frozenset({ids.research_id("CO-OPTICAL-COMMUNICATIONS-01")}),
                    ),
            power=PowerSpec(None, 1.75, standby_load_mw=0.18),
        ),
        # ORBITAL_CONSTRUCTION_PLATFORM
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_CONSTRUCTION_PLATFORM, "軌道上ロボット施工プラットフォーム",
                        req._capabilities("robotic_orbital_construction"), orbit, orbit,
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_CONSTRUCTION_PLATFORM,
                        (req._structure_resource(4.0), req._machinery_resource(3.0), req._electronics_resource(1.5)),
                        0.0, req.ORBIT_SITE, frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_01}), True,
                    ),
            power=PowerSpec(SolarGeneration(0.35 / 0.62, 1361.0), 0.15),
            construction_provider=ConstructionProviderSpec(ids.ORBITAL_CONSTRUCTION_PLATFORM, 0.7),
        ),
        # ORBITAL_SOLAR_ARRAY
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_SOLAR_ARRAY, "軌道上太陽電池アレイ",
                        req._capabilities("orbital_solar_generation"), orbit, orbit,
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_SOLAR_ARRAY,
                        (req._structure_resource(3.0), req._machinery_resource(1.0), req._electronics_resource(1.2)),
                        0.0, req.ORBIT_SITE, frozenset({ids.PG_SOLAR_POWER_02}), True,
                    ),
            power=PowerSpec(SolarGeneration(4.0 / 0.62, 1361.0), 0.04),
        ),
        # TRACKING_ORBITAL_SOLAR_ARRAY
        FacilityAsset(
            definition=FacilityDef(
                        ids.TRACKING_ORBITAL_SOLAR_ARRAY, "軌道追尾式多接合太陽電池アレイ",
                        req._capabilities("orbital_solar_generation"), orbit, orbit,
                    ),
            construction=ConstructionRecipe(
                        ids.TRACKING_ORBITAL_SOLAR_ARRAY,
                        (req._structure_resource(6.0),
                         req._machinery_resource(3.5),
                         BuildResourceRequirement(ids.OPTICAL_INSTRUMENT_PACKAGES, 0.6)),
                        28.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.research_id("PG-SOLAR-POWER-04"), ids.research_id("MC-MANUFACTURING-CONSTRUCTION-04")}),
                    ),
            power=PowerSpec(SolarGeneration(10.0 / 0.62, 1361.0), 0.09),
        ),
        # HIGH_OUTPUT_ORBITAL_FISSION_POWER
        FacilityAsset(
            definition=FacilityDef(
                        ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER, "軌道高出力核分裂電源",
                        req._capabilities("orbital_power_supply", "fission_reactor_control_instrumentation"), orbit, orbit,
                    ),
            construction=ConstructionRecipe(
                        ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER,
                        (req._structure_resource(9.0),
                         BuildResourceRequirement(ids.THERMAL_CONTROL_ASSEMBLIES, 2.0),
                         BuildResourceRequirement(ids.RADIATION_SHIELDING_PANELS, 3.0)),
                        44.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.research_id("FP-REACTOR-POWER-04")}),
                    ),
            power=PowerSpec(FixedGeneration(7.0), 0.20),
        ),
        # ORBITAL_PROPELLANT_DEPOT
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_PROPELLANT_DEPOT, "軌道上推進剤貯蔵・補給所",
                        req._capabilities("vehicle_refueling", "cryogenic_storage", "orbital_fuel_transfer"),
                        orbit, orbit, service_capacity_supplies=req._services(spacecraft_servicing=0.3),
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_PROPELLANT_DEPOT,
                        (req._structure_resource(7.0), req._machinery_resource(5.0), req._electronics_resource(2.0)),
                        26.0, req.ORBIT_SITE, frozenset({ids.research_id("CR-CRYOGENIC-STORAGE-TRANSFER-08")}),
                    ),
            power=PowerSpec(None, 0.20, standby_load_mw=0.20),
            storage=StorageProviderSpec(
                        ids.ORBITAL_PROPELLANT_DEPOT, {"cryogenic": 80.0}, frozenset({"cryogenic"}),
                    ),
        ),
        # ORBITAL_MATERIALS_WORKSHOP
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_MATERIALS_WORKSHOP, "軌道トラス加工・精密工作モジュール",
                        req._capabilities("structural_fabrication", "basic_machine_shop", "precision_machining"),
                        orbit, orbit, process_throughput_per_day=2.5,
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_MATERIALS_WORKSHOP,
                        (req._structure_resource(14.0), req._machinery_resource(12.0), req._electronics_resource(5.0)),
                        54.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_14}),
                    ),
            power=PowerSpec(None, 1.25, standby_load_mw=0.08),
        ),
        # NUCLEAR_THERMAL_TEST_STAND
        FacilityAsset(
            definition=FacilityDef(
                        ids.NUCLEAR_THERMAL_TEST_STAND, "核熱推進模擬炉心・水素流動試験設備",
                        req._capabilities("nuclear_thermal_flow_test_equipment", "research_lab"),
                        req.SiteRequirements(), req.SiteRequirements(),
                    ),
            construction=ConstructionRecipe(
                        ids.NUCLEAR_THERMAL_TEST_STAND,
                        (req._machinery_resource(10.0),
                         BuildResourceRequirement(ids.THERMAL_CONTROL_ASSEMBLIES, 2.0),
                         BuildResourceRequirement(ids.RADIATION_SHIELDING_PANELS, 2.0)),
                        60.0,
                        req.with_capabilities(req.SiteRequirements(), "fission_reactor_control_instrumentation"),
                        frozenset({ids.research_id("NT-NUCLEAR-THERMAL-01"),
                                   ids.research_id("FP-REACTOR-POWER-02")}),
                    ),
            power=PowerSpec(None, 1.50, standby_load_mw=0.12),
        ),
        # PLASMA_PROPULSION_TEST_MODULE
        FacilityAsset(
            definition=FacilityDef(
                        ids.PLASMA_PROPULSION_TEST_MODULE, "高電圧プラズマ推進器・真空試験モジュール",
                        req._capabilities("plasma_propulsion_test_instrumentation", "research_lab"),
                        orbit, orbit,
                    ),
            construction=ConstructionRecipe(
                        ids.PLASMA_PROPULSION_TEST_MODULE,
                        (req._structure_resource(9.0), req._machinery_resource(7.0),
                         req._electronics_resource(6.0)),
                        37.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.research_id("EP-PLASMA-THRUSTERS-01"),
                                   ids.research_id("PD-STORAGE-DISTRIBUTION-04")}),
                    ),
            power=PowerSpec(None, 1.65, standby_load_mw=0.08),
        ),
        # ORBITAL_HEAVY_CARGO_TERMINAL
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_HEAVY_CARGO_TERMINAL, "大型貨物係留・移載ターミナル",
                        req._capabilities("cargo_transfer", "spacecraft_servicing", "vehicle_refueling", "orbital_fuel_transfer"),
                        orbit, orbit, service_capacity_supplies=req._services(cargo_transfer=4.0, spacecraft_servicing=2.0),
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_HEAVY_CARGO_TERMINAL,
                        (req._structure_resource(22.0), req._machinery_resource(15.0), req._electronics_resource(6.0)),
                        72.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.LM_LOGISTICS_MAINTENANCE_13}),
                    ),
            power=PowerSpec(None, 0.65, standby_load_mw=0.20),
        ),
        # ORBITAL_ASSEMBLY_YARD
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_ASSEMBLY_YARD, "軌道上宇宙機組立ヤード",
                        req._capabilities("vehicle_assembly", "robotic_orbital_assembly"), orbit, orbit,
                        service_capacity_supplies=req._services(vehicle_assembly=1.4),
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_ASSEMBLY_YARD,
                        (req._structure_resource(14.0), req._machinery_resource(12.0), req._electronics_resource(3.5)),
                        50.0, req.ORBIT_SITE, frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_05}),
                    ),
            power=PowerSpec(None, 0.95),
        ),
        # ORBITAL_HYDROPONICS
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_HYDROPONICS, "軌道閉鎖環境水耕栽培ユニット",
                        req._capabilities("food_hydroponics"), orbit, orbit,
                        process_throughput_per_day=1.6,
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_HYDROPONICS,
                        (req._structure_resource(10.0), req._machinery_resource(9.0),
                         req._electronics_resource(5.0)),
                        55.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.research_id("PL-PLANT-FOOD-04"),
                                   ids.research_id("PL-PLANT-FOOD-05")}),
                    ),
            power=PowerSpec(None, 1.05, standby_load_mw=0.12),
        ),
        # ORBITAL_WATER_ELECTROLYSIS
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_WATER_ELECTROLYSIS, "軌道水電解・ガス分離モジュール",
                        req._capabilities("industrial_electrolysis"), orbit, orbit,
                        process_throughput_per_day=2.1,
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_WATER_ELECTROLYSIS,
                        (req._structure_resource(9.0), req._machinery_resource(10.0),
                         req._electronics_resource(5.0)),
                        48.0, req.with_capabilities(req.ORBIT_SITE, "robotic_orbital_construction"),
                        frozenset({ids.research_id("RP-RESOURCE-CHAIN-12"),
                                   ids.research_id("CR-CRYOGENIC-STORAGE-TRANSFER-04")}),
                    ),
            power=PowerSpec(None, 1.65, standby_load_mw=0.10),
        ),
        # RESEARCH_DATA_ARCHIVE
        FacilityAsset(
            definition=FacilityDef(
                        ids.RESEARCH_DATA_ARCHIVE, "宇宙探査研究データ保存・受入アーカイブ",
                        req._capabilities("research_data_retention"),
                        req.SiteRequirements(), req.SiteRequirements(),
                    ),
            construction=ConstructionRecipe(
                        ids.RESEARCH_DATA_ARCHIVE,
                        (req._structure_resource(7.0), req._machinery_resource(8.0),
                         req._electronics_resource(12.0)),
                        42.0, req.SiteRequirements(),
                        frozenset({ids.research_id("PL-EARTH-RESEARCH-ARCHIVE")}),
                    ),
            power=PowerSpec(None, 0.60, standby_load_mw=0.38),
        ),
        # MATERIALS_FATIGUE_BEAMLINE
        FacilityAsset(
            definition=FacilityDef(
                        ids.MATERIALS_FATIGUE_BEAMLINE, "複合熱・放射線材料疲労試験施設",
                        req._capabilities("research_lab", "material_fatigue_beamline"),
                        surface, surface, maintenance_fraction_per_year=0.085,
                    ),
            construction=ConstructionRecipe(
                        ids.MATERIALS_FATIGUE_BEAMLINE,
                        (req._machinery_resource(26.0),
                         BuildResourceRequirement(ids.RADIATION_SHIELDING_PANELS, 4.0),
                         BuildResourceRequirement(ids.OPTICAL_INSTRUMENT_PACKAGES, 0.8)),
                        145.0, req.with_capabilities(req.SURFACE_SITE,
                                                      "precision_machining"),
                        frozenset({ids.research_id("MS-MATERIALS-07"),
                                   ids.research_id("TH-THERMAL-TRANSPORT-05")}),
                    ),
            power=PowerSpec(None, 3.5, standby_load_mw=0.12),
        ),
        # ORBITAL_THERMAL_VACUUM_LAB
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_THERMAL_VACUUM_LAB, "軌道熱真空・二相流実験モジュール",
                        req._capabilities("research_lab", "orbital_thermal_vacuum_calorimetry"),
                        orbit, orbit, maintenance_fraction_per_year=0.09,
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_THERMAL_VACUUM_LAB,
                        (req._machinery_resource(28.0),
                         BuildResourceRequirement(ids.THERMAL_CONTROL_ASSEMBLIES, 3.0),
                         BuildResourceRequirement(ids.OPTICAL_INSTRUMENT_PACKAGES, 1.0)),
                        172.0, req.with_capabilities(req.ORBIT_SITE,
                                                      "robotic_orbital_construction"),
                        frozenset({ids.research_id("TH-THERMAL-TRANSPORT-06"),
                                   ids.research_id("MC-MANUFACTURING-CONSTRUCTION-05")}),
                    ),
            power=PowerSpec(None, 2.8, standby_load_mw=0.18),
        ),
        # BIOREGENERATIVE_BIOMEDICAL_LAB
        FacilityAsset(
            definition=FacilityDef(
                        ids.BIOREGENERATIVE_BIOMEDICAL_LAB, "閉鎖生態・宇宙生体曝露解析施設",
                        req._capabilities("research_lab", "bioregenerative_biomedical_research"),
                        req.SiteRequirements(), req.SiteRequirements(),
                        maintenance_fraction_per_year=0.09,
                    ),
            construction=ConstructionRecipe(
                        ids.BIOREGENERATIVE_BIOMEDICAL_LAB,
                        (req._machinery_resource(30.0),
                         BuildResourceRequirement(ids.RADIATION_SHIELDING_PANELS, 3.0),
                         BuildResourceRequirement(ids.OPTICAL_INSTRUMENT_PACKAGES, 0.8)),
                        160.0, req.with_capabilities(req.SiteRequirements(),
                                                      "closed_cycle_life_support"),
                        frozenset({ids.research_id("BIO-HUMAN-BIOLOGY-MEDICINE-09"),
                                   ids.research_id("LS-ATMOSPHERE-WATER-WASTE-09")}),
                    ),
            power=PowerSpec(None, 2.2, standby_load_mw=0.32),
        ),
        # ORBITAL_HABITAT
        FacilityAsset(
            definition=FacilityDef(
                        ids.ORBITAL_HABITAT, "軌道居住・生命維持モジュール",
                        req._capabilities("pressurized_habitation"), orbit, orbit, housing_capacity=18,
                        life_support=LifeSupportSpec(18, ((ids.FOOD, 0.001), (ids.WATER, 0.002), (ids.OXYGEN, 0.003))),
                    ),
            construction=ConstructionRecipe(
                        ids.ORBITAL_HABITAT,
                        (req._structure_resource(7.0), req._machinery_resource(5.0), req._electronics_resource(3.0)),
                        30.0, req.ORBIT_SITE, frozenset({ids.LS_ATMOSPHERE_WATER_WASTE_01}),
                    ),
            power=PowerSpec(None, 0.55),
        ),
        # PROPULSION_TEST_FACILITY
        FacilityAsset(
            definition=FacilityDef(
                        ids.PROPULSION_TEST_FACILITY, "ロケット推進系試験場",
                        req._capabilities("propulsion_test_equipment", "research_lab"), surface, surface,
                    ),
            construction=req._surface_recipe(
                        ids.PROPULSION_TEST_FACILITY, 10.0, 10.0, 4.0, 55.0,
                        technologies=frozenset({ids.research_id("CH-COMBUSTION-01")}),
                    ),
            power=PowerSpec(None, 0.45),
        ),
        # DEEP_SPACE_TRACKING_ARRAY
        FacilityAsset(
            definition=FacilityDef(
                        ids.DEEP_SPACE_TRACKING_ARRAY, "深宇宙通信・測距アンテナ群",
                        req._capabilities("deep_space_tracking_equipment", "research_lab"), surface, surface,
                    ),
            construction=ConstructionRecipe(
                        ids.DEEP_SPACE_TRACKING_ARRAY,
                        (req._structure_resource(8.0),
                         req._machinery_resource(5.0),
                         BuildResourceRequirement(ids.OPTICAL_INSTRUMENT_PACKAGES, 1.0)),
                        42.0, req.SURFACE_SITE,
                        frozenset({ids.research_id("CO-RF-COMMUNICATIONS-02")}),
                    ),
            power=PowerSpec(None, 0.38),
        ),
        # SURFACE_ROVER_SERVICE_DEPOT
        FacilityAsset(
            definition=FacilityDef(
                        ids.SURFACE_ROVER_SERVICE_DEPOT, "地表探査車整備・充填拠点",
                        req._capabilities("rover_maintenance"), surface, surface,
                        service_capacity_supplies=req._services(surface_vehicle_servicing=1.2),
                    ),
            construction=req._surface_recipe(
                        ids.SURFACE_ROVER_SERVICE_DEPOT, 4.0, 5.0, 1.0, 23.0,
                        technologies=frozenset({ids.research_id("SM-SURFACE-MOBILITY-01")}),
                    ),
            power=PowerSpec(None, 0.15),
        ),
        # GENERAL_RESEARCH_LAB
        FacilityAsset(
            definition=FacilityDef(ids.GENERAL_RESEARCH_LAB, "総合研究所", req._capabilities("research_lab", "general_research_equipment"), surface, surface),
            construction=req._surface_recipe(
                        ids.GENERAL_RESEARCH_LAB, 12, 10, 8, 55,
                    ),
            power=PowerSpec(None, 0.10),
        ),
        # MICROGRAVITY_EXPERIMENT_PLATFORM
        FacilityAsset(
            definition=FacilityDef(ids.MICROGRAVITY_EXPERIMENT_PLATFORM, "微小重力実験プラットフォーム", req._capabilities("research_lab", "microgravity_experiment_equipment"), orbit, orbit),
            construction=ConstructionRecipe(
                        ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
                        (req._structure_resource(2.0), req._machinery_resource(1.5), req._electronics_resource(1.5)),
                        0.0,
                        SiteRequirements(),
                        frozenset(),
                        True,
                    ),
            power=PowerSpec(SolarGeneration(0.24 / 0.62, 1361.0), 0.10),
        ),
        # CREWED_ORBITAL_LABORATORY
        FacilityAsset(
            definition=replace(FacilityDef(ids.CREWED_ORBITAL_LABORATORY, "有人軌道研究所", req._capabilities("research_lab", "crewed_orbital_research_equipment"), orbit, req.SiteRequirements(environment=req.LOW_RADIATION_ENV, spatial_classification_requirements=req.ORBIT_CLASSIFICATION)), housing_capacity=8, life_support=LifeSupportSpec(8, ((ids.FOOD, 0.001), (ids.WATER, 0.002), (ids.OXYGEN, 0.003)))),
            construction=ConstructionRecipe(
                        ids.CREWED_ORBITAL_LABORATORY,
                        (req._structure_resource(8.0), req._machinery_resource(7.0), req._electronics_resource(5.0)),
                        0.0,
                        SiteRequirements(),
                        frozenset({ids.LS_ATMOSPHERE_WATER_WASTE_01}),
                        True,
                    ),
            power=PowerSpec(SolarGeneration(1.20 / 0.62, 1361.0), 0.65),
        ),
        # ROBOTIC_GEOLOGY_STATION
        FacilityAsset(
            definition=FacilityDef(ids.ROBOTIC_GEOLOGY_STATION, "ロボット地質調査ステーション", req._capabilities("research_lab", "robotic_geology_equipment", "surface_survey", "robotic_operations"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
            construction=req._surface_recipe(
                        ids.ROBOTIC_GEOLOGY_STATION,
                        3.0,
                        3.0,
                        2.0,
                        0.0,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_01}),
                        capabilities=frozenset(),
                        self_deploying=True,
                    ),
            power=PowerSpec(SolarGeneration(0.28 / 0.78, 1361.0), 0.10),
        ),
        # SAMPLE_ANALYSIS_LABORATORY
        FacilityAsset(
            definition=FacilityDef(ids.SAMPLE_ANALYSIS_LABORATORY, "試料分析研究所", req._capabilities("research_lab", "sample_analysis_equipment"), surface, surface),
            construction=req._surface_recipe(
                        ids.SAMPLE_ANALYSIS_LABORATORY,
                        6.0,
                        7.0,
                        5.0,
                        35.0,
                        technologies=frozenset({ids.SS_SENSING_05}),
                        capabilities=frozenset({"surface_survey"}),
                    ),
            power=PowerSpec(None, 0.40),
        ),
        # VACUUM_REGOLITH_PROCESS_LABORATORY
        FacilityAsset(
            definition=FacilityDef(ids.VACUUM_REGOLITH_PROCESS_LABORATORY, "真空レゴリスプロセス研究所", req._capabilities("research_lab", "vacuum_regolith_research_equipment"), surface, req.VACUUM_SURFACE_SITE),
            construction=req._surface_recipe(
                        ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
                        10.0,
                        12.0,
                        7.0,
                        70.0,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_03}),
                        capabilities=frozenset({"granular_mineral_extraction"}),
                    ),
            power=PowerSpec(None, 0.85),
        ),
        # GRID_POWER_SUPPLY
        FacilityAsset(
            definition=FacilityDef(
                        ids.GRID_POWER_SUPPLY, "外部電力網接続", req._capabilities("grid_power"),
                        req.EXTERNAL_GRID_SITE, req.EXTERNAL_GRID_SITE,
                        placement_scope=FacilityPlacementScope.SURFACE_CELL,
                    ),
            construction=req._surface_recipe(
                        ids.GRID_POWER_SUPPLY, 8, 6, 0, 36,
                    ),
            power=PowerSpec(FixedGeneration(20.0), 0.0),
        ),
        # ORBITAL_FISSION_POWER
        FacilityAsset(
            definition=FacilityDef(ids.ORBITAL_FISSION_POWER, "軌道核分裂電源", req._capabilities("orbital_power_supply", "fission_reactor_control_instrumentation"), orbit, orbit),
            construction=ConstructionRecipe(
                        ids.ORBITAL_FISSION_POWER,
                        (req._structure_resource(3.0), req._machinery_resource(2.0),
                         req._electronics_resource(0.8)),
                        0.0,
                        req.ORBIT_SITE,
                        frozenset({ids.FP_REACTOR_POWER_02}),
                        True,
                    ),
            power=PowerSpec(FixedGeneration(0.6), 0.03),
        ),
        # ORBITAL_LOGISTICS_NODE
        FacilityAsset(
            definition=FacilityDef(ids.ORBITAL_LOGISTICS_NODE, "軌道物流・整備ノード", req._capabilities("cargo_transfer", "vehicle_refueling", "spacecraft_servicing"), orbit, orbit, service_capacity_supplies=req._services(cargo_transfer=1.0, spacecraft_servicing=1.0)),
            construction=ConstructionRecipe(
                        ids.ORBITAL_LOGISTICS_NODE,
                        (req._structure_resource(3.0), req._machinery_resource(2.0), req._electronics_resource(1.0)),
                        0.0,
                        SiteRequirements(),
                        frozenset({ids.LM_LOGISTICS_MAINTENANCE_01, ids.CR_CRYOGENIC_STORAGE_TRANSFER_03}),
                        True,
                    ),
            power=PowerSpec(SolarGeneration(0.35 / 0.62, 1361.0), 0.12, standby_load_mw=0.04),
            storage=StorageProviderSpec(
                        ids.ORBITAL_LOGISTICS_NODE, {"cryogenic": 4.0}, frozenset({"cryogenic"}),
                    ),
        ),
        # SURFACE_LAUNCH_SUPPORT
        FacilityAsset(
            definition=FacilityDef(ids.SURFACE_LAUNCH_SUPPORT, "打上げ・回収整備設備", req._capabilities("cargo_transfer", "vehicle_refueling", "launch_vehicle_servicing", "launch_operations", "surface_access_anchor"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL, service_capacity_supplies=req._services(cargo_transfer=1.0, launch_vehicle_servicing=1.0, surface_distribution=10.0)),
            construction=req._surface_recipe(
                        ids.SURFACE_LAUNCH_SUPPORT, 10, 8, 2, 54,
                    ),
            power=PowerSpec(None, 0.08),
        ),
        # CARGO_LAUNCH_INTEGRATION_PAD
        FacilityAsset(
            definition=FacilityDef(
                        ids.CARGO_LAUNCH_INTEGRATION_PAD, "貨物ロケット地上統合・再使用整備射場",
                        req._capabilities("cargo_transfer", "vehicle_refueling", "launch_vehicle_servicing",
                                          "launch_operations", "surface_access_anchor"),
                        surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL,
                        service_capacity_supplies=req._services(cargo_transfer=2.5,
                                                                 launch_vehicle_servicing=2.2),
                    ),
            construction=req._surface_recipe(
                        ids.CARGO_LAUNCH_INTEGRATION_PAD, 26.0, 20.0, 7.0, 190.0,
                        technologies=frozenset({ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09"),
                                                 ids.research_id("LM-LOGISTICS-MAINTENANCE-07")}),
                    ),
            power=PowerSpec(None, 0.55, standby_load_mw=0.06),
        ),
        # VEHICLE_ASSEMBLY_FACILITY
        FacilityAsset(
            definition=FacilityDef(ids.VEHICLE_ASSEMBLY_FACILITY, "宇宙輸送機製造・組立設備", req._capabilities("vehicle_assembly"), surface, surface, service_capacity_supplies=req._services(vehicle_assembly=1.0)),
            construction=req._surface_recipe(
                        ids.VEHICLE_ASSEMBLY_FACILITY, 10, 10, 3, 60,
                    ),
            power=PowerSpec(None, 0.18),
        ),
        # Automated dimensional inspection and flexible fixtures allow the same
        # assembly Service to support materially larger mixed Vehicle batches.
        # It is a purchased, power-hungry surface asset, not an RP multiplier.
        FacilityAsset(
            definition=FacilityDef(
                ids.AUTOMATED_VEHICLE_ASSEMBLY, "自動計測・モジュール宇宙機組立工場",
                req._capabilities("vehicle_assembly"), surface, surface,
                service_capacity_supplies=req._services(vehicle_assembly=3.0),
                maintenance_fraction_per_year=0.08,
            ),
            construction=ConstructionRecipe(
                ids.AUTOMATED_VEHICLE_ASSEMBLY,
                (req._structure_resource(35.0), req._machinery_resource(27.0),
                 BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 5.0)),
                175.0, req.SURFACE_SITE,
                frozenset({ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09"),
                           ids.research_id("LM-LOGISTICS-MAINTENANCE-09")}),
            ),
            power=PowerSpec(None, 1.65, standby_load_mw=0.16),
        ),
        # AUTONOMOUS_SURFACE_OUTPOST
        FacilityAsset(
            definition=FacilityDef(
                        ids.AUTONOMOUS_SURFACE_OUTPOST, "自律地表初期拠点",
                        req._capabilities("surface_survey", "compact_surface_prospecting_kit",
                                          "robotic_operations", "base_construction", "surface_access_anchor",
                                          "cargo_transfer", "spacecraft_servicing", "vehicle_refueling",
                                          "surface_distribution"),
                        surface, req.ROBOTIC_OUTPOST_SURFACE_SITE,
                        placement_scope=FacilityPlacementScope.SURFACE_CELL,
                        service_capacity_supplies=req._services(cargo_transfer=0.18,
                                                                 spacecraft_servicing=0.12,
                                                                 surface_distribution=0.12),
                        maintenance_fraction_per_year=0.085,
                    ),
            construction=ConstructionRecipe(
                        ids.AUTONOMOUS_SURFACE_OUTPOST,
                        (req._structure_resource(2.7), req._machinery_resource(1.5),
                         BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 0.5)),
                        18.0, req.ROBOTIC_OUTPOST_SURFACE_SITE,
                    ),
            power=PowerSpec(FixedGeneration(0.12), 0.035, standby_load_mw=0.025),
            storage=StorageProviderSpec(
                        ids.AUTONOMOUS_SURFACE_OUTPOST, {"cryogenic": 0.8}, frozenset({"cryogenic"}),
                    ),
            construction_provider=ConstructionProviderSpec(ids.AUTONOMOUS_SURFACE_OUTPOST, 0.12),
        ),
        # AUTONOMOUS_ORBITAL_OUTPOST
        FacilityAsset(
            definition=FacilityDef(
                        ids.AUTONOMOUS_ORBITAL_OUTPOST, "自律軌道初期拠点",
                        req._capabilities("cargo_transfer", "spacecraft_servicing", "vehicle_refueling"),
                        orbit, orbit,
                        service_capacity_supplies=req._services(cargo_transfer=0.22,
                                                                 spacecraft_servicing=0.13),
                        maintenance_fraction_per_year=0.085,
                    ),
            construction=ConstructionRecipe(
                        ids.AUTONOMOUS_ORBITAL_OUTPOST,
                        (req._structure_resource(3.4), req._machinery_resource(1.9)),
                        19.0, req.ORBIT_SITE,
                    ),
            power=PowerSpec(FixedGeneration(0.14), 0.045, standby_load_mw=0.03),
            storage=StorageProviderSpec(
                        ids.AUTONOMOUS_ORBITAL_OUTPOST, {"cryogenic": 1.0}, frozenset({"cryogenic"}),
                    ),
            construction_provider=ConstructionProviderSpec(ids.AUTONOMOUS_ORBITAL_OUTPOST, 0.11),
        ),
        # ROBOTIC_SURVEY_PACKAGE
        FacilityAsset(
            definition=FacilityDef(ids.ROBOTIC_SURVEY_PACKAGE, "ロボット探査・初期建設パッケージ", req._capabilities("surface_survey", "robotic_prospecting_kit", "base_construction", "robotic_operations", "spacecraft_servicing", "cargo_transfer", "surface_access_anchor"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL, service_capacity_supplies=req._services(cargo_transfer=1.0, spacecraft_servicing=1.0)),
            construction=req._surface_recipe(
                        ids.ROBOTIC_SURVEY_PACKAGE, 2.0, 3.0, 1.5, 0.0,
                        technologies=frozenset({ids.SS_SENSING_04}), capabilities=frozenset(), self_deploying=True,
                    ),
            power=PowerSpec(SolarGeneration(0.55 / 0.78, 1361.0), 0.08, standby_load_mw=0.025),
            storage=StorageProviderSpec(
                        ids.ROBOTIC_SURVEY_PACKAGE, {"cryogenic": 2.0}, frozenset({"cryogenic"}),
                    ),
            construction_provider=ConstructionProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, 0.35),
        ),
        # SURFACE_POWER_GRID
        FacilityAsset(
            definition=FacilityDef(ids.SURFACE_POWER_GRID, "地表太陽光発電・配電設備", req._capabilities("power_grid"), surface, surface, placement_scope=FacilityPlacementScope.SURFACE_CELL),
            construction=req._surface_recipe(
                        ids.SURFACE_POWER_GRID, 12, 5, 2, 45,
                        technologies=frozenset({ids.PG_SOLAR_POWER_02}),
                    ),
            power=PowerSpec(SolarGeneration(1.0 / 0.78, 1361.0), 0.05),
        ),
        # INDUSTRIAL_POWER_BLOCK
        FacilityAsset(
            definition=FacilityDef(ids.INDUSTRIAL_POWER_BLOCK, "核分裂電源ユニット", req._capabilities("industrial_power", "fission_reactor_control_instrumentation"), surface, surface),
            construction=req._surface_recipe(
                        ids.INDUSTRIAL_POWER_BLOCK, 14, 9, 3, 60,
                        technologies=frozenset({ids.FP_REACTOR_POWER_02}),
                    ),
            power=PowerSpec(FixedGeneration(2.0), 0.05),
        ),
        # CONSTRUCTION_YARD
        FacilityAsset(
            definition=FacilityDef(ids.CONSTRUCTION_YARD, "建設ヤード", req._capabilities("construction_yard"), surface, surface),
            construction=req._surface_recipe(ids.CONSTRUCTION_YARD, 10, 6, 2, 50),
            power=PowerSpec(None, 0.15),
            construction_provider=ConstructionProviderSpec(ids.CONSTRUCTION_YARD, 0.8),
        ),
        # Coordinated mobile work cells supply construction work beyond
        # independent manual yards; the controls require genuine research,
        # construction equipment and continuing power/maintenance.
        FacilityAsset(
            definition=FacilityDef(
                ids.AUTOMATED_CONSTRUCTION_YARD, "協調ロボット施工・プレハブ建設センター",
                req._capabilities("construction_yard"), surface, surface,
                maintenance_fraction_per_year=0.08,
            ),
            construction=ConstructionRecipe(
                ids.AUTOMATED_CONSTRUCTION_YARD,
                (req._structure_resource(28.0), req._machinery_resource(24.0),
                 BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 6.0)),
                145.0, req.SURFACE_SITE,
                frozenset({ids.research_id("MC-MANUFACTURING-CONSTRUCTION-12")}),
            ),
            power=PowerSpec(None, 1.40, standby_load_mw=0.12),
            construction_provider=ConstructionProviderSpec(ids.AUTOMATED_CONSTRUCTION_YARD, 3.2),
        ),
        # VOLATILE_EXTRACTOR
        FacilityAsset(
            definition=FacilityDef(
                        ids.VOLATILE_EXTRACTOR, "揮発性原料採取設備",
                        req._capabilities("volatile_extraction"),
                        req.COLD_VOLATILE_SURFACE_SITE, req.COLD_VOLATILE_SURFACE_SITE,
                        placement_scope=FacilityPlacementScope.SURFACE_CELL,
                        extraction_capacity_t_per_day=6.0,
                    ),
            construction=req._surface_recipe(
                        ids.VOLATILE_EXTRACTOR, 4, 4, 1, 25,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_05}),
                    ),
            power=PowerSpec(None, 0.20),
        ),
        # VOLATILE_PROCESSING
        FacilityAsset(
            definition=FacilityDef(ids.VOLATILE_PROCESSING, "揮発性成分回収設備", req._capabilities("volatile_processing"), surface, surface),
            construction=req._surface_recipe(
                        ids.VOLATILE_PROCESSING, 5, 5, 1, 32,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_06}),
                    ),
            power=PowerSpec(None, 0.28),
        ),
        # VACUUM_MINERAL_HARVESTER
        FacilityAsset(
            definition=FacilityDef(ids.VACUUM_MINERAL_HARVESTER, "真空粒状鉱物採掘設備", req._capabilities("granular_mineral_extraction"), surface, req.VACUUM_SURFACE_SITE, extraction_capacity_t_per_day=8.0),
            construction=req._surface_recipe(
                        ids.VACUUM_MINERAL_HARVESTER, 4, 5, 1, 28,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_02}),
                    ),
            power=PowerSpec(None, 0.25),
        ),
        # CRYOGENIC_STORAGE
        FacilityAsset(
            definition=FacilityDef(ids.CRYOGENIC_STORAGE, "極低温貯蔵設備", req._capabilities("cryogenic_storage", "vehicle_refueling"), surface, surface),
            construction=req._surface_recipe(
                        ids.CRYOGENIC_STORAGE, 3, 2, 0.8, 22,
                        technologies=frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_02}),
                    ),
            power=PowerSpec(None, 0.06, standby_load_mw=0.06),
            storage=StorageProviderSpec(ids.CRYOGENIC_STORAGE, {"cryogenic": 30.0}, frozenset({"cryogenic"})),
        ),
        # VACUUM_CARGO_HANDLING_TERMINAL
        FacilityAsset(
            definition=FacilityDef(
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
            construction=ConstructionRecipe(
                        ids.VACUUM_CARGO_HANDLING_TERMINAL,
                        (req._structure_resource(18.0), req._machinery_resource(14.0),
                         req._electronics_resource(5.0)),
                        110.0, req.VACUUM_SURFACE_SITE,
                        frozenset({ids.research_id("LM-LOGISTICS-MAINTENANCE-14")}),
                    ),
            power=PowerSpec(None, 0.75, standby_load_mw=0.15),
        ),
        # SURFACE_DISTRIBUTION_HUB
        FacilityAsset(
            definition=FacilityDef(
                        ids.SURFACE_DISTRIBUTION_HUB,
                        "地表物流・配給ハブ",
                        req._capabilities("surface_distribution", "surface_access_anchor"),
                        surface,
                        surface,
                        placement_scope=FacilityPlacementScope.SURFACE_CELL,
                        service_capacity_supplies=req._services(surface_distribution=12.0),
                    ),
            construction=req._surface_recipe(
                        ids.SURFACE_DISTRIBUTION_HUB, 5, 4, 1, 28
                    ),
            power=PowerSpec(None, 0.08),
        ),
        # ELECTROLYSIS_PLANT
        FacilityAsset(
            definition=FacilityDef(ids.ELECTROLYSIS_PLANT, "工業電解設備", req._capabilities("industrial_electrolysis"), surface, surface),
            construction=ConstructionRecipe(
                        ids.ELECTROLYSIS_PLANT,
                        (BuildResourceRequirement(ids.STRUCTURAL_COMPONENTS, 3.5),
                         BuildResourceRequirement(ids.MACHINERY, 2.5),
                         BuildResourceRequirement(ids.PRECISION_ELECTRONICS, 0.8)),
                        28,
                        req.SURFACE_SITE,
                        frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_02}),
                    ),
            power=PowerSpec(None, 0.22),
        ),
        # PROPELLANT_PLANT
        FacilityAsset(
            definition=FacilityDef(ids.PROPELLANT_PLANT, "推進剤調製設備", req._capabilities("propellant_production"), surface, surface),
            construction=ConstructionRecipe(
                        ids.PROPELLANT_PLANT,
                        (BuildResourceRequirement(ids.STRUCTURAL_COMPONENTS, 4.0),
                         BuildResourceRequirement(ids.MACHINERY, 3.0),
                         BuildResourceRequirement(ids.PRECISION_ELECTRONICS, 1.0)),
                        30,
                        req.SURFACE_SITE,
                        frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_02}),
                    ),
            power=PowerSpec(None, 0.16),
        ),
        # CRYOGENIC_PROPELLANT_TERMINAL
        FacilityAsset(
            definition=FacilityDef(
                        ids.CRYOGENIC_PROPELLANT_TERMINAL, "極低温推進剤液化・充填ターミナル",
                        req._capabilities("propellant_production", "cryogenic_storage", "vehicle_refueling"),
                        surface, surface, process_throughput_per_day=4.5,
                    ),
            construction=ConstructionRecipe(
                        ids.CRYOGENIC_PROPELLANT_TERMINAL,
                        (req._structure_resource(12.0), req._machinery_resource(11.0),
                         req._electronics_resource(4.0)),
                        125.0, req.SURFACE_SITE,
                        frozenset({ids.CR_CRYOGENIC_STORAGE_TRANSFER_04,
                                   ids.research_id("CR-CRYOGENIC-STORAGE-TRANSFER-07")}),
                    ),
            power=PowerSpec(None, 1.20, standby_load_mw=0.35),
            storage=StorageProviderSpec(
                        ids.CRYOGENIC_PROPELLANT_TERMINAL, {"cryogenic": 150.0}, frozenset({"cryogenic"}),
                    ),
        ),
        # MINERAL_SINTERING
        FacilityAsset(
            definition=FacilityDef(ids.MINERAL_SINTERING, "鉱物焼結設備", req._capabilities("mineral_sintering"), surface, surface),
            construction=req._surface_recipe(
                        ids.MINERAL_SINTERING, 8, 6, 2, 55,
                        technologies=frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_10}),
                    ),
            power=PowerSpec(None, 0.30),
        ),
        # ORE_PROCESSING
        FacilityAsset(
            definition=FacilityDef(ids.ORE_PROCESSING, "鉱石処理設備", req._capabilities("ore_processing"), surface, surface),
            construction=req._surface_recipe(
                        ids.ORE_PROCESSING, 10, 7, 2, 60,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_04}),
                    ),
            power=PowerSpec(None, 0.35),
        ),
        # METALLURGY
        FacilityAsset(
            definition=FacilityDef(ids.METALLURGY, "金属精錬設備", req._capabilities("metallurgy"), surface, surface),
            construction=req._surface_recipe(
                        ids.METALLURGY, 12, 8, 3, 70,
                        technologies=frozenset({ids.RP_RESOURCE_CHAIN_13}),
                    ),
            power=PowerSpec(None, 0.60),
        ),
        # FABRICATION_WORKSHOP
        FacilityAsset(
            definition=FacilityDef(ids.FABRICATION_WORKSHOP, "構造材加工工場", req._capabilities("structural_fabrication"), surface, surface),
            construction=req._surface_recipe(
                        ids.FABRICATION_WORKSHOP, 8, 8, 4, 65,
                    ),
            power=PowerSpec(None, 0.35),
        ),
        # MACHINE_SHOP
        FacilityAsset(
            definition=FacilityDef(ids.MACHINE_SHOP, "機械工場", req._capabilities("basic_machine_shop", "precision_machining"), surface, surface),
            construction=req._surface_recipe(
                        ids.MACHINE_SHOP, 10, 10, 5, 80,
                    ),
            power=PowerSpec(None, 0.45),
        ),
        # HEAVY_EQUIPMENT_ASSEMBLY
        FacilityAsset(
            definition=FacilityDef(ids.HEAVY_EQUIPMENT_ASSEMBLY, "重機組立設備", req._capabilities("heavy_equipment_assembly"), surface, surface),
            construction=ConstructionRecipe(
                        ids.HEAVY_EQUIPMENT_ASSEMBLY,
                        (
                            BuildResourceRequirement(ids.FABRICATED_STRUCTURE, 8.0),
                            BuildResourceRequirement(ids.BASIC_MACHINE_PARTS, 6.0),
                            BuildResourceRequirement(ids.PRECISION_COMPONENTS, 1.0),
                        ),
                        100,
                        req.SURFACE_SITE,
                        frozenset({ids.MC_MANUFACTURING_CONSTRUCTION_09}),
                    ),
            power=PowerSpec(None, 0.55),
        ),
        # MINERAL_QUARRY
        FacilityAsset(
            definition=FacilityDef(ids.MINERAL_QUARRY, "露天鉱物採掘場", req._capabilities("mineral_extraction"), surface, surface, 0.10, extraction_capacity_t_per_day=2.4),
            construction=req._surface_recipe(
                        ids.MINERAL_QUARRY, 5, 7, 0, 32,
                    ),
            power=PowerSpec(None, 0.25),
        ),
        # METAL_ORE_MINE
        FacilityAsset(
            definition=FacilityDef(ids.METAL_ORE_MINE, "露天金属鉱山", req._capabilities("metal_ore_extraction"), surface, surface, 0.10, extraction_capacity_t_per_day=1.7),
            construction=req._surface_recipe(
                        ids.METAL_ORE_MINE, 6, 8, 0, 38,
                    ),
            power=PowerSpec(None, 0.30),
        ),
        # AUTONOMOUS_ORE_MINE
        FacilityAsset(
            definition=FacilityDef(
                        ids.AUTONOMOUS_ORE_MINE, "自律掘削・鉱石搬送鉱山",
                        req._capabilities("metal_ore_extraction"), surface, surface,
                        extraction_capacity_t_per_day=8.0,
                    ),
            construction=ConstructionRecipe(
                        ids.AUTONOMOUS_ORE_MINE,
                        (req._structure_resource(22.0), req._machinery_resource(26.0),
                         BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 3.0)),
                        150.0, req.SURFACE_SITE,
                        frozenset({ids.research_id("RP-RESOURCE-CHAIN-09")}),
                    ),
            power=PowerSpec(None, 1.25),
        ),
        # CONTINUOUS_ORE_CONCENTRATOR
        FacilityAsset(
            definition=FacilityDef(
                        ids.CONTINUOUS_ORE_CONCENTRATOR, "多段破砕・品位選別プラント",
                        req._capabilities("ore_processing"), surface, surface,
                        process_throughput_per_day=3.5,
                    ),
            construction=ConstructionRecipe(
                        ids.CONTINUOUS_ORE_CONCENTRATOR,
                        (req._structure_resource(26.0), req._machinery_resource(24.0),
                         BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 4.5)),
                        170.0, req.SURFACE_SITE,
                        frozenset({ids.research_id("RP-RESOURCE-CHAIN-10")}),
                    ),
            power=PowerSpec(None, 1.10),
        ),
        # CONTINUOUS_REDUCTION_FURNACE
        FacilityAsset(
            definition=FacilityDef(
                        ids.CONTINUOUS_REDUCTION_FURNACE, "原料組成制御型還元精錬炉",
                        req._capabilities("metallurgy"), surface, surface,
                        process_throughput_per_day=3.0,
                    ),
            construction=req._surface_recipe(
                        ids.CONTINUOUS_REDUCTION_FURNACE, 34, 30, 11, 220,
                        technologies=frozenset({ids.research_id("RP-RESOURCE-CHAIN-15")}),
                    ),
            power=PowerSpec(None, 2.10),
        ),
        # AUTOMATED_STRUCTURAL_FABRICATION_LINE
        FacilityAsset(
            definition=FacilityDef(
                        ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE, "自動寸法補正構造材加工工場",
                        req._capabilities("structural_fabrication"), surface, surface,
                        process_throughput_per_day=4.0,
                    ),
            construction=ConstructionRecipe(
                        ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE,
                        (req._structure_resource(30.0), req._machinery_resource(22.0),
                         BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 5.0)),
                        180.0, req.SURFACE_SITE,
                        frozenset({ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09")}),
                    ),
            power=PowerSpec(None, 1.45),
        ),
        # INDUSTRIAL_MACHINERY_ASSEMBLY
        FacilityAsset(
            definition=FacilityDef(
                        ids.INDUSTRIAL_MACHINERY_ASSEMBLY, "産業機械モジュール組立工場",
                        req._capabilities("industrial_machinery_assembly"), surface, surface,
                        process_throughput_per_day=2.2,
                    ),
            construction=req._surface_recipe(
                        ids.INDUSTRIAL_MACHINERY_ASSEMBLY, 17, 16, 5, 105,
                        technologies=frozenset({ids.research_id("AR-AUTONOMY-ROBOTICS-07")}),
                    ),
            power=PowerSpec(None, 0.80),
        ),
        # MICROELECTRONICS_FAB
        FacilityAsset(
            definition=FacilityDef(
                        ids.MICROELECTRONICS_FAB, "薄膜回路・電子モジュール製造工場",
                        req._capabilities("microelectronics_fabrication"), surface, surface,
                        process_throughput_per_day=1.6,
                    ),
            construction=ConstructionRecipe(
                        ids.MICROELECTRONICS_FAB,
                        (req._structure_resource(12.0),
                         req._machinery_resource(15.0),
                         BuildResourceRequirement(ids.CERAMICS_GLASS, 4.0)),
                        125.0, req.SURFACE_SITE,
                        frozenset({ids.research_id("EM-ELECTRONICS-MANUFACTURING-01")}),
                    ),
            power=PowerSpec(None, 1.70),
        ),
        # AUTOMATED_PRECISION_MACHINING
        FacilityAsset(
            definition=FacilityDef(
                ids.AUTOMATED_PRECISION_MACHINING, "計測制御型精密工作センター",
                req._capabilities("basic_machine_shop", "precision_machining"),
                surface, surface, process_throughput_per_day=3.2,
                maintenance_fraction_per_year=0.08,
            ),
            construction=ConstructionRecipe(
                ids.AUTOMATED_PRECISION_MACHINING,
                (req._structure_resource(19.0), req._machinery_resource(21.0),
                 BuildResourceRequirement(ids.CONSTRUCTION_EQUIPMENT, 3.0)),
                130.0, req.SURFACE_SITE,
                frozenset({ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09"),
                           ids.research_id("AR-AUTONOMY-ROBOTICS-07")}),
            ),
            power=PowerSpec(None, 2.30, standby_load_mw=0.16),
        ),
        # IN_LINE_ELECTRONICS_FAB
        FacilityAsset(
            definition=FacilityDef(
                ids.IN_LINE_ELECTRONICS_FAB, "インライン欠陥検査型半導体製造工場",
                req._capabilities("inline_microelectronics_inspection"),
                surface, surface, process_throughput_per_day=3.6,
                maintenance_fraction_per_year=0.085,
            ),
            construction=ConstructionRecipe(
                ids.IN_LINE_ELECTRONICS_FAB,
                (req._structure_resource(22.0), req._machinery_resource(24.0),
                 BuildResourceRequirement(ids.PRECISION_COMPONENTS, 3.5)),
                185.0, req.SURFACE_SITE,
                frozenset({ids.research_id("EM-ELECTRONICS-MANUFACTURING-02")}),
            ),
            power=PowerSpec(None, 3.60, standby_load_mw=0.24),
        ),
        # MOLTEN_OXIDE_ELECTROLYZER
        FacilityAsset(
            definition=FacilityDef(
                        ids.MOLTEN_OXIDE_ELECTROLYZER, "溶融酸化物電解製錬設備",
                        req._capabilities("molten_oxide_electrolysis"),
                        surface, surface,
                        process_throughput_per_day=2.0,
                    ),
            construction=ConstructionRecipe(
                        ids.MOLTEN_OXIDE_ELECTROLYZER,
                        (BuildResourceRequirement(ids.FABRICATED_STRUCTURE, 8.0),
                         req._machinery_resource(7.0), req._electronics_resource(2.5)),
                        95.0, req.SURFACE_SITE,
                        frozenset({ids.RP_RESOURCE_CHAIN_16}),
                    ),
            power=PowerSpec(None, 2.40),
        ),
        # INDUSTRIAL_WATER_INTAKE
        FacilityAsset(
            definition=FacilityDef(ids.INDUSTRIAL_WATER_INTAKE, "工業用水取水・処理設備", req._capabilities("industrial_water_supply"), surface, surface, 0.08, extraction_capacity_t_per_day=1.0),
            construction=req._surface_recipe(
                        ids.INDUSTRIAL_WATER_INTAKE, 5, 5, 0, 30,
                    ),
            power=PowerSpec(None, 0.18),
        ),
        # BASIC_STRUCTURAL_MATERIAL_PLANT
        FacilityAsset(
            definition=FacilityDef(ids.BASIC_STRUCTURAL_MATERIAL_PLANT, "基礎構造材工場", req._capabilities("basic_structural_material"), surface, surface, 0.09),
            construction=req._surface_recipe(
                        ids.BASIC_STRUCTURAL_MATERIAL_PLANT, 8, 8, 1, 45,
                    ),
            power=PowerSpec(None, 0.40),
        ),
        # BASIC_MACHINERY_WORKS
        FacilityAsset(
            definition=FacilityDef(ids.BASIC_MACHINERY_WORKS, "基礎機械製作所", req._capabilities("basic_machinery_production"), surface, surface, 0.09),
            construction=req._surface_recipe(
                        ids.BASIC_MACHINERY_WORKS, 8, 10, 1, 52,
                    ),
            power=PowerSpec(None, 0.48),
        ),
        # BIOREGENERATIVE_GROWTH_MODULE
        FacilityAsset(
            definition=FacilityDef(
                    ids.BIOREGENERATIVE_GROWTH_MODULE, "再生養液・閉鎖環境栽培モジュール",
                    req._capabilities("food_hydroponics", "recirculating_hydroponics"),
                    process_throughput_per_day=1.8, maintenance_fraction_per_year=0.075,
                ),
            construction=ConstructionRecipe(
                        ids.BIOREGENERATIVE_GROWTH_MODULE,
                        (req._structure_resource(10.0), req._machinery_resource(9.0),
                         req._electronics_resource(7.0)),
                        56.0, req.SiteRequirements(),
                        frozenset({ids.research_id("PL-PLANT-FOOD-07"),
                                   ids.research_id("LS-ATMOSPHERE-WATER-WASTE-14")}),
                    ),
            power=PowerSpec(None, 1.05, standby_load_mw=0.20),
        ),
        # VOLATILE_FRACTIONATION_PLANT
        FacilityAsset(
            definition=FacilityDef(
                    ids.VOLATILE_FRACTIONATION_PLANT, "多段揮発成分分留・凝縮装置",
                    req._capabilities("volatile_processing", "multistage_volatile_fractionation"),
                    process_throughput_per_day=2.2, maintenance_fraction_per_year=0.075,
                ),
            construction=ConstructionRecipe(
                        ids.VOLATILE_FRACTIONATION_PLANT,
                        (req._structure_resource(12.0), req._machinery_resource(13.0),
                         req._electronics_resource(4.0)),
                        68.0, req.SiteRequirements(),
                        frozenset({ids.research_id("RP-RESOURCE-CHAIN-11")}),
                    ),
            power=PowerSpec(None, 1.40, standby_load_mw=0.18),
        ),
        # CLOSED_CYCLE_HABITAT
        FacilityAsset(
            definition=FacilityDef(
                    ids.CLOSED_CYCLE_HABITAT, "閉鎖水循環・大気再生居住区",
                    req._capabilities("pressurized_habitation", "closed_cycle_life_support"),
                    housing_capacity=48, maintenance_fraction_per_year=0.085,
                    life_support=LifeSupportSpec(48, ((ids.FOOD, 0.001),
                                                    (ids.WATER, 0.00040),
                                                    (ids.OXYGEN, 0.0014))),
                ),
            construction=ConstructionRecipe(
                        ids.CLOSED_CYCLE_HABITAT,
                        (req._structure_resource(17.0),
                         BuildResourceRequirement(ids.RADIATION_SHIELDING_PANELS, 4.0),
                         BuildResourceRequirement(ids.THERMAL_CONTROL_ASSEMBLIES, 1.0)),
                        82.0, req.SiteRequirements(),
                        frozenset({ids.research_id("LS-ATMOSPHERE-WATER-WASTE-13"),
                                   ids.research_id("HB-HABITATION-PROTECTION-06")}),
                    ),
            power=PowerSpec(None, 1.15, standby_load_mw=0.42),
        ),
        # FOOD_FARM
        FacilityAsset(
            definition=FacilityDef(
                    ids.FOOD_FARM, '閉鎖式食料栽培設備', req._capabilities('food_hydroponics'), installation_requirements=surface, operating_requirements=surface,
                ),
            construction=req._surface_recipe(ids.FOOD_FARM, 6, 4, 2, 28),
            power=PowerSpec(None, 0.14),
        ),
        # HABITAT
        FacilityAsset(
            definition=FacilityDef(
                    ids.HABITAT, '与圧居住モジュール', housing_capacity=24,
                    installation_requirements=surface, operating_requirements=surface,
                    life_support=LifeSupportSpec(24, ((ids.FOOD, 0.001), (ids.WATER, 0.002), (ids.OXYGEN, 0.003))),
                ),
            construction=ConstructionRecipe(
                        ids.HABITAT,
                        (req._structure_resource(5), req._machinery_resource(4)),
                        28.0, SiteRequirements(), frozenset(), True,
                    ),
            power=PowerSpec(None, 0.08),
        ),
        # BREATHABLE_SURFACE_LIFE_SUPPORT
        FacilityAsset(
            definition=FacilityDef(
                    ids.BREATHABLE_SURFACE_LIFE_SUPPORT, '地上居住・生活供給設備', housing_capacity=160,
                    installation_requirements=req.BREATHABLE_SURFACE_SITE,
                    operating_requirements=req.BREATHABLE_SURFACE_SITE,
                    life_support=LifeSupportSpec(160, ((ids.FOOD, 0.001), (ids.WATER, 0.002))),
                ),
            construction=req._surface_recipe(ids.BREATHABLE_SURFACE_LIFE_SUPPORT, 6, 4, 1, 30),
            power=PowerSpec(None, 0.04),
        ),
    )
    vehicles = (
        # CREW_TRANSFER_SPACECRAFT
        VehicleDef(
                    id=ids.CREW_TRANSFER_SPACECRAFT,
                    display_name="軌道間有人輸送船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=9.0, payload_t=3.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=5.0,
                        propellant_t_per_total_t_per_km_s=0.018,
                        operation_capabilities=(SpaceflightCapability(7.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=120.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=9.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 6.0), (ids.MACHINERY, 3.5), (ids.PRECISION_ELECTRONICS, 3.0)),
                        prerequisite_technologies=frozenset({ids.LS_ATMOSPHERE_WATER_WASTE_01, ids.research_id("GN-NAVIGATION-04")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=4.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.0), (ids.MACHINERY, 1.75), (ids.PRECISION_ELECTRONICS, 1.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=3.0),
                    passengers=PassengerAccommodation(
                        seats=12, life_support_person_days_per_day=12, onboard_power_mw=1.5,
                        power_mw_per_person=0.1,
                        net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
                    ),
                ),
        # ROBOTIC_SURFACE_PROSPECTOR
        VehicleDef(
                    id=ids.ROBOTIC_SURFACE_PROSPECTOR,
                    display_name="自律地表地質探査車",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=0.9, payload_t=0.2,
                        operation_capabilities=(SurfaceTransportCapability(45.0),),
                        endurance_days=360.0,
                        generic_capabilities=("surface_survey", "robotic_prospecting_sensor"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=3.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 0.9), (ids.MACHINERY, 0.6), (ids.PRECISION_ELECTRONICS, 1.2)),
                        prerequisite_technologies=frozenset({ids.research_id("SM-SURFACE-MOBILITY-02"), ids.SS_SENSING_04}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=1.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.45), (ids.MACHINERY, 0.3), (ids.PRECISION_ELECTRONICS, 0.6)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="surface_vehicle_servicing", turnaround_days=1.0),
                ),
        # PRESSURIZED_SURFACE_ROVER
        VehicleDef(
                    id=ids.PRESSURIZED_SURFACE_ROVER,
                    display_name="与圧有人地表探査車",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=6.0, payload_t=1.0,
                        operation_capabilities=(SurfaceTransportCapability(110.0),),
                        endurance_days=90.0,
                        generic_capabilities=("surface_mobility",),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=8.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 5.0), (ids.MACHINERY, 3.0), (ids.PRECISION_ELECTRONICS, 2.0)),
                        prerequisite_technologies=frozenset({ids.LS_ATMOSPHERE_WATER_WASTE_01, ids.research_id("SM-SURFACE-MOBILITY-04")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=3.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 2.5), (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 1.0)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="surface_vehicle_servicing", turnaround_days=2.0),
                    passengers=PassengerAccommodation(
                        seats=6, life_support_person_days_per_day=6, onboard_power_mw=0.8,
                        power_mw_per_person=0.1,
                        net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
                    ),
                ),
        # RADAR_MAPPING_ORBITER
        VehicleDef(
                    id=ids.RADAR_MAPPING_ORBITER,
                    display_name="合成開口レーダー地質探査衛星",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=3.0, payload_t=0.8,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=1.2,
                        propellant_t_per_total_t_per_km_s=0.018,
                        operation_capabilities=(SpaceflightCapability(6.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=800.0,
                        generic_capabilities=("radar_sounder", "docking_interface", "refueling_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=6.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 2.8), (ids.MACHINERY, 1.4), (ids.PRECISION_ELECTRONICS, 3.0)),
                        prerequisite_technologies=frozenset({ids.research_id("SS-SENSING-06"), ids.research_id("GN-NAVIGATION-03")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=2.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 1.4), (ids.MACHINERY, 0.7), (ids.PRECISION_ELECTRONICS, 1.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=2.0),
                ),
        # REUSABLE_LAUNCH_VEHICLE
        VehicleDef(
                    id=ids.REUSABLE_LAUNCH_VEHICLE,
                    display_name="再使用型打上げヴィークル",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=80.0, payload_t=25.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=45.0,
                        propellant_t_per_total_t_per_km_s=0.040,
                        operation_capabilities=(PoweredAscentCapability(10.0, 10.0, 110000.0, 400.0, OperationAssetDisposition.ORIGIN),),
                        operation_support_requirements=(OperationSupportRequirement(TransportOperationKind.POWERED_ASCENT, OperationSupportLocation.ORIGIN, "launch_operations"),),
                        resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                        endurance_days=14.0,
                        generic_capabilities=("refueling_interface",),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=10.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 64.0), (ids.MACHINERY, 13.0), (ids.PRECISION_ELECTRONICS, 3.5)),
                        prerequisite_technologies=frozenset({ids.research_id("CH-COMBUSTION-01"), ids.research_id("GN-NAVIGATION-01")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=5.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 32.0), (ids.MACHINERY, 6.5), (ids.PRECISION_ELECTRONICS, 1.75)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="launch_vehicle_servicing", turnaround_days=5.0),
                    passengers=PassengerAccommodation(
                        seats=6, life_support_person_days_per_day=6, onboard_power_mw=0.6,
                        power_mw_per_person=0.1,
                        net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
                    ),
                ),
        # MODULAR_CARGO_LAUNCHER
        VehicleDef(
                    id=ids.MODULAR_CARGO_LAUNCHER,
                    display_name="モジュール集成型貨物打上げ機",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=160.0, payload_t=52.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=105.0,
                        propellant_t_per_total_t_per_km_s=0.021,
                        operation_capabilities=(PoweredAscentCapability(
                            10.0, 10.0, 110000.0, 450.0, OperationAssetDisposition.ORIGIN,
                        ),),
                        operation_support_requirements=(OperationSupportRequirement(
                            TransportOperationKind.POWERED_ASCENT,
                            OperationSupportLocation.ORIGIN, "launch_operations",
                        ),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=14.0,
                        generic_capabilities=("refueling_interface",),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=24.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 124.0),
                                   (ids.MACHINERY, 26.0), (ids.PRECISION_ELECTRONICS, 10.0)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("CH-COMBUSTION-09"),
                            ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09"),
                            ids.research_id("GN-NAVIGATION-06"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=12.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 62.0),
                                                     (ids.MACHINERY, 13.0),
                                                     (ids.PRECISION_ELECTRONICS, 5.0)),
                    ),
                    maintenance=VehicleMaintenanceSpec(
                        service_type="launch_vehicle_servicing", turnaround_days=8.0,
                    ),
                ),
        # REUSABLE_ORBITAL_CARGO_TUG
        VehicleDef(
                    id=ids.REUSABLE_ORBITAL_CARGO_TUG,
                    display_name="再使用型軌道間貨物船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=8.0, payload_t=12.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=4.0,
                        propellant_t_per_total_t_per_km_s=0.020,
                        operation_capabilities=(SpaceflightCapability(5.0),),
                        resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                        endurance_days=60.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=4.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 5.0), (ids.MACHINERY, 2.0), (ids.PRECISION_ELECTRONICS, 1.0)),
                        prerequisite_technologies=frozenset({ids.research_id("CH-COMBUSTION-06"), ids.research_id("GN-NAVIGATION-04")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=2.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 2.5), (ids.MACHINERY, 1.0), (ids.PRECISION_ELECTRONICS, 0.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
                    passengers=PassengerAccommodation(
                        seats=4, life_support_person_days_per_day=4, onboard_power_mw=0.4,
                        power_mw_per_person=0.1,
                        net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
                    ),
                ),
        # HEAVY_ORBITAL_FREIGHTER
        VehicleDef(
                    id=ids.HEAVY_ORBITAL_FREIGHTER,
                    display_name="大型軌道間モジュール貨物船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=22.0, payload_t=44.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=28.0,
                        propellant_t_per_total_t_per_km_s=0.011,
                        operation_capabilities=(SpaceflightCapability(14.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=520.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=20.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 26.0),
                                   (ids.MACHINERY, 11.0), (ids.PRECISION_ELECTRONICS, 5.0)),
                        prerequisite_technologies=frozenset({
                            ids.LM_LOGISTICS_MAINTENANCE_13,
                            ids.MC_MANUFACTURING_CONSTRUCTION_05,
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=9.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 13.0),
                                                     (ids.MACHINERY, 5.5), (ids.PRECISION_ELECTRONICS, 2.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=7.0),
                ),
        # DEEP_SPACE_FREIGHTER
        VehicleDef(
                    id=ids.DEEP_SPACE_FREIGHTER,
                    display_name="長距離軌道間貨物船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=12.0, payload_t=16.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=18.0,
                        propellant_t_per_total_t_per_km_s=0.008,
                        operation_capabilities=(SpaceflightCapability(35.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=30_000.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=18.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 12.0),
                                   (ids.MACHINERY, 5.0), (ids.PRECISION_ELECTRONICS, 4.0)),
                        prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-06"), ids.research_id("CO-RF-COMMUNICATIONS-04")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=8.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 6.0),
                                                    (ids.MACHINERY, 2.5), (ids.PRECISION_ELECTRONICS, 2.0)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=8.0),
                    passengers=PassengerAccommodation(
                        seats=8, life_support_person_days_per_day=8, onboard_power_mw=0.8,
                        power_mw_per_person=0.1,
                        net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
                    ),
                ),
        # INTERPLANETARY_LANDER
        VehicleDef(
                    id=ids.INTERPLANETARY_LANDER,
                    display_name="惑星間地表輸送機",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=8.0, payload_t=8.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=13.0,
                        propellant_t_per_total_t_per_km_s=0.012,
                        operation_capabilities=(
                            SpaceflightCapability(25.0),
                            PoweredAscentCapability(9.0, 12.0, 500_000.0, 500.0),
                            LandingCapability(9.0, 12.0, 500_000.0, 500.0),
                            AtmosphericEntryCapability(500_000.0, 500.0, 40.0),
                        ),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=2_000.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=12.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 8.0),
                                   (ids.MACHINERY, 3.0), (ids.PRECISION_ELECTRONICS, 3.0)),
                        prerequisite_technologies=frozenset({ids.research_id("EDL-EDL-08")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=6.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 4.0),
                                                    (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 1.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=6.0),
                    passengers=PassengerAccommodation(
                        seats=4, life_support_person_days_per_day=4, onboard_power_mw=0.4,
                        power_mw_per_person=0.1,
                        net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003), (ids.OXYGEN, 0.001)),
                    ),
                ),
        # ORBITAL_OBSERVATION_SPACECRAFT
        VehicleDef(
                    id=ids.ORBITAL_OBSERVATION_SPACECRAFT,
                    display_name="自律軌道観測宇宙機",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=2.0, payload_t=0.3,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=0.8,
                        propellant_t_per_total_t_per_km_s=0.018,
                        operation_capabilities=(SpaceflightCapability(5.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=180.0,
                        generic_capabilities=("optical_observation_instrument", "docking_interface", "refueling_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=3.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 1.5),
                                   (ids.MACHINERY, 1.0), (ids.PRECISION_ELECTRONICS, 1.0)),
                        prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-01"), ids.SS_SENSING_01}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=1.5,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.75),
                                                    (ids.MACHINERY, 0.5), (ids.PRECISION_ELECTRONICS, 0.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
                ),
        # ORBITAL_RESOURCE_MAPPING_SPACECRAFT
        VehicleDef(
                    id=ids.ORBITAL_RESOURCE_MAPPING_SPACECRAFT,
                    display_name="軌道分光資源マッピング衛星",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=2.5, payload_t=0.5,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=1.0,
                        propellant_t_per_total_t_per_km_s=0.018,
                        operation_capabilities=(SpaceflightCapability(5.0),),
                        resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                        endurance_days=180.0,
                        generic_capabilities=("survey_sensor", "docking_interface", "refueling_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=3.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 1.2), (ids.MACHINERY, 0.8), (ids.PRECISION_ELECTRONICS, 1.5)),
                        prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-02"), DefinitionId("SS-SENSING-01")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=1.5,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 0.6), (ids.MACHINERY, 0.4), (ids.PRECISION_ELECTRONICS, 0.75)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
                ),
        # HALL_ELECTRIC_CARGO_TUG
        VehicleDef(
                    id=ids.HALL_ELECTRIC_CARGO_TUG,
                    display_name="ホール電気推進軌道間貨物船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=13.0, payload_t=14.0, transit_time_multiplier=2.4,
                        propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=3.2,
                        propellant_t_per_total_t_per_km_s=0.0025,
                        operation_capabilities=(SpaceflightCapability(30.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=4000.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=16.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 13),
                                   (ids.PRECISION_ELECTRONICS, 8),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 1.6)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("EP-PLASMA-THRUSTERS-06"),
                            ids.research_id("GN-NAVIGATION-06"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=8.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 6.5),
                                   (ids.PRECISION_ELECTRONICS, 4),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 0.8)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=6.0),
                ),
        # ION_PROPULSION_SCIENCE_PROBE
        VehicleDef(
                    id=ids.ION_PROPULSION_SCIENCE_PROBE,
                    display_name="グリッド式イオン推進深宇宙探査機",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=4.5, payload_t=1.1, transit_time_multiplier=2.0,
                        propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=1.2,
                        propellant_t_per_total_t_per_km_s=0.0017,
                        operation_capabilities=(SpaceflightCapability(45.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=30000.0,
                        generic_capabilities=("survey_sensor", "docking_interface", "refueling_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=12.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 6),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 0.6),
                                   (ids.OPTICAL_INSTRUMENT_PACKAGES, 0.75)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("EP-PLASMA-THRUSTERS-04"),
                            ids.research_id("EP-PLASMA-THRUSTERS-07"),
                            ids.research_id("SS-SENSING-01"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=5.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 0.3),
                                   (ids.OPTICAL_INSTRUMENT_PACKAGES, 0.375)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=4.0),
                ),
        # NUCLEAR_THERMAL_CARGO_SHIP
        VehicleDef(
                    id=ids.NUCLEAR_THERMAL_CARGO_SHIP,
                    display_name="水素核熱推進・惑星間貨物輸送船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=28.0, payload_t=40.0, transit_time_multiplier=1.05,
                        propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=22.0,
                        propellant_t_per_total_t_per_km_s=0.005,
                        operation_capabilities=(SpaceflightCapability(38.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=17000.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=26.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 23),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 3),
                                   (ids.RADIATION_SHIELDING_PANELS, 2)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("NT-NUCLEAR-THERMAL-04"),
                            ids.research_id("FP-REACTOR-POWER-03"),
                            ids.research_id("MC-MANUFACTURING-CONSTRUCTION-05"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=11.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 11.5),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 1.5),
                                   (ids.RADIATION_SHIELDING_PANELS, 1)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=9.0),
                ),
        # NUCLEAR_THERMAL_CREW_SHIP
        VehicleDef(
                    id=ids.NUCLEAR_THERMAL_CREW_SHIP,
                    display_name="核熱推進・有人深宇宙航行船",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=33.0, payload_t=25.0, transit_time_multiplier=1.12,
                        propellant_resource_id=ids.HYDROGEN, propellant_capacity_t=15.0,
                        propellant_t_per_total_t_per_km_s=0.0045,
                        operation_capabilities=(SpaceflightCapability(50.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.HYDROGEN, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=12000.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=38.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 31),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 4),
                                   (ids.RADIATION_SHIELDING_PANELS, 6)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("NT-NUCLEAR-THERMAL-07"),
                            ids.research_id("LS-ATMOSPHERE-WATER-WASTE-05"),
                            ids.research_id("HB-HABITATION-PROTECTION-04"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=16.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 15.5),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 2),
                                   (ids.RADIATION_SHIELDING_PANELS, 3)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=12.0),
                    passengers=PassengerAccommodation(
                        seats=10, life_support_person_days_per_day=10, onboard_power_mw=2.0,
                        power_mw_per_person=0.14,
                        net_resources_per_person_day=((ids.FOOD, 0.002),
                                                      (ids.WATER, 0.003), (ids.OXYGEN, 0.002)),
                    ),
                ),
        # DEEP_SPACE_PROBE
        VehicleDef(
                    id=ids.DEEP_SPACE_PROBE,
                    display_name="長距離無人探査機",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=3.0, payload_t=1.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=3.0,
                        propellant_t_per_total_t_per_km_s=0.015,
                        operation_capabilities=(SpaceflightCapability(20.0),),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=20_000.0,
                        generic_capabilities=("survey_sensor", "docking_interface", "refueling_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=14.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 7),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 0.4),
                                   (ids.OPTICAL_INSTRUMENT_PACKAGES, 1)),
                        prerequisite_technologies=frozenset({ids.research_id("GN-NAVIGATION-06"), ids.research_id("SS-SENSING-01"), ids.research_id("CO-RF-COMMUNICATIONS-04")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=5.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.5),
                                   (ids.THERMAL_CONTROL_ASSEMBLIES, 0.2),
                                   (ids.OPTICAL_INSTRUMENT_PACKAGES, 0.5)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=5.0),
                ),
        # SURFACE_CARGO_HAULER
        VehicleDef(
                    id=ids.SURFACE_CARGO_HAULER,
                    display_name="地表貨物輸送車",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=4.0, payload_t=12.0,
                        operation_capabilities=(SurfaceTransportCapability(180.0),),
                        endurance_days=120.0,
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=2.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 2.75), (ids.CONSTRUCTION_EQUIPMENT, 1.25), (ids.PRECISION_ELECTRONICS, 0.25)),
                        prerequisite_technologies=frozenset({ids.research_id("SM-SURFACE-MOBILITY-01")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=1.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 1.375), (ids.CONSTRUCTION_EQUIPMENT, 0.625), (ids.PRECISION_ELECTRONICS, 0.125)),
                    ),
                    maintenance=VehicleMaintenanceSpec(turnaround_days=0.25),
                ),
        # Articulated high-load chassis extends Surface Transport reach and
        # shipment size, in exchange for finite maintenance-bay occupancy and
        # actual spare parts each turnaround. The lightweight hauler remains
        # preferable for small cargo flows without a servicing depot.
        VehicleDef(
            id=ids.MODULAR_SURFACE_FREIGHTER,
            display_name="連接式重量貨物地表輸送車",
            performance=TransportPerformanceProfile(
                dry_mass_t=16.0, payload_t=32.0,
                operation_capabilities=(SurfaceTransportCapability(210.0),),
                endurance_days=180.0,
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=8.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 10.5),
                           (ids.MACHINERY, 5.0),
                           (ids.CONSTRUCTION_EQUIPMENT, 0.8)),
                prerequisite_technologies=frozenset({
                    ids.research_id("SM-SURFACE-MOBILITY-08"),
                    ids.research_id("LM-LOGISTICS-MAINTENANCE-09"),
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=3.0,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 5.25),
                                             (ids.MACHINERY, 2.5),
                                             (ids.CONSTRUCTION_EQUIPMENT, 0.4)),
            ),
            maintenance=VehicleMaintenanceSpec(
                service_type="surface_vehicle_servicing", turnaround_days=1.0,
                resources=((ids.BASIC_MACHINE_PARTS, 0.04),),
            ),
        ),
        # REUSABLE_SURFACE_CARGO_LANDER
        VehicleDef(
                    id=ids.REUSABLE_SURFACE_CARGO_LANDER,
                    display_name="小型再使用着陸貨物艇",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=5.0, payload_t=6.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=3.0,
                        propellant_t_per_total_t_per_km_s=0.030,
                        operation_capabilities=(SpaceflightCapability(5.0), PoweredAscentCapability(2.1, 2.0, 1000.0, 420.0), LandingCapability(2.1, 2.0, 1000.0, 420.0)),
                        resource_support_requirements=(ResourceSupportRequirement(ids.PROPELLANT, "vehicle_refueling", "refueling_interface"),),
                        endurance_days=30.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=3.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 2.5), (ids.MACHINERY, 1.5), (ids.PRECISION_ELECTRONICS, 0.8)),
                        prerequisite_technologies=frozenset({ids.research_id("CH-COMBUSTION-01"), ids.research_id("EDL-EDL-06")}),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=1.5,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 1.25), (ids.MACHINERY, 0.75), (ids.PRECISION_ELECTRONICS, 0.4)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=1.0),
                ),
        # CREWED_LOW_GRAVITY_LANDER
        # Pressurized personnel delivery between vacuum surfaces and orbital
        # infrastructure. Passenger capacity is not inferred from cargo space.
        VehicleDef(
            id=ids.CREWED_LOW_GRAVITY_LANDER,
            display_name="低重力有人着陸連絡艇",
            performance=TransportPerformanceProfile(
                dry_mass_t=6.5, payload_t=2.0,
                propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=4.0,
                propellant_t_per_total_t_per_km_s=0.028,
                operation_capabilities=(
                    SpaceflightCapability(5.0),
                    PoweredAscentCapability(2.1, 2.0, 1000.0, 420.0),
                    LandingCapability(2.1, 2.0, 1000.0, 420.0),
                ),
                resource_support_requirements=(ResourceSupportRequirement(
                    ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                ),),
                endurance_days=45.0,
                generic_capabilities=("refueling_interface", "docking_interface", "pressurized_crew_transport"),
            ),
            production=VehicleProductionSpec(
                service_type="vehicle_assembly", days=7.0,
                resources=((ids.STRUCTURAL_COMPONENTS, 4.5),
                           (ids.MACHINERY, 2.5), (ids.PRECISION_ELECTRONICS, 2.0)),
                prerequisite_technologies=frozenset({
                    ids.research_id("EDL-EDL-06"),
                    ids.research_id("BIO-HUMAN-BIOLOGY-MEDICINE-04"),
                    ids.LS_ATMOSPHERE_WATER_WASTE_01,
                }),
            ),
            retirement=VehicleRetirementSpec(
                service_type="vehicle_assembly", work_days_per_unit=3.5,
                recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 2.25),
                                             (ids.MACHINERY, 1.25), (ids.PRECISION_ELECTRONICS, 1.0)),
            ),
            maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=2.0,
                                               resources=((ids.BASIC_MACHINE_PARTS, 0.06),)),
            passengers=PassengerAccommodation(
                seats=4, life_support_person_days_per_day=4, onboard_power_mw=0.6,
                power_mw_per_person=0.1,
                net_resources_per_person_day=((ids.FOOD, 0.002), (ids.WATER, 0.003),
                                              (ids.OXYGEN, 0.001)),
            ),
        ),
        # LOW_GRAVITY_CARGO_FERRY
        VehicleDef(
                    id=ids.LOW_GRAVITY_CARGO_FERRY,
                    display_name="低重力往復貨物フェリー",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=7.0, payload_t=8.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=5.0,
                        propellant_t_per_total_t_per_km_s=0.015,
                        operation_capabilities=(
                            SpaceflightCapability(4.5),
                            PoweredAscentCapability(2.3, 2.8, 900.0, 410.0),
                            LandingCapability(2.3, 2.8, 900.0, 410.0),
                        ),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=45.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=7.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 6.5),
                                   (ids.MACHINERY, 4.0), (ids.PRECISION_ELECTRONICS, 3.1)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("CH-COMBUSTION-08"),
                            ids.research_id("LM-LOGISTICS-MAINTENANCE-14"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=2.5,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.25),
                                                     (ids.MACHINERY, 2.0),
                                                     (ids.PRECISION_ELECTRONICS, 1.55)),
                    ),
                    maintenance=VehicleMaintenanceSpec(
                        service_type="spacecraft_servicing", turnaround_days=1.8,
                    ),
                ),
        # THROTTLEABLE_CARGO_LANDER
        VehicleDef(
                    id=ids.THROTTLEABLE_CARGO_LANDER,
                    display_name="推力可変式地表アクセス貨物艇",
                    performance=TransportPerformanceProfile(
                        dry_mass_t=9.0, payload_t=10.0,
                        propellant_resource_id=ids.PROPELLANT, propellant_capacity_t=11.0,
                        propellant_t_per_total_t_per_km_s=0.021,
                        operation_capabilities=(
                            SpaceflightCapability(9.0),
                            PoweredAscentCapability(4.5, 5.0, 1500.0, 440.0),
                            LandingCapability(4.5, 5.0, 1500.0, 440.0),
                        ),
                        resource_support_requirements=(ResourceSupportRequirement(
                            ids.PROPELLANT, "vehicle_refueling", "refueling_interface",
                        ),),
                        endurance_days=75.0,
                        generic_capabilities=("refueling_interface", "docking_interface"),
                    ),
                    production=VehicleProductionSpec(
                        service_type="vehicle_assembly", days=8.0,
                        resources=((ids.STRUCTURAL_COMPONENTS, 6.0),
                                   (ids.MACHINERY, 4.0), (ids.PRECISION_ELECTRONICS, 2.2)),
                        prerequisite_technologies=frozenset({
                            ids.research_id("CH-COMBUSTION-08"),
                            ids.research_id("EDL-EDL-08"),
                        }),
                    ),
                    retirement=VehicleRetirementSpec(
                        service_type="vehicle_assembly", work_days_per_unit=3.0,
                        recovery_resources_per_unit=((ids.STRUCTURAL_COMPONENTS, 3.0),
                                                     (ids.MACHINERY, 2.0),
                                                     (ids.PRECISION_ELECTRONICS, 1.1)),
                    ),
                    maintenance=VehicleMaintenanceSpec(service_type="spacecraft_servicing", turnaround_days=3.5),
                ),
    )
    # Default balance parameters apply equally to all ordinary facilities.
    facilities = tuple(replace(row, definition=replace(
        row.definition,
        maintenance_fraction_per_year=(
            row.definition.maintenance_fraction_per_year
            if row.definition.maintenance_fraction_per_year > 1e-12 else 0.05
        ),
        decommission_recovery_fraction=0.5,
    ), decommission=(row.decommission or FacilityDecommissionRecipe(
        row.definition.id, construction_work=12.0)))
                       for row in facilities + build_extended_facility_assets() + build_concept_facility_assets())
    return facilities, vehicles + build_extended_vehicle_defs() + build_concept_vehicle_defs()
