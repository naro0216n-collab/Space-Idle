from __future__ import annotations

from dataclasses import dataclass

from .market import MarketInterfaceState
from .shared import CelestialBodyId, DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .supply import SupplyRoutingConstraintScope
from .spatial import OperationalNodeState
from .population import PopulationRules, ExternalPopulationSourceDefinition


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
    selected_extraction_method_id: DefinitionId | None = None


@dataclass(frozen=True)
class ScenarioStorageInfrastructure:
    operational_node_id: SpatialNodeId
    storage_pool_key: str
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
class ScenarioProviderFleetAssignment:
    """Initial provider use of real Fleet units; quantity remains owned by Fleet."""
    provider_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    vehicle_definition_id: DefinitionId
    units: int


@dataclass(frozen=True)
class ScenarioMarketInterface:
    id: EntityId
    provider_id: DefinitionId
    operational_node_id: SpatialNodeId
    enabled: bool = True


@dataclass(frozen=True)
class ScenarioSupplyRoutingConstraint:
    destination_id: SpatialNodeId
    owner_kind: str | None = None
    owner_id: EntityId | None = None
    resource_id: DefinitionId | None = None
    source_node_id: SpatialNodeId | None = None
    required_via_node_ids: tuple[SpatialNodeId, ...] = ()
    required_transport_allocation_ids: tuple[EntityId, ...] = ()


@dataclass(frozen=True)
class ScenarioPopulation:
    operational_node_id: SpatialNodeId
    count: int


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
    storage_infrastructure: tuple[ScenarioStorageInfrastructure, ...] = ()
    inventory_stock: tuple[ScenarioInventoryStock, ...] = ()
    fleet: tuple[ScenarioFleet, ...] = ()
    survey_fleet_assignments: tuple[ScenarioProviderFleetAssignment, ...] = ()
    research_fleet_assignments: tuple[ScenarioProviderFleetAssignment, ...] = ()
    known_surface_resources: tuple[tuple[SurfaceCellId, DefinitionId], ...] = ()
    completed_technologies: tuple[DefinitionId, ...] = ()
    funds_balance_musd: float = 0.0
    market_provider_ids: tuple[DefinitionId, ...] = ()
    market_interfaces: tuple[ScenarioMarketInterface, ...] = ()
    routing_constraints: tuple[ScenarioSupplyRoutingConstraint, ...] = ()
    initial_population: tuple[ScenarioPopulation, ...] = ()
    external_population_sources: tuple[ExternalPopulationSourceDefinition, ...] = ()
    population_rules: PopulationRules = PopulationRules(0.25, 0.05, 2.0, 3.0)

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

        for row in self.storage_infrastructure:
            sim.storage.set_infrastructure_capacity(row.operational_node_id, row.storage_pool_key, row.amount_t)
        initial_extraction_choices = []
        for row in self.facilities:
            facility_id = sim.facilities.install(
                row.definition_id,
                row.operational_node_id,
                site_cell_id=row.site_cell_id,
                invested_resources=dict(row.invested_resources),
            )
            if row.selected_extraction_method_id is not None:
                initial_extraction_choices.append((facility_id, row.selected_extraction_method_id))
        sim.refresh_storage()
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
        for facility_id, method_id in initial_extraction_choices:
            if sim.extraction is None:
                raise ValueError("Scenario has extraction choices without Extraction Domain")
            sim.extraction.set_method(sim.facilities.facilities[facility_id], method_id)
        if self.survey_fleet_assignments and sim.survey is None:
            raise ValueError("Scenario has Survey Fleet assignments without Survey Domain")
        for row in self.survey_fleet_assignments:
            sim.survey.set_provider_fleet_quantity(
                row.provider_definition_id,
                row.operational_node_id,
                row.vehicle_definition_id,
                row.units,
                day=sim.day,
            )

        for row in self.research_fleet_assignments:
            sim.research.set_provider_fleet_quantity(
                row.provider_definition_id,
                row.operational_node_id,
                row.vehicle_definition_id,
                row.units,
                day=sim.day,
            )

        sim.market.initialize_funds(self.funds_balance_musd)
        for provider_id in self.market_provider_ids:
            sim.market.initialize_provider_state(provider_id, day=sim.day)
        for row in self.market_interfaces:
            sim.market.set_interface(
                MarketInterfaceState(row.id, row.provider_id, row.operational_node_id, row.enabled)
            )
        for row in self.routing_constraints:
            sim.logistics.set_supply_routing_constraint(
                SupplyRoutingConstraintScope(
                    destination_id=row.destination_id,
                    owner_kind=row.owner_kind,
                    owner_id=row.owner_id,
                    resource_id=row.resource_id,
                ),
                source_node_id=row.source_node_id,
                required_via_node_ids=row.required_via_node_ids,
                required_transport_allocation_ids=row.required_transport_allocation_ids,
            )
        if sim.population is not None:
            for row in self.initial_population:
                sim.population.initialize(row.operational_node_id, row.count)
            sim.population.initialize_external_sources()
        sim.mark_runtime_state_initialized()
