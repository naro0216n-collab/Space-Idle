from __future__ import annotations

from dataclasses import dataclass, field
import math

from .allocation_graph import AllocationDependency, allocation_dependency_order
from .contracts import ContractService
from .domain import DomainExtension
from .market import MarketBuyAllocationPlan, MarketService
from .facilities import FacilityBook
from .founding import LocationFoundingService
from .industry import IndustryService
from .inventory import InventoryBook
from .knowledge import DomainActivity
from .logistics import LogisticsService
from .transport.service import TransportService
from .transport.models import DirectionalCapacity
from .maintenance import FacilityMaintenanceService
from .power import PowerPhysicalSnapshot, PowerService, PowerSnapshot
from .projects import ProjectService
from .research import ResearchService
from .allocation_projection import ResourceAllocationProjection, ResourceAllocationProjectionRow
from .execution_requirements import (
    AllocationConstraintKey, AllocationIntent, ExecutionAllocation, ExecutionAllocationPlan,
    ExecutionRequirementBundle, PoolRequirement, ReservationAcquisitionRequirement,
    ResourceRequirement, ServiceCapacityRequirement, StockOrPoolAdmissionRequirement,
    admission_constraint, allocate_execution_requirements, pool_constraint, resource_constraint,
    service_constraint, service_pool_constraint, with_service_capacity_conservation,
)
from .service_capacity import (
    ServiceCapacityAllocation,
    ServiceCapacityAllocationPlan,
    ServiceCapacityDependency,
    ServiceCapacityProvider,
    ServiceCapacityRegistry,
    ServiceCapacityRequest,
    ServiceCapacityScope,
    allocate_service_capacity,
    merge_service_capacity_plans,
    service_capacity_dependency_order,
)
from .supply import (
    SupplyRequirement,
    resolve_local_supply,
    SupplyRequirementResolution,
)
from .shared import EntityId, SpatialNodeId
from .spatial import EnvironmentResolver, SpatialGraph
from .storage import StorageService
from .surface_infrastructure import SurfaceInfrastructureService
from .technology import TechnologyState
from .survey import ExtractionService, SurveyService
from .scientific_exploration import ScientificExplorationService
from .logistics_flow import LogisticsExecutionAllocation, LogisticsResourcePlan


@dataclass(frozen=True)
class OfflineProgressPolicy:
    """Maps elapsed real time to normal simulation days."""

    real_seconds_per_game_day: float
    max_game_days_per_resume: int | None = None

    def __post_init__(self) -> None:
        if self.real_seconds_per_game_day <= 0:
            raise ValueError("real_seconds_per_game_day must be positive")
        if self.max_game_days_per_resume is not None and self.max_game_days_per_resume < 0:
            raise ValueError("max_game_days_per_resume must be non-negative")


@dataclass(frozen=True)
class OfflineProgressResult:
    elapsed_real_seconds: float
    credited_game_days: float
    advanced_days: int
    pending_fractional_day: float
    capped: bool


@dataclass(frozen=True)
class TickPhysicalSnapshot:
    day: int
    ordered_locations: tuple[SpatialNodeId, ...]
    power_inputs_by_location: dict[SpatialNodeId, PowerPhysicalSnapshot]


@dataclass(frozen=True)
class TickIntents:
    supplys: tuple[SupplyRequirement, ...]
    execution_requirements: tuple[AllocationIntent, ...]


@dataclass(frozen=True)
class TickPlan:
    requirement_resolutions: tuple[SupplyRequirementResolution, ...]
    external_requirements: tuple[SupplyRequirement, ...]
    logistics: LogisticsResourcePlan


@dataclass(frozen=True)
class TickAllocations:
    market_buys: MarketBuyAllocationPlan
    logistics: LogisticsResourcePlan
    execution: ExecutionAllocationPlan
    resources: ResourceAllocationProjection
    power_by_location: dict[SpatialNodeId, PowerSnapshot]
    services: ServiceCapacityAllocationPlan
    transport: LogisticsExecutionAllocation


ALLOCATION_LOGISTICS = "logistics_authorization"
ALLOCATION_RESOURCES = "resources"
ALLOCATION_MAINTENANCE = "maintenance"
ALLOCATION_POWER = "power"
ALLOCATION_TRANSPORT = "transport"
SERVICE_NODE_PREFIX = "service:"


def _service_allocation_node(service_type: str) -> str:
    return SERVICE_NODE_PREFIX + service_type


@dataclass(frozen=True)
class TickDecisionProjection:
    snapshot: TickPhysicalSnapshot
    intents: TickIntents
    plan: TickPlan
    allocations: TickAllocations


