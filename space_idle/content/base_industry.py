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
        # Physically closed irrigation and nutrient recapture require a newly
        # installed recirculation interface. Existing farms do not gain better
        # yields when Technology is completed.
        ids.PROCESS_WATER_EFFICIENT_CULTIVATION: ProcessSpec(
            ids.PROCESS_WATER_EFFICIENT_CULTIVATION, "循環養液制御による閉鎖栽培",
            frozenset({"recirculating_hydroponics"}),
            {ids.WATER: 0.12}, {ids.FOOD: 0.36},
            frozenset({ids.research_id("PL-PLANT-FOOD-07"),
                       ids.research_id("LS-ATMOSPHERE-WATER-WASTE-14")}),
        ),
        # Liquid water is physically separated from the collected volatile
        # feed. This is a different installed column/condensation interface,
        # not an arbitrary Technology buff of an existing still.
        ids.PROCESS_VOLATILE_FRACTIONATION: ProcessSpec(
            ids.PROCESS_VOLATILE_FRACTIONATION, "揮発性原料の多段分留・凝縮",
            frozenset({"multistage_volatile_fractionation"}),
            {ids.VOLATILE_BEARING_MATERIAL: 1.0}, {ids.WATER: 0.58},
            frozenset({ids.research_id("RP-RESOURCE-CHAIN-11")}),
        ),
        # Equipment assemblies are actual manufactured stocks needed by
        # downstream research, habitat, power and spacecraft acquisition.
        # Each line is a separate installed technical capability; research does
        # not alter existing machinery or silently grant products.
        ids.PROCESS_THERMAL_HARDWARE_ASSEMBLY: ProcessSpec(
            ids.PROCESS_THERMAL_HARDWARE_ASSEMBLY, "ヒートパイプ封止・放熱器組立",
            frozenset({"heat_pipe_radiator_assembly"}),
            {ids.METAL_FEEDSTOCK: 0.42, ids.PRECISION_COMPONENTS: 0.24,
             ids.CERAMICS_GLASS: 0.18},
            {ids.THERMAL_CONTROL_ASSEMBLIES: 0.65},
            frozenset({ids.research_id("TH-THERMAL-TRANSPORT-03")}),
        ),
        ids.PROCESS_SHIELDING_PANEL_FABRICATION: ProcessSpec(
            ids.PROCESS_SHIELDING_PANEL_FABRICATION, "鉱物積層・二次粒子遮蔽パネル成形",
            frozenset({"graded_radiation_shielding"}),
            {ids.MINERAL_FEEDSTOCK: 1.0, ids.CERAMICS_GLASS: 0.35,
             ids.BULK_STRUCTURE: 0.28},
            {ids.RADIATION_SHIELDING_PANELS: 1.3},
            frozenset({ids.research_id("HB-HABITATION-PROTECTION-04")}),
        ),
        ids.PROCESS_OPTICAL_INSTRUMENT_INTEGRATION: ProcessSpec(
            ids.PROCESS_OPTICAL_INSTRUMENT_INTEGRATION, "光学素子精密芯出し・撮像端末実装",
            frozenset({"precision_optical_alignment"}),
            {ids.CERAMICS_GLASS: 0.30, ids.PRECISION_COMPONENTS: 0.20,
             ids.PRECISION_ELECTRONICS: 0.18},
            {ids.OPTICAL_INSTRUMENT_PACKAGES: 0.50},
            frozenset({ids.research_id("CO-OPTICAL-COMMUNICATIONS-01")}),
        ),
        ids.PROCESS_ELECTROLYSIS: ProcessSpec(ids.PROCESS_ELECTROLYSIS, "水電解", frozenset({"industrial_electrolysis"}), {ids.WATER: 0.50}, {ids.OXYGEN: 0.44, ids.HYDROGEN: 0.055}),
        ids.PROCESS_PROPELLANT_BLEND: ProcessSpec(ids.PROCESS_PROPELLANT_BLEND, "化学推進剤調製", frozenset({"propellant_production"}), {ids.OXYGEN: 0.40, ids.HYDROGEN: 0.05}, {ids.PROPELLANT: 0.45}),
        ids.PROCESS_MINERAL_SINTER: ProcessSpec(ids.PROCESS_MINERAL_SINTER, "鉱物原料焼結", frozenset({"mineral_sintering"}), {ids.MINERAL_FEEDSTOCK: 1.0}, {ids.CERAMICS_GLASS: 0.8}, frozenset({DefinitionId("MC-MANUFACTURING-CONSTRUCTION-10")})),
        ids.PROCESS_VOLATILE_WATER_RECOVERY: ProcessSpec(ids.PROCESS_VOLATILE_WATER_RECOVERY, "揮発性成分回収", frozenset({"volatile_processing"}), {ids.VOLATILE_BEARING_MATERIAL: 1.0}, {ids.WATER: 0.35}),
        ids.PROCESS_ORE_PROCESS: ProcessSpec(ids.PROCESS_ORE_PROCESS, "鉱石処理", frozenset({"ore_processing"}), {ids.METAL_ORE: 2.5}, {ids.METAL_FEEDSTOCK: 1.0}),
        # Water-intensive wet separation offers improved recovery where water
        # and storage are available; the dry method remains appropriate where
        # those resources are limiting. Both use the same installed separator.
        ids.PROCESS_WET_ORE_BENEFICIATION: ProcessSpec(
            ids.PROCESS_WET_ORE_BENEFICIATION, "湿式鉱石選別・回収",
            frozenset({"ore_processing"}),
            {ids.METAL_ORE: 2.5, ids.WATER: 0.7},
            {ids.METAL_FEEDSTOCK: 1.45},
            frozenset({ids.research_id("RP-RESOURCE-CHAIN-10")}),
        ),
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
        # Downstream fabrication supplies the same construction commodities as
        # opening industry. Both routes consume physical stock; no substitution
        # of Resource identity takes place inside Construction or Vehicle Core.
        ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS: ProcessSpec(
            ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS, "規格構造部材成形・接合",
            frozenset({"structural_fabrication"}),
            {ids.BULK_STRUCTURE: 0.70}, {ids.STRUCTURAL_COMPONENTS: 0.55},
        ),
        ids.PROCESS_BASIC_MACHINING: ProcessSpec(ids.PROCESS_BASIC_MACHINING, "基礎機械加工", frozenset({"basic_machine_shop"}), {ids.BULK_STRUCTURE: 0.4}, {ids.BASIC_MACHINE_PARTS: 0.25}),
        ids.PROCESS_PRECISION_COMPONENTS: ProcessSpec(ids.PROCESS_PRECISION_COMPONENTS, "精密部品加工", frozenset({"basic_machine_shop", "precision_machining"}), {ids.BASIC_MACHINE_PARTS: 0.30, ids.PRECISION_ELECTRONICS: 0.05}, {ids.PRECISION_COMPONENTS: 0.22}),
        ids.PROCESS_INDUSTRIAL_MACHINERY_ASSEMBLY: ProcessSpec(
            ids.PROCESS_INDUSTRIAL_MACHINERY_ASSEMBLY, "産業機械モジュール組立",
            frozenset({"industrial_machinery_assembly"}),
            {ids.BASIC_MACHINE_PARTS: 0.32, ids.PRECISION_ELECTRONICS: 0.06},
            {ids.MACHINERY: 0.27},
        ),
        # A locally operated microelectronics production chain is an alternative
        # to finite imported electronics, consuming upstream bulk products and
        # process water rather than minting Construction/Vehicle supplies.
        ids.PROCESS_MICROELECTRONICS_FABRICATION: ProcessSpec(
            ids.PROCESS_MICROELECTRONICS_FABRICATION, "薄膜回路形成・電子モジュール実装",
            frozenset({"microelectronics_fabrication"}),
            {ids.CERAMICS_GLASS: 0.60, ids.METAL_FEEDSTOCK: 0.25, ids.WATER: 0.15},
            {ids.PRECISION_ELECTRONICS: 0.20},
        ),
        # Molten-oxide electrolysis is a distinct high-power enclosed process for
        # oxygen and metallurgical feedstock from common mineral feedstock.
        # Neither Water nor a planet-specific Resource identity is invented.
        ids.PROCESS_MOLTEN_OXIDE_ELECTROLYSIS: ProcessSpec(
            ids.PROCESS_MOLTEN_OXIDE_ELECTROLYSIS, "溶融酸化物電解・酸素金属分離",
            frozenset({"molten_oxide_electrolysis"}),
            {ids.MINERAL_FEEDSTOCK: 2.0},
            {ids.OXYGEN: 0.55, ids.METAL_FEEDSTOCK: 0.80},
            frozenset({ids.RP_RESOURCE_CHAIN_16}),
        ),
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
