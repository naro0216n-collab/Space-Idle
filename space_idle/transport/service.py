from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..facilities import FacilityBook
from ..inventory import InventoryBook
from ..power import PowerService
from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from ..technology import TechnologyState
from .compatibility import TransportCompatibilityMixin
from .fleet_allocations import FleetAllocationMixin
from .models import (
    ExternalTransportServiceDef,
    FleetPool,
    FleetRelocation,
    FleetRelease,
    FleetReservation,
    RouteDef,
    TransportAllocation,
    VehicleDef,
)
from .operations import OperationEvaluatorRegistry, build_default_operation_registry
from .production import VehicleProductionMixin, VehicleProductionState
from .surface_routes import SurfaceOrbitRouteRule, SurfaceTransportRouteRule
from .supply import TransportSupplyMixin


@dataclass
class TransportService(
    TransportCompatibilityMixin,
    FleetAllocationMixin,
    VehicleProductionMixin,
    TransportSupplyMixin,
):
    """Authoritative Fleet and Transport state owner.

    Logistics consumes capacity derived here but does not own or mutate Fleet
    commitments. Route/Vehicle definitions and vehicle production live with the
    same Transport/Fleet aggregate because they determine and change Fleet state.
    """

    routes: dict
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    vehicle_defs: dict[DefinitionId, VehicleDef] = field(default_factory=dict)
    external_services: dict[DefinitionId, ExternalTransportServiceDef] = field(default_factory=dict)
    operation_registry: OperationEvaluatorRegistry = field(default_factory=build_default_operation_registry)
    surface_route_rules: tuple[SurfaceTransportRouteRule, ...] = ()
    surface_orbit_route_rules: tuple[SurfaceOrbitRouteRule, ...] = ()
    fleet_pools: dict[tuple[DefinitionId, SpatialNodeId], FleetPool] = field(default_factory=dict)
    fleet_reservations: dict[EntityId, FleetReservation] = field(default_factory=dict)
    transport_allocations: dict[EntityId, TransportAllocation] = field(default_factory=dict)
    fleet_relocations: dict[EntityId, FleetRelocation] = field(default_factory=dict)
    fleet_releases: dict[EntityId, FleetRelease] = field(default_factory=dict)
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    vehicle_production_projects: dict[EntityId, VehicleProductionState] = field(default_factory=dict)
    _transport_allocation_counter: int = 0
    _fleet_relocation_counter: int = 0
    _fleet_release_counter: int = 0
    _vehicle_production_counter: int = 0

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed

    def vehicle_definition(self, vehicle_definition_id: DefinitionId) -> VehicleDef | None:
        """Return the immutable Vehicle definition through the Transport facade."""
        return self.vehicle_defs.get(vehicle_definition_id)

    def vehicle_definitions(self) -> tuple[VehicleDef, ...]:
        """Return immutable Vehicle definitions in deterministic order."""
        return tuple(sorted(self.vehicle_defs.values(), key=lambda row: str(row.id)))
    def route_definition(self, route_id: RouteId) -> RouteDef | None:
        """Return one immutable Route definition through the Transport facade."""
        return self.routes.get(route_id)

    def route_definitions(self) -> tuple[RouteDef, ...]:
        """Return immutable Route definitions in deterministic order."""
        return tuple(sorted(self.routes.values(), key=lambda row: str(row.id)))

    def external_transport_service_definition(
        self, service_id: DefinitionId
    ) -> ExternalTransportServiceDef | None:
        """Return one immutable external Transport service definition."""
        return self.external_services.get(service_id)

    def external_transport_service_definitions(
        self,
    ) -> tuple[ExternalTransportServiceDef, ...]:
        """Return immutable external Transport service definitions."""
        return tuple(sorted(self.external_services.values(), key=lambda row: str(row.id)))

    def fleet_pool_keys(self) -> tuple[tuple[DefinitionId, SpatialNodeId], ...]:
        """Return Fleet pool identities without exposing the mutable pool container."""
        return tuple(sorted(self.fleet_pools, key=lambda row: (str(row[0]), str(row[1]))))

    def transport_allocation_snapshot(
        self, allocation_id: EntityId
    ) -> TransportAllocation | None:
        """Return a detached snapshot of one mutable Transport allocation."""
        allocation = self.transport_allocations.get(allocation_id)
        return None if allocation is None else replace(allocation)

    def transport_allocation_snapshots(self) -> tuple[TransportAllocation, ...]:
        """Return detached Transport allocation snapshots in deterministic order."""
        return tuple(
            replace(row)
            for row in sorted(self.transport_allocations.values(), key=lambda row: str(row.id))
        )

    def fleet_relocation_snapshots(self) -> tuple[FleetRelocation, ...]:
        """Return detached Fleet relocation snapshots in deterministic order."""
        return tuple(
            replace(row)
            for row in sorted(self.fleet_relocations.values(), key=lambda row: str(row.id))
        )

    def fleet_release_snapshots(self) -> tuple[FleetRelease, ...]:
        """Return detached Fleet release snapshots in deterministic order."""
        return tuple(
            replace(row)
            for row in sorted(self.fleet_releases.values(), key=lambda row: str(row.id))
        )

    def vehicle_production_snapshots(self) -> tuple[VehicleProductionState, ...]:
        """Return detached Vehicle-production snapshots in deterministic order."""
        return tuple(
            replace(row)
            for row in sorted(
                self.vehicle_production_projects.values(), key=lambda row: str(row.id)
            )
        )
