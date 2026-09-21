from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from collections.abc import Callable

from ..facilities import FacilityBook
from ..facility_lifecycle import FacilityLifecycleBlocker
from ..inventory import InventoryBook
from ..power import PowerService
from ..service_capacity import ServiceCapacityRegistry
from ..shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId, SurfaceCellId
from ..technology import TechnologyState
from .compatibility import TransportCompatibilityMixin
from .fleet_allocations import FleetAllocationMixin
from .executions import MovementExecutionMixin
from .models import (
    DirectionalCapacity,
    FleetActivityRef,
    FleetPool,
    FleetRelocation,
    FleetRelease,
    FleetCommitmentState,
    MovementExecution,
    MovementPlan,
    TransportAllocation,
    TransportCapacitySnapshot,
    TransportOperationDependencyProjection,
    TransportOperationUsageRequirements,
    TransportServicePlan,
    TransportServiceSupply,
    VehicleDef,
)
from .operations import OperationEvaluatorRegistry, build_default_operation_registry
from .production import VehicleProductionMixin, VehicleProductionState
from .retirement import FleetRetirementMixin
from .models import FleetRetirementState
from .movement import MovementResolver, SpaceflightMovementRule, SurfaceAccessMovementRule, SurfaceTransportMovementRule
from .supply import TransportSupplyMixin


