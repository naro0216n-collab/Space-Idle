from __future__ import annotations

from dataclasses import dataclass
import math

from .allocation_graph import AllocationDependency, allocation_dependency_order
from .contracts import ContractService
from .construction.models import CONSTRUCTION_SERVICE_TYPE
from .domain import DomainExtension
from .external_economy import ExternalEconomyState, FundsAllocationPlan, FundsRequest
from .external_procurement import ExternalProcurementPlan
from .facilities import FacilityBook, FacilityPlacementScope
from .founding import LocationFoundingService
from .industry import IndustryService
from .inventory import InventoryBook
from .knowledge import DomainActivity
from .logistics import LogisticsService
from .transport.service import TransportService
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
    resource_demands: tuple[ResourceDemand, ...]
    resource_claims: tuple[ResourceClaim, ...]
    service_requests: tuple[ServiceCapacityRequest, ...]


@dataclass(frozen=True)
class TickPlan:
    demand_resolutions: tuple[ResourceDemandResolution, ...]
    external_demands: tuple[ResourceDemand, ...]
    logistics: LogisticsResourcePlan
    procurement: ExternalProcurementPlan

    @property
    def spending_requests(self) -> tuple[FundsRequest, ...]:
        return tuple(
            sorted(
                self.logistics.spending_requests + self.procurement.spending_requests,
                key=lambda row: str(row.id),
            )
        )


@dataclass(frozen=True)
class TickAllocations:
    funds: FundsAllocationPlan
    logistics: LogisticsResourcePlan
    procurement: ExternalProcurementPlan
    resources: ResourceAllocationPlan
    power_by_location: dict[SpatialNodeId, PowerSnapshot]
    services: ServiceCapacityAllocationPlan
    transport: LogisticsExecutionAllocation


