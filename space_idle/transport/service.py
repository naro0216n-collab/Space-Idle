from __future__ import annotations

from dataclasses import dataclass, field

from ..facilities import FacilityBook
from ..inventory import InventoryBook
from ..power import PowerService
from ..shared import DefinitionId, EntityId, SpatialNodeId
from ..technology import TechnologyState
from .compatibility import TransportCompatibilityMixin
from .fleet_allocations import FleetAllocationMixin
from .models import (
    ExternalTransportServiceDef,
    FleetPool,
    FleetRelocation,
    FleetRelease,
    FleetReservation,
    TransportAllocation,
    VehicleDef,
)
from .operations import OperationEvaluatorRegistry, build_default_operation_registry
from .production import VehicleProductionMixin, VehicleProductionState
from .surface_routes import SurfaceOrbitRouteRule, SurfaceTransportRouteRule


@dataclass
class TransportService(
    TransportCompatibilityMixin,
    FleetAllocationMixin,
    VehicleProductionMixin,
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
