from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..facilities import FacilityBook
from ..inventory import InventoryBook
from ..power import PowerService
from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId, SurfaceCellId
from ..technology import TechnologyState
from .compatibility import TransportCompatibilityMixin
from .fleet_allocations import FleetAllocationMixin
from .models import (
    ExternalTransportServiceDef,
    FleetPool,
    FleetRelocation,
    FleetRelease,
    FleetReservation,
    MovementPlan,
    TransportAllocation,
    VehicleDef,
)
from .operations import OperationEvaluatorRegistry, build_default_operation_registry
from .production import VehicleProductionMixin, VehicleProductionState
from .movement import MovementResolver, SpaceflightMovementRule, SurfaceAccessMovementRule, SurfaceTransportMovementRule
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
    commitments. Movement rules/Vehicle definitions and vehicle production live with the
    same Transport/Fleet aggregate because they determine and change Fleet state.
    """

    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    vehicle_defs: dict[DefinitionId, VehicleDef] = field(default_factory=dict)
    external_services: dict[DefinitionId, ExternalTransportServiceDef] = field(default_factory=dict)
    operation_registry: OperationEvaluatorRegistry = field(default_factory=build_default_operation_registry)
    surface_movement_rules: tuple[SurfaceTransportMovementRule, ...] = ()
    surface_access_movement_rules: tuple[SurfaceAccessMovementRule, ...] = ()
    spaceflight_movement_rules: tuple[SpaceflightMovementRule, ...] = ()
    _movement_plan_cache: dict[RouteId, MovementPlan] = field(default_factory=dict, repr=False)
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
    def movement_resolver(self) -> MovementResolver:
        return MovementResolver(
            self.facilities.environment.graph,
            self.facilities,
            surface_rules=self.surface_movement_rules,
            surface_access_rules=self.surface_access_movement_rules,
            spaceflight_rules=self.spaceflight_movement_rules,
        )

    def movement_plan_candidates(
        self, origin_id: SpatialNodeId, destination_id: SpatialNodeId
    ) -> tuple[MovementPlan, ...]:
        return self.movement_resolver().direct_plans(origin_id, destination_id)

    def movement_plans_to_physical_target(
        self, origin_id: SpatialNodeId, target_cell_id: SurfaceCellId
    ) -> tuple[MovementPlan, ...]:
        # Physical targets are not part of the regular Operational Node graph, so
        # retain only these ephemeral candidates long enough for one-shot owners
        # to validate/start them. Established-node plans are always re-derived.
        plans = self.movement_resolver().plans_to_physical_target(origin_id, target_cell_id)
        self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        return plans

    def outbound_movement_plans(self, origin_id: SpatialNodeId) -> tuple[MovementPlan, ...]:
        return self.movement_resolver().outbound_plans(origin_id)

    def movement_plan(self, plan_id: RouteId) -> MovementPlan | None:
        current = self.movement_resolver().plan_by_id(plan_id)
        if current is not None:
            return current
        return self._movement_plan_cache.get(plan_id)

    def movement_plan_options(self) -> tuple[MovementPlan, ...]:
        return self.movement_resolver().all_direct_plans()

    def require_movement_plan(self, plan_id: RouteId) -> MovementPlan:
        plan = self.movement_plan(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        return plan

    def invalidate_movement_plans(self) -> None:
        """Drop derived Movement Plan cache after physical/spatial state changes."""
        self._movement_plan_cache.clear()

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
