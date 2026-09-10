from __future__ import annotations

from ..power import FixedGeneration, PowerSpec, SolarGeneration
from . import base_ids as ids


def build_power_specs() -> dict:
    return {
        ids.EARTH_RESEARCH_LAB: PowerSpec(None, 0.10, 80),
        ids.EARTH_OBSERVATION_SATELLITE: PowerSpec(SolarGeneration(0.08 / 0.62, 1361.0), 0.025, 95),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: PowerSpec(SolarGeneration(0.24 / 0.62, 1361.0), 0.10, 90),
        ids.CREWED_ORBITAL_LABORATORY: PowerSpec(SolarGeneration(1.20 / 0.62, 1361.0), 0.65, 90),
        ids.ROBOTIC_GEOLOGY_STATION: PowerSpec(SolarGeneration(0.28 / 0.78, 1361.0), 0.10, 85),
        ids.SAMPLE_ANALYSIS_LABORATORY: PowerSpec(None, 0.40, 75),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: PowerSpec(None, 0.85, 70),
        ids.EARTH_LAUNCH_SUPPORT: PowerSpec(None, 0.08, 85),
        ids.VEHICLE_ASSEMBLY_FACILITY: PowerSpec(None, 0.18, 55),
        ids.GRID_POWER_SUPPLY: PowerSpec(FixedGeneration(20.0), 0.0, 100),
        ids.ORBITAL_LOGISTICS_NODE: PowerSpec(SolarGeneration(0.35 / 0.62, 1361.0), 0.12, 90),
        ids.ROBOTIC_SURVEY_PACKAGE: PowerSpec(SolarGeneration(0.55 / 0.78, 1361.0), 0.08, 100),
        ids.SURFACE_POWER_GRID: PowerSpec(SolarGeneration(1.0 / 0.78, 1361.0), 0.05, 90),
        ids.INDUSTRIAL_POWER_BLOCK: PowerSpec(FixedGeneration(2.0), 0.05, 90),
        ids.CONSTRUCTION_YARD: PowerSpec(None, 0.15, 60),
        ids.VOLATILE_EXTRACTOR: PowerSpec(None, 0.20, 70),
        ids.REGOLITH_HARVESTER: PowerSpec(None, 0.25, 65),
        ids.WATER_STORAGE: PowerSpec(None, 0.01, 90),
        ids.CRYOGENIC_STORAGE: PowerSpec(None, 0.06, 95, 0.06),
        ids.BULK_STORAGE: PowerSpec(None, 0.0, 90),
        ids.CARGO_WAREHOUSE: PowerSpec(None, 0.02, 90),
        ids.ELECTROLYSIS_PLANT: PowerSpec(None, 0.22, 60),
        ids.PROPELLANT_PLANT: PowerSpec(None, 0.16, 55),
        ids.REGOLITH_SINTERING: PowerSpec(None, 0.30, 50),
        ids.ORE_PROCESSING: PowerSpec(None, 0.35, 50),
        ids.METALLURGY: PowerSpec(None, 0.60, 45),
        ids.FABRICATION_WORKSHOP: PowerSpec(None, 0.35, 45),
        ids.MACHINE_SHOP: PowerSpec(None, 0.45, 40),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: PowerSpec(None, 0.55, 40),
        ids.SURFACE_AGGREGATE_QUARRY: PowerSpec(None, 0.25, 45),
        ids.METAL_ORE_MINE: PowerSpec(None, 0.30, 45),
        ids.INDUSTRIAL_WATER_INTAKE: PowerSpec(None, 0.18, 50),
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: PowerSpec(None, 0.40, 40),
        ids.BASIC_MACHINERY_WORKS: PowerSpec(None, 0.48, 40),
    }
