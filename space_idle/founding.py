from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import math
from typing import Callable

from .facilities import FacilityBook, FacilityPlacementScope
from .inventory import InventoryBook
from .transport.service import TransportService
from .power import PowerService, PowerSnapshot
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .resource_demand import ResourceDemand
from .service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityRequest
from .shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements, evaluate_environment_requirements, evaluate_site_requirements
from .storage import StorageService
from .transport.models import (
    FleetReservationKind,
    OperationAssetDisposition,
    TransportOperationRequirement,
)


@dataclass(frozen=True)
class FoundingResourceRequirement:
    resource_id: DefinitionId
    amount_t: float

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("founding resource amount must be positive")


@dataclass(frozen=True)
class FoundingFacilityDeployment:
    facility_def_id: DefinitionId
    invested_resources: tuple[FoundingResourceRequirement, ...] = ()
    place_at_core_cell: bool = False


@dataclass(frozen=True)
class FoundingPackageDefinition:
    id: DefinitionId
    display_name: str
    deployed_facilities: tuple[FoundingFacilityDeployment, ...]
    preparation_work: float
    preparation_service_type: str
    operations: tuple[TransportOperationRequirement, ...]
    transit_days: int
    initial_inventory: tuple[FoundingResourceRequirement, ...] = ()
    staging_requirements: SiteRequirements = SiteRequirements()
    target_requirements: SiteRequirements = SiteRequirements()
    minimum_survey_knowledge_level: int = 0
    required_units: int = 1

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("founding package display name must not be empty")
        if self.preparation_work < 0:
            raise ValueError("founding preparation work must be non-negative")
        if not self.preparation_service_type:
            raise ValueError("founding preparation capability must not be empty")
        if self.transit_days <= 0:
            raise ValueError("founding transit must be positive")
        if not 0 <= self.minimum_survey_knowledge_level <= 4:
            raise ValueError("founding survey knowledge must be within 0..4")
        if self.required_units <= 0:
            raise ValueError("founding required units must be positive")

    @staticmethod
    def _accumulate(requirements, totals: dict[DefinitionId, float]) -> None:
        for req in requirements:
            totals[req.resource_id] = totals.get(req.resource_id, 0.0) + req.amount_t

    def investment_totals(self) -> dict[DefinitionId, float]:
        totals: dict[DefinitionId, float] = {}
        for deployment in self.deployed_facilities:
            self._accumulate(deployment.invested_resources, totals)
        return totals

    def initial_inventory_totals(self) -> dict[DefinitionId, float]:
        totals: dict[DefinitionId, float] = {}
        self._accumulate(self.initial_inventory, totals)
        return totals

    @property
    def payload_resources(self) -> tuple[FoundingResourceRequirement, ...]:
        totals = self.investment_totals()
        self._accumulate(self.initial_inventory, totals)
        return tuple(
            FoundingResourceRequirement(resource_id, amount_t)
            for resource_id, amount_t in sorted(totals.items(), key=lambda row: str(row[0]))
            if amount_t > 1e-12
        )

    @property
    def payload_t(self) -> float:
        return math.fsum(req.amount_t for req in self.payload_resources)

    @property
    def payload_t_per_unit(self) -> float:
        return self.payload_t / self.required_units


class FoundingStatus(str, Enum):
    PREPARING = "preparing"
    DEPLOYING = "deploying"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


@dataclass
class LocationFoundingProject:
    id: ProjectId
    staging_node_id: SpatialNodeId
    display_name: str
    target_body_id: CelestialBodyId
    target_core_cell_id: SurfaceCellId
    new_location_id: SpatialNodeId
    founding_package_id: DefinitionId
    vehicle_definition_id: DefinitionId
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    preferred_source_id: SpatialNodeId | None = None
    status: FoundingStatus = FoundingStatus.PREPARING
    preparation_done: float = 0.0
    inputs_consumed: bool = False
    paused: bool = False
    departure_day: int | None = None
    arrival_day: int | None = None
    completed_day: int | None = None

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)


