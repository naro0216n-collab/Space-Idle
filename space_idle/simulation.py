from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import ContractService
from .construction.models import CONSTRUCTION_SERVICE_TYPE
from .domain import DomainExtension
from .external_economy import ExternalEconomyState, FundsAllocationPlan, FundsRequest
from .facilities import FacilityBook, FacilityPlacementScope
from .founding import LocationFoundingService
from .industry import IndustryService
from .inventory import InventoryBook
from .knowledge import DomainActivity
from .logistics import LogisticsService
from .maintenance import FacilityMaintenanceService
from .power import PowerPhysicalSnapshot, PowerService, PowerSnapshot
from .projects import ProjectService
from .research import ResearchService
from .resource_claim import ResourceAllocationPlan, ResourceClaim, allocate_resource_claims
from .service_capacity import (
    ServiceCapacityAllocationPlan,
    ServiceCapacityDependency,
    ServiceCapacityRequest,
    allocate_service_capacity,
    merge_service_capacity_plans,
    service_capacity_dependency_order,
)
from .resource_demand import (
    ResourceDemand,
    resolve_local_resource_supply,
    ResourceDemandResolution,
)
from .shared import SpatialNodeId
from .spatial import EnvironmentResolver, SpatialGraph
from .storage import StorageService
from .surface_infrastructure import SurfaceInfrastructureService
from .technology import TechnologyState
from .survey import ExtractionService, SurveyService
from .scientific_exploration import ScientificExplorationService
from .transport.steady_logistics import LogisticsResourcePlan


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
    resource_demands: tuple[ResourceDemand, ...]
    resource_claims: tuple[ResourceClaim, ...]
    service_requests: tuple[ServiceCapacityRequest, ...]


@dataclass(frozen=True)
class TickPlan:
    external_demands: tuple[ResourceDemand, ...]
    logistics: LogisticsResourcePlan


@dataclass(frozen=True)
class TickAllocations:
    funds: FundsAllocationPlan
    logistics: LogisticsResourcePlan
    resources: ResourceAllocationPlan
    power_by_location: dict[SpatialNodeId, PowerSnapshot]
    services: ServiceCapacityAllocationPlan


@dataclass(frozen=True)
class TickDecisionProjection:
    snapshot: TickPhysicalSnapshot
    intents: TickIntents
    plan: TickPlan
    allocations: TickAllocations


