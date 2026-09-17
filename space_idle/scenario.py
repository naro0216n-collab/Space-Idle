from __future__ import annotations

from dataclasses import dataclass

from .market import MarketInterfaceState
from .shared import CelestialBodyId, DefinitionId, EntityId, MovementPlanId, SpatialNodeId, SurfaceCellId
from .supply import PathSelectionMode, SourceSelectionMode
from .transport.models import PathPolicy
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
class ScenarioLogisticsPolicy:
    id: EntityId
    source_mode: SourceSelectionMode = SourceSelectionMode.ALLOW_ANY
    allowed_source_ids: tuple[SpatialNodeId, ...] = ()
    preferred_source_id: SpatialNodeId | None = None
    path_mode: PathSelectionMode = PathSelectionMode.ALLOW_ANY
    explicit_path: tuple[MovementPlanId, ...] = ()
    allowed_handoff_ids: tuple[SpatialNodeId, ...] = ()
    allowed_service_ids: tuple[str, ...] = ()
    path_preference: PathPolicy = PathPolicy.BALANCED
    global_policy: bool = False


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
    logistics_policies: tuple[ScenarioLogisticsPolicy, ...] = ()

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
        global_policy_id = None
        for row in self.logistics_policies:
            sim.logistics.create_logistics_policy(
                row.id,
                source_mode=row.source_mode,
                allowed_source_ids=None if not row.allowed_source_ids else tuple(row.allowed_source_ids),
                preferred_source_id=row.preferred_source_id,
                path_mode=row.path_mode,
                explicit_path=None if not row.explicit_path else tuple(row.explicit_path),
                allowed_handoff_ids=None if not row.allowed_handoff_ids else tuple(row.allowed_handoff_ids),
                allowed_service_ids=None if not row.allowed_service_ids else tuple(row.allowed_service_ids),
                path_preference=row.path_preference,
            )
            if row.global_policy:
                if global_policy_id is not None:
                    raise ValueError("scenario defines multiple global logistics policies")
                global_policy_id = row.id
        sim.logistics.set_global_logistics_policy(global_policy_id)
        sim.mark_runtime_state_initialized()
