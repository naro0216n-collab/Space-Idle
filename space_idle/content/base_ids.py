from __future__ import annotations

from ..shared import CelestialBodyId, DefinitionId, SpatialNodeId, SurfaceCellId

STRUCTURAL_COMPONENTS = DefinitionId("base.resource.structural_components")
MACHINERY = DefinitionId("base.resource.machinery")
PRECISION_ELECTRONICS = DefinitionId("base.resource.precision_electronics")
BULK_STRUCTURE = DefinitionId("base.resource.bulk_structure")
FABRICATED_STRUCTURE = DefinitionId("base.resource.fabricated_structure")
BASIC_MACHINE_PARTS = DefinitionId("base.resource.basic_machine_parts")
CONSTRUCTION_EQUIPMENT = DefinitionId("base.resource.construction_equipment")
REGOLITH = DefinitionId("base.resource.regolith")
METAL_FEEDSTOCK = DefinitionId("base.resource.metal_feedstock")
AGGREGATE = DefinitionId("base.resource.aggregate")
METAL_ORE = DefinitionId("base.resource.metal_ore")
WATER = DefinitionId("base.resource.water")
OXYGEN = DefinitionId("base.resource.oxygen")
HYDROGEN = DefinitionId("base.resource.hydrogen")
PROPELLANT = DefinitionId("base.resource.chemical_propellant")

# ---------------------------------------------------------------------------
# Spatial content. Surface geography is separate from player-operated
# Locations; orbital/non-surface nodes remain SpatialNodeDef endpoints.
# ---------------------------------------------------------------------------
EARTH_BODY = CelestialBodyId("base.body.earth")
MOON = CelestialBodyId("base.body.moon")

# Player-operated/pre-existing economic Locations. These IDs continue to own
# Inventory/Facility/Fleet state, but are no longer static surface geography.
EARTH = SpatialNodeId("base.location.earth_industrial")
SOUTH_POLAR_RIDGE = SpatialNodeId("base.location.lunar_south_polar_ridge")
POLAR_COLD_TRAP = SpatialNodeId("base.location.lunar_polar_cold_trap")
NEARSIDE_MARE = SpatialNodeId("base.location.lunar_nearside_mare")

# Non-surface spatial nodes.
LEO = SpatialNodeId("base.node.low_earth_orbit")
LUNAR_ORBIT = SpatialNodeId("base.node.lunar_orbit")

# Surface Cell topology. Cell counts intentionally differ by body and the
# topology does not assume six neighbors.
EARTH_CELL_INDUSTRIAL = SurfaceCellId("base.cell.earth.industrial_core")
EARTH_CELL_COASTAL = SurfaceCellId("base.cell.earth.coastal")
EARTH_CELL_INLAND = SurfaceCellId("base.cell.earth.inland")

MOON_CELL_SOUTH_POLAR_RIDGE = SurfaceCellId("base.cell.moon.south_polar_ridge")
MOON_CELL_POLAR_COLD_TRAP = SurfaceCellId("base.cell.moon.polar_cold_trap")
MOON_CELL_SOUTH_POLAR_PLAIN = SurfaceCellId("base.cell.moon.south_polar_plain")
MOON_CELL_NEARSIDE_MARE = SurfaceCellId("base.cell.moon.nearside_mare")
MOON_CELL_EQUATORIAL_HIGHLANDS = SurfaceCellId("base.cell.moon.equatorial_highlands")
MOON_CELL_FARSIDE_HIGHLANDS = SurfaceCellId("base.cell.moon.farside_highlands")

# Construction project recipe IDs for geographic investment.
LOCATION_FOUNDATION_PROJECT = DefinitionId("base.construction.location_foundation")
SURFACE_CELL_DEVELOPMENT_PROJECT = DefinitionId("base.construction.surface_cell_development")