@dataclass
class Simulation:
    day: int
    external_economy: ExternalEconomyState
    graph: SpatialGraph
    environment: EnvironmentResolver
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    storage: StorageService
    industry: IndustryService
    logistics: LogisticsService
    projects: ProjectService
    technology: TechnologyState
    founding: LocationFoundingService | None = None
    contracts: ContractService | None = None
    research: ResearchService | None = None
    survey: SurveyService | None = None
    extraction: ExtractionService | None = None
    scientific_exploration: ScientificExplorationService | None = None
    maintenance: FacilityMaintenanceService | None = None
    surface_infrastructure: SurfaceInfrastructureService | None = None
    content_id: str = "unconfigured"
    pending_offline_game_days: float = 0.0
    domain_extensions: tuple[DomainExtension, ...] = ()

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
            for project in self.logistics.vehicle_production_projects.values()
        )
        if self.scientific_exploration is not None:
            for definition_id in self.scientific_exploration.campaigns:
                definition = self.scientific_exploration.definitions[definition_id]
                locations.add(definition.origin_id)
                locations.add(definition.destination_id)
        return locations

    def refresh_storage(self) -> None:
        locations = set(self.graph.operational_node_ids()) | {
            facility.operational_node_id for facility in self.facilities.facilities.values()
        }
        power_by_location = {
            loc: self.power.snapshot(loc, self.facilities, self.day)
            for loc in sorted(locations, key=str)
        }
        self.storage.refresh(self.day, power_by_location)

    def _gross_resource_demands(self) -> tuple[ResourceDemand, ...]:
        """Collect pre-allocation physical need from every active Domain."""
        locations = self._active_locations()
        demands: list[ResourceDemand] = list(self.projects.resource_demands(self.day))
        if self.founding is not None:
            demands.extend(self.founding.resource_demands())
        for location_id in sorted(locations, key=str):
            demands.extend(
                self.industry.resource_demands(
                    location_id, self.facilities, self.inventory, self.day
                )
            )
        if self.research is not None:
            demands.extend(self.research.resource_demands(self.day))
        if self.maintenance is not None:
            demands.extend(self.maintenance.resource_demands(self.day))
        demands.extend(self.logistics.vehicle_production_resource_demands(self.day))
        demands.extend(self.logistics.fleet_relocation_resource_demands(self.day))
        if self.scientific_exploration is not None:
            demands.extend(self.scientific_exploration.resource_demands(self.day))
        seen: set[object] = set()
        for demand in demands:
            if demand.id in seen:
                raise RuntimeError(f"duplicate resource demand id: {demand.id}")
            seen.add(demand.id)
        return tuple(demands)

    def resource_demand_resolutions(self) -> tuple[ResourceDemandResolution, ...]:
        """Expose gross need and deterministic on-site allocation for queries."""
        return resolve_local_resource_supply(self._gross_resource_demands(), self.inventory)

    def resource_demands(self) -> tuple[ResourceDemand, ...]:
        """Return only the true off-site shortage after shared local netting."""
        rows: list[ResourceDemand] = []
        for resolution in self.resource_demand_resolutions():
            demand = resolution.external_demand()
            if demand is not None:
                rows.append(demand)
        return tuple(rows)

    def _resource_claims(self) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = list(self.projects.resource_claims(self.day))
        if self.founding is not None:
            claims.extend(self.founding.resource_claims())
        for location_id in sorted(self._active_locations(), key=str):
            claims.extend(
                self.industry.resource_claims(location_id, self.facilities, self.day)
            )
        if self.research is not None:
            claims.extend(self.research.resource_claims(self.day))
        if self.maintenance is not None:
            claims.extend(self.maintenance.resource_claims(self.day))
        claims.extend(self.logistics.vehicle_production_resource_claims(self.day))
        claims.extend(self.logistics.fleet_relocation_resource_claims(self.day))
        if self.scientific_exploration is not None:
            claims.extend(self.scientific_exploration.resource_claims(self.day))
        seen: set[object] = set()
        for claim in claims:
            if claim.id in seen:
                raise RuntimeError(f"duplicate resource claim id: {claim.id}")
            seen.add(claim.id)
        return tuple(claims)

    def _allocate_tick_resources(
        self,
        logistics_claims: tuple[ResourceClaim, ...] = (),
        *,
        domain_claims: tuple[ResourceClaim, ...] | None = None,
    ) -> ResourceAllocationPlan:
        claims = (
            self._resource_claims() if domain_claims is None else domain_claims
        ) + tuple(logistics_claims)
        return allocate_resource_claims(claims, self.inventory)

    def _service_capacity_requests(self) -> tuple[ServiceCapacityRequest, ...]:
        requests: list[ServiceCapacityRequest] = list(
            self.logistics.vehicle_production_service_requests(self.day)
        )
        requests.extend(self.projects.construction_service_requests(self.day))
        requests.extend(self.projects.surface_infrastructure_service_requests(self.day))
        if self.founding is not None:
            requests.extend(self.founding.service_requests(self.day))
        if self.survey is not None:
            requests.extend(self.survey.service_requests(self.day))
        if self.research is not None:
            requests.extend(self.research.service_requests(self.day))
        for location_id in sorted(self._active_locations(), key=str):
            requests.extend(
                self.industry.service_requests(location_id, self.facilities, self.day)
            )
            if self.extraction is not None:
                requests.extend(
                    self.extraction.service_requests(
                        location_id, self.facilities, self.day
                    )
                )
        if self.surface_infrastructure is not None:
            for location_id in sorted(self.graph.locations, key=str):
                requests.append(self.surface_infrastructure.service_request(location_id))
        seen: set[object] = set()
        for request in requests:
            if request.id in seen:
                raise RuntimeError(f"duplicate service capacity request id: {request.id}")
            seen.add(request.id)
        return tuple(requests)

    def service_capacity_dependencies(self) -> tuple[ServiceCapacityDependency, ...]:
        """Declare static same-tick Service Capacity provider dependencies.

        The graph is derived from generic placement/provider metadata.  A
        Surface-Cell provider depends on the Location's aggregate distribution
        service unless it is itself a provider of that upstream service.
        Service types that intrinsically use the network (for example cargo
        handling) declare the same edge independent of provider placement.
        """
        surface = self.surface_infrastructure
        if surface is None:
            return ()
        upstream = surface.service_type
        dependent = set(surface.network_dependent_service_types)
        remote_dependent: set[str] = set()
        for definition_id, definition in self.facilities.definitions.items():
            if definition.placement_scope is not FacilityPlacementScope.SURFACE_CELL:
                continue
            remote_dependent.update(
                supply.service_type
                for supply in definition.service_capacity_supplies
                if supply.service_type != upstream
            )
            if definition_id in self.projects.construction_providers:
                remote_dependent.add(CONSTRUCTION_SERVICE_TYPE)
            if self.survey is not None and definition_id in self.survey.providers:
                remote_dependent.add(self.survey.SERVICE_TYPE)
            if self.extraction is not None and definition_id in self.extraction.specs:
                remote_dependent.add(
                    self.extraction.service_type(
                        self.extraction.specs[definition_id].resource_id
                    )
                )
            remote_dependent.update(
                self.industry.process_service_type(process.id)
                for process in self.industry.processes.values()
                if process.facility_def_id == definition_id
            )
        dependent.update(remote_dependent)
        return tuple(
            ServiceCapacityDependency(service_type, upstream)
            for service_type in sorted(dependent)
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
        return surface.facility_availability_factors(
            location_id, service_type, self.facilities, resolved_plan
        )

    def _service_supply_at(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        power: PowerSnapshot,
        provider_factors: dict | None,
    ) -> tuple[float, float]:
        key = (location_id, service_type)
        if service_type == CONSTRUCTION_SERVICE_TYPE:
            return (
                self.projects.construction_nominal_capacity_at(location_id, self.day),
                self.projects.construction_capacity_at(
                    location_id, power, self.day, provider_factors=provider_factors
                ),
            )
        if self.survey is not None and service_type == self.survey.SERVICE_TYPE:
            return (
                self.survey.nominal_service_capacity_at(location_id, self.day),
                self.survey.enabled_service_capacity_at(
                    location_id, power, self.day, provider_factors=provider_factors
                ),
            )
        if (
            self.surface_infrastructure is not None
            and service_type == self.surface_infrastructure.service_type
        ):
            return (
                self.facilities.nominal_service_capacity_at(
                    location_id, service_type, self.day
                ),
                self.surface_infrastructure.provider_available_capacity(
                    location_id, self.facilities, power, self.day
                ),
            )

        industry_nominal, industry_enabled = self.industry.service_supply(
            location_id, self.facilities, power, self.day,
            provider_factors=provider_factors,
        )
        if key in industry_nominal or key in industry_enabled:
            return industry_nominal.get(key, 0.0), industry_enabled.get(key, 0.0)

        if self.extraction is not None:
            extraction_nominal, extraction_enabled = self.extraction.service_supply(
                location_id, self.facilities, power, self.day,
                provider_factors=provider_factors,
            )
            if key in extraction_nominal or key in extraction_enabled:
                return (
                    extraction_nominal.get(key, 0.0),
                    extraction_enabled.get(key, 0.0),
                )

        return (
            self.facilities.nominal_service_capacity_at(
                location_id, service_type, self.day
            ),
            self.facilities.enabled_service_capacity_at(
                location_id, service_type, power, self.day,
                provider_factors=provider_factors,
            ),
        )

    def _allocate_tick_services(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        requests: tuple[ServiceCapacityRequest, ...] | None = None,
    ) -> ServiceCapacityAllocationPlan:
        requests = self._service_capacity_requests() if requests is None else requests
        if self.surface_infrastructure is not None:
            request_ids = {request.id for request in requests}
            upstream = tuple(
                self.surface_infrastructure.service_request(location_id)
                for location_id in sorted(self.graph.locations, key=str)
                if self.surface_infrastructure.service_request_id(location_id) not in request_ids
            )
            requests = requests + upstream

        locations = tuple(
            sorted(
                self._active_locations() | set(self.graph.operational_node_ids()),
                key=str,
            )
        )
        service_types = {request.service_type for request in requests}
        service_types.update(self.facilities.service_types())
        service_types.add(CONSTRUCTION_SERVICE_TYPE)
        service_types.update(
            self.industry.process_service_type(process.id)
            for process in self.industry.processes.values()
        )
        if self.extraction is not None:
            service_types.update(
                self.extraction.service_type(spec.resource_id)
                for spec in self.extraction.specs.values()
            )
        if self.survey is not None:
            service_types.add(self.survey.SERVICE_TYPE)
        dependencies = self.service_capacity_dependencies()
        order = service_capacity_dependency_order(service_types, dependencies)

        plans: list[ServiceCapacityAllocationPlan] = []
        for service_type in order:
            resolved_plan = merge_service_capacity_plans(plans)
            stage_requests = tuple(
                request for request in requests if request.service_type == service_type
            )
            nominal: dict[tuple[SpatialNodeId, str], float] = {}
            enabled: dict[tuple[SpatialNodeId, str], float] = {}
            limiting: dict[tuple[SpatialNodeId, str], tuple[str, ...]] = {}
            requested_locations = {
                request.operational_node_id for request in stage_requests
            }
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
            plans.append(
                allocate_service_capacity(
                    stage_requests,
                    nominal_supply=nominal,
                    enabled_supply=enabled,
                    limiting_factors=limiting,
                )
            )
        return merge_service_capacity_plans(plans)

    def service_capacity_allocation_projection(self) -> ServiceCapacityAllocationPlan:
        return self.tick_decision_projection().allocations.services

    def tick_decision_projection(self) -> TickDecisionProjection:
        """Project current intent, planning and allocation without mutation."""
        snapshot = self._physical_tick_snapshot()
        intents = self._generate_tick_intents(snapshot)
        plan = self._plan_tick(intents)
        allocations = self._allocate_tick(snapshot, intents, plan)
        return TickDecisionProjection(snapshot, intents, plan, allocations)

    def external_funds_projection(self) -> tuple[tuple[FundsRequest, ...], FundsAllocationPlan]:
        """Project current External Service spending requests and authorization."""
        external_demands = tuple(
            demand
            for resolution in resolve_local_resource_supply(
                self._gross_resource_demands(), self.inventory
            )
            if (demand := resolution.external_demand()) is not None
        )
        logistics_plan = self.logistics.plan_capacity_logistics(self.day, external_demands)
        requests = logistics_plan.spending_requests
        return requests, self.external_economy.allocate(requests, self.day)

    def resource_allocation_projection(self) -> ResourceAllocationPlan:
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
        """Settle state whose completion time was reached before this tick."""
        self.external_economy.settle_periods(self.day)
        self.logistics.advance_fleet_state(self.day)
        if self.founding is not None:
            self.founding.settle_arrivals(self.day)
        self.logistics.synchronize_surface_access_routes()
        self.logistics.settle_cargo_arrivals(self.day)

        # Procurement wait/policy maturation is a clock-boundary transition.
        # It may expose intents for this tick but never consumes inventory.
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
            resource_demands=self._gross_resource_demands(),
            resource_claims=self._resource_claims(),
            service_requests=self._service_capacity_requests(),
        )

    def _plan_tick(self, intents: TickIntents) -> TickPlan:
        external_demands = tuple(
            demand
            for resolution in resolve_local_resource_supply(
                intents.resource_demands, self.inventory
            )
            if (demand := resolution.external_demand()) is not None
        )
        logistics_plan = self.logistics.plan_capacity_logistics(
            self.day, external_demands
        )
        return TickPlan(external_demands, logistics_plan)

    def _allocate_tick(
        self,
        snapshot: TickPhysicalSnapshot,
        intents: TickIntents,
        plan: TickPlan,
    ) -> TickAllocations:
        funds = self.external_economy.allocate(plan.logistics.spending_requests, self.day)
        authorized_logistics = self.logistics.authorize_capacity_logistics(
            plan.logistics, funds, self.day
        )
        resources = self._allocate_tick_resources(
            authorized_logistics.claims,
            domain_claims=intents.resource_claims,
        )
        maintenance_factors = (
            self.maintenance.satisfaction_projection(resources)
            if self.maintenance is not None
            else {facility.id: 1.0 for facility in self.facilities.facilities.values()}
        )
        power_by_location = {
            location_id: self.power.resolve_snapshot(
                snapshot.power_inputs_by_location[location_id], maintenance_factors
            )
            for location_id in snapshot.ordered_locations
        }
        transport_requests = self.logistics.transport_service_capacity_requests(
            self.day, authorized_logistics.planned_usage
        )
        service_requests = intents.service_requests + transport_requests
        seen: set[object] = set()
        for request in service_requests:
            if request.id in seen:
                raise RuntimeError(f"duplicate service capacity request id: {request.id}")
            seen.add(request.id)
        services = self._allocate_tick_services(power_by_location, service_requests)
        return TickAllocations(
            funds, authorized_logistics, resources, power_by_location, services
        )

    def _execute_tick_domains(
        self,
        snapshot: TickPhysicalSnapshot,
        allocations: TickAllocations,
    ) -> tuple[DomainActivity, ...]:
        activities: list[DomainActivity] = []
        powers = allocations.power_by_location
        self.storage.refresh(self.day, powers)
        if self.maintenance is not None:
            self.maintenance.advance_day(allocations.resources, self.day)

        active_locations = set(self._active_locations())
        for location_id in snapshot.ordered_locations:
            if location_id not in active_locations:
                continue
            activities.extend(self.industry.advance_day(
                location_id,
                self.facilities,
                self.inventory,
                powers[location_id],
                self.day,
                allocations.resources,
                allocations.services,
            ))
            if self.extraction is not None:
                activities.extend(self.extraction.advance_day(
                    location_id,
                    self.facilities,
                    self.inventory,
                    powers[location_id],
                    self.day,
                    allocations.services,
                ))

        if self.research is not None:
            self.research.advance_day(
                powers, allocations.resources, allocations.services, self.day
            )
        if self.scientific_exploration is not None:
            self.scientific_exploration.advance_day(
                powers, allocations.resources, self.day
            )
        if self.survey is not None:
            self.survey.advance_day(powers, allocations.services, self.day)

        self.logistics.advance_vehicle_production_day(
            powers, allocations.resources, allocations.services, self.day
        )
        self.projects.finalize_procurement(allocations.resources, self.day)
        self.projects.advance_construction(powers, allocations.services, self.day)
        if self.founding is not None:
            self.founding.advance_day(
                allocations.resources,
                allocations.services,
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
        self.logistics.advance_fleet_relocations(allocations.resources, self.day)
        return self.logistics.advance_capacity_logistics(
            self.day,
            allocations.logistics,
            allocations.resources,
            allocations.funds,
            allocations.services,
        )

    def _settle_tick_state_transitions(self, allocations: TickAllocations) -> None:
        if self.research is not None:
            self.research.settle_completions()
        self.projects.settle_completions(allocations.power_by_location, self.day)
        self.logistics.synchronize_surface_access_routes()
        next_day = self.day + 1
        if self.contracts is not None:
            self.contracts.advance_day(next_day)
        self.day = next_day
        self.refresh_storage()

    def advance_days(self, days: int) -> None:
        if days < 0:
            raise ValueError("days must be non-negative")
        for _ in range(days):
            self._settle_tick_boundary()
            snapshot = self._physical_tick_snapshot()
            intents = self._generate_tick_intents(snapshot)
            plan = self._plan_tick(intents)
            allocations = self._allocate_tick(snapshot, intents, plan)
            activities = self._execute_tick_domains(snapshot, allocations)
            movement_activities = self._progress_tick_movement(plan, allocations)
            if self.research is not None:
                self.research.knowledge_state.record(
                    activities + movement_activities, self.research.experience_rules
                )
            self._settle_tick_state_transitions(allocations)
