from __future__ import annotations

from dataclasses import dataclass

from .market import MarketInterfaceState
from .shared import CelestialBodyId, DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .spatial import OperationalNodeState


@dataclass(frozen=True)
class ScenarioSurfaceLocation:
    operational_node_id: SpatialNodeId
    display_name: str
    body_id: CelestialBodyId
    core_cell_id: SurfaceCellId


@dataclass(frozen=True)
class ScenarioFacility:
    definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    site_cell_id: SurfaceCellId | None = None
    invested_resources: tuple[tuple[DefinitionId, float], ...] = ()


@dataclass(frozen=True)
class ScenarioStorageCapacity:
    operational_node_id: SpatialNodeId
    storage_class: str
    amount_t: float


@dataclass(frozen=True)
class ScenarioInventoryStock:
    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float


@dataclass(frozen=True)
class ScenarioFleet:
    vehicle_definition_id: DefinitionId
    units: int
    operational_node_id: SpatialNodeId


@dataclass(frozen=True)
class ScenarioMarketInterface:
    id: EntityId
    provider_id: DefinitionId
    operational_node_id: SpatialNodeId
    enabled: bool = True


@dataclass(frozen=True)
class ScenarioDefinition:
    """Content-owned new-game state definition.

    The definition is not runtime state. ``apply`` transfers its values into the
    normal owner Domains exactly once for a new game. Load composition builds the
    same Domain definitions without calling this method and restores authoritative
    saved state instead.
    """

    id: str
    operational_node_ids: tuple[SpatialNodeId, ...] = ()
    surface_locations: tuple[ScenarioSurfaceLocation, ...] = ()
    facilities: tuple[ScenarioFacility, ...] = ()
    storage_capacities: tuple[ScenarioStorageCapacity, ...] = ()
    inventory_stock: tuple[ScenarioInventoryStock, ...] = ()
    fleet: tuple[ScenarioFleet, ...] = ()
    known_surface_resources: tuple[tuple[SurfaceCellId, DefinitionId], ...] = ()
    completed_technologies: tuple[DefinitionId, ...] = ()
    funds_balance_musd: float = 0.0
    market_provider_ids: tuple[DefinitionId, ...] = ()
    market_interfaces: tuple[ScenarioMarketInterface, ...] = ()

    def apply(self, sim) -> None:
        sim.require_uninitialized_runtime_state()

        for node_id in self.operational_node_ids:
            sim.graph.add_operational_node(OperationalNodeState(node_id))
        for location in self.surface_locations:
            sim.graph.found_location(
                location.operational_node_id,
                location.display_name,
                location.body_id,
                location.core_cell_id,
            )

        for row in self.storage_capacities:
            sim.inventory.add_capacity(row.operational_node_id, row.storage_class, row.amount_t)
        for row in self.facilities:
            sim.facilities.install(
                row.definition_id,
                row.operational_node_id,
                site_cell_id=row.site_cell_id,
                invested_resources=dict(row.invested_resources),
            )
        for row in self.inventory_stock:
            sim.inventory.add(row.operational_node_id, row.resource_id, row.amount_t)
        for row in self.fleet:
            sim.transport.add_fleet_units(
                row.vehicle_definition_id,
                row.units,
                row.operational_node_id,
                day=sim.day,
            )
        if sim.survey is not None:
            for cell_id, resource_id in self.known_surface_resources:
                sim.survey.initialize_known(cell_id, resource_id)
        sim.technology.replace(set(self.completed_technologies))

        sim.market.initialize_funds(self.funds_balance_musd)
        for provider_id in self.market_provider_ids:
            sim.market.initialize_provider_state(provider_id, day=sim.day)
        for row in self.market_interfaces:
            sim.market.set_interface(
                MarketInterfaceState(row.id, row.provider_id, row.operational_node_id, row.enabled)
            )
        sim.mark_runtime_state_initialized()
