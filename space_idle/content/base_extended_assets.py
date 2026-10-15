"""Physical asset Content for the eight-stage industrial and research expansion.

Acquisition/Operation use ordinary Facility, Construction, Power, Process,
Research and logistics ownership. Numbers are initial Content calibration points,
not new Core rules or fixed stage-wide bonuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from ..facilities import FacilityDef, FacilityPlacementScope, LifeSupportSpec
from ..projects import ConstructionRecipe, BuildResourceRequirement, ConstructionProviderSpec
from ..power import PowerSpec, SolarGeneration, FixedGeneration
from ..shared import DefinitionId
from ..research import ResearchProviderSpec, ResearchProviderLevelSpec, ResearchProviderSourceKind
from .asset_content import FacilityAsset
from . import base_ids as ids
from . import base_requirements as req

@dataclass(frozen=True)
class FacilityRole:
    capabilities: tuple[str, ...]
    load_mw: float
    throughput: float = 0.0
    extraction_tpd: float = 0.0
    services: tuple[tuple[str, float], ...] = ()
    construction_tpd: float = 0.0
    housing: int = 0
    # Archives increase RP storage without artificially generating points.
    storage_points: float = 0.0
    research_points_tpd: float = 0.0
    research_execution_tpd: float = 0.0
    power_generation_mw: float = 0.0
    orbital: bool = False
    cell: bool = False

# Equipment capabilities and physical operating envelopes are per-Facility;
# they never apply a Technology-wide buff to another installed Facility.
_PHYSICAL_ROLES: dict[str, FacilityRole] = {
    'remote_operations_lab': FacilityRole(('research_lab','remote_robotics_lab'), .34, research_points_tpd=12, research_execution_tpd=2.5),
    'robotic_data_archive': FacilityRole(('research_data_archive_robotic',), .17, storage_points=600),
    'survey_power_microgrid': FacilityRole(('surface_microgrid',), .08, power_generation_mw=1.9),
    'crew_biomedical_research_center': FacilityRole(('research_lab','crew_biomedical_research'), .82, research_points_tpd=29, research_execution_tpd=5.0),
    'crew_research_archive': FacilityRole(('research_archive_crew',), .34, storage_points=2200),
    'habitation12': FacilityRole(('pressurized_habitation','closed_cycle_life_support'), 1.2, housing=12),
    'permanent_research_station': FacilityRole(('research_lab','permanent_science_station'), 2.4, research_points_tpd=65, research_execution_tpd=9.0),
    'permanent_science_archive': FacilityRole(('permanent_science_archive',), .75, storage_points=6700),
    'low_volume_sintering_station': FacilityRole(('pilot_regolith_sintering',), .9, throughput=.7),
    'local_supply_terminal': FacilityRole(('cargo_transfer','vehicle_refueling','surface_distribution'), .33, services=(('cargo_transfer',3.0),('surface_distribution',12.0))),
    'pilot_volatile_processing': FacilityRole(('volatile_processing','carbon_nutrient_separation'), 1.0, throughput=1.4),
    'industrial_science_institute': FacilityRole(('research_lab','industrial_materials_research'), 6.3, research_points_tpd=190, research_execution_tpd=22.0),
    'industrial_data_archive': FacilityRole(('industrial_research_archive',), 1.5, storage_points=18000),
    'selective_mining_complex': FacilityRole(('metal_ore_extraction','mineral_extraction','continuous_mineral_separation'), 4.8, throughput=7.0, extraction_tpd=9.0,cell=True),
    'vacuum_metallurgical_complex': FacilityRole(('high_temperature_alloy_furnace','metallurgy','recovered_alloy_refining'), 10.0, throughput=5.0),
    'industrial_parts_shop': FacilityRole(('industrial_exchange_machining','basic_machine_shop','precision_machining'), 3.0, throughput=5.0),
    'integrated_propellant_refinery': FacilityRole(('industrial_volatile_fractionation','continuous_electrolysis','industrial_propellant_processing'), 9.0, throughput=8.0),
    'industrial_heat_network': FacilityRole(('industrial_heat_exchange','heat_pipe_radiator_assembly'), 1.7, throughput=2.0),
    'industrial_construction_bureau': FacilityRole(('construction_yard','surface_distribution'), 4.5, construction_tpd=16.0),
    'industrial_power_station': FacilityRole(('fission_reactor_control_instrumentation','industrial_power_supply'), 1.6, power_generation_mw=25.0),
    'local_spares_workshop': FacilityRole(('industrial_disassembly','industrial_exchange_machining','basic_machine_shop'), 2.5, throughput=2.5, services=(('spacecraft_servicing',.8),)),
    'cross_site_science_array': FacilityRole(('research_lab','distributed_science_array'), 12.0, research_points_tpd=480, research_execution_tpd=43.0),
    'network_science_archive': FacilityRole(('distributed_science_archive',), 3.0, storage_points=45000),
    'regional_extraction_complex': FacilityRole(('mineral_extraction','metal_ore_extraction','volatile_extraction','continuous_mineral_separation'), 17.0, throughput=12, extraction_tpd=32,cell=True),
    'orbital_manufacturing_hub': FacilityRole(('orbital_precision_module_fabrication','basic_machine_shop','precision_machining','industrial_machinery_assembly','recovered_alloy_refining'), 12.0, throughput=14.0,orbital=True),
    'interplanetary_handoff_hub': FacilityRole(('cargo_transfer','spacecraft_servicing','vehicle_refueling','docking_interface'), 8.0, services=(('cargo_transfer',17.0),('spacecraft_servicing',5.0))),
    'bulk_construction_complex': FacilityRole(('construction_yard','robotic_orbital_construction'), 7.5, construction_tpd=42.0),
    'power_transit_station': FacilityRole(('fission_reactor_control_instrumentation','industrial_power_supply'), 3.0, power_generation_mw=65.0),
    'industrial_habitat120': FacilityRole(('pressurized_habitation','closed_cycle_life_support'), 9.0, housing=120),
    'extreme_environment_science_array': FacilityRole(('research_lab','extreme_radiation_science'), 23.0, research_points_tpd=1100, research_execution_tpd=77.0),
    'outer_system_science_archive': FacilityRole(('radiation_shielded_science_archive',), 7.0, storage_points=120000),
    # Instrumented orbital baseline supplies tracking locally; a surface antenna
    # cannot satisfy an orbital Research execution site.
    'orbital_precision_tracking_array': FacilityRole(('deep_space_tracking_equipment', 'orbital_phase_reference'), 6.0, orbital=True),
    'cryogenic_ice_drilling_station': FacilityRole(('volatile_extraction','cryogenic_drilling'), 13.0, extraction_tpd=24.0,cell=True),
    'outer_system_fission_field': FacilityRole(('fission_reactor_control_instrumentation','low_sun_power_supply'), 5.0, power_generation_mw=120.0),
    'self_servicing_autonomy_node': FacilityRole(('industrial_disassembly','hardened_electronics_fabrication','autonomous_equipment_servicing'), 5.0, throughput=4.0, services=(('spacecraft_servicing',3.0),)),
    'outer_system_habitation_module': FacilityRole(('pressurized_habitation','closed_cycle_life_support','radiation_shielded_housing'), 19.0, housing=160),
    'far_industry_construction_bureau': FacilityRole(('construction_yard','robotic_operations'), 9.0, construction_tpd=48.0),
    'solar_system_science_coordination_center': FacilityRole(('research_lab','multi_region_science'), 38.0, research_points_tpd=2400, research_execution_tpd=160.0),
    'solar_system_science_archive': FacilityRole(('distributed_science_archive_solar',), 13.0, storage_points=280000),
    'regional_mass_extraction_field': FacilityRole(('metal_ore_extraction','mineral_extraction','volatile_extraction'), 40.0, extraction_tpd=135.0,cell=True),
    'distributed_power_coordination_grid': FacilityRole(('grid_control_equipment','industrial_heat_exchange'), 12.0),
    'autonomous_infrastructure_rebuilder': FacilityRole(('construction_yard','industrial_disassembly','circular_precision_remanufacturing'), 22.0, throughput=12.0, construction_tpd=90.0),
    'solar_system_logistics_node': FacilityRole(('cargo_transfer','vehicle_refueling','spacecraft_servicing'), 19.0, services=(('cargo_transfer',90.0),('spacecraft_servicing',15.0))),
    'multi_region_bioregeneration_center': FacilityRole(('pressurized_habitation','closed_cycle_life_support','controlled_nutrient_cultivation'), 24.0, throughput=7.0, housing=200),
    'circular_materials_campus': FacilityRole(('industrial_disassembly','circular_precision_remanufacturing','recovered_alloy_refining'), 19.0, throughput=23.0),
    'terrain_remediation_complex': FacilityRole(('construction_yard','terrain_engineering'), 17.0, construction_tpd=110.0,cell=True),
    'modular_construction_workshop': FacilityRole(('construction_yard','basic_machine_shop'), 1.0, throughput=.6, construction_tpd=5.0),
    'remote_crane_assembly_yard': FacilityRole(('construction_yard','robotic_operations'), 1.8, construction_tpd=9.0),
    'basic_data_archive': FacilityRole(('basic_research_data_archive',), .08, storage_points=120),
    'hardened_electronics_fab': FacilityRole(('hardened_electronics_fabrication','cryogenic_protected_fabrication'), 14.0, throughput=3.0),
    'screened_surface_excavator': FacilityRole(('metal_ore_extraction','mineral_extraction','surface_survey'), .45, extraction_tpd=.7,cell=True),
    'autonomous_multi_tool_excavator': FacilityRole(('metal_ore_extraction','mineral_extraction','surface_survey'), .8, extraction_tpd=2.2,cell=True),
    'earth_biomass_feedstock_collector': FacilityRole(('biomass_collection','carbon_nutrient_separation'), .12, throughput=.35, extraction_tpd=.55),
    'earth_basic_electronics_shop': FacilityRole(('earth_basic_electronics',), .7, throughput=.8),
}

# Each table entry declares its own physical construction materials and explicit
# Technology requirements. A provisional 'planned' ID becomes a real catalog
# Definition only through the composition below.
_EXTENDED_FACILITY_ROWS = (
    ('remote_operations_lab', '遠隔ロボット・計測総合実験室', 2, ('X2-REMOTE-OPERATIONS-LAB',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('robotic_data_archive', '無人探査耐障害データアーカイブ', 2, ('X2-DATA-RETENTION',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('survey_power_microgrid', '無人拠点電力・熱管理装置', 2, ('PG-SOLAR-POWER-04',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('crew_biomedical_research_center', '有人長期生理・生命維持実験室', 3, ('X3-CREW-LIFE-SUPPORT-TEST',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('crew_research_archive', '有人長期実験記録アーカイブ', 3, ('X3-CREW-LIFE-SUPPORT-TEST',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('habitation12', '遠隔有人居住・生命維持12人モジュール', 3, ('X3-CREW-LIFE-SUPPORT-TEST',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('permanent_research_station', '長期補給型域外総合研究所', 4, ('LM-LOGISTICS-MAINTENANCE-08',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('permanent_science_archive', '恒久拠点用故障冗長研究アーカイブ', 4, ('LM-LOGISTICS-MAINTENANCE-08',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('low_volume_sintering_station', '試験焼結・初期現地構造材工房', 4, ('X4-SINTER-BUILD',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('local_supply_terminal', '域外反復補給・荷役拠点', 4, ('X4-REUSABLE-CARGO',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('pilot_volatile_processing', '小型揮発成分抽出・精製装置', 4, ('RP-RESOURCE-CHAIN-06',), ('base.resource.machinery', 'base.resource.precision_electronics', 'base.resource.structural_components')),
    ('industrial_science_institute', '産業材料・設備実証研究院', 5, ('X5-THERMAL-REFINING',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('industrial_data_archive', '工業材料・工程実証アーカイブ', 5, ('X5-PRECISION-FABRICATION',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('selective_mining_complex', '選鉱併設大型採取施設', 5, ('RP-RESOURCE-CHAIN-10',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.construction_equipment')),
    ('vacuum_metallurgical_complex', '真空精錬・回収設備', 5, ('X5-THERMAL-REFINING',), ('base.resource.machinery', 'base.resource.thermal_control_assemblies', 'base.resource.structural_components')),
    ('industrial_parts_shop', '現地高精度交換部品工場', 5, ('X5-PRECISION-FABRICATION',), ('base.resource.basic_machine_parts', 'base.resource.precision_electronics', 'base.resource.bulk_structure')),
    ('integrated_propellant_refinery', '水電解・液化・推進剤製造プラント', 5, ('X5-LOCAL-PROPELLANT',), ('base.resource.machinery', 'base.resource.thermal_control_assemblies', 'base.resource.structural_components')),
    ('industrial_heat_network', '工業用熱交換・放熱拠点', 5, ('X5-HEAT-REJECTION',), ('base.resource.thermal_control_assemblies', 'base.resource.machinery', 'base.resource.structural_components')),
    ('industrial_construction_bureau', '工業地表施工・機械稼働拠点', 5, ('X5-INDUSTRIAL-CONSTRUCTION',), ('base.resource.construction_equipment', 'base.resource.machinery', 'base.resource.structural_components')),
    ('industrial_power_station', '産業用固定電源プラント', 5, ('FP-REACTOR-POWER-08',), ('base.resource.machinery', 'base.resource.structural_components', 'base.resource.thermal_control_assemblies')),
    ('local_spares_workshop', '現地設備保守・交換部品工房', 5, ('X5-SPARE-PARTS-REPAIR',), ('base.resource.machinery', 'base.resource.basic_machine_parts', 'base.resource.precision_electronics')),
    ('cross_site_science_array', '分散科学実証ネットワーク施設', 6, ('X6-CROSS-SITE-RESEARCH',), ('base.resource.precision_electronics', 'base.resource.machinery', 'base.resource.structural_components')),
    ('network_science_archive', '大規模分散実験データ保存局', 6, ('X6-CROSS-SITE-RESEARCH',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('regional_extraction_complex', '広域自動資源採取センター', 6, ('RP-RESOURCE-CHAIN-10',), ('base.resource.machinery', 'base.resource.construction_equipment', 'base.resource.structural_components')),
    ('orbital_manufacturing_hub', '軌道製造・最終組立拠点', 6, ('X6-ORBITAL-MANUFACTURING',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('interplanetary_handoff_hub', '惑星間荷役・中継・整備ハブ', 6, ('X6-DIRECT-HANDOFF',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.thermal_control_assemblies')),
    ('bulk_construction_complex', '惑星間向け大容量施工センター', 6, ('X6-CISLUNAR-MASS-BUILD',), ('base.resource.construction_equipment', 'base.resource.machinery', 'base.resource.structural_components')),
    ('power_transit_station', '惑星間産業大型核分裂・熱循環電源', 6, ('X5-HEAT-REJECTION',), ('base.resource.machinery', 'base.resource.structural_components', 'base.resource.thermal_control_assemblies')),
    ('industrial_habitat120', '工業人口用居住・水再生120人棟', 6, ('LS-ATMOSPHERE-WATER-WASTE-13',), ('base.resource.fabricated_structure', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('extreme_environment_science_array', '極端環境自律科学研究基地', 7, ('X7-REMOTE-RADIATION-SCIENCE',), ('base.resource.hardened_electronics', 'base.resource.machinery', 'base.resource.thermal_control_assemblies')),
    ('outer_system_science_archive', '極低温・高放射線冗長研究記録庫', 7, ('X7-REMOTE-RADIATION-SCIENCE',), ('base.resource.hardened_electronics', 'base.resource.machinery', 'base.resource.radiation_shielding_panels')),
    ('orbital_precision_tracking_array', '軌道位相基準・精密追尾アレイ', 7, ('X7-DEEP-SPACE-RELAY',), ('base.resource.hardened_electronics', 'base.resource.optical_instrument_packages', 'base.resource.thermal_control_assemblies')),
    ('cryogenic_ice_drilling_station', '極低温氷殻・揮発物掘削基地', 7, ('VR-7-RESOURCE-CHAIN-01',), ('base.resource.construction_equipment', 'base.resource.thermal_control_assemblies', 'base.resource.machinery')),
    ('outer_system_fission_field', '外惑星長寿命電力炉・遮蔽設備', 7, ('X7-EXTREME-POWER',), ('base.resource.thermal_control_assemblies', 'base.resource.machinery', 'base.resource.radiation_shielding_panels')),
    ('self_servicing_autonomy_node', '長遅延自律保守・部品交換拠点', 7, ('X7-DELAY-TOLERANT-AUTONOMY',), ('base.resource.machinery', 'base.resource.hardened_electronics', 'base.resource.structural_components')),
    ('outer_system_habitation_module', '低日射域居住・遮蔽160人群', 7, ('X7-REMOTE-LIFE-SUPPORT',), ('base.resource.radiation_shielding_panels', 'base.resource.machinery', 'base.resource.fabricated_structure')),
    ('far_industry_construction_bureau', '極端環境分散施工拠点', 7, ('X7-DELAY-TOLERANT-AUTONOMY',), ('base.resource.construction_equipment', 'base.resource.hardened_electronics', 'base.resource.fabricated_structure')),
    ('solar_system_science_coordination_center', '太陽系研究実証統合複合体', 8, ('X6-CROSS-SITE-RESEARCH',), ('base.resource.hardened_electronics', 'base.resource.fabricated_structure', 'base.resource.machinery')),
    ('solar_system_science_archive', '太陽系広域実験保存センター', 8, ('X6-CROSS-SITE-RESEARCH',), ('base.resource.hardened_electronics', 'base.resource.fabricated_structure', 'base.resource.machinery')),
    ('regional_mass_extraction_field', '多地点大規模採取・輸送設備群', 8, ('X8-CIRCULAR-MANUFACTURING',), ('base.resource.construction_equipment', 'base.resource.machinery', 'base.resource.fabricated_structure')),
    ('distributed_power_coordination_grid', '広域電力・熱廃熱統合プラント', 8, ('X8-DISTRIBUTED-POWER',), ('base.resource.thermal_control_assemblies', 'base.resource.fabricated_structure', 'base.resource.machinery')),
    ('autonomous_infrastructure_rebuilder', '更新・撤去・再施工ロボット複合施設', 8, ('X8-AUTONOMOUS-INFRASTRUCTURE',), ('base.resource.construction_equipment', 'base.resource.hardened_electronics', 'base.resource.fabricated_structure')),
    ('solar_system_logistics_node', '太陽系長距離荷役・点検・補給センター', 8, ('PL-MULTIREGION-CARGO-CUSTODY',), ('base.resource.machinery', 'base.resource.fabricated_structure', 'base.resource.thermal_control_assemblies')),
    ('multi_region_bioregeneration_center', '大規模域外居住・生命維持200人棟', 8, ('X8-REMOTE-HABITATION-NETWORK',), ('base.resource.fabricated_structure', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('circular_materials_campus', '多拠点再利用素材・工業部品加工群', 8, ('X8-CIRCULAR-MANUFACTURING',), ('base.resource.machinery', 'base.resource.fabricated_structure', 'base.resource.hardened_electronics')),
    ('terrain_remediation_complex', '地形造成・排土・基盤建設群', 8, ('X8-REMOTE-CELL-REMEDIATION',), ('base.resource.construction_equipment', 'base.resource.machinery', 'base.resource.fabricated_structure')),
    ('modular_construction_workshop', 'モジュール化施工・据付作業場', 3, ('MC-MANUFACTURING-CONSTRUCTION-08',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('remote_crane_assembly_yard', '域外遠隔クレーン施工ステーション', 4, ('MC-MANUFACTURING-CONSTRUCTION-10',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('basic_data_archive', '初期研究データ保管サーバ', 1, ('CO-RF-COMMUNICATIONS-01',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('hardened_electronics_fab', '遠隔耐放射線電子製造工場', 7, ('X7-RADIATION-HARDENED-COMPONENTS',), ('base.resource.machinery', 'base.resource.precision_electronics', 'base.resource.radiation_shielding_panels')),
    ('screened_surface_excavator', 'ロボット計測付き地表採取モジュール', 2, ('RP-RESOURCE-CHAIN-03',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('autonomous_multi_tool_excavator', '自律資源採取・試料計測複合機', 3, ('RP-RESOURCE-CHAIN-05',), ('base.resource.structural_components', 'base.resource.machinery', 'base.resource.precision_electronics')),
    ('earth_biomass_feedstock_collector', '初期炭素・栄養資源回収設備', 1, (), ('base.resource.structural_components', 'base.resource.machinery')),
    ('earth_basic_electronics_shop', '低歩留まり地球基礎電子部品工場', 1, ('PL-EARTH-PRECISION-PARTS',), ('base.resource.structural_components', 'base.resource.machinery')),
)

_CONSTRUCTION_SCALES = {1: 1.0, 2: 2.2, 3: 3.8, 4: 7.0, 5: 15.0, 6: 31.0, 7: 49.0, 8: 78.0}


def build_extended_facility_assets() -> tuple[FacilityAsset, ...]:
    rows = []
    for slug, label, stage, technologies, material_ids in _EXTENDED_FACILITY_ROWS:
        role = _PHYSICAL_ROLES[slug]
        identity = DefinitionId('planned.facility.' + slug)
        site = req.ORBIT_SITE if role.orbital else req.SURFACE_SITE
        scale = _CONSTRUCTION_SCALES[stage]
        construction_resources = tuple(
            BuildResourceRequirement(DefinitionId(resource), scale * (0.95 if 'machinery' in resource else 0.68))
            for resource in material_ids
        )
        facilities = FacilityDef(
            identity, label, req._capabilities(*role.capabilities),
            installation_requirements=site, operating_requirements=site,
            maintenance_fraction_per_year=0.065,
            decommission_recovery_fraction=0.45,
            placement_scope=(FacilityPlacementScope.SURFACE_CELL if role.cell else FacilityPlacementScope.OPERATIONAL_NODE),
            service_capacity_supplies=req._services(**dict(role.services)),
            housing_capacity=role.housing,
            life_support=LifeSupportSpec(role.housing, ((ids.FOOD, .001),(ids.WATER,.002),(ids.OXYGEN,.003))) if role.housing else None,
            process_throughput_per_day=role.throughput,
            extraction_capacity_t_per_day=role.extraction_tpd,
        )
        if role.power_generation_mw:
            generation = (
                SolarGeneration(role.power_generation_mw / .62, 1361.0)
                if slug == 'survey_power_microgrid' else FixedGeneration(role.power_generation_mw)
            )
        else:
            generation = None
        rows.append(FacilityAsset(
            definition=facilities,
            construction=ConstructionRecipe(
                identity, construction_resources, scale * 6.0,
                site, frozenset(DefinitionId(item) for item in technologies),
            ),
            power=PowerSpec(generation, role.load_mw, standby_load_mw=role.load_mw * .08),
            construction_provider=(ConstructionProviderSpec(identity, role.construction_tpd)
                                   if role.construction_tpd else None),
        ))
    if len(rows) != len(_PHYSICAL_ROLES):
        raise ValueError('Every extended Facility must have exactly one physical design')
    return tuple(rows)


def build_extended_research_providers() -> dict[DefinitionId, ResearchProviderSpec]:
    providers = {}
    stages = {slug: stage for slug, _name, stage, _technologies, _materials in _EXTENDED_FACILITY_ROWS}
    for slug, role in _PHYSICAL_ROLES.items():
        if not (role.research_points_tpd or role.storage_points):
            continue
        identity = DefinitionId('planned.research_provider.' + slug)
        # One capability unique to this exact installed Facility (not a generic
        # research_lab capability that double-counts an existing provider).
        matching_capability = next(cap for cap in role.capabilities if cap != 'research_lab')
        providers[identity] = ResearchProviderSpec(
            identity, ResearchProviderSourceKind.FACILITY,
            frozenset({matching_capability}), tier=stages[slug],
            levels=(ResearchProviderLevelSpec(
                1, role.research_points_tpd, max(role.storage_points, role.research_points_tpd * 36),
                role.research_execution_tpd,
            ),),
        )
    return providers