@dataclass
class Simulation:
    day: int
    market: MarketService
    graph: SpatialGraph
    environment: EnvironmentResolver
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    storage: StorageService
    industry: IndustryService
    transport: TransportService
    logistics: LogisticsService
    projects: ProjectService
    technology: TechnologyState
    service_capacity_registry: ServiceCapacityRegistry
    founding: LocationFoundingService | None = None
    contracts: ContractService | None = None
    research: ResearchService | None = None
    survey: SurveyService | None = None
    extraction: ExtractionService | None = None
    scientific_exploration: ScientificExplorationService | None = None
    maintenance: FacilityMaintenanceService | None = None
    surface_infrastructure: SurfaceInfrastructureService | None = None
    content_id: str = "unconfigured"
    world_definition_id: str = "unconfigured"
    scenario_id: str = "unconfigured"
    pending_offline_game_days: float = 0.0
    domain_extensions: tuple[DomainExtension, ...] = ()
    _boundary_used_by_constraint: dict[AllocationConstraintKey, float] = field(default_factory=dict, init=False, repr=False)
    _initial_state_initialized: bool = field(default=False, init=False, repr=False)
    _boundary_settled_day: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # A freshly composed Simulation has not yet executed the day-0 boundary.
        # Composition finalization calls prepare_player_command(), after all
        # domains are attached, so externally visible state is always post-boundary.
        self._boundary_settled_day = self.day - 1

    @property
    def boundary_settled_day(self) -> int:
        return self._boundary_settled_day

    @property
    def runtime_state_initialized(self) -> bool:
        return self._initial_state_initialized

    def require_uninitialized_runtime_state(self) -> None:
        if self._initial_state_initialized:
            raise ValueError("initial runtime state has already been established")

    def mark_runtime_state_initialized(self) -> None:
        if self._initial_state_initialized:
            raise ValueError("initial runtime state has already been established")
        self._initial_state_initialized = True

    def restore_boundary_settled_day(self, day: int) -> None:
        if day != self.day:
            raise ValueError("saved canonical boundary does not match simulation day")
        self._boundary_settled_day = day

    def boundary_capacity_usage_snapshot(self) -> tuple[tuple[AllocationConstraintKey, float], ...]:
        """Authoritative same-day capacity already consumed at Boundary settlement."""
        return tuple(
            sorted(
                ((key, amount) for key, amount in self._boundary_used_by_constraint.items() if amount > 1e-12),
                key=lambda row: (row[0].kind, row[0].scope_id, row[0].name),
            )
        )

    def restore_boundary_capacity_usage(
        self, rows: tuple[tuple[AllocationConstraintKey, float], ...]
    ) -> None:
        restored: dict[AllocationConstraintKey, float] = {}
        for key, amount in rows:
            if key.kind not in {"service", "service_pool"}:
                raise ValueError("boundary capacity usage must reference Service constraints")
            if not math.isfinite(amount) or amount < -1e-9:
                raise ValueError("boundary capacity usage must be finite and non-negative")
            if key in restored:
                raise ValueError("duplicate boundary capacity usage constraint")
            if amount > 1e-12:
                restored[key] = amount
        self._boundary_used_by_constraint = restored

    def _ensure_current_boundary_settled(self) -> None:
        if self._boundary_settled_day == self.day:
            return
        if self._boundary_settled_day > self.day:
            raise RuntimeError("simulation boundary is ahead of canonical day")
        if self._boundary_settled_day != self.day - 1:
            raise RuntimeError("simulation has an unsettled canonical-day gap")
        self._settle_tick_boundary()
        self._boundary_settled_day = self.day

    def prepare_player_command(self) -> None:
        """Place Player Command application after Boundary settlement.

        Application Commands mutate authoritative intent/state only between ticks.
        Calling this is idempotent for the normal post-boundary resting state.
        """
        self._ensure_current_boundary_settled()

    def _active_locations(self) -> set[SpatialNodeId]:
        locations = {facility.operational_node_id for facility in self.facilities.facilities.values()}
        locations.update(project.operational_node_id for project in self.projects.projects.values())
        if self.founding is not None:
            locations.update(
                project.staging_node_id
                for project in self.founding.projects.values()
                if project.status.value in {"preparing", "deploying"}
            )
        if self.survey is not None:
            locations.update(campaign.provider_operational_node_id for campaign in self.survey.campaigns.values())
        locations.update(
            project.operational_node_id
            for project in self.transport.vehicle_production_snapshots()
        )
        if self.scientific_exploration is not None:
            for definition_id in self.scientific_exploration.campaigns:
                definition = self.scientific_exploration.definitions[definition_id]
                locations.add(definition.origin_id)
                locations.add(definition.destination_id)
        return locations

    def refresh_storage(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> None:
        if power_by_location is None:
            power_by_location = (
                self.tick_decision_projection().allocations.power_by_location
            )
        self.storage.refresh(self.day, power_by_location)

    def _gross_supplys(self) -> tuple[SupplyRequirement, ...]:
        """Collect pre-allocation physical need from every active Domain."""
        locations = self._active_locations()
        requirements: list[SupplyRequirement] = list(self.projects.supplys(self.day))
        requirements.extend(self.logistics.target_stock_requirements(self.day))
        if self.founding is not None:
            requirements.extend(self.founding.supplys())
        for location_id in sorted(locations, key=str):
            requirements.extend(
                self.industry.supplys(
                    location_id, self.facilities, self.inventory, self.day
                )
            )
        if self.research is not None:
            requirements.extend(self.research.supplys(self.day))
        if self.maintenance is not None:
            requirements.extend(self.maintenance.supplys(self.day))
        requirements.extend(self.transport.vehicle_production_supplys(self.day))
        requirements.extend(self.transport.fleet_relocation_supplys(self.day))
        if self.scientific_exploration is not None:
            requirements.extend(self.scientific_exploration.supplys(self.day))
        requirements.extend(self.market.sell_supply_requirements())
        seen: set[object] = set()
        for requirement in requirements:
            if requirement.id in seen:
                raise RuntimeError(f"duplicate supply requirement id: {requirement.id}")
            seen.add(requirement.id)
        return tuple(requirements)

    def supply_resolutions(self) -> tuple[SupplyRequirementResolution, ...]:
        """Return local/external Supply Requirement coverage from the shared tick plan."""
        return self.tick_decision_projection().plan.requirement_resolutions

    def supplys(self) -> tuple[SupplyRequirement, ...]:
        """Return off-site Supply Requirements from the shared tick plan."""
        return self.tick_decision_projection().plan.external_requirements

    def _execution_requirements(self) -> tuple[AllocationIntent, ...]:
        rows: list[AllocationIntent] = []
        rows.extend(self.projects.reservation_acquisition_requirements(self.day))
        rows.extend(self.projects.execution_requirement_bundles(self.day))
        if self.founding is not None:
            rows.extend(self.founding.execution_requirement_bundles(self.day))
        rows.extend(self.transport.vehicle_production_execution_requirement_bundles(self.day))
        rows.extend(self.transport.fleet_relocation_execution_requirement_bundles(self.day))
        if self.maintenance is not None:
            rows.extend(self.maintenance.execution_requirement_bundles(self.day))
        for location_id in sorted(self._active_locations(), key=str):
            rows.extend(
                self.industry.execution_requirement_bundles(
                    location_id, self.facilities, self.inventory, self.day
                )
            )
            if self.extraction is not None:
                rows.extend(
                    self.extraction.execution_requirement_bundles(
                        location_id, self.facilities, self.inventory, self.day
                    )
                )
        if self.research is not None:
            rows.extend(self.research.reservation_acquisition_requirements(self.day))
            rows.extend(self.research.execution_requirement_bundles(self.day))
        if self.survey is not None:
            rows.extend(self.survey.execution_requirement_bundles(self.day))
        if self.scientific_exploration is not None:
            rows.extend(
                self.scientific_exploration.reservation_acquisition_requirements(self.day)
            )
            rows.extend(self.scientific_exploration.execution_requirement_bundles(self.day))
        rows.extend(self.transport.fleet_retirement_execution_requirement_bundles(self.day))
        rows.extend(self.market.sell_execution_bundles())
        service_scopes = self.service_capacity_scopes()
        rows = [
            with_service_capacity_conservation(row, service_scopes)
            if isinstance(row, ExecutionRequirementBundle)
            else row
            for row in rows
        ]
        ids = [row.id for row in rows]
        if len(set(ids)) != len(ids):
            raise RuntimeError("duplicate execution requirement id")
        return tuple(rows)

    def service_capacity_dependencies(self) -> tuple[ServiceCapacityDependency, ...]:
        """Declare static same-tick Service Capacity provider dependencies."""
        surface = self.surface_infrastructure
        if surface is None:
            return ()
        return surface.provider_dependencies(
            self.service_capacity_providers(), self.facilities
        )

    def _service_provider_factors(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        resolved_plan: ServiceCapacityAllocationPlan,
        dependencies: tuple[ServiceCapacityDependency, ...],
    ) -> dict | None:
        surface = self.surface_infrastructure
        if surface is None:
            return None
        if not any(
            edge.service_type == service_type
            and edge.upstream_service_type == surface.service_type
            for edge in dependencies
        ):
            return None
        provider = self._service_capacity_provider(service_type)
        if provider is None:
            return None
        return surface.provider_availability_factors(
            location_id, service_type, provider, self.facilities, resolved_plan, self.day
        )

    def service_capacity_providers(self) -> tuple[ServiceCapacityProvider, ...]:
        """Return configured finite-service providers through Domain registration."""
        rows: list[ServiceCapacityProvider] = []
        for extension in self.domain_extensions:
            factory = extension.service_capacity_provider
            if factory is None:
                continue
            provider = factory(self)
            if provider is not None:
                rows.append(provider)
        return tuple(rows)

    def service_capacity_scopes(self) -> dict[str, ServiceCapacityScope]:
        scopes: dict[str, ServiceCapacityScope] = {}
        for provider in self.service_capacity_providers():
            for service_type in provider.service_capacity_types():
                scope = provider.service_capacity_scope(service_type)
                prior = scopes.get(service_type)
                if prior is not None and prior is not scope:
                    raise RuntimeError(f"mixed service capacity scopes for {service_type}")
                scopes[service_type] = scope
        return scopes

    def service_capacity_scope(self, service_type: str) -> ServiceCapacityScope:
        try:
            return self.service_capacity_scopes()[service_type]
        except KeyError as exc:
            raise KeyError(f"no service capacity provider for {service_type}") from exc

    def _service_capacity_provider(
        self, service_type: str
    ) -> ServiceCapacityProvider | None:
        return self.service_capacity_registry.provider_for(service_type)

    def _service_supply_at(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        power: PowerSnapshot,
        provider_factors: dict | None,
    ) -> tuple[float, float]:
        provider = self._service_capacity_provider(service_type)
        if provider is None:
            return (0.0, 0.0)
        return provider.service_capacity_supply_at(
            location_id,
            service_type,
            self.facilities,
            power,
            self.day,
            provider_factors=provider_factors,
        )

    def _service_allocation_types(
        self, requests: tuple[ServiceCapacityRequest, ...]
    ) -> tuple[str, ...]:
        service_types = {request.service_type for request in requests}
        for provider in self.service_capacity_providers():
            service_types.update(provider.service_capacity_types())
        return tuple(sorted(service_types))

    def _allocate_service_stage(
        self,
        service_type: str,
        *,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        requests: tuple[ServiceCapacityRequest, ...],
        resolved_plan: ServiceCapacityAllocationPlan,
        dependencies: tuple[ServiceCapacityDependency, ...],
    ) -> ServiceCapacityAllocationPlan:
        locations = tuple(
            sorted(
                self._active_locations() | set(self.graph.operational_node_ids()),
                key=str,
            )
        )
        stage_requests = tuple(
            request for request in requests if request.service_type == service_type
        )
        nominal: dict[tuple[SpatialNodeId, str], float] = {}
        enabled: dict[tuple[SpatialNodeId, str], float] = {}
        limiting: dict[tuple[SpatialNodeId, str], tuple[str, ...]] = {}
        requested_locations = {request.operational_node_id for request in stage_requests}
        for location_id in locations:
            power = power_by_location[location_id]
            provider_factors = self._service_provider_factors(
                location_id, service_type, resolved_plan, dependencies
            )
            nominal_rate, enabled_rate = self._service_supply_at(
                location_id, service_type, power, provider_factors
            )
            if (
                nominal_rate <= 1e-12
                and enabled_rate <= 1e-12
                and location_id not in requested_locations
            ):
                continue
            key = (location_id, service_type)
            nominal[key] = nominal_rate
            enabled[key] = enabled_rate
            factors: list[str] = []
            if nominal_rate <= 1e-12:
                if any(
                    request.operational_node_id == location_id
                    and request.requested_rate > 1e-12
                    for request in stage_requests
                ):
                    factors.append("provider_absent")
            elif enabled_rate + 1e-9 < nominal_rate:
                factors.append("provider_dependency")
            limiting[key] = tuple(factors)
        return allocate_service_capacity(
            stage_requests,
            nominal_supply=nominal,
            enabled_supply=enabled,
            limiting_factors=limiting,
        )

    def _allocate_tick_services(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        requests: tuple[ServiceCapacityRequest, ...] | None = None,
    ) -> ServiceCapacityAllocationPlan:
        """Standalone Service projection; normal ticks use the full DAG."""
        requests = self._complete_service_requests(() if requests is None else requests)
        service_types = self._service_allocation_types(requests)
        dependencies = self.service_capacity_dependencies()
        order = service_capacity_dependency_order(service_types, dependencies)
        plans: list[ServiceCapacityAllocationPlan] = []
        for service_type in order:
            plans.append(
                self._allocate_service_stage(
                    service_type,
                    power_by_location=power_by_location,
                    requests=requests,
                    resolved_plan=merge_service_capacity_plans(plans),
                    dependencies=dependencies,
                )
            )
        return merge_service_capacity_plans(plans)

    def service_capacity_allocation_projection(self) -> ServiceCapacityAllocationPlan:
        return self.tick_decision_projection().allocations.services

    def tick_decision_projection(self) -> TickDecisionProjection:
        """Project current intent, planning and allocation without mutation."""
        with self.transport.derived_projection_scope(), self.logistics.derived_projection_scope():
            snapshot = self._physical_tick_snapshot()
            intents = self._generate_tick_intents(snapshot)
            plan = self._plan_tick(intents)
            allocations = self._allocate_tick(snapshot, intents, plan)
            return TickDecisionProjection(snapshot, intents, plan, allocations)

    def resource_allocation_projection(self) -> ResourceAllocationProjection:
        """Derive the current shared Resource allocation without mutating state."""
        return self.tick_decision_projection().allocations.resources

    def advance_to_day(self, target_day: int) -> None:
        if target_day < self.day:
            raise ValueError("target day is in the past")
        self.advance_days(target_day - self.day)

    def advance_offline(
        self, elapsed_real_seconds: float, policy: OfflineProgressPolicy
    ) -> OfflineProgressResult:
        if elapsed_real_seconds < 0:
            raise ValueError("elapsed_real_seconds must be non-negative")
        raw_game_days = elapsed_real_seconds / policy.real_seconds_per_game_day
        capped = False
        if (
            policy.max_game_days_per_resume is not None
            and raw_game_days > policy.max_game_days_per_resume
        ):
            raw_game_days = float(policy.max_game_days_per_resume)
            capped = True
        credited = raw_game_days + self.pending_offline_game_days
        whole_days = math.floor(credited + 1e-12)
        self.pending_offline_game_days = max(0.0, credited - whole_days)
        if whole_days:
            self.advance_days(whole_days)
        return OfflineProgressResult(
            elapsed_real_seconds=elapsed_real_seconds,
            credited_game_days=credited,
            advanced_days=whole_days,
            pending_fractional_day=self.pending_offline_game_days,
            capped=capped,
        )

    def _settle_tick_boundary(self) -> None:
        """Settle prior physical obligations through the common finite constraints."""
        self._boundary_used_by_constraint = {}
        self.market.replenish_to_day(self.day)
        self.transport.advance_fleet_state(self.day)
        if self.scientific_exploration is not None:
            self.scientific_exploration.settle_movement_arrivals(self.day)
        if self.founding is not None and self.founding.settle_arrivals(self.day):
            self.transport.invalidate_movement_plans()

        # Policy assignment is Logistics-owned intent while owner lifecycle is
        # authoritative in each activity Domain. Boundary settlement completes
        # movement-driven owner transitions first, then prunes any assignment
        # whose owner no longer exists so no dangling reference survives the
        # externally observable resting boundary.
        self.logistics.prune_orphan_policy_assignments()

        self.logistics.prepare_cargo_arrivals(self.day)
        cargo_bundles = self.logistics.boundary_execution_bundles(self.day)
        buy_bundles = self.market.buy_boundary_bundles(self.day, self.inventory)
        bundles = cargo_bundles + buy_bundles
        if bundles:
            locations = self._active_locations() | set(self.graph.operational_node_ids())
            power_by_location = {
                location_id: self.power.resolve_snapshot(
                    self.power.physical_snapshot(location_id, self.facilities, self.day)
                )
                for location_id in locations
            }
            # Boundary obligations are consumers in the same common Execution
            # allocation below.  Derive provider supply/dependencies only here;
            # pre-allocating the same Cargo/Buy consumer as a Service request would
            # turn its own allocation into zero ``spare_rate`` and double-settle
            # the finite capacity.
            service_supply = self._allocate_tick_services(power_by_location, requests=())
            capacities = self._constraint_capacities(bundles, service_supply=service_supply)
            boundary_execution = allocate_execution_requirements(bundles, capacities)
            self._boundary_used_by_constraint = {
                key: amount for key, amount in boundary_execution.used_by_constraint.items()
                if key.kind in {"service", "service_pool"} and amount > 1e-12
            }
            self.logistics.settle_cargo_boundary_execution(self.day, boundary_execution)
            self.market.settle_matured_buys(self.day, boundary_execution, self.inventory)

        # Project procurement is an internal durable reservation lifecycle unrelated
        # to the External Resource Market. Its clock maturation remains boundary-owned.
        self.projects.advance_procurement(self.day)

    def _physical_tick_snapshot(self) -> TickPhysicalSnapshot:
        locations = self._active_locations() | set(self.graph.operational_node_ids())
        ordered_locations = tuple(sorted(locations, key=str))
        power_inputs = {
            location_id: self.power.physical_snapshot(
                location_id, self.facilities, self.day
            )
            for location_id in ordered_locations
        }
        return TickPhysicalSnapshot(self.day, ordered_locations, power_inputs)

    def _generate_tick_intents(self, snapshot: TickPhysicalSnapshot) -> TickIntents:
        return TickIntents(
            supplys=self._gross_supplys(),
            execution_requirements=self._execution_requirements(),
        )

    def _plan_tick(self, intents: TickIntents) -> TickPlan:
        requirement_resolutions = resolve_local_supply(
            intents.supplys, self.inventory
        )
        external_requirements = self.logistics.active_shipping_requirements(
            self.day, intents.supplys
        )
        logistics_plan = self.logistics.plan_capacity_logistics(
            self.day, external_requirements
        )
        return TickPlan(requirement_resolutions, external_requirements, logistics_plan)

    def service_capacity_request_providers(self) -> tuple[object, ...]:
        """Return composed owners of root finite-Service demand."""
        rows: list[object] = []
        for extension in self.domain_extensions:
            factory = extension.service_capacity_request_provider
            if factory is None:
                continue
            provider = factory(self)
            if provider is not None:
                rows.append(provider)
        return tuple(rows)

    def service_capacity_root_requests(self) -> tuple[ServiceCapacityRequest, ...]:
        rows: list[ServiceCapacityRequest] = []
        seen: set[object] = set()
        for provider in self.service_capacity_request_providers():
            for request in provider.service_capacity_requests(self.day):
                if request.id in seen:
                    raise RuntimeError(f"duplicate root service capacity request id: {request.id}")
                seen.add(request.id)
                rows.append(request)
        return tuple(rows)

    def _complete_service_requests(
        self, requests: tuple[ServiceCapacityRequest, ...]
    ) -> tuple[ServiceCapacityRequest, ...]:
        rows = list(requests)
        by_id = {request.id: request for request in rows}
        if len(by_id) != len(rows):
            raise RuntimeError("duplicate service capacity request id")
        for request in self.service_capacity_root_requests():
            prior = by_id.get(request.id)
            if prior is None:
                rows.append(request)
                by_id[request.id] = request
            elif prior != request:
                raise RuntimeError(f"conflicting service capacity request id: {request.id}")
        return tuple(rows)

    def allocation_pool_providers(self) -> tuple[object, ...]:
        """Return composed owners of finite non-Resource allocation pools."""
        rows: list[object] = []
        for extension in self.domain_extensions:
            factory = extension.allocation_pool_provider
            if factory is None:
                continue
            provider = factory(self)
            if provider is not None:
                rows.append(provider)
        return tuple(rows)

    def allocation_pool_capacities(
        self,
        overrides: dict[AllocationConstraintKey, float] | None = None,
    ) -> dict[AllocationConstraintKey, float]:
        """Collect finite allocation pools from composed Domain providers."""
        capacities: dict[AllocationConstraintKey, float] = {}
        for provider in self.allocation_pool_providers():
            for key, amount in provider.allocation_pool_capacities(self.day).items():
                if key in capacities:
                    raise RuntimeError(f"duplicate allocation pool capacity: {key}")
                capacities[key] = amount
        for key, amount in (overrides or {}).items():
            if key not in capacities:
                raise RuntimeError(f"allocation pool override has no registered owner: {key}")
            capacities[key] = amount
        return capacities

    @staticmethod
    def _as_execution_bundle(intent: AllocationIntent) -> ExecutionRequirementBundle:
        return intent.as_bundle() if isinstance(intent, ReservationAcquisitionRequirement) else intent

    def _constraint_capacities(
        self,
        intents: tuple[AllocationIntent | ExecutionRequirementBundle, ...],
        *,
        resource_used: dict[AllocationConstraintKey, float] | None = None,
        service_supply: ServiceCapacityAllocationPlan | None = None,
        pool_capacity_overrides: dict[AllocationConstraintKey, float] | None = None,
    ) -> dict[AllocationConstraintKey, float]:
        bundles = tuple(self._as_execution_bundle(row) for row in intents)
        resource_used = resource_used or {}
        pool_capacities = self.allocation_pool_capacities(pool_capacity_overrides)
        capacities: dict[AllocationConstraintKey, float] = {}
        for bundle in bundles:
            for requirement in bundle.requirements:
                if isinstance(requirement, ServiceCapacityRequirement):
                    keys = requirement.constraint_keys(bundle.operational_node_id)
                    for key in keys:
                        if key in capacities:
                            continue
                        if service_supply is None:
                            capacities[key] = 0.0
                            continue
                        if key.kind == "service":
                            node_id = requirement.constraint_node(bundle.operational_node_id)
                            capacities[key] = max(
                                0.0,
                                service_supply.summary(node_id, requirement.service_type).spare_rate
                                - self._boundary_used_by_constraint.get(key, 0.0),
                            )
                            continue
                        if (
                            requirement.scope is ServiceCapacityScope.ORGANIZATION
                            and self.service_capacity_scope(requirement.service_type)
                            is not ServiceCapacityScope.ORGANIZATION
                        ):
                            capacities[key] = 0.0
                            continue
                        capacities[key] = max(
                            0.0,
                            math.fsum(
                                max(0.0, service_supply.summary(node_id, requirement.service_type).spare_rate)
                                for node_id, service_type in service_supply.supply_enabled
                                if service_type == requirement.service_type
                            ) - self._boundary_used_by_constraint.get(key, 0.0),
                        )
                    continue

                key = requirement.constraint_key(bundle.operational_node_id)
                if key in capacities:
                    continue
                if isinstance(requirement, ResourceRequirement):
                    node_id = requirement.constraint_node(bundle.operational_node_id)
                    capacities[key] = max(
                        0.0,
                        self.inventory.available(node_id, requirement.resource_id)
                        - resource_used.get(key, 0.0),
                    )
                elif isinstance(requirement, StockOrPoolAdmissionRequirement):
                    if bundle.operational_node_id is None:
                        raise ValueError("stock/admission requirement requires an Operational Node")
                    state = self.inventory.admission_state_for_class(
                        bundle.operational_node_id, requirement.pool_id
                    )
                    capacities[key] = state.admission_capacity_t or 0.0
                elif isinstance(requirement, PoolRequirement):
                    if key not in pool_capacities:
                        raise KeyError(f"no allocation pool owner for {key}")
                    capacities[key] = pool_capacities[key]
                else:
                    raise TypeError(f"unknown execution requirement: {type(requirement)!r}")
        return capacities

    @staticmethod
    def _resource_projection_from_execution(
        execution: ExecutionAllocationPlan,
    ) -> tuple[ResourceAllocationProjectionRow, ...]:
        """Project physical Resource usage from authoritative root Bundles."""
        rows: list[ResourceAllocationProjectionRow] = []
        for bundle in execution.bundles:
            if bundle.owner_kind == "logistics_dispatch":
                continue
            requirements = tuple(
                requirement
                for requirement in bundle.requirements
                if isinstance(requirement, ResourceRequirement)
                and requirement.amount_per_execution > 1e-12
            )
            allocated_execution = execution.allocated(bundle.id)
            for index, requirement in enumerate(requirements):
                node_id = requirement.constraint_node(bundle.operational_node_id)
                requested = bundle.requested_execution * requirement.amount_per_execution
                allocated = allocated_execution * requirement.amount_per_execution
                rows.append(
                    ResourceAllocationProjectionRow(
                        EntityId(
                            f"allocation.resource:{bundle.id}:{index}:{node_id}:{requirement.resource_id}"
                        ),
                        node_id,
                        requirement.resource_id,
                        bundle.owner_kind,
                        bundle.owner_id,
                        bundle.purpose,
                        bundle.priority,
                        requested,
                        min(requested, max(0.0, allocated)),
                        minimum_amount=(
                            bundle.minimum_execution * requirement.amount_per_execution
                        ),
                        atomic=bundle.atomic,
                    )
                )
        return tuple(rows)

    @staticmethod
    def _service_projection_requests_from_execution(
        execution: ExecutionAllocationPlan,
    ) -> tuple[tuple[ServiceCapacityRequest, ...], dict[EntityId, float]]:
        """Adapt node-scoped Bundle Service constraints for reporting only."""
        requests: list[ServiceCapacityRequest] = []
        overrides: dict[EntityId, float] = {}
        for bundle in execution.bundles:
            if bundle.owner_kind == "logistics_dispatch":
                continue
            for index, requirement in enumerate(bundle.requirements):
                if not isinstance(requirement, ServiceCapacityRequirement):
                    continue
                if requirement.scope is not ServiceCapacityScope.OPERATIONAL_NODE:
                    continue
                if requirement.amount_per_execution <= 1e-12:
                    continue
                node_id = requirement.constraint_node(bundle.operational_node_id)
                request_id = EntityId(
                    f"projection.service:{bundle.id}:{index}:{node_id}:{requirement.service_type}"
                )
                requested = bundle.requested_execution * requirement.amount_per_execution
                allocated = execution.allocated(bundle.id) * requirement.amount_per_execution
                requests.append(ServiceCapacityRequest(
                    request_id,
                    node_id,
                    requirement.service_type,
                    requested,
                    bundle.priority,
                    bundle.owner_kind,
                    bundle.owner_id,
                    bundle.purpose,
                ))
                overrides[request_id] = allocated
        return tuple(requests), overrides

    @staticmethod
    def _service_plan_from_execution(
        requests: tuple[ServiceCapacityRequest, ...],
        execution: ExecutionAllocationPlan,
        provider_plan: ServiceCapacityAllocationPlan,
        allocation_overrides: dict[EntityId, float] | None = None,
    ) -> ServiceCapacityAllocationPlan:
        allocation_overrides = allocation_overrides or {}
        provider_ids = {request.id for request in provider_plan.requests}
        consumer_requests = tuple(request for request in requests if request.id not in provider_ids)
        allocations = list(provider_plan.allocations)
        for request in consumer_requests:
            if request.id in allocation_overrides:
                amount = allocation_overrides[request.id]
            else:
                try:
                    amount = execution.allocated(request.id)
                except KeyError:
                    amount = 0.0
            amount = min(request.requested_rate, max(0.0, amount))
            allocations.append(ServiceCapacityAllocation(
                request.id, request.requested_rate, amount,
                max(0.0, request.requested_rate - amount),
            ))
        return ServiceCapacityAllocationPlan(
            provider_plan.requests + consumer_requests,
            tuple(allocations),
            provider_plan.supply_nominal,
            provider_plan.supply_enabled,
            provider_plan.supply_limiting_factors,
        )

    @staticmethod
    def _directional_capacity_delta(
        left: DirectionalCapacity,
        right: DirectionalCapacity,
    ) -> float:
        values = (
            (left.forward_t_per_day, right.forward_t_per_day),
            (left.reverse_t_per_day, right.reverse_t_per_day),
        )
        return max(
            (abs(a - b) / max(1.0, abs(a), abs(b)) for a, b in values),
            default=0.0,
        )

    def _resolve_transport_execution_fixed_point(
        self,
        day: int,
        logistics_plan: LogisticsResourcePlan,
        static_intents: tuple[AllocationIntent | ExecutionRequirementBundle, ...],
        provider_plan: ServiceCapacityAllocationPlan,
        all_service_requests: tuple[ServiceCapacityRequest, ...],
    ) -> tuple[
        ExecutionAllocationPlan,
        dict[EntityId, DirectionalCapacity],
        dict[EntityId, DirectionalCapacity],
        dict[EntityId, float],
        dict[EntityId, tuple[str, ...]],
    ]:
        """Resolve Cargo and Fleet operation inputs through one allocation graph."""
        dependencies = self.transport.transport_operation_dependencies(day)
        surface_factors = {row.allocation_id: 1.0 for row in dependencies}
        reference_usage = dict(logistics_plan.planned_usage)
        tolerance = 1e-8
        damping = 0.5

        def resolve(reference, surface):
            dispatch_intents = self.logistics.dispatch_execution_requirements(
                day, logistics_plan, reference
            )
            allocation_intents = static_intents + dispatch_intents
            capacities = self._constraint_capacities(
                allocation_intents,
                service_supply=provider_plan,
                pool_capacity_overrides=self.logistics.allocation_pool_capacities(
                    day, surface
                ),
            )
            execution = allocate_execution_requirements(allocation_intents, capacities)
            provisional_services = self._service_plan_from_execution(
                all_service_requests, execution, provider_plan
            )
            next_surface, surface_limits = self.logistics.transport_surface_availability(
                day, provisional_services
            )
            actual_usage = self.logistics.dispatch_usage_from_execution(
                logistics_plan, execution
            )
            return execution, actual_usage, next_surface, surface_limits

        for _ in range(64):
            execution, actual_usage, next_surface, surface_limits = resolve(
                reference_usage, surface_factors
            )
            allocation_ids = (
                set(reference_usage)
                | set(actual_usage)
                | set(surface_factors)
                | set(next_surface)
            )
            usage_delta = max(
                (
                    self._directional_capacity_delta(
                        reference_usage.get(allocation_id, DirectionalCapacity()),
                        actual_usage.get(allocation_id, DirectionalCapacity()),
                    )
                    for allocation_id in allocation_ids
                ),
                default=0.0,
            )
            surface_delta = max(
                (
                    abs(
                        surface_factors.get(allocation_id, 1.0)
                        - next_surface.get(allocation_id, 1.0)
                    )
                    for allocation_id in allocation_ids
                ),
                default=0.0,
            )
            if max(usage_delta, surface_delta) <= tolerance:
                verified_reference = dict(actual_usage)
                verified_surface = dict(next_surface)
                verified_execution, verified_usage, verified_next_surface, verified_limits = (
                    resolve(verified_reference, verified_surface)
                )
                verify_ids = (
                    set(verified_reference)
                    | set(verified_usage)
                    | set(verified_surface)
                    | set(verified_next_surface)
                )
                verify_usage_delta = max(
                    (
                        self._directional_capacity_delta(
                            verified_reference.get(allocation_id, DirectionalCapacity()),
                            verified_usage.get(allocation_id, DirectionalCapacity()),
                        )
                        for allocation_id in verify_ids
                    ),
                    default=0.0,
                )
                verify_surface_delta = max(
                    (
                        abs(
                            verified_surface.get(allocation_id, 1.0)
                            - verified_next_surface.get(allocation_id, 1.0)
                        )
                        for allocation_id in verify_ids
                    ),
                    default=0.0,
                )
                if max(verify_usage_delta, verify_surface_delta) <= tolerance:
                    return (
                        verified_execution,
                        verified_usage,
                        verified_reference,
                        verified_next_surface,
                        verified_limits,
                    )

            reference_usage = {
                allocation_id: DirectionalCapacity(
                    damping
                    * reference_usage.get(
                        allocation_id, DirectionalCapacity()
                    ).forward_t_per_day
                    + (1.0 - damping)
                    * actual_usage.get(
                        allocation_id, DirectionalCapacity()
                    ).forward_t_per_day,
                    damping
                    * reference_usage.get(
                        allocation_id, DirectionalCapacity()
                    ).reverse_t_per_day
                    + (1.0 - damping)
                    * actual_usage.get(
                        allocation_id, DirectionalCapacity()
                    ).reverse_t_per_day,
                )
                for allocation_id in sorted(allocation_ids, key=str)
            }
            surface_factors = dict(next_surface)

        raise RuntimeError("transport operation requirement attribution did not converge")

    def tick_allocation_dependencies(
        self, service_types: tuple[str, ...] | set[str]
    ) -> tuple[AllocationDependency, ...]:
        """Return the explicit same-tick cross-Domain allocation DAG."""
        service_types = tuple(sorted(set(service_types)))
        dependencies: list[AllocationDependency] = [
            AllocationDependency(ALLOCATION_RESOURCES, ALLOCATION_LOGISTICS),
            AllocationDependency(ALLOCATION_MAINTENANCE, ALLOCATION_RESOURCES),
            AllocationDependency(ALLOCATION_POWER, ALLOCATION_MAINTENANCE),
            AllocationDependency(ALLOCATION_TRANSPORT, ALLOCATION_LOGISTICS),
            AllocationDependency(ALLOCATION_TRANSPORT, ALLOCATION_RESOURCES),
        ]
        for service_type in service_types:
            node = _service_allocation_node(service_type)
            dependencies.append(AllocationDependency(node, ALLOCATION_POWER))
            dependencies.append(AllocationDependency(node, ALLOCATION_LOGISTICS))
            dependencies.append(AllocationDependency(ALLOCATION_TRANSPORT, node))
        for edge in self.service_capacity_dependencies():
            dependencies.append(
                AllocationDependency(
                    _service_allocation_node(edge.service_type),
                    _service_allocation_node(edge.upstream_service_type),
                )
            )
        return tuple(dependencies)

    def tick_allocation_order(
        self, service_types: tuple[str, ...] | set[str]
    ) -> tuple[str, ...]:
        nodes = {
            ALLOCATION_LOGISTICS,
            ALLOCATION_RESOURCES,
            ALLOCATION_MAINTENANCE,
            ALLOCATION_POWER,
            ALLOCATION_TRANSPORT,
            *(_service_allocation_node(row) for row in service_types),
        }
        return allocation_dependency_order(
            nodes,
            self.tick_allocation_dependencies(service_types),
            cycle_label="tick allocation dependency cycle",
        )

    def _allocate_tick(
        self,
        snapshot: TickPhysicalSnapshot,
        intents: TickIntents,
        plan: TickPlan,
    ) -> TickAllocations:
        """Resolve the current tick as one priority allocation with provider dependencies.

        Maintenance is an Activity Priority consumer of physical Resources, not a
        privileged pre-allocation stage.  At the same time, its fulfillment enables
        Power and downstream Service Capacity.  Resolve that dependency by iterating
        the common execution allocation to a deterministic fixed point instead of
        letting Domain call order decide who receives shared stock.
        """
        market_buys = self.market.plan_buy_allocations()
        authorized_logistics = plan.logistics

        transport_requests = self.transport.transport_service_capacity_requests(
            self.day, authorized_logistics.planned_usage
        )
        all_service_requests = self._complete_service_requests(transport_requests)
        base_intents: tuple[AllocationIntent | ExecutionRequirementBundle, ...] = tuple(
            intents.execution_requirements
        )

        def resolve_for_maintenance(maintenance_factors):
            power_by_location = {
                location_id: self.power.resolve_snapshot(
                    snapshot.power_inputs_by_location[location_id], maintenance_factors
                )
                for location_id in snapshot.ordered_locations
            }

            # Provider dependencies are derived from the current upstream
            # fulfillment estimate. Consumer Service requirements join the same
            # root Execution Bundles as their Resource/Transport requirements.
            provider_plan = self._allocate_tick_services(power_by_location, requests=())
            static_intents = base_intents

            (
                execution,
                actual_usage,
                reference_usage,
                surface_factors,
                surface_limits,
            ) = self._resolve_transport_execution_fixed_point(
                self.day,
                authorized_logistics,
                static_intents,
                provider_plan,
                all_service_requests,
            )

            next_maintenance_factors = (
                maintenance_factors
                if self.maintenance is None
                else self.maintenance.satisfaction_projection(execution)
            )
            return (
                power_by_location,
                provider_plan,
                execution,
                next_maintenance_factors,
                actual_usage,
                reference_usage,
                surface_factors,
                surface_limits,
            )

        maintenance_factors = {
            facility.id: 1.0 for facility in self.facilities.facilities.values()
        }
        convergence_tolerance = 1e-8
        max_iterations = 64
        damping = 0.5

        for _iteration in range(max_iterations):
            (
                power_by_location,
                provider_plan,
                execution,
                next_maintenance_factors,
                transport_usage,
                transport_reference_usage,
                transport_surface_factors,
                transport_surface_limits,
            ) = resolve_for_maintenance(maintenance_factors)

            facility_ids = set(maintenance_factors) | set(next_maintenance_factors)
            delta = max(
                (
                    abs(
                        next_maintenance_factors.get(facility_id, 1.0)
                        - maintenance_factors.get(facility_id, 1.0)
                    )
                    for facility_id in facility_ids
                ),
                default=0.0,
            )
            if delta <= convergence_tolerance:
                # Re-evaluate once at the actual fulfillment rather than at the
                # damped estimate. This preserves exact 0/1 dependency states
                # while accepting only a self-consistent result within tolerance.
                maintenance_factors = dict(next_maintenance_factors)
                (
                    power_by_location,
                    provider_plan,
                    execution,
                    verified_factors,
                    transport_usage,
                    transport_reference_usage,
                    transport_surface_factors,
                    transport_surface_limits,
                ) = resolve_for_maintenance(maintenance_factors)
                verify_ids = set(maintenance_factors) | set(verified_factors)
                verification_delta = max(
                    (
                        abs(
                            verified_factors.get(facility_id, 1.0)
                            - maintenance_factors.get(facility_id, 1.0)
                        )
                        for facility_id in verify_ids
                    ),
                    default=0.0,
                )
                if verification_delta <= convergence_tolerance:
                    break
                next_maintenance_factors = verified_factors
                facility_ids = verify_ids

            maintenance_factors = {
                facility_id: (
                    damping * maintenance_factors.get(facility_id, 1.0)
                    + (1.0 - damping)
                    * next_maintenance_factors.get(facility_id, 1.0)
                )
                for facility_id in sorted(facility_ids, key=str)
            }
        else:
            raise RuntimeError(
                "tick allocation provider dependencies did not converge"
            )

        resources = ResourceAllocationProjection(
            self._resource_projection_from_execution(execution)
            + self.logistics.resource_allocation_projection(
                self.day,
                authorized_logistics,
                execution,
                transport_usage,
                transport_reference_usage,
            )
        )
        service_overrides = self.logistics.transport_service_allocation_overrides(
            self.day, transport_usage
        )
        bundle_service_requests, bundle_service_overrides = (
            self._service_projection_requests_from_execution(execution)
        )
        service_overrides = {**bundle_service_overrides, **service_overrides}
        services = self._service_plan_from_execution(
            all_service_requests + bundle_service_requests,
            execution,
            provider_plan,
            allocation_overrides=service_overrides,
        )
        operation_factors = self.logistics.transport_operation_execution_projection(
            self.day,
            authorized_logistics,
            execution,
            transport_usage,
            transport_reference_usage,
            transport_surface_factors,
            transport_surface_limits,
        )
        transport = self.logistics.build_capacity_logistics_execution(
            self.day, authorized_logistics, execution, operation_factors
        )
        return TickAllocations(
            market_buys,
            authorized_logistics,
            execution,
            resources,
            power_by_location,
            services,
            transport,
        )

    def _execute_tick_domains(
        self,
        snapshot: TickPhysicalSnapshot,
        allocations: TickAllocations,
    ) -> tuple[DomainActivity, ...]:
        activities: list[DomainActivity] = []
        powers = allocations.power_by_location
        self.storage.refresh(self.day, powers)
        # Buy commitments acquire only Funds/provider reservations; Sell settles
        # physical Interface inventory and credits Funds after this tick's allocation.
        self.market.create_buy_commitments(allocations.market_buys, self.day)
        self.market.settle_sells(allocations.execution, self.inventory)
        if self.maintenance is not None:
            self.maintenance.advance_day(allocations.execution, self.day)

        active_locations = set(self._active_locations())
        for location_id in snapshot.ordered_locations:
            if location_id not in active_locations:
                continue
            activities.extend(self.industry.advance_day(
                location_id,
                self.facilities,
                self.inventory,
                self.day,
                allocations.execution,
            ))
            if self.extraction is not None:
                activities.extend(self.extraction.advance_day(
                    location_id,
                    self.facilities,
                    self.inventory,
                    powers[location_id],
                    self.day,
                    allocations.execution,
                ))

        if self.research is not None:
            self.research.advance_day(powers, allocations.execution, self.day)
        if self.scientific_exploration is not None:
            self.scientific_exploration.advance_day(
                powers, allocations.execution, self.day
            )
        if self.survey is not None:
            self.survey.advance_day(powers, allocations.execution, self.day)

        self.transport.advance_vehicle_production_day(
            powers, allocations.execution, self.day
        )
        self.transport.advance_fleet_retirements(allocations.execution, self.day)
        self.projects.finalize_procurement(allocations.execution, self.day)
        self.projects.advance_construction(powers, allocations.execution, self.day)
        if self.founding is not None:
            self.founding.advance_day(
                allocations.execution,
                self.day,
                powers,
            )
        return tuple(activities)

    def _progress_tick_movement(
        self,
        plan: TickPlan,
        allocations: TickAllocations,
    ) -> tuple[DomainActivity, ...]:
        # Movement is deliberately after every Domain execution.  It may spend
        # only amounts authorized from the start-of-tick allocation and cannot
        # admit arriving Cargo to Inventory until the next boundary.
        self.transport.advance_fleet_relocations(allocations.execution, self.day)
        return self.logistics.advance_capacity_logistics(
            self.day, allocations.logistics, allocations.transport
        )

    def _settle_tick_state_transitions(self, allocations: TickAllocations) -> None:
        if self.research is not None:
            self.research.settle_completions(self.day + 1)
        if self.projects.settle_completions(
            allocations.power_by_location, allocations.execution, self.day
        ):
            self.transport.invalidate_movement_plans()
        next_day = self.day + 1
        if self.contracts is not None:
            self.contracts.advance_day(
                next_day, allocations.power_by_location
            )
        self.day = next_day
        # Phase 8 may refresh derived state only from allocations already
        # settled for the completed day. Do not project the next day's
        # snapshot/allocation before its Boundary settlement. Boundary-owned
        # transitions that install storage (for example Founding completion)
        # refresh their new physical envelope during that boundary.
        self.storage.refresh(self.day, allocations.power_by_location)

    def _advance_canonical_day(self) -> None:
        """Advance exactly one canonical game day through the phase contract."""
        # Phase 1: Boundary settlement.  In the normal resting state this was
        # already completed when the previous day returned.
        self._ensure_current_boundary_settled()

        # Phase 2: Physical snapshot.
        snapshot = self._physical_tick_snapshot()
        # Phase 3: Intent generation.
        intents = self._generate_tick_intents(snapshot)
        # Phase 4: Planning.
        plan = self._plan_tick(intents)
        # Phase 5: Allocation.
        allocations = self._allocate_tick(snapshot, intents, plan)
        # Phase 6: Domain execution.
        activities = self._execute_tick_domains(snapshot, allocations)
        # Phase 7: Logistics / Movement progression.
        movement_activities = self._progress_tick_movement(plan, allocations)
        if self.research is not None:
            self.research.knowledge_state.record(
                activities + movement_activities, self.research.experience_rules
            )
        # Phase 8: State transition / derived refresh.
        self._settle_tick_state_transitions(allocations)

        # The externally observable resting point is after the next day's
        # Boundary settlement and before its Physical snapshot.  This is where
        # Player Commands are allowed to mutate authoritative intent/state.
        self._ensure_current_boundary_settled()

    def advance_days(self, days: int) -> None:
        if days < 0:
            raise ValueError("days must be non-negative")
        for _ in range(days):
            self._advance_canonical_day()