# ---------------------------------------------------------------------------
# Facilities. IDs and display names describe function, not placement.
# ---------------------------------------------------------------------------
EARTH_RESEARCH_LAB = DefinitionId("base.facility.research_laboratory")
EARTH_OBSERVATION_SATELLITE = DefinitionId("base.facility.earth_observation_satellite")
MICROGRAVITY_EXPERIMENT_PLATFORM = DefinitionId("base.facility.microgravity_experiment_platform")
CREWED_ORBITAL_LABORATORY = DefinitionId("base.facility.crewed_orbital_laboratory")
ROBOTIC_GEOLOGY_STATION = DefinitionId("base.facility.robotic_geology_station")
SAMPLE_ANALYSIS_LABORATORY = DefinitionId("base.facility.sample_analysis_laboratory")
VACUUM_REGOLITH_PROCESS_LABORATORY = DefinitionId("base.facility.vacuum_regolith_process_laboratory")
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
SURFACE_DISTRIBUTION_HUB = DefinitionId("base.facility.surface_distribution_hub")
ELECTROLYSIS_PLANT = DefinitionId("base.facility.electrolysis")
PROPELLANT_PLANT = DefinitionId("base.facility.propellant_blending")
REGOLITH_SINTERING = DefinitionId("base.facility.regolith_sintering")
ORE_PROCESSING = DefinitionId("base.facility.ore_processing")
METALLURGY = DefinitionId("base.facility.metallurgy")
FABRICATION_WORKSHOP = DefinitionId("base.facility.fabrication_workshop")
MACHINE_SHOP = DefinitionId("base.facility.machine_shop")
HEAVY_EQUIPMENT_ASSEMBLY = DefinitionId("base.facility.heavy_equipment_assembly")
SURFACE_AGGREGATE_QUARRY = DefinitionId("base.facility.surface_aggregate_quarry")
METAL_ORE_MINE = DefinitionId("base.facility.metal_ore_mine")
INDUSTRIAL_WATER_INTAKE = DefinitionId("base.facility.industrial_water_intake")
BASIC_STRUCTURAL_MATERIAL_PLANT = DefinitionId("base.facility.basic_structural_material_plant")
BASIC_MACHINERY_WORKS = DefinitionId("base.facility.basic_machinery_works")

# Industrial processes are separately selectable from facility definitions.
PROCESS_ELECTROLYSIS = DefinitionId("base.process.water_electrolysis")
PROCESS_PROPELLANT_BLEND = DefinitionId("base.process.propellant_blending")
PROCESS_REGOLITH_SINTER = DefinitionId("base.process.regolith_sintering")
PROCESS_STRUCTURAL_FABRICATION = DefinitionId("base.process.structural_fabrication")
PROCESS_ORE_PROCESS = DefinitionId("base.process.ore_processing")
PROCESS_METALLURGY = DefinitionId("base.process.metallurgy")
PROCESS_BASIC_MACHINING = DefinitionId("base.process.basic_machining")
PROCESS_HEAVY_EQUIPMENT = DefinitionId("base.process.heavy_equipment_assembly")
PROCESS_BASIC_STRUCTURAL_MATERIAL = DefinitionId("base.process.basic_structural_material")
PROCESS_BASIC_MACHINERY = DefinitionId("base.process.basic_machinery")

# Research IDs identify concrete engineering/science subjects. Progression is
# based on technical difficulty and experimental infrastructure rather than a
# location-labelled technology tier.
TECH_ORBITAL_OPERATIONS = DefinitionId("base.tech.orbital_operations")
TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS = DefinitionId("base.tech.microgravity_experiment_systems")
TECH_CISLUNAR_LOGISTICS = DefinitionId("base.tech.cislunar_logistics")
TECH_CREWED_ORBITAL_RESEARCH = DefinitionId("base.tech.crewed_orbital_research_systems")
TECH_LUNAR_PROSPECTING = DefinitionId("base.tech.lunar_prospecting")
TECH_ROBOTIC_FIELD_GEOLOGY = DefinitionId("base.tech.robotic_field_geology")
TECH_SAMPLE_ANALYSIS_SYSTEMS = DefinitionId("base.tech.surface_sample_analysis")
TECH_VACUUM_REGOLITH_PROCESS_RESEARCH = DefinitionId("base.tech.vacuum_regolith_process_control")
TECH_VOLATILE_ISRU = DefinitionId("base.tech.volatile_isru")
TECH_REGOLITH_EXCAVATION = DefinitionId("base.tech.regolith_excavation_granulometry")
TECH_LUNAR_MATERIALS = DefinitionId("base.tech.lunar_materials")
TECH_ORE_BENEFICIATION = DefinitionId("base.tech.vacuum_mineral_beneficiation")
TECH_HIGH_TEMPERATURE_METALLURGY = DefinitionId("base.tech.high_temperature_oxide_metallurgy")
TECH_STRUCTURAL_FABRICATION = DefinitionId("base.tech.vacuum_structural_fabrication")
TECH_PRECISION_MACHINING = DefinitionId("base.tech.low_gravity_precision_machining")
TECH_HEAVY_EQUIPMENT_ASSEMBLY = DefinitionId("base.tech.modular_heavy_equipment_assembly")
TECH_INDUSTRIAL_ELECTROLYSIS = DefinitionId("base.tech.industrial_water_electrolysis")
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

# Scientific Exploration campaigns are finite science activities, separate from resource survey.
CISLUNAR_SCIENCE_EXPLORATION = DefinitionId("base.scientific_exploration.cislunar_environment_observation")