@dataclass
class TransportService(
    TransportCompatibilityMixin,
    MovementExecutionMixin,
    FleetAllocationMixin,
    FleetRetirementMixin,
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
    service_capacity_registry: ServiceCapacityRegistry
    vehicle_defs: dict[DefinitionId, VehicleDef] = field(default_factory=dict)
    operation_registry: OperationEvaluatorRegistry = field(default_factory=build_default_operation_registry)
    surface_movement_rules: tuple[SurfaceTransportMovementRule, ...] = ()
    surface_access_movement_rules: tuple[SurfaceAccessMovementRule, ...] = ()
    spaceflight_movement_rules: tuple[SpaceflightMovementRule, ...] = ()
    _movement_plan_cache: dict[MovementPlanId, MovementPlan] = field(default_factory=dict, repr=False)
    _movement_plan_options_cache: tuple[MovementPlan, ...] | None = field(default=None, repr=False)
    _movement_plan_outbound_index: dict[SpatialNodeId, tuple[MovementPlan, ...]] = field(
        default_factory=dict, init=False, repr=False
    )
    _movement_plan_inbound_index: dict[SpatialNodeId, tuple[MovementPlan, ...]] = field(
        default_factory=dict, init=False, repr=False
    )
    _projection_service_plan_cache: dict[tuple[object, ...], TransportServicePlan] | None = field(
        default=None, init=False, repr=False
    )
    _projection_service_supply_cache: dict[int, tuple[TransportServiceSupply, ...]] | None = field(
        default=None, init=False, repr=False
    )
    _projection_operation_dependency_cache: dict[int, tuple[TransportOperationDependencyProjection, ...]] | None = field(
        default=None, init=False, repr=False
    )
    _projection_capacity_snapshot_cache: dict[
        tuple[EntityId, int, DirectionalCapacity], TransportCapacitySnapshot
    ] | None = field(default=None, init=False, repr=False)
    _projection_operation_usage_cache: dict[
        tuple[EntityId, int, DirectionalCapacity], TransportOperationUsageRequirements
    ] | None = field(default=None, init=False, repr=False)
    _projection_cache_depth: int = field(default=0, init=False, repr=False)
    fleet_pools: dict[tuple[DefinitionId, SpatialNodeId], FleetPool] = field(default_factory=dict)
    fleet_commitments: dict[EntityId, FleetCommitmentState] = field(default_factory=dict)
    transport_allocations: dict[EntityId, TransportAllocation] = field(default_factory=dict)
    fleet_relocations: dict[EntityId, FleetRelocation] = field(default_factory=dict)
    movement_executions: dict[EntityId, MovementExecution] = field(default_factory=dict)
    fleet_releases: dict[EntityId, FleetRelease] = field(default_factory=dict)
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    vehicle_production_projects: dict[EntityId, VehicleProductionState] = field(default_factory=dict)
    fleet_retirements: dict[EntityId, FleetRetirementState] = field(default_factory=dict)
    _transport_allocation_counter: int = 0
    _fleet_relocation_counter: int = 0
    _fleet_release_counter: int = 0
    _vehicle_production_counter: int = 0
    _fleet_retirement_counter: int = 0
    _fleet_commitment_owner_resolvers: dict[str, Callable[[EntityId], bool]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        # Fleet owns exclusivity, while each activity Domain remains authoritative
        # for whether its owner State exists. Register existence resolvers instead
        # of encoding a closed purpose enum in Fleet State.
        self.register_fleet_commitment_owner_resolver(
            "transport_allocation", lambda owner_id: owner_id in self.transport_allocations
        )
        self.register_fleet_commitment_owner_resolver(
            "fleet_relocation", lambda owner_id: owner_id in self.fleet_relocations
        )
        self.register_fleet_commitment_owner_resolver(
            "fleet_release", lambda owner_id: owner_id in self.fleet_releases
        )
        self.register_fleet_commitment_owner_resolver(
            "fleet_retirement", lambda owner_id: owner_id in self.fleet_retirements
        )

    def register_fleet_commitment_owner_resolver(
        self, activity_type: str, resolver: Callable[[EntityId], bool]
    ) -> None:
        if not activity_type:
            raise ValueError("Fleet commitment owner activity type must be non-empty")
        if activity_type in self._fleet_commitment_owner_resolvers:
            raise ValueError(f"Fleet commitment owner resolver already registered: {activity_type}")
        self._fleet_commitment_owner_resolvers[activity_type] = resolver

    def fleet_commitment_owner_exists(self, owner: FleetActivityRef) -> bool:
        resolver = self._fleet_commitment_owner_resolvers.get(owner.activity_type)
        return False if resolver is None else bool(resolver(owner.activity_id))

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed

    def vehicle_definition(self, vehicle_definition_id: DefinitionId) -> VehicleDef | None:
        """Return the immutable Vehicle definition through the Transport facade."""
        return self.vehicle_defs.get(vehicle_definition_id)

    def vehicle_definitions(self) -> tuple[VehicleDef, ...]:
        """Return immutable Vehicle definitions in deterministic order."""
        return tuple(sorted(self.vehicle_defs.values(), key=lambda row: str(row.id)))

    def fleet_commitment(self, commitment_id: EntityId):
        """Return a Fleet commitment through the Transport-owned query boundary."""
        return self.fleet_commitments.get(commitment_id)

    def facility_decommission_blockers(
        self, facility_id: EntityId
    ) -> tuple[FacilityLifecycleBlocker, ...]:
        """Return durable Movement commitments that still require a gateway facility."""
        blockers: list[FacilityLifecycleBlocker] = []
        for execution in sorted(self.movement_executions.values(), key=lambda row: str(row.id)):
            if any(
                leg.origin.surface_interface_id == facility_id
                or leg.destination.surface_interface_id == facility_id
                for leg in execution.legs
            ):
                blockers.append(FacilityLifecycleBlocker("active_movement_commitment", str(execution.id)))
        return tuple(blockers)

    def movement_resolver(self) -> MovementResolver:
        return MovementResolver(
            self.facilities.environment.graph,
            self.facilities,
            surface_rules=self.surface_movement_rules,
            surface_access_rules=self.surface_access_movement_rules,
            spaceflight_rules=self.spaceflight_movement_rules,
        )

    @contextmanager
    def derived_projection_scope(self):
        """Reuse pure Transport derivations within one immutable physical projection.

        The cache is deliberately scoped to the caller's projection and is discarded
        afterwards.  It therefore removes repeated route/service derivation inside
        fixed-point allocation without turning derived state into a long-lived source
        of truth.
        """
        root_scope = self._projection_cache_depth == 0
        if root_scope:
            self._projection_service_plan_cache = {}
            self._projection_service_supply_cache = {}
            self._projection_operation_dependency_cache = {}
            self._projection_capacity_snapshot_cache = {}
            self._projection_operation_usage_cache = {}
        self._projection_cache_depth += 1
        try:
            yield
        finally:
            self._projection_cache_depth -= 1
            if root_scope:
                self._projection_service_plan_cache = None
                self._projection_service_supply_cache = None
                self._projection_operation_dependency_cache = None
                self._projection_capacity_snapshot_cache = None
                self._projection_operation_usage_cache = None

    def movement_plan_candidates(
        self, origin_id: SpatialNodeId, destination_id: SpatialNodeId
    ) -> tuple[MovementPlan, ...]:
        plans = self.movement_resolver().direct_plans(origin_id, destination_id)
        self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        return plans

    def movement_plans_to_physical_target(
        self, origin_id: SpatialNodeId, target_cell_id: SurfaceCellId
    ) -> tuple[MovementPlan, ...]:
        # Physical targets are not part of the regular Operational Node graph, so
        # retain only these ephemeral candidates long enough for one-shot owners
        # to validate/start them. Established-node plans are always re-derived.
        plans = self.movement_resolver().plans_to_physical_target(origin_id, target_cell_id)
        self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        return plans

    def movement_plans_to_non_surface_physical_target(
        self, origin_id: SpatialNodeId, target_node_id: SpatialNodeId
    ) -> tuple[MovementPlan, ...]:
        plans = self.movement_resolver().plans_to_non_surface_physical_target(origin_id, target_node_id)
        self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        return plans

    def movement_path_for_vehicle(
        self,
        origin_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        vehicle_definition_id: DefinitionId,
        *,
        day: int = 0,
        movement_hard_constraint: tuple[MovementPlanId, ...] | None = None,
        require_destination_disposition: bool = False,
    ) -> tuple[MovementPlan, ...]:
        path = self._movement_path_for_vehicle(
            origin_id,
            destination_id,
            vehicle_definition_id,
            day,
            movement_hard_constraint,
            require_destination_disposition=require_destination_disposition,
        )
        return tuple(self.require_movement_plan(plan_id) for plan_id in path)

    def movement_plan_to_physical_target_for_vehicle(
        self,
        origin_id: SpatialNodeId,
        target_cell_id: SurfaceCellId,
        vehicle_definition_id: DefinitionId,
        *,
        payload_t_per_unit: float = 0.0,
        day: int = 0,
        require_destination_disposition: bool = True,
    ) -> MovementPlan:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        vehicle = self.vehicle_defs[vehicle_definition_id]
        candidates = []
        for plan in self.movement_plans_to_physical_target(origin_id, target_cell_id):
            failures = self.vehicle_movement_physical_failures(
                plan.id, vehicle_definition_id, day
            )
            if failures:
                continue
            if vehicle.max_cargo_for_movement(plan) + 1e-9 < payload_t_per_unit:
                continue
            if (
                require_destination_disposition
                and vehicle.movement_asset_disposition(plan).value != "destination"
            ):
                continue
            candidates.append(plan)
        if not candidates:
            raise ValueError(
                f"no executable movement plan {origin_id} -> physical target {target_cell_id}"
            )
        from ..path_selection import select_canonical_candidate

        return select_canonical_candidate(
            candidates,
            metric_time=lambda plan: self.performance_movement_transit_days(
                plan, vehicle.performance
            ),
            metric_propellant=lambda plan: vehicle.propellant_t(
                plan, max(vehicle.max_cargo_for_movement(plan), 0.0)
            ),
            metric_handoffs=lambda _plan: 0.0,
            metric_capacity_burden=lambda plan: 1.0 / max(
                vehicle.max_cargo_for_movement(plan), 1.0e-12
            ),
            stable_key=lambda plan: str(plan.id),
        )

    def movement_plan_to_non_surface_physical_target_for_vehicle(
        self,
        origin_id: SpatialNodeId,
        target_node_id: SpatialNodeId,
        vehicle_definition_id: DefinitionId,
        *,
        payload_t_per_unit: float = 0.0,
        day: int = 0,
        require_destination_disposition: bool = True,
    ) -> MovementPlan:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        vehicle = self.vehicle_defs[vehicle_definition_id]
        candidates = []
        for plan in self.movement_plans_to_non_surface_physical_target(origin_id, target_node_id):
            failures = self.vehicle_movement_physical_failures(plan.id, vehicle_definition_id, day)
            if failures:
                continue
            if vehicle.max_cargo_for_movement(plan) + 1e-9 < payload_t_per_unit:
                continue
            if require_destination_disposition and vehicle.movement_asset_disposition(plan).value != "destination":
                continue
            candidates.append(plan)
        if not candidates:
            raise ValueError(f"no executable movement plan {origin_id} -> non-surface physical target {target_node_id}")
        from ..path_selection import select_canonical_candidate

        return select_canonical_candidate(
            candidates,
            metric_time=lambda plan: self.performance_movement_transit_days(
                plan, vehicle.performance
            ),
            metric_propellant=lambda plan: vehicle.propellant_t(
                plan, max(vehicle.max_cargo_for_movement(plan), 0.0)
            ),
            metric_handoffs=lambda _plan: 0.0,
            metric_capacity_burden=lambda plan: 1.0 / max(
                vehicle.max_cargo_for_movement(plan), 1.0e-12
            ),
            stable_key=lambda plan: str(plan.id),
        )

    def outbound_movement_plans(self, origin_id: SpatialNodeId) -> tuple[MovementPlan, ...]:
        cached = self._movement_plan_outbound_index.get(origin_id)
        if cached is not None:
            return cached
        plans = self.movement_resolver().outbound_plans(origin_id)
        self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        self._movement_plan_outbound_index[origin_id] = plans
        return plans

    def inbound_movement_plans(self, destination_id: SpatialNodeId) -> tuple[MovementPlan, ...]:
        cached = self._movement_plan_inbound_index.get(destination_id)
        if cached is not None:
            return cached
        plans = self.movement_resolver().inbound_plans(destination_id)
        self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        self._movement_plan_inbound_index[destination_id] = plans
        return plans

    def movement_plan(self, plan_id: MovementPlanId) -> MovementPlan | None:
        cached = self._movement_plan_cache.get(plan_id)
        if cached is not None:
            return cached
        # A plan id is a stable opaque hash and cannot be inverted back to its
        # endpoints.  Materialize the current direct-plan index at most once for
        # this physical state, then use O(1) lookup for every dependent query.
        self.movement_plan_options()
        return self._movement_plan_cache.get(plan_id)

    def movement_plan_options(self) -> tuple[MovementPlan, ...]:
        if self._movement_plan_options_cache is None:
            plans = self.movement_resolver().all_direct_plans()
            self._movement_plan_options_cache = plans
            self._movement_plan_cache.update((plan.id, plan) for plan in plans)
        return self._movement_plan_options_cache

    def require_movement_plan(self, plan_id: MovementPlanId) -> MovementPlan:
        plan = self.movement_plan(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        return plan

    def invalidate_movement_plans(self) -> None:
        """Drop derived Movement Plan indexes after physical/spatial state changes."""
        self._movement_plan_cache.clear()
        self._movement_plan_options_cache = None
        self._movement_plan_outbound_index.clear()
        self._movement_plan_inbound_index.clear()
        if self._projection_service_plan_cache is not None:
            self._projection_service_plan_cache.clear()
        if self._projection_service_supply_cache is not None:
            self._projection_service_supply_cache.clear()
        if self._projection_operation_dependency_cache is not None:
            self._projection_operation_dependency_cache.clear()
        if self._projection_capacity_snapshot_cache is not None:
            self._projection_capacity_snapshot_cache.clear()
        if self._projection_operation_usage_cache is not None:
            self._projection_operation_usage_cache.clear()

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