ALLOCATION_FUNDS = "funds"
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
    external_economy: ExternalEconomyState
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
            for project in self.transport.vehicle_production_projects.values()
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
        demands.extend(self.transport.vehicle_production_resource_demands(self.day))
        demands.extend(self.transport.fleet_relocation_resource_demands(self.day))
        if self.scientific_exploration is not None:
            demands.extend(self.scientific_exploration.resource_demands(self.day))
        seen: set[object] = set()
        for demand in demands:
            if demand.id in seen:
                raise RuntimeError(f"duplicate resource demand id: {demand.id}")
            seen.add(demand.id)
        return tuple(demands)

    def resource_demand_resolutions(self) -> tuple[ResourceDemandResolution, ...]:
        """Return local/external Resource Demand from the shared tick plan."""
        return self.tick_decision_projection().plan.demand_resolutions

    def resource_demands(self) -> tuple[ResourceDemand, ...]:
        """Return external Resource Demand from the shared tick plan."""
        return self.tick_decision_projection().plan.external_demands

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
        claims.extend(self.transport.vehicle_production_resource_claims(self.day))
        claims.extend(self.transport.fleet_relocation_resource_claims(self.day))
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
            self.transport.vehicle_production_service_requests(self.day)
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

    def _service_allocation_types(
        self, requests: tuple[ServiceCapacityRequest, ...]
    ) -> tuple[str, ...]:
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
        if self.surface_infrastructure is not None:
            service_types.add(self.surface_infrastructure.service_type)
        service_types.update(
            definition.turnaround_service_type
            for definition in self.transport.vehicle_defs.values()
            if definition.turnaround_service_type is not None
        )
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
        requests = self._service_capacity_requests() if requests is None else requests
        if self.surface_infrastructure is not None:
            request_ids = {request.id for request in requests}
            upstream = tuple(
                self.surface_infrastructure.service_request(location_id)
                for location_id in sorted(self.graph.locations, key=str)
                if self.surface_infrastructure.service_request_id(location_id)
                not in request_ids
            )
            requests = requests + upstream

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
        snapshot = self._physical_tick_snapshot()
        intents = self._generate_tick_intents(snapshot)
        plan = self._plan_tick(intents)
        allocations = self._allocate_tick(snapshot, intents, plan)
        return TickDecisionProjection(snapshot, intents, plan, allocations)

    def external_funds_projection(self) -> tuple[tuple[FundsRequest, ...], FundsAllocationPlan]:
        """Expose Funds requests and authorization from the shared tick DAG."""
        decision = self.tick_decision_projection()
        return decision.plan.spending_requests, decision.allocations.funds

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
        self.transport.advance_fleet_state(self.day)
        if self.founding is not None:
            self.founding.settle_arrivals(self.day)
        self.transport.synchronize_surface_access_routes()
        self.logistics.settle_cargo_arrivals(self.day)
        self.logistics.settle_procurement_arrivals(self.day)

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
        demand_resolutions = resolve_local_resource_supply(
            intents.resource_demands, self.inventory
        )
        external_demands = tuple(
            demand
            for resolution in demand_resolutions
            if (demand := resolution.external_demand()) is not None
        )
        logistics_plan = self.logistics.plan_capacity_logistics(
            self.day, external_demands
        )
        procurement_plan = self.logistics.plan_external_procurement(
            self.day, external_demands, logistics_plan
        )
        return TickPlan(
            demand_resolutions, external_demands, logistics_plan, procurement_plan
        )

    def _complete_service_requests(
        self, requests: tuple[ServiceCapacityRequest, ...]
    ) -> tuple[ServiceCapacityRequest, ...]:
        rows = requests
        if self.surface_infrastructure is not None:
            request_ids = {request.id for request in rows}
            rows += tuple(
                self.surface_infrastructure.service_request(location_id)
                for location_id in sorted(self.graph.locations, key=str)
                if self.surface_infrastructure.service_request_id(location_id)
                not in request_ids
            )
        seen: set[object] = set()
        for request in rows:
            if request.id in seen:
                raise RuntimeError(f"duplicate service capacity request id: {request.id}")
            seen.add(request.id)
        return rows

    def tick_allocation_dependencies(
        self, service_types: tuple[str, ...] | set[str]
    ) -> tuple[AllocationDependency, ...]:
        """Return the explicit same-tick cross-Domain allocation DAG."""
        service_types = tuple(sorted(set(service_types)))
        dependencies: list[AllocationDependency] = [
            AllocationDependency(ALLOCATION_LOGISTICS, ALLOCATION_FUNDS),
            AllocationDependency(ALLOCATION_RESOURCES, ALLOCATION_LOGISTICS),
            AllocationDependency(ALLOCATION_MAINTENANCE, ALLOCATION_RESOURCES),
            AllocationDependency(ALLOCATION_POWER, ALLOCATION_MAINTENANCE),
            AllocationDependency(ALLOCATION_TRANSPORT, ALLOCATION_FUNDS),
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
            ALLOCATION_FUNDS,
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
        """Resolve one tick through the explicit cross-Domain allocation DAG."""
        service_types = self._service_allocation_types(intents.service_requests)
        order = self.tick_allocation_order(service_types)
        service_dependencies = self.service_capacity_dependencies()

        funds: FundsAllocationPlan | None = None
        authorized_logistics: LogisticsResourcePlan | None = None
        authorized_procurement: ExternalProcurementPlan | None = None
        resources: ResourceAllocationPlan | None = None
        maintenance_factors: dict[EntityId, float] | None = None
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None
        service_requests: tuple[ServiceCapacityRequest, ...] | None = None
        service_plans: list[ServiceCapacityAllocationPlan] = []
        transport: LogisticsExecutionAllocation | None = None

        for node in order:
            if node == ALLOCATION_FUNDS:
                funds = self.external_economy.allocate(
                    plan.spending_requests, self.day
                )
                continue
            if node == ALLOCATION_LOGISTICS:
                if funds is None:
                    raise RuntimeError("allocation graph resolved logistics before funds")
                authorized_logistics = self.logistics.authorize_capacity_logistics(
                    plan.logistics, funds, self.day
                )
                authorized_procurement = self.logistics.authorize_external_procurement(
                    plan.procurement, funds
                )
                transport_requests = self.transport.transport_service_capacity_requests(
                    self.day, authorized_logistics.planned_usage
                )
                service_requests = self._complete_service_requests(
                    intents.service_requests + transport_requests
                )
                continue
            if node == ALLOCATION_RESOURCES:
                if authorized_logistics is None:
                    raise RuntimeError(
                        "allocation graph resolved resources before logistics authorization"
                    )
                resources = self._allocate_tick_resources(
                    authorized_logistics.claims, domain_claims=intents.resource_claims
                )
                continue
            if node == ALLOCATION_MAINTENANCE:
                if resources is None:
                    raise RuntimeError(
                        "allocation graph resolved maintenance before resources"
                    )
                maintenance_factors = (
                    self.maintenance.satisfaction_projection(resources)
                    if self.maintenance is not None
                    else {
                        facility.id: 1.0
                        for facility in self.facilities.facilities.values()
                    }
                )
                continue
            if node == ALLOCATION_POWER:
                if maintenance_factors is None:
                    raise RuntimeError(
                        "allocation graph resolved power before maintenance"
                    )
                power_by_location = {
                    location_id: self.power.resolve_snapshot(
                        snapshot.power_inputs_by_location[location_id],
                        maintenance_factors,
                    )
                    for location_id in snapshot.ordered_locations
                }
                continue
            if node.startswith(SERVICE_NODE_PREFIX):
                if power_by_location is None or service_requests is None:
                    raise RuntimeError(
                        "allocation graph resolved service before its upstream allocations"
                    )
                service_type = node[len(SERVICE_NODE_PREFIX):]
                service_plans.append(
                    self._allocate_service_stage(
                        service_type,
                        power_by_location=power_by_location,
                        requests=service_requests,
                        resolved_plan=merge_service_capacity_plans(service_plans),
                        dependencies=service_dependencies,
                    )
                )
                continue
            if node == ALLOCATION_TRANSPORT:
                if (
                    funds is None
                    or authorized_logistics is None
                    or resources is None
                ):
                    raise RuntimeError(
                        "allocation graph resolved transport before upstream allocations"
                    )
                services = merge_service_capacity_plans(service_plans)
                transport = self.logistics.allocate_capacity_logistics_execution(
                    self.day, authorized_logistics, resources, services
                )
                continue
            raise RuntimeError(f"unknown allocation graph node: {node}")

        if (
            funds is None
            or authorized_logistics is None
            or authorized_procurement is None
            or resources is None
            or power_by_location is None
            or transport is None
        ):
            raise RuntimeError("allocation graph did not resolve all required nodes")
        services = merge_service_capacity_plans(service_plans)
        return TickAllocations(
            funds,
            authorized_logistics,
            authorized_procurement,
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

        self.transport.advance_vehicle_production_day(
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
        self.transport.advance_fleet_relocations(allocations.resources, self.day)
        self.logistics.advance_external_procurement(
            self.day, allocations.procurement, allocations.funds
        )
        return self.logistics.advance_capacity_logistics(
            self.day,
            allocations.logistics,
            allocations.funds,
            allocations.transport,
        )

    def _settle_tick_state_transitions(self, allocations: TickAllocations) -> None:
        if self.research is not None:
            self.research.settle_completions()
        self.projects.settle_completions(allocations.power_by_location, self.day)
        self.transport.synchronize_surface_access_routes()
        next_day = self.day + 1
        if self.contracts is not None:
            self.contracts.advance_day(
                next_day, allocations.power_by_location
            )
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
