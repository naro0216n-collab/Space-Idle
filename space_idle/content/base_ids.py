from __future__ import annotations

from ..shared import CelestialBodyId, DefinitionId, SpatialNodeId

STRUCTURAL_COMPONENTS = DefinitionId("base.resource.structural_components")
MACHINERY = DefinitionId("base.resource.machinery")
PRECISION_ELECTRONICS = DefinitionId("base.resource.precision_electronics")
BULK_STRUCTURE = DefinitionId("base.resource.bulk_structure")
FABRICATED_STRUCTURE = DefinitionId("base.resource.fabricated_structure")
BASIC_MACHINE_PARTS = DefinitionId("base.resource.basic_machine_parts")
CONSTRUCTION_EQUIPMENT = DefinitionId("base.resource.construction_equipment")
REGOLITH = DefinitionId("base.resource.regolith")
METAL_FEEDSTOCK = DefinitionId("base.resource.metal_feedstock")
CONTRACT_PAYLOAD = DefinitionId("base.resource.contract_payload")
WATER = DefinitionId("base.resource.water")
OXYGEN = DefinitionId("base.resource.oxygen")
HYDROGEN = DefinitionId("base.resource.hydrogen")
PROPELLANT = DefinitionId("base.resource.chemical_propellant")

# ---------------------------------------------------------------------------
# Spatial nodes. Hierarchy expresses containment; environmental behavior is
# resolved through typed facets rather than node-name branches.
# ---------------------------------------------------------------------------
EARTH_BODY = CelestialBodyId("base.body.earth")
EARTH = SpatialNodeId("base.node.earth_surface")
LEO = SpatialNodeId("base.node.low_earth_orbit")
MOON = CelestialBodyId("base.body.moon")
LUNAR_ORBIT = SpatialNodeId("base.node.lunar_orbit")
SOUTH_POLAR_RIDGE = SpatialNodeId("base.node.south_polar_ridge")
POLAR_COLD_TRAP = SpatialNodeId("base.node.polar_cold_trap")
NEARSIDE_MARE = SpatialNodeId("base.node.nearside_mare")

# ---------------------------------------------------------------------------
# Facilities. IDs and display names describe function, not placement.
# ---------------------------------------------------------------------------
EARTH_RESEARCH_LAB = DefinitionId("base.facility.research_laboratory")
GRID_POWER_SUPPLY = DefinitionId("base.facility.grid_power_supply")
ORBITAL_LOGISTICS_NODE = DefinitionId("base.facility.orbital_logistics_node")
EARTH_LAUNCH_SUPPORT = DefinitionId("base.facility.earth_launch_support")
VEHICLE_ASSEMBLY_FACILITY = DefinitionId("base.facility.vehicle_assembly")
ROBOTIC_SURVEY_PACKAGE = DefinitionId("base.facility.robotic_survey_package")
SURFACE_POWER_GRID = DefinitionId("base.facility.surface_solar_power_grid")
INDUSTRIAL_POWER_BLOCK = DefinitionId("base.facility.fission_power_unit")
CONSTRUCTION_YARD = DefinitionId("base.facility.construction_yard")
VOLATILE_EXTRACTOR = DefinitionId("base.facility.volatile_extractor")
REGOLITH_HARVESTER = DefinitionId("base.facility.regolith_harvester")
WATER_STORAGE = DefinitionId("base.facility.water_storage")
CRYOGENIC_STORAGE = DefinitionId("base.facility.cryogenic_storage")
BULK_STORAGE = DefinitionId("base.facility.bulk_stockpile")
CARGO_WAREHOUSE = DefinitionId("base.facility.cargo_warehouse")
ELECTROLYSIS_PLANT = DefinitionId("base.facility.electrolysis")
PROPELLANT_PLANT = DefinitionId("base.facility.propellant_blending")
REGOLITH_SINTERING = DefinitionId("base.facility.regolith_sintering")
ORE_PROCESSING = DefinitionId("base.facility.ore_processing")
METALLURGY = DefinitionId("base.facility.metallurgy")
FABRICATION_WORKSHOP = DefinitionId("base.facility.fabrication_workshop")
MACHINE_SHOP = DefinitionId("base.facility.machine_shop")
HEAVY_EQUIPMENT_ASSEMBLY = DefinitionId("base.facility.heavy_equipment_assembly")

# Industrial processes are separately selectable from facility definitions.
PROCESS_ELECTROLYSIS = DefinitionId("base.process.water_electrolysis")
PROCESS_PROPELLANT_BLEND = DefinitionId("base.process.propellant_blending")
PROCESS_REGOLITH_SINTER = DefinitionId("base.process.regolith_sintering")
PROCESS_STRUCTURAL_FABRICATION = DefinitionId("base.process.structural_fabrication")
PROCESS_ORE_PROCESS = DefinitionId("base.process.ore_processing")
PROCESS_METALLURGY = DefinitionId("base.process.metallurgy")
PROCESS_BASIC_MACHINING = DefinitionId("base.process.basic_machining")
PROCESS_HEAVY_EQUIPMENT = DefinitionId("base.process.heavy_equipment_assembly")

# Research definitions can describe the current Earth-to-Moon progression, while
# the base game remains one continuous content namespace.
TECH_ORBITAL_OPERATIONS = DefinitionId("base.tech.orbital_operations")
TECH_CISLUNAR_LOGISTICS = DefinitionId("base.tech.cislunar_logistics")
TECH_LUNAR_PROSPECTING = DefinitionId("base.tech.lunar_prospecting")
TECH_VOLATILE_ISRU = DefinitionId("base.tech.volatile_isru")
TECH_LUNAR_MATERIALS = DefinitionId("base.tech.lunar_materials")
TECH_PROPELLANT_HANDLING = DefinitionId("base.tech.propellant_handling")

# Transport assets are reusable physical assets. Route eligibility is derived
# from performance and endpoint environment, not purpose/category labels.
REUSABLE_LAUNCH_VEHICLE = DefinitionId("base.vehicle.reusable_launch_vehicle")
REUSABLE_ORBITAL_CARGO_TUG = DefinitionId("base.vehicle.reusable_orbital_cargo_tug")
REUSABLE_SURFACE_CARGO_LANDER = DefinitionId("base.vehicle.reusable_surface_cargo_lander")

EARTH_LEO_LAUNCH_SERVICE = DefinitionId("base.transport_service.commercial_earth_launch")
LEO_LUNAR_SERVICE = DefinitionId("base.transport_service.commercial_orbital_transfer")
LUNAR_LANDING_SERVICE = DefinitionId("base.transport_service.commercial_vacuum_lander")
DIRECT_LUNAR_SERVICE = DefinitionId("base.transport_service.commercial_earth_lunar_direct")
