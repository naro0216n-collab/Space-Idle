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
from .service_capacity import ServiceCapacityRegistry
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ResourceRequirement,
    ServiceCapacityRequirement,
)
from .supply import SupplyRequirement
from .spatial_claims import SurfaceCellClaim, SurfaceCellClaimRegistry
from .shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements, evaluate_physical_site_requirements, evaluate_site_requirements
from .storage import StorageService
from .transport.models import (
    FleetActivityRef, MovementExecutionKind, MovementExecutionPayloadResource,
    OperationAssetDisposition,
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
    fleet_commitment_id: EntityId | None = None
    status: FoundingStatus = FoundingStatus.PREPARING
    preparation_done: float = 0.0
    inputs_consumed: bool = False
    paused: bool = False
    movement_execution_id: EntityId | None = None
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
    service_capacity_registry: ServiceCapacityRegistry
    surface_knowledge_level_provider: Callable[[SurfaceCellId], int] | None = None
    surface_cell_claim_registry: SurfaceCellClaimRegistry = field(default_factory=SurfaceCellClaimRegistry)
    projects: dict[ProjectId, LocationFoundingProject] = field(default_factory=dict)
    _counter: int = 0

    def __post_init__(self) -> None:
        self.surface_cell_claim_registry.register(self)

    def surface_cell_claims(self) -> tuple[SurfaceCellClaim, ...]:
        return tuple(
            SurfaceCellClaim(
                project.target_core_cell_id,
                "founding_project",
                EntityId(project.id),
                "location_founding",
            )
            for project in sorted(self.projects.values(), key=lambda row: str(row.id))
            if project.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}
        )

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
    def fleet_commitment_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"fleet.commitment.founding:{project_id}")

    @staticmethod
    def requirement_id(project_id: ProjectId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"requirement.founding:{project_id}:{resource_id}")

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
        for claim in self.surface_cell_claim_registry.claims_for(cell_id):
            failures.append(FoundingBlocker("cell_claimed", str(claim.claimant_id)))
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
        preparation_capacity = self.service_capacity_registry.available_at(
            staging_node_id,
            package.preparation_service_type,
            self.facilities,
            snapshot,
            day,
        )
        if preparation_capacity <= 1e-12:
            failures.append(FoundingBlocker("staging_service", package.preparation_service_type))
        for failure in evaluate_site_requirements(
            package.staging_requirements,
            staging_node_id,
            day,
            self.facilities.environment,
            self.facilities,
        ):
            failures.append(FoundingBlocker(f"staging:{failure.code}", failure.detail))
        for failure in evaluate_physical_site_requirements(
            package.target_requirements,
            cell_id,
            day,
            self.facilities.environment,
        ):
            failures.append(FoundingBlocker(f"target:{failure.code}", failure.detail))
        if self.transport.vehicle_definition(vehicle_definition_id) is None:
            failures.append(FoundingBlocker("vehicle_definition", str(vehicle_definition_id)))
            return tuple(failures)
        try:
            movement_plan = self.transport.movement_plan_to_physical_target_for_vehicle(
                staging_node_id,
                cell_id,
                vehicle_definition_id,
                payload_t_per_unit=package.payload_t_per_unit,
                day=day,
            )
        except ValueError as exc:
            failures.append(FoundingBlocker("deployment_vehicle", str(exc)))
        else:
            failures.extend(
                FoundingBlocker("deployment_vehicle", detail)
                for detail in (
                    *self.transport.movement_plan_failures(movement_plan.id, day),
                    *self.transport.vehicle_movement_failures(
                        movement_plan.id, vehicle_definition_id, day
                    ),
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
        commitment_id = self.fleet_commitment_id(project_id)
        self.transport.commit_fleet_units(
            commitment_id,
            FleetActivityRef("founding", EntityId(str(project_id))),
            vehicle_definition_id,
            staging_node_id,
            package.required_units,
        )
        project.fleet_commitment_id = commitment_id
        return project_id

    def resource_requirements_for(
        self,
        package_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        staging_node_id: SpatialNodeId,
        target_cell_id: SurfaceCellId,
        *,
        day: int = 0,
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
        movement_plan = self.transport.movement_plan_to_physical_target_for_vehicle(
            staging_node_id,
            target_cell_id,
            vehicle_definition_id,
            payload_t_per_unit=package.payload_t_per_unit,
            day=day,
        )
        vehicle = self.transport.vehicle_definition(vehicle_definition_id)
        if vehicle is None:
            raise KeyError(vehicle_definition_id)
        propellant = vehicle.propellant_t(
            movement_plan, package.payload_t_per_unit
        ) * package.required_units
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
            project.founding_package_id,
            project.vehicle_definition_id,
            project.staging_node_id,
            project.target_core_cell_id,
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

    def supplys(self) -> tuple[SupplyRequirement, ...]:
        rows: list[SupplyRequirement] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is not FoundingStatus.PREPARING or project.inputs_consumed or project.paused:
                continue
            for requirement in self.project_resource_requirements(project.id):
                resource_id = requirement.resource_id
                amount = requirement.amount_t
                remaining = max(0.0, amount - self.staged_payload_t(project.id, resource_id))
                if remaining <= 1e-9:
                    continue
                rows.append(SupplyRequirement(
                    self.requirement_id(project.id, resource_id),
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
    def payload_execution_id(project_id: ProjectId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"execution.founding_payload:{project_id}:{resource_id}")

    @staticmethod
    def preparation_execution_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"execution.founding_preparation:{project_id}")

    def execution_requirement_bundles(
        self, day: int = 0
    ) -> tuple[ExecutionRequirementBundle, ...]:
        del day
        rows: list[ExecutionRequirementBundle] = []
        for project in sorted(self.projects.values(), key=lambda row: (-row.priority, str(row.id))):
            if project.status is not FoundingStatus.PREPARING or project.paused:
                continue
            if not project.inputs_consumed:
                for requirement in self.project_resource_requirements(project.id):
                    staged = self.staged_payload_t(project.id, requirement.resource_id)
                    missing = max(0.0, requirement.amount_t - staged)
                    if missing <= 1e-9:
                        continue
                    rows.append(ExecutionRequirementBundle(
                        id=self.payload_execution_id(project.id, requirement.resource_id),
                        owner_kind="founding",
                        owner_id=EntityId(project.id),
                        purpose="payload_preparation",
                        operational_node_id=project.staging_node_id,
                        requested_execution=missing,
                        priority=project.priority,
                        requirements=(ResourceRequirement(requirement.resource_id, 1.0),),
                    ))

            package = self.packages[project.founding_package_id]
            remaining = max(0.0, package.preparation_work - project.preparation_done)
            if remaining > 1e-12:
                rows.append(ExecutionRequirementBundle(
                    id=self.preparation_execution_id(project.id),
                    owner_kind="founding",
                    owner_id=EntityId(project.id),
                    purpose="preparation_work",
                    operational_node_id=project.staging_node_id,
                    requested_execution=remaining,
                    priority=project.priority,
                    requirements=(
                        ServiceCapacityRequirement(package.preparation_service_type, 1.0),
                    ),
                ))
        return tuple(rows)

    def _commit_allocated_payload(
        self, project: LocationFoundingProject, allocations: ExecutionAllocationPlan
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
                allocated = allocations.allocated(
                    self.payload_execution_id(project.id, resource_id)
                )
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
        for claim in self.surface_cell_claim_registry.claims_for(
            project.target_core_cell_id,
            exclude=("founding_project", EntityId(project.id)),
        ):
            failures.append(FoundingBlocker("cell_claimed", str(claim.claimant_id)))
        if project.status is FoundingStatus.PREPARING:
            package = self.packages[project.founding_package_id]
            snapshot = power
            preparation_capacity = self.service_capacity_registry.available_at(
                project.staging_node_id,
                package.preparation_service_type,
                self.facilities,
                snapshot,
                day,
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
        if project.fleet_commitment_id is not None:
            self.transport.release_fleet_commitment(project.fleet_commitment_id, day=day)
            project.fleet_commitment_id = None
        project.status = FoundingStatus.CANCELLED
        project.paused = False

    def advance_day(
        self,
        allocations: ExecutionAllocationPlan,
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
                    allocated_service = allocations.allocated(
                        self.preparation_execution_id(project.id)
                    )
                except KeyError:
                    allocated_service = 0.0
                remaining = max(0.0, package.preparation_work - project.preparation_done)
                project.preparation_done += min(
                    remaining, max(0.0, allocated_service)
                )
                if project.preparation_done + 1e-9 >= package.preparation_work:
                    project.preparation_done = package.preparation_work
                    movement_plan = self.transport.movement_plan_to_physical_target_for_vehicle(
                        project.staging_node_id,
                        project.target_core_cell_id,
                        project.vehicle_definition_id,
                        payload_t_per_unit=package.payload_t_per_unit,
                        day=day,
                    )
                    execution_id = EntityId(f"movement.founding:{project.id}")
                    if project.fleet_commitment_id is None:
                        raise RuntimeError("founding Fleet commitment missing")
                    execution = self.transport.start_movement_execution_for_plan(
                        execution_id,
                        EntityId(str(project.id)),
                        MovementExecutionKind.FOUNDING_DEPLOYMENT,
                        project.fleet_commitment_id,
                        movement_plan,
                        payload_t_per_unit=package.payload_t_per_unit,
                        payload_resources=tuple(
                            MovementExecutionPayloadResource(req.resource_id, req.amount_t)
                            for req in package.payload_resources
                        ),
                        day=day,
                    )
                    try:
                        self.transport.dispatch_fleet_commitment(
                            project.fleet_commitment_id, execution.id, day=day
                        )
                    except Exception:
                        self.transport.finish_movement_execution(execution.id)
                        raise
                    self._release_prepared_payload(project)
                    project.status = FoundingStatus.DEPLOYING
                    project.movement_execution_id = execution.id

    def settle_arrivals(self, day: int) -> bool:
        """Complete deployments whose arrival time was reached before this tick."""
        physical_state_changed = False
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is not FoundingStatus.DEPLOYING:
                continue
            if project.movement_execution_id is None:
                raise RuntimeError(f"deploying founding lacks MovementExecution: {project.id}")
            execution = self.transport.movement_execution_snapshot(project.movement_execution_id)
            if execution is None:
                raise RuntimeError(f"founding MovementExecution missing: {project.id}")
            if execution.completion_day <= day:
                self._complete(project, day)
                physical_state_changed = True
        return physical_state_changed

    def _complete(self, project: LocationFoundingProject, day: int) -> None:
        graph = self.facilities.environment.graph
        if graph.owner_of_cell(project.target_core_cell_id) is not None:
            raise RuntimeError(f"founding target cell became occupied: {project.target_core_cell_id}")
        execution_id = project.movement_execution_id
        if execution_id is None:
            raise RuntimeError(f"founding completion lacks MovementExecution: {project.id}")
        execution = self.transport.movement_execution_snapshot(execution_id)
        if execution is None:
            raise RuntimeError(f"founding completion MovementExecution missing: {project.id}")
        package = self.packages[project.founding_package_id]
        expected_payload = {
            req.resource_id: req.amount_t for req in package.payload_resources
        }
        actual_payload = {
            req.resource_id: req.amount_t for req in execution.payload_resources
        }
        if actual_payload.keys() != expected_payload.keys() or any(
            abs(actual_payload[resource_id] - amount_t) > 1e-9
            for resource_id, amount_t in expected_payload.items()
        ):
            raise RuntimeError(f"founding MovementExecution payload manifest mismatch: {project.id}")
        graph.found_location(
            project.new_location_id,
            project.display_name,
            project.target_body_id,
            project.target_core_cell_id,
        )
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
        # Founding completion is a Boundary transition. Rebuild the newly
        # installed physical storage envelope before the next Physical snapshot,
        # even when the package carries no initial Inventory. Power-sensitive
        # usable capacity is refined by the canonical allocation/execution path.
        self.storage.refresh(day, {})
        if package.initial_inventory:
            for req in package.initial_inventory:
                admission = self.inventory.admit(
                    project.new_location_id, req.resource_id, req.amount_t
                )
                if not admission.fully_admitted:
                    raise RuntimeError(
                        f"founding manifest exceeds Inventory Admission: {req.resource_id}"
                    )
        final_location = (
            project.new_location_id
            if execution.final_asset_disposition is OperationAssetDisposition.DESTINATION
            else project.staging_node_id
        )
        if project.fleet_commitment_id is None:
            raise RuntimeError(f"founding completion lacks Fleet commitment: {project.id}")
        self.transport.receive_fleet_commitment(
            project.fleet_commitment_id, final_location, execution_id=execution_id, day=day
        )
        self.transport.finish_movement_execution(execution_id)
        self.transport.release_fleet_commitment(project.fleet_commitment_id, day=day)
        project.fleet_commitment_id = None
        project.movement_execution_id = None
        project.status = FoundingStatus.COMPLETE
        project.completed_day = day
        project.paused = False
