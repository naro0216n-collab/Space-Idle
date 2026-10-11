from __future__ import annotations

from ..power import FixedGeneration, PowerSpec, SolarGeneration
from . import base_ids as ids


def build_power_specs() -> dict:
    return {
        ids.THERMAL_HARDWARE_ASSEMBLY: PowerSpec(None, 1.35, standby_load_mw=0.09),
        ids.SHIELDING_PANEL_FABRICATION: PowerSpec(None, 0.85, standby_load_mw=0.07),
        ids.OPTICAL_INSTRUMENT_INTEGRATION: PowerSpec(None, 1.75, standby_load_mw=0.18),
        ids.ORBITAL_CONSTRUCTION_PLATFORM: PowerSpec(SolarGeneration(0.35 / 0.62, 1361.0), 0.15),
        ids.ORBITAL_SOLAR_ARRAY: PowerSpec(SolarGeneration(4.0 / 0.62, 1361.0), 0.04),
        # The tracking array trades more electronics, machinery and orbital
        # construction work for greater solar output. The reactor trades a
        # higher acquisition investment for generation independent of sunlight.
        ids.TRACKING_ORBITAL_SOLAR_ARRAY: PowerSpec(SolarGeneration(10.0 / 0.62, 1361.0), 0.09),
        ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER: PowerSpec(FixedGeneration(7.0), 0.20),
        ids.ORBITAL_PROPELLANT_DEPOT: PowerSpec(None, 0.20, standby_load_mw=0.20),
        # Active plasma discharge and beam calibration require a continuous high
        # voltage load; an unpowered test bench cannot qualify an experiment.
        # Control electronics and cryogenic circulation remain finite load;
        # an active reactor instrumentation source is separately required by
        # the technical Research stage, rather than implied by this building.
        ids.NUCLEAR_THERMAL_TEST_STAND: PowerSpec(None, 1.50, standby_load_mw=0.12),
        ids.PLASMA_PROPULSION_TEST_MODULE: PowerSpec(None, 1.65, standby_load_mw=0.08),
        ids.ORBITAL_MATERIALS_WORKSHOP: PowerSpec(None, 1.25, standby_load_mw=0.08),
        ids.ORBITAL_HEAVY_CARGO_TERMINAL: PowerSpec(None, 0.65, standby_load_mw=0.20),
        ids.ORBITAL_ASSEMBLY_YARD: PowerSpec(None, 0.95),
        ids.ORBITAL_HABITAT: PowerSpec(None, 0.55),
        ids.ORBITAL_HYDROPONICS: PowerSpec(None, 1.05, standby_load_mw=0.12),
        ids.ORBITAL_WATER_ELECTROLYSIS: PowerSpec(None, 1.65, standby_load_mw=0.10),
        ids.RESEARCH_DATA_ARCHIVE: PowerSpec(None, 0.60, standby_load_mw=0.38),
        ids.MATERIALS_FATIGUE_BEAMLINE: PowerSpec(None, 3.5, standby_load_mw=0.12),
        ids.ORBITAL_THERMAL_VACUUM_LAB: PowerSpec(None, 2.8, standby_load_mw=0.18),
        ids.BIOREGENERATIVE_BIOMEDICAL_LAB: PowerSpec(None, 2.2, standby_load_mw=0.32),
        ids.PROPULSION_TEST_FACILITY: PowerSpec(None, 0.45),
        ids.DEEP_SPACE_TRACKING_ARRAY: PowerSpec(None, 0.38),
        ids.SURFACE_ROVER_SERVICE_DEPOT: PowerSpec(None, 0.15),
        ids.GENERAL_RESEARCH_LAB: PowerSpec(None, 0.10),
        ids.BREATHABLE_SURFACE_LIFE_SUPPORT: PowerSpec(None, 0.04),
        # Improved water and oxygen autonomy is purchased with continuous
        # pumps, environmental control and higher installation investment.
        ids.BIOREGENERATIVE_GROWTH_MODULE: PowerSpec(None, 1.05, standby_load_mw=0.20),
        ids.VOLATILE_FRACTIONATION_PLANT: PowerSpec(None, 1.40, standby_load_mw=0.18),
        ids.CLOSED_CYCLE_HABITAT: PowerSpec(None, 1.15, standby_load_mw=0.42),
        ids.FOOD_FARM: PowerSpec(None, 0.14),
        ids.HABITAT: PowerSpec(None, 0.08),
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: PowerSpec(SolarGeneration(0.24 / 0.62, 1361.0), 0.10),
        ids.CREWED_ORBITAL_LABORATORY: PowerSpec(SolarGeneration(1.20 / 0.62, 1361.0), 0.65),
        ids.ROBOTIC_GEOLOGY_STATION: PowerSpec(SolarGeneration(0.28 / 0.78, 1361.0), 0.10),
        ids.SAMPLE_ANALYSIS_LABORATORY: PowerSpec(None, 0.40),
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: PowerSpec(None, 0.85),
        ids.SURFACE_LAUNCH_SUPPORT: PowerSpec(None, 0.08),
        ids.CARGO_LAUNCH_INTEGRATION_PAD: PowerSpec(None, 0.55, standby_load_mw=0.06),
        ids.VEHICLE_ASSEMBLY_FACILITY: PowerSpec(None, 0.18),
        ids.GRID_POWER_SUPPLY: PowerSpec(FixedGeneration(20.0), 0.0),
        ids.ORBITAL_FISSION_POWER: PowerSpec(FixedGeneration(0.6), 0.03),
        ids.ORBITAL_LOGISTICS_NODE: PowerSpec(SolarGeneration(0.35 / 0.62, 1361.0), 0.12),
        # On-board low-output autonomous power serves the deployment itself,
        # not an industrial base or a full-scale orbital reactor. Physical
        # Resource cost and maintenance are paid by the founding recipe.
        ids.AUTONOMOUS_SURFACE_OUTPOST: PowerSpec(FixedGeneration(0.12), 0.035),
        ids.AUTONOMOUS_ORBITAL_OUTPOST: PowerSpec(FixedGeneration(0.14), 0.045),
        ids.ROBOTIC_SURVEY_PACKAGE: PowerSpec(SolarGeneration(0.55 / 0.78, 1361.0), 0.08),
        ids.SURFACE_POWER_GRID: PowerSpec(SolarGeneration(1.0 / 0.78, 1361.0), 0.05),
        ids.INDUSTRIAL_POWER_BLOCK: PowerSpec(FixedGeneration(2.0), 0.05),
        ids.CONSTRUCTION_YARD: PowerSpec(None, 0.15),
        ids.VOLATILE_EXTRACTOR: PowerSpec(None, 0.20),
        ids.VOLATILE_PROCESSING: PowerSpec(None, 0.28),
        ids.VACUUM_MINERAL_HARVESTER: PowerSpec(None, 0.25),
        ids.WATER_STORAGE: PowerSpec(None, 0.01),
        ids.CRYOGENIC_STORAGE: PowerSpec(None, 0.06, standby_load_mw=0.06),
        ids.BULK_STORAGE: PowerSpec(None, 0.0),
        ids.CARGO_WAREHOUSE: PowerSpec(None, 0.02),
        ids.VACUUM_CARGO_HANDLING_TERMINAL: PowerSpec(None, 0.75, standby_load_mw=0.15),
        ids.SURFACE_DISTRIBUTION_HUB: PowerSpec(None, 0.08),
        ids.ELECTROLYSIS_PLANT: PowerSpec(None, 0.22),
        ids.PROPELLANT_PLANT: PowerSpec(None, 0.16),
        ids.CRYOGENIC_PROPELLANT_TERMINAL: PowerSpec(None, 1.20, standby_load_mw=0.35),
        ids.MINERAL_SINTERING: PowerSpec(None, 0.30),
        ids.ORE_PROCESSING: PowerSpec(None, 0.35),
        ids.METALLURGY: PowerSpec(None, 0.60),
        ids.FABRICATION_WORKSHOP: PowerSpec(None, 0.35),
        ids.MACHINE_SHOP: PowerSpec(None, 0.45),
        ids.HEAVY_EQUIPMENT_ASSEMBLY: PowerSpec(None, 0.55),
        ids.MINERAL_QUARRY: PowerSpec(None, 0.25),
        ids.METAL_ORE_MINE: PowerSpec(None, 0.30),
        ids.AUTONOMOUS_ORE_MINE: PowerSpec(None, 1.25),
        ids.CONTINUOUS_ORE_CONCENTRATOR: PowerSpec(None, 1.10),
        ids.CONTINUOUS_REDUCTION_FURNACE: PowerSpec(None, 2.10),
        ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE: PowerSpec(None, 1.45),
        ids.INDUSTRIAL_MACHINERY_ASSEMBLY: PowerSpec(None, 0.80),
        ids.MICROELECTRONICS_FAB: PowerSpec(None, 1.70),
        ids.MOLTEN_OXIDE_ELECTROLYZER: PowerSpec(None, 2.40),
        ids.INDUSTRIAL_WATER_INTAKE: PowerSpec(None, 0.18),
        ids.BASIC_STRUCTURAL_MATERIAL_PLANT: PowerSpec(None, 0.40),
        ids.BASIC_MACHINERY_WORKS: PowerSpec(None, 0.48),
    }
