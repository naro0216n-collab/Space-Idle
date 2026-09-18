from __future__ import annotations

from ..scenario import (
    ScenarioDefinition,
    ScenarioFacility,
    ScenarioFleet,
    ScenarioInventoryStock,
    ScenarioMarketInterface,
    ScenarioLogisticsPolicy,
    ScenarioStorageInfrastructure,
    ScenarioSurfaceLocation,
)
from . import base_ids as ids
from .base_market import EARTH_MARKET_INTERFACE, EARTH_MARKET_PROVIDER
from ..shared import EntityId
from ..supply import SourceSelectionMode
from ..transport.models import PathPolicy

STANDARD_SCENARIO_ID = "base.scenario.standard"


def build_standard_scenario_definition() -> ScenarioDefinition:
    S, M, E = ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS
    facilities = (
        ScenarioFacility(ids.EARTH_RESEARCH_LAB, ids.EARTH, invested_resources=((S, 12.0), (M, 10.0), (E, 8.0))),
        ScenarioFacility(ids.EARTH_OBSERVATION_SATELLITE, ids.LEO, invested_resources=((S, 1.5), (M, 1.0), (E, 1.0))),
        ScenarioFacility(ids.LUNAR_RESOURCE_SURVEY_ORBITER, ids.LUNAR_ORBIT, invested_resources=((S, 1.5), (M, 1.0), (E, 1.5))),
        ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT, invested_resources=((S, 3.0), (M, 2.0), (E, 1.0))),
        ScenarioFacility(ids.GRID_POWER_SUPPLY, ids.EARTH, invested_resources=((S, 8.0), (M, 6.0))),
        ScenarioFacility(ids.EARTH_LAUNCH_SUPPORT, ids.EARTH, ids.EARTH_CELL_INDUSTRIAL, ((S, 10.0), (M, 8.0), (E, 2.0))),
        ScenarioFacility(ids.VEHICLE_ASSEMBLY_FACILITY, ids.EARTH, invested_resources=((S, 10.0), (M, 10.0), (E, 3.0))),
        ScenarioFacility(ids.SURFACE_AGGREGATE_QUARRY, ids.EARTH, invested_resources=((S, 5.0), (M, 7.0))),
        ScenarioFacility(ids.METAL_ORE_MINE, ids.EARTH, invested_resources=((S, 6.0), (M, 8.0))),
        ScenarioFacility(ids.INDUSTRIAL_WATER_INTAKE, ids.EARTH, invested_resources=((S, 5.0), (M, 5.0))),
        ScenarioFacility(ids.BASIC_STRUCTURAL_MATERIAL_PLANT, ids.EARTH, invested_resources=((S, 8.0), (M, 8.0))),
        ScenarioFacility(ids.BASIC_MACHINERY_WORKS, ids.EARTH, invested_resources=((S, 8.0), (M, 10.0), (E, 1.0))),
    )
    storage_infrastructure = (
        ScenarioStorageInfrastructure(ids.EARTH, "default", 100000.0),
        ScenarioStorageInfrastructure(ids.EARTH, "cryogenic", 100000.0),
        ScenarioStorageInfrastructure(ids.LEO, "default", 1000.0),
        ScenarioStorageInfrastructure(ids.LEO, "cryogenic", 120.0),
        ScenarioStorageInfrastructure(ids.LUNAR_ORBIT, "default", 1000.0),
        ScenarioStorageInfrastructure(ids.LUNAR_ORBIT, "cryogenic", 120.0),
    )
    inventory = (
        ScenarioInventoryStock(ids.EARTH, ids.STRUCTURAL_COMPONENTS, 120.0),
        ScenarioInventoryStock(ids.EARTH, ids.MACHINERY, 100.0),
        ScenarioInventoryStock(ids.EARTH, ids.PRECISION_ELECTRONICS, 70.0),
        ScenarioInventoryStock(ids.EARTH, ids.CONSTRUCTION_EQUIPMENT, 120.0),
        ScenarioInventoryStock(ids.EARTH, ids.WATER, 5000.0),
        ScenarioInventoryStock(ids.EARTH, ids.OXYGEN, 5000.0),
        ScenarioInventoryStock(ids.EARTH, ids.HYDROGEN, 2000.0),
        ScenarioInventoryStock(ids.EARTH, ids.PROPELLANT, 5000.0),
        ScenarioInventoryStock(ids.LEO, ids.STRUCTURAL_COMPONENTS, 1.0),
        ScenarioInventoryStock(ids.LEO, ids.MACHINERY, 1.0),
        ScenarioInventoryStock(ids.LEO, ids.PRECISION_ELECTRONICS, 1.0),
        ScenarioInventoryStock(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS, 1.0),
        ScenarioInventoryStock(ids.LUNAR_ORBIT, ids.MACHINERY, 1.0),
        ScenarioInventoryStock(ids.LUNAR_ORBIT, ids.PRECISION_ELECTRONICS, 1.0),
    )
    known = tuple(
        (cell_id, resource_id)
        for cell_id in (ids.EARTH_CELL_INDUSTRIAL, ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND)
        for resource_id in (ids.AGGREGATE, ids.METAL_ORE, ids.WATER)
    )
    return ScenarioDefinition(
        id=STANDARD_SCENARIO_ID,
        operational_node_ids=(ids.LEO, ids.LUNAR_ORBIT),
        surface_locations=(
            ScenarioSurfaceLocation(
                ids.EARTH, "地球産業拠点", ids.EARTH_BODY, ids.EARTH_CELL_INDUSTRIAL
            ),
        ),
        facilities=facilities,
        storage_infrastructure=storage_infrastructure,
        inventory_stock=inventory,
        fleet=(
            ScenarioFleet(ids.REUSABLE_LAUNCH_VEHICLE, 1, ids.EARTH),
            ScenarioFleet(ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO),
            ScenarioFleet(ids.REUSABLE_SURFACE_CARGO_LANDER, 1, ids.LUNAR_ORBIT),
        ),
        known_surface_resources=known,
        funds_balance_musd=1800.0,
        market_provider_ids=(EARTH_MARKET_PROVIDER,),
        market_interfaces=(
            ScenarioMarketInterface(
                EARTH_MARKET_INTERFACE, EARTH_MARKET_PROVIDER, ids.EARTH, True
            ),
        ),
        logistics_policies=(
            ScenarioLogisticsPolicy(
                EntityId("logistics.policy.standard"),
                source_mode=SourceSelectionMode.ALLOW_ANY,
                path_preference=PathPolicy.BALANCED,
                global_policy=True,
            ),
        ),
    )