@dataclass(frozen=True)
class FoundingBlocker:
    code: str
    detail: str


@dataclass(frozen=True)
class FoundingResourceStatus:
    resource_id: DefinitionId
    required_t: float
    staged_t: float
    committed_t: float
    shortage_t: float


@dataclass
class LocationFoundingService:
    packages: dict[DefinitionId, FoundingPackageDefinition]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    transport: TransportService
    storage: StorageService
    surface_knowledge_level_provider: Callable[[SurfaceCellId], int] | None = None
    external_cell_claim_provider: Callable[[SurfaceCellId], EntityId | None] | None = None
    projects: dict[ProjectId, LocationFoundingProject] = field(default_factory=dict)
    _counter: int = 0

    def _generated_location_id(self, body_id: CelestialBodyId, cell_id: SurfaceCellId) -> SpatialNodeId:
        digest = sha256(f"{body_id}\0{cell_id}".encode("utf-8")).hexdigest()[:24]
        base = f"player.location.{digest}"
        graph = self.facilities.environment.graph
        occupied = set(graph.nodes) | set(graph.locations) | set(graph.operational_node_ids())
        occupied.update(
            p.new_location_id
            for p in self.projects.values()
            if p.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}
        )
        candidate = SpatialNodeId(base)
        suffix = 2
        while candidate in occupied:
            candidate = SpatialNodeId(f"{base}.{suffix}")
            suffix += 1
        return candidate

    @staticmethod
    def fleet_reservation_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"founding.fleet:{project_id}")

    @staticmethod
    def demand_id(project_id: ProjectId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"demand.founding:{project_id}:{resource_id}")

    @staticmethod
    def payload_owner_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"founding.payload:{project_id}")

    def active_project_for_cell(self, cell_id: SurfaceCellId) -> LocationFoundingProject | None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.target_core_cell_id == cell_id and project.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}:
                return project
        return None

    def planning_failures(
        self,
        staging_node_id: SpatialNodeId,
        body_id: CelestialBodyId,
        cell_id: SurfaceCellId,
        package_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[FoundingBlocker, ...]:
        graph = self.facilities.environment.graph
        failures: list[FoundingBlocker] = []
        for code, detail in graph.location_foundation_failures(body_id, cell_id):
            failures.append(FoundingBlocker(code, detail))
        active = self.active_project_for_cell(cell_id)
        if active is not None:
            failures.append(FoundingBlocker("founding_active", str(active.id)))
        if self.external_cell_claim_provider is not None:
            owner = self.external_cell_claim_provider(cell_id)
            if owner is not None:
                failures.append(FoundingBlocker("cell_claimed", str(owner)))
        package = self.packages.get(package_id)
        if package is None:
            failures.append(FoundingBlocker("founding_package", str(package_id)))
            return tuple(failures)
        if not graph.has_operational_node(staging_node_id):
            failures.append(FoundingBlocker("staging_node", str(staging_node_id)))
            return tuple(failures)
        if self.surface_knowledge_level_provider is not None:
            actual = self.surface_knowledge_level_provider(cell_id)
            if actual < package.minimum_survey_knowledge_level:
                failures.append(FoundingBlocker("survey_knowledge", f"{actual}/{package.minimum_survey_knowledge_level}"))
        snapshot = power
        preparation_capacity = (
            self.facilities.nominal_service_capacity_at(
                staging_node_id, package.preparation_service_type, day
            )
            if snapshot is None
            else self.facilities.enabled_service_capacity_at(
                staging_node_id, package.preparation_service_type, snapshot, day
            )
        )
        if preparation_capacity <= 1e-12:
            failures.append(FoundingBlocker("staging_service", package.preparation_service_type))
        for failure in evaluate_site_requirements(
            package.staging_requirements,
            staging_node_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
        ):
            failures.append(FoundingBlocker(f"staging:{failure.code}", failure.detail))
        for failure in evaluate_environment_requirements(
            package.target_requirements,
            cell_id,
            day,
            self.facilities.environment,
        ):
            failures.append(FoundingBlocker(f"target:{failure.code}", failure.detail))
        if self.transport.vehicle_definition(vehicle_definition_id) is None:
            failures.append(FoundingBlocker("vehicle_definition", str(vehicle_definition_id)))
            return tuple(failures)
        failures.extend(
            FoundingBlocker("deployment_vehicle", detail)
            for detail in self.transport.deployment_vehicle_failures(
                vehicle_definition_id,
                staging_node_id,
                cell_id,
                package.operations,
                package.payload_t_per_unit,
                package.transit_days,
                day=day,
            )
        )
        free = self.transport.fleet_free_units(vehicle_definition_id, staging_node_id)
        if free < package.required_units:
            failures.append(FoundingBlocker("fleet_units", f"{free}/{package.required_units}"))
        return tuple(failures)

    def plan(
        self,
        staging_node_id: SpatialNodeId,
        display_name: str,
        body_id: CelestialBodyId,
        cell_id: SurfaceCellId,
        package_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        *,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        preferred_source_id: SpatialNodeId | None = None,
        day: int = 0,
    ) -> ProjectId:
        if not display_name:
            raise ValueError("location display name must not be empty")
        if preferred_source_id is not None:
            if not self.facilities.environment.graph.has_operational_node(preferred_source_id):
                raise KeyError(preferred_source_id)
            if preferred_source_id == staging_node_id:
                raise ValueError("preferred source must differ from staging node")
        failures = self.planning_failures(staging_node_id, body_id, cell_id, package_id, vehicle_definition_id, day)
        if failures:
            raise ValueError("; ".join(f"{row.code}: {row.detail}" for row in failures))
        self._counter += 1
        project_id = ProjectId(f"founding.{self._counter}")
        project = LocationFoundingProject(
            project_id,
            staging_node_id,
            display_name,
            body_id,
            cell_id,
            self._generated_location_id(body_id, cell_id),
            package_id,
            vehicle_definition_id,
            priority,
            preferred_source_id,
        )
        self.projects[project_id] = project
        package = self.packages[package_id]
        self.transport.reserve_fleet_units(
            self.fleet_reservation_id(project_id),
            EntityId(project_id),
            FleetReservationKind.SPECIAL_MISSION,
            vehicle_definition_id,
            staging_node_id,
            package.required_units,
        )
        return project_id

    def resource_requirements_for(
        self, package_id: DefinitionId, vehicle_definition_id: DefinitionId
    ) -> tuple[FoundingResourceRequirement, ...]:
        """Return the complete staging-side resource requirement for a deployment.

        The package owns payload composition while Transport owns propellant
        requirements.  Application projections consume this aggregate contract
        instead of reconstructing either rule.
        """
        package = self.packages[package_id]
        totals: dict[DefinitionId, float] = {
            req.resource_id: req.amount_t for req in package.payload_resources
        }
        propellant = self.transport.deployment_propellant_t(
            vehicle_definition_id,
            package.operations,
            package.payload_t_per_unit,
        ) * package.required_units
        vehicle = self.transport.vehicle_definition(vehicle_definition_id)
        if vehicle is None:
            raise KeyError(vehicle_definition_id)
        if vehicle.propellant_resource_id is not None and propellant > 1e-12:
            totals[vehicle.propellant_resource_id] = (
                totals.get(vehicle.propellant_resource_id, 0.0) + propellant
            )
        return tuple(
            FoundingResourceRequirement(resource_id, amount_t)
            for resource_id, amount_t in sorted(totals.items(), key=lambda row: str(row[0]))
            if amount_t > 1e-12
        )

    def project_resource_requirements(
        self, project_id: ProjectId
    ) -> tuple[FoundingResourceRequirement, ...]:
        project = self.projects[project_id]
        return self.resource_requirements_for(
            project.founding_package_id, project.vehicle_definition_id
        )

    def staged_payload_t(self, project_id: ProjectId, resource_id: DefinitionId) -> float:
        project = self.projects[project_id]
        return self.inventory.staged_for(
            self.payload_owner_id(project.id), project.staging_node_id, resource_id
        )

    def project_resource_status(
        self, project_id: ProjectId
    ) -> tuple[FoundingResourceStatus, ...]:
        project = self.projects[project_id]
        rows: list[FoundingResourceStatus] = []
        for requirement in self.project_resource_requirements(project_id):
            reserved = 0.0
            staged = self.staged_payload_t(project.id, requirement.resource_id)
            if project.status is FoundingStatus.PREPARING:
                committed = staged
                shortage = max(0.0, requirement.amount_t - staged)
            elif project.status in {FoundingStatus.DEPLOYING, FoundingStatus.COMPLETE}:
                committed = requirement.amount_t
                shortage = 0.0
            else:
                committed = 0.0
                shortage = 0.0
            rows.append(FoundingResourceStatus(
                requirement.resource_id,
                requirement.amount_t,
                reserved,
                committed,
                shortage,
            ))
        return tuple(rows)

    def resource_demands(self) -> tuple[ResourceDemand, ...]:
        rows: list[ResourceDemand] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is not FoundingStatus.PREPARING or project.inputs_consumed or project.paused:
                continue
            for requirement in self.project_resource_requirements(project.id):
                resource_id = requirement.resource_id
                amount = requirement.amount_t
                remaining = max(0.0, amount - self.staged_payload_t(project.id, resource_id))
                if remaining <= 1e-9:
                    continue
                rows.append(ResourceDemand(
                    self.demand_id(project.id, resource_id),
                    "founding",
                    EntityId(project.id),
                    project.staging_node_id,
                    resource_id,
                    remaining,
                    project.priority,
                    project.preferred_source_id,
                ))
        return tuple(rows)

    @staticmethod
    def claim_id(project_id: ProjectId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"claim.founding:{project_id}:{resource_id}")

    def resource_claims(self) -> tuple[ResourceClaim, ...]:
        rows: list[ResourceClaim] = []
        for project in sorted(self.projects.values(), key=lambda row: (-row.priority, str(row.id))):
            if project.status is not FoundingStatus.PREPARING or project.inputs_consumed or project.paused:
                continue
            for requirement in self.project_resource_requirements(project.id):
                staged = self.staged_payload_t(project.id, requirement.resource_id)
                missing = max(0.0, requirement.amount_t - staged)
                if missing <= 1e-9:
                    continue
                rows.append(ResourceClaim(
                    self.claim_id(project.id, requirement.resource_id),
                    project.staging_node_id,
                    requirement.resource_id,
                    missing,
                    project.priority,
                    "founding",
                    EntityId(project.id),
                    "payload_preparation",
                    demand_id=self.demand_id(project.id, requirement.resource_id),
                ))
        return tuple(rows)

    def _commit_allocated_payload(
        self, project: LocationFoundingProject, allocations: ResourceAllocationPlan
    ) -> bool:
        """Move this tick's founding allocation into durable payload staging."""
        payload_owner = self.payload_owner_id(project.id)
        all_committed = True
        for requirement in self.project_resource_requirements(project.id):
            resource_id = requirement.resource_id
            amount = requirement.amount_t
            staged = self.staged_payload_t(project.id, resource_id)
            missing = max(0.0, amount - staged)
            if missing <= 1e-9:
                continue
            try:
                allocated = allocations.allocated(self.claim_id(project.id, resource_id))
            except KeyError:
                allocated = 0.0
            commit = min(missing, max(0.0, allocated))
            if commit > 1e-12:
                self.inventory.stage_allocated(
                    payload_owner, project.staging_node_id, resource_id, commit
                )
                staged += commit
            if staged + 1e-9 < amount:
                all_committed = False
        project.inputs_consumed = all_committed
        return all_committed

    def _release_prepared_payload(self, project: LocationFoundingProject) -> None:
        payload_owner = self.payload_owner_id(project.id)
        for requirement in self.project_resource_requirements(project.id):
            resource_id = requirement.resource_id
            staged = self.staged_payload_t(project.id, resource_id)
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    payload_owner, project.staging_node_id, resource_id, staged
                )

    def _restore_prepared_payload(self, project: LocationFoundingProject) -> None:
        payload_owner = self.payload_owner_id(project.id)
        for requirement in self.project_resource_requirements(project.id):
            resource_id = requirement.resource_id
            staged = self.staged_payload_t(project.id, resource_id)
            if staged > 1e-12:
                self.inventory.unstage_to_stock(
                    payload_owner, project.staging_node_id, resource_id, staged
                )

    def blockers(self, project_id: ProjectId, day: int = 0, power: PowerSnapshot | None = None) -> tuple[FoundingBlocker, ...]:
        project = self.projects[project_id]
        if project.status in {FoundingStatus.COMPLETE, FoundingStatus.CANCELLED}:
            return ()
        graph = self.facilities.environment.graph
        failures: list[FoundingBlocker] = []
        owner = graph.owner_of_cell(project.target_core_cell_id)
        if owner is not None:
            failures.append(FoundingBlocker("cell_owned", str(owner)))
        if self.external_cell_claim_provider is not None:
            claimant = self.external_cell_claim_provider(project.target_core_cell_id)
            if claimant is not None:
                failures.append(FoundingBlocker("cell_claimed", str(claimant)))
        if project.status is FoundingStatus.PREPARING:
            package = self.packages[project.founding_package_id]
            snapshot = power
            preparation_capacity = (
                self.facilities.nominal_service_capacity_at(
                    project.staging_node_id, package.preparation_service_type, day
                )
                if snapshot is None
                else self.facilities.enabled_service_capacity_at(
                    project.staging_node_id, package.preparation_service_type, snapshot, day
                )
            )
            if preparation_capacity <= 1e-12:
                failures.append(FoundingBlocker("staging_service", package.preparation_service_type))
            if not project.inputs_consumed:
                for requirement in self.project_resource_requirements(project.id):
                    resource_id = requirement.resource_id
                    amount = requirement.amount_t
                    staged = self.staged_payload_t(project.id, resource_id)
                    if staged + 1e-9 < amount:
                        failures.append(FoundingBlocker("resource_shortage", str(resource_id)))
        return tuple(failures)

    def pause(self, project_id: ProjectId) -> None:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            raise ValueError("founding can only pause during preparation")
        project.paused = True

    def resume(self, project_id: ProjectId) -> None:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            raise ValueError("founding can only resume during preparation")
        project.paused = False

    def set_priority(self, project_id: ProjectId, priority: ActivityPriority) -> None:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            raise ValueError("founding priority can only change during preparation")
        project.priority = ActivityPriority(priority)

    def cancel(self, project_id: ProjectId, day: int = 0) -> None:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            raise ValueError("founding cannot be cancelled after deployment begins")
        self._restore_prepared_payload(project)
        project.inputs_consumed = False
        reservation_id = self.fleet_reservation_id(project_id)
        if self.transport.fleet_reservation_snapshot(reservation_id) is not None:
            self.transport.release_fleet_reservation(reservation_id, day=day)
        project.status = FoundingStatus.CANCELLED
        project.paused = False

    @staticmethod
    def service_request_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"service.founding_preparation:{project_id}")

    def service_requests(self, day: int = 0) -> tuple[ServiceCapacityRequest, ...]:
        requests: list[ServiceCapacityRequest] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is not FoundingStatus.PREPARING or project.paused:
                continue
            package = self.packages[project.founding_package_id]
            remaining = max(0.0, package.preparation_work - project.preparation_done)
            if remaining <= 1e-12:
                continue
            requests.append(
                ServiceCapacityRequest(
                    self.service_request_id(project.id),
                    project.staging_node_id,
                    package.preparation_service_type,
                    remaining,
                    project.priority,
                    "founding",
                    EntityId(str(project.id)),
                    "preparation_work",
                )
            )
        return tuple(requests)

    def advance_day(
        self,
        allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is FoundingStatus.PREPARING:
                if project.paused:
                    continue
                power = None if power_by_location is None else power_by_location.get(
                    project.staging_node_id
                )
                blockers = self.blockers(project.id, day, power)
                non_resource = [b for b in blockers if b.code != "resource_shortage"]
                if non_resource:
                    continue
                if not project.inputs_consumed and not self._commit_allocated_payload(project, allocations):
                    continue
                package = self.packages[project.founding_package_id]
                try:
                    allocated_service = service_allocations.allocated(
                        self.service_request_id(project.id)
                    )
                except KeyError:
                    allocated_service = 0.0
                remaining = max(0.0, package.preparation_work - project.preparation_done)
                project.preparation_done += min(
                    remaining, max(0.0, allocated_service)
                )
                if project.preparation_done + 1e-9 >= package.preparation_work:
                    project.preparation_done = package.preparation_work
                    self._release_prepared_payload(project)
                    project.status = FoundingStatus.DEPLOYING
                    project.departure_day = day
                    project.arrival_day = day + package.transit_days

    def settle_arrivals(self, day: int) -> None:
        """Complete deployments whose arrival time was reached before this tick."""
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.status is FoundingStatus.DEPLOYING
                and project.arrival_day is not None
                and project.arrival_day <= day
            ):
                self._complete(project, day)

    def _complete(self, project: LocationFoundingProject, day: int) -> None:
        graph = self.facilities.environment.graph
        if graph.owner_of_cell(project.target_core_cell_id) is not None:
            raise RuntimeError(f"founding target cell became occupied: {project.target_core_cell_id}")
        graph.found_location(
            project.new_location_id,
            project.display_name,
            project.target_body_id,
            project.target_core_cell_id,
        )
        package = self.packages[project.founding_package_id]
        for deployment in package.deployed_facilities:
            definition = self.facilities.definitions[deployment.facility_def_id]
            site_cell_id = project.target_core_cell_id if (
                deployment.place_at_core_cell or definition.placement_scope is FacilityPlacementScope.SURFACE_CELL
            ) else None
            self.facilities.install(
                deployment.facility_def_id,
                project.new_location_id,
                site_cell_id=site_cell_id,
                invested_resources={req.resource_id: req.amount_t for req in deployment.invested_resources},
            )
        if package.initial_inventory:
            # Founding completion is a boundary transition.  Establish the new
            # physical/nominal storage envelope without privately allocating
            # Power; current-tick usable capacity is derived by Simulation's
            # allocation graph after the boundary.
            self.storage.refresh(day, {})
            for req in package.initial_inventory:
                self.inventory.add(project.new_location_id, req.resource_id, req.amount_t)
        reservation_id = self.fleet_reservation_id(project.id)
        if self.transport.fleet_reservation_snapshot(reservation_id) is not None:
            disposition = self.transport.deployment_asset_disposition(
                project.vehicle_definition_id, package.operations
            )
            final_location = (
                project.new_location_id
                if disposition is OperationAssetDisposition.DESTINATION
                else project.staging_node_id
            )
            self.transport.complete_fleet_reservation(
                reservation_id, final_location_id=final_location, day=day
            )
        project.status = FoundingStatus.COMPLETE
        project.completed_day = day
        project.paused = False
