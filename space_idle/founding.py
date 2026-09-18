from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import math
from typing import Callable, TypeAlias

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
from .exploration_models import KnowledgeRequirement, KnowledgeRequirementSpec
from .spatial import OperationalNodeState
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
class DeploymentRecipe:
    id: DefinitionId
    display_name: str
    deployed_facilities: tuple[FoundingFacilityDeployment, ...]
    preparation_work: float
    preparation_service_type: str
    initial_inventory: tuple[FoundingResourceRequirement, ...] = ()
    staging_requirements: SiteRequirements = SiteRequirements()
    target_requirements: SiteRequirements = SiteRequirements()
    knowledge_requirements: tuple[KnowledgeRequirementSpec, ...] = ()
    required_units: int = 1

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("deployment recipe display name must not be empty")
        if self.preparation_work < 0:
            raise ValueError("founding preparation work must be non-negative")
        if not self.preparation_service_type:
            raise ValueError("founding preparation capability must not be empty")
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


@dataclass(frozen=True)
class SurfaceLocationTargetSpec:
    body_id: CelestialBodyId
    core_cell_id: SurfaceCellId
    operational_node_id: SpatialNodeId


@dataclass(frozen=True)
class NonSurfaceOperationalNodeTargetSpec:
    spatial_node_id: SpatialNodeId


FoundingTargetSpec: TypeAlias = SurfaceLocationTargetSpec | NonSurfaceOperationalNodeTargetSpec


@dataclass
class OperationalNodeFoundingProject:
    id: ProjectId
    staging_node_id: SpatialNodeId
    display_name: str
    target_spec: FoundingTargetSpec
    deployment_recipe_id: DefinitionId
    vehicle_definition_id: DefinitionId
    resource_requirements: tuple[FoundingResourceRequirement, ...]
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
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
class OperationalNodeFoundingService:
    deployment_recipes: dict[DefinitionId, DeploymentRecipe]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    transport: TransportService
    storage: StorageService
    service_capacity_registry: ServiceCapacityRegistry
    knowledge_requirement_failures: Callable[[KnowledgeRequirement], tuple[str, ...]] | None = None
    surface_cell_claim_registry: SurfaceCellClaimRegistry = field(default_factory=SurfaceCellClaimRegistry)
    projects: dict[ProjectId, OperationalNodeFoundingProject] = field(default_factory=dict)
    _counter: int = 0

    def __post_init__(self) -> None:
        self.surface_cell_claim_registry.register(self)

    def surface_cell_claims(self) -> tuple[SurfaceCellClaim, ...]:
        rows: list[SurfaceCellClaim] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status not in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}:
                continue
            if isinstance(project.target_spec, SurfaceLocationTargetSpec):
                rows.append(SurfaceCellClaim(
                    project.target_spec.core_cell_id,
                    "founding_project",
                    EntityId(project.id),
                    "operational_node_founding",
                ))
        return tuple(rows)

    def _generated_location_id(self, body_id: CelestialBodyId, cell_id: SurfaceCellId) -> SpatialNodeId:
        digest = sha256(f"{body_id}\0{cell_id}".encode("utf-8")).hexdigest()[:24]
        base = f"player.location.{digest}"
        graph = self.facilities.environment.graph
        occupied = set(graph.nodes) | set(graph.locations) | set(graph.operational_node_ids())
        occupied.update(
            p.target_spec.operational_node_id
            for p in self.projects.values()
            if isinstance(p.target_spec, SurfaceLocationTargetSpec)
            and p.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}
        )
        candidate = SpatialNodeId(base)
        suffix = 2
        while candidate in occupied:
            candidate = SpatialNodeId(f"{base}.{suffix}")
            suffix += 1
        return candidate

    def surface_target_spec(
        self, body_id: CelestialBodyId, cell_id: SurfaceCellId
    ) -> SurfaceLocationTargetSpec:
        return SurfaceLocationTargetSpec(
            body_id, cell_id, self._generated_location_id(body_id, cell_id)
        )

    @staticmethod
    def target_type(target_spec: FoundingTargetSpec) -> str:
        return "surface_location" if isinstance(target_spec, SurfaceLocationTargetSpec) else "non_surface_operational_node"

    @staticmethod
    def target_operational_node_id(target_spec: FoundingTargetSpec) -> SpatialNodeId:
        if isinstance(target_spec, SurfaceLocationTargetSpec):
            return target_spec.operational_node_id
        return target_spec.spatial_node_id

    @staticmethod
    def target_surface_cell_id(target_spec: FoundingTargetSpec) -> SurfaceCellId | None:
        return target_spec.core_cell_id if isinstance(target_spec, SurfaceLocationTargetSpec) else None

    @staticmethod
    def target_body_id(target_spec: FoundingTargetSpec) -> CelestialBodyId | None:
        return target_spec.body_id if isinstance(target_spec, SurfaceLocationTargetSpec) else None

    def target_context_id(self, target_spec: FoundingTargetSpec) -> SpatialNodeId | SurfaceCellId:
        if isinstance(target_spec, SurfaceLocationTargetSpec):
            return target_spec.core_cell_id
        return target_spec.spatial_node_id

    def movement_plan_for_target(
        self,
        staging_node_id: SpatialNodeId,
        target_spec: FoundingTargetSpec,
        vehicle_definition_id: DefinitionId,
        payload_t_per_unit: float,
        day: int,
    ):
        if isinstance(target_spec, SurfaceLocationTargetSpec):
            return self.transport.movement_plan_to_physical_target_for_vehicle(
                staging_node_id, target_spec.core_cell_id, vehicle_definition_id,
                payload_t_per_unit=payload_t_per_unit, day=day,
            )
        return self.transport.movement_plan_to_non_surface_physical_target_for_vehicle(
            staging_node_id, target_spec.spatial_node_id, vehicle_definition_id,
            payload_t_per_unit=payload_t_per_unit, day=day,
        )

    def knowledge_requirements_for_target(
        self, target_spec: FoundingTargetSpec, recipe: DeploymentRecipe
    ) -> tuple[KnowledgeRequirement, ...]:
        if not isinstance(target_spec, SurfaceLocationTargetSpec):
            return ()
        return tuple(req.bind(target_spec.core_cell_id) for req in recipe.knowledge_requirements)

    @staticmethod
    def fleet_commitment_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"fleet.commitment.founding:{project_id}")

    @staticmethod
    def requirement_id(project_id: ProjectId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"requirement.founding:{project_id}:{resource_id}")

    @staticmethod
    def payload_owner_id(project_id: ProjectId) -> EntityId:
        return EntityId(f"founding.payload:{project_id}")

    def active_project_for_cell(self, cell_id: SurfaceCellId) -> OperationalNodeFoundingProject | None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                isinstance(project.target_spec, SurfaceLocationTargetSpec)
                and project.target_spec.core_cell_id == cell_id
                and project.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}
            ):
                return project
        return None

    def planning_failures(
        self,
        staging_node_id: SpatialNodeId,
        target_spec: FoundingTargetSpec,
        recipe_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[FoundingBlocker, ...]:
        del power
        graph = self.facilities.environment.graph
        failures: list[FoundingBlocker] = []
        recipe = self.deployment_recipes.get(recipe_id)
        if recipe is None:
            return (FoundingBlocker("deployment_recipe", str(recipe_id)),)
        if not graph.has_operational_node(staging_node_id):
            return (FoundingBlocker("staging_node", str(staging_node_id)),)

        if isinstance(target_spec, SurfaceLocationTargetSpec):
            for code, detail in graph.location_foundation_failures(
                target_spec.body_id, target_spec.core_cell_id
            ):
                failures.append(FoundingBlocker(code, detail))
            if (
                target_spec.operational_node_id in graph.nodes
                or target_spec.operational_node_id in graph.locations
                or graph.has_operational_node(target_spec.operational_node_id)
            ):
                failures.append(FoundingBlocker("target_operational_node", str(target_spec.operational_node_id)))
            for claim in self.surface_cell_claim_registry.claims_for(target_spec.core_cell_id):
                failures.append(FoundingBlocker("cell_claimed", str(claim.claimant_id)))
            if self.knowledge_requirement_failures is not None:
                for requirement in self.knowledge_requirements_for_target(target_spec, recipe):
                    for detail in self.knowledge_requirement_failures(requirement):
                        failures.append(FoundingBlocker("knowledge_requirement", detail))
        else:
            if target_spec.spatial_node_id not in graph.nodes:
                failures.append(FoundingBlocker("target_spatial_node", str(target_spec.spatial_node_id)))
            elif graph.has_operational_node(target_spec.spatial_node_id):
                failures.append(FoundingBlocker("target_already_operational", str(target_spec.spatial_node_id)))
            if recipe.knowledge_requirements:
                failures.append(FoundingBlocker(
                    "knowledge_target_type",
                    "surface Resource Knowledge requirements require a Surface Location target",
                ))
            for deployment in recipe.deployed_facilities:
                definition = self.facilities.definitions.get(deployment.facility_def_id)
                if definition is not None and (
                    deployment.place_at_core_cell
                    or definition.placement_scope is FacilityPlacementScope.SURFACE_CELL
                ):
                    failures.append(FoundingBlocker(
                        "surface_facility_target", str(deployment.facility_def_id)
                    ))

        for failure in evaluate_site_requirements(
            recipe.staging_requirements, staging_node_id, day,
            self.facilities.environment, self.facilities,
        ):
            failures.append(FoundingBlocker(f"staging:{failure.code}", failure.detail))
        try:
            target_context_id = self.target_context_id(target_spec)
            for failure in evaluate_physical_site_requirements(
                recipe.target_requirements, target_context_id, day, self.facilities.environment
            ):
                failures.append(FoundingBlocker(f"target:{failure.code}", failure.detail))
        except KeyError as exc:
            failures.append(FoundingBlocker("target_context", str(exc)))

        if self.transport.vehicle_definition(vehicle_definition_id) is None:
            failures.append(FoundingBlocker("vehicle_definition", str(vehicle_definition_id)))
            return tuple(failures)
        try:
            movement_plan = self.movement_plan_for_target(
                staging_node_id, target_spec, vehicle_definition_id,
                recipe.payload_t_per_unit, day,
            )
        except (KeyError, ValueError) as exc:
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
        if free < recipe.required_units:
            failures.append(FoundingBlocker("fleet_units", f"{free}/{recipe.required_units}"))
        return tuple(failures)

    def plan(
        self,
        staging_node_id: SpatialNodeId,
        display_name: str,
        target_spec: FoundingTargetSpec,
        recipe_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        *,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        day: int = 0,
    ) -> ProjectId:
        if not display_name:
            raise ValueError("operational node display name must not be empty")
        failures = self.planning_failures(
            staging_node_id, target_spec, recipe_id, vehicle_definition_id, day
        )
        if failures:
            raise ValueError("; ".join(f"{row.code}: {row.detail}" for row in failures))
        next_counter = self._counter + 1
        project_id = ProjectId(f"founding.{next_counter}")
        recipe = self.deployment_recipes[recipe_id]
        resource_requirements = self.resource_requirements_for(
            recipe_id, vehicle_definition_id, staging_node_id, target_spec, day=day
        )
        commitment_id = self.fleet_commitment_id(project_id)
        self.transport.commit_fleet_units(
            commitment_id,
            FleetActivityRef("founding", EntityId(str(project_id))),
            vehicle_definition_id, staging_node_id, recipe.required_units,
        )
        project = OperationalNodeFoundingProject(
            project_id, staging_node_id, display_name, target_spec, recipe_id,
            vehicle_definition_id, resource_requirements, priority,
            fleet_commitment_id=commitment_id,
        )
        self.projects[project_id] = project
        self._counter = next_counter
        return project_id

    def resource_requirements_for(
        self,
        recipe_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        staging_node_id: SpatialNodeId,
        target_spec: FoundingTargetSpec,
        *,
        day: int = 0,
    ) -> tuple[FoundingResourceRequirement, ...]:
        recipe = self.deployment_recipes[recipe_id]
        totals: dict[DefinitionId, float] = {
            req.resource_id: req.amount_t for req in recipe.payload_resources
        }
        movement_plan = self.movement_plan_for_target(
            staging_node_id, target_spec, vehicle_definition_id,
            recipe.payload_t_per_unit, day,
        )
        vehicle = self.transport.vehicle_definition(vehicle_definition_id)
        if vehicle is None:
            raise KeyError(vehicle_definition_id)
        propellant = vehicle.propellant_t(
            movement_plan, recipe.payload_t_per_unit
        ) * recipe.required_units
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
        return self.projects[project_id].resource_requirements

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
                staged,
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

            recipe = self.deployment_recipes[project.deployment_recipe_id]
            remaining = max(0.0, recipe.preparation_work - project.preparation_done)
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
                        ServiceCapacityRequirement(recipe.preparation_service_type, 1.0),
                    ),
                ))
        return tuple(rows)

    def _commit_allocated_payload(
        self, project: OperationalNodeFoundingProject, allocations: ExecutionAllocationPlan
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

    def _release_prepared_payload(self, project: OperationalNodeFoundingProject) -> None:
        payload_owner = self.payload_owner_id(project.id)
        for requirement in self.project_resource_requirements(project.id):
            resource_id = requirement.resource_id
            staged = self.staged_payload_t(project.id, resource_id)
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    payload_owner, project.staging_node_id, resource_id, staged
                )

    def _restore_prepared_payload(self, project: OperationalNodeFoundingProject) -> None:
        payload_owner = self.payload_owner_id(project.id)
        for requirement in self.project_resource_requirements(project.id):
            resource_id = requirement.resource_id
            staged = self.staged_payload_t(project.id, resource_id)
            if staged > 1e-12:
                self.inventory.unstage_to_stock(
                    payload_owner, project.staging_node_id, resource_id, staged
                )

    def blockers(
        self, project_id: ProjectId, day: int = 0, power: PowerSnapshot | None = None
    ) -> tuple[FoundingBlocker, ...]:
        project = self.projects[project_id]
        if project.status in {FoundingStatus.COMPLETE, FoundingStatus.CANCELLED}:
            return ()
        failures = list(self.planning_failures(
            project.staging_node_id, project.target_spec, project.deployment_recipe_id,
            project.vehicle_definition_id, day, power,
        ))
        # The project's own Surface Cell and Fleet commitments are already valid
        # claims; exclude the self-conflicts that planning a new project must reject.
        if isinstance(project.target_spec, SurfaceLocationTargetSpec):
            failures = [
                row for row in failures
                if not (row.code == "cell_claimed" and row.detail == str(EntityId(project.id)))
            ]
        failures = [row for row in failures if row.code != "fleet_units"]
        if project.status is FoundingStatus.PREPARING and not project.inputs_consumed:
            for requirement in self.project_resource_requirements(project.id):
                staged = self.staged_payload_t(project.id, requirement.resource_id)
                if staged + 1e-9 < requirement.amount_t:
                    failures.append(FoundingBlocker("resource_shortage", str(requirement.resource_id)))
        return tuple(failures)


    def preparation_fulfillment(
        self, project_id: ProjectId, allocations: ExecutionAllocationPlan
    ) -> float:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            return 1.0
        recipe = self.deployment_recipes[project.deployment_recipe_id]
        if project.preparation_done + 1e-12 >= recipe.preparation_work:
            return 1.0
        try:
            return allocations.fulfillment(self.preparation_execution_id(project.id))
        except KeyError:
            return 0.0

    def preparation_limiting_factors(
        self, project_id: ProjectId, allocations: ExecutionAllocationPlan
    ) -> tuple[str, ...]:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            return ()
        try:
            allocation = allocations.allocation(self.preparation_execution_id(project.id))
        except KeyError:
            return ()
        if allocation.unmet_execution <= 1e-9:
            return ()
        factors: list[str] = []
        for key in allocation.limiting_constraints:
            if key.kind == "service":
                factors.append(f"service:{key.name}")
            else:
                factors.append(f"{key.kind}:{key.name}")
        return tuple(dict.fromkeys(factors))

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
                recipe = self.deployment_recipes[project.deployment_recipe_id]
                try:
                    allocated_service = allocations.allocated(
                        self.preparation_execution_id(project.id)
                    )
                except KeyError:
                    allocated_service = 0.0
                remaining = max(0.0, recipe.preparation_work - project.preparation_done)
                project.preparation_done += min(
                    remaining, max(0.0, allocated_service)
                )
                if project.preparation_done + 1e-9 >= recipe.preparation_work:
                    project.preparation_done = recipe.preparation_work
                    movement_plan = self.movement_plan_for_target(
                        project.staging_node_id, project.target_spec,
                        project.vehicle_definition_id, recipe.payload_t_per_unit, day,
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
                        payload_t_per_unit=recipe.payload_t_per_unit,
                        payload_resources=tuple(
                            MovementExecutionPayloadResource(req.resource_id, req.amount_t)
                            for req in recipe.payload_resources
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

    def _complete(self, project: OperationalNodeFoundingProject, day: int) -> None:
        graph = self.facilities.environment.graph
        target_spec = project.target_spec
        if isinstance(target_spec, SurfaceLocationTargetSpec):
            if graph.owner_of_cell(target_spec.core_cell_id) is not None:
                raise RuntimeError(f"founding target cell became occupied: {target_spec.core_cell_id}")
        elif graph.has_operational_node(target_spec.spatial_node_id):
            raise RuntimeError(f"founding target became operational before arrival: {target_spec.spatial_node_id}")

        execution_id = project.movement_execution_id
        if execution_id is None:
            raise RuntimeError(f"founding completion lacks MovementExecution: {project.id}")
        execution = self.transport.movement_execution_snapshot(execution_id)
        if execution is None:
            raise RuntimeError(f"founding completion MovementExecution missing: {project.id}")
        recipe = self.deployment_recipes[project.deployment_recipe_id]
        expected_payload = {req.resource_id: req.amount_t for req in recipe.payload_resources}
        actual_payload = {req.resource_id: req.amount_t for req in execution.payload_resources}
        if actual_payload.keys() != expected_payload.keys() or any(
            abs(actual_payload[resource_id] - amount_t) > 1e-9
            for resource_id, amount_t in expected_payload.items()
        ):
            raise RuntimeError(f"founding MovementExecution payload manifest mismatch: {project.id}")

        target_node_id = self.target_operational_node_id(target_spec)
        if isinstance(target_spec, SurfaceLocationTargetSpec):
            graph.found_location(
                target_spec.operational_node_id, project.display_name,
                target_spec.body_id, target_spec.core_cell_id,
            )
            core_cell_id: SurfaceCellId | None = target_spec.core_cell_id
        else:
            graph.add_operational_node(OperationalNodeState(target_spec.spatial_node_id))
            core_cell_id = None

        for deployment in recipe.deployed_facilities:
            definition = self.facilities.definitions[deployment.facility_def_id]
            if core_cell_id is None and (
                deployment.place_at_core_cell
                or definition.placement_scope is FacilityPlacementScope.SURFACE_CELL
            ):
                raise RuntimeError(
                    f"surface Facility cannot settle on non-surface founding target: {deployment.facility_def_id}"
                )
            site_cell_id = core_cell_id if (
                core_cell_id is not None
                and (deployment.place_at_core_cell or definition.placement_scope is FacilityPlacementScope.SURFACE_CELL)
            ) else None
            self.facilities.install(
                deployment.facility_def_id, target_node_id, site_cell_id=site_cell_id,
                invested_resources={
                    req.resource_id: req.amount_t for req in deployment.invested_resources
                },
            )

        self.storage.refresh(day, {})
        for req in recipe.initial_inventory:
            admission = self.inventory.admit(target_node_id, req.resource_id, req.amount_t)
            if not admission.fully_admitted:
                raise RuntimeError(
                    f"founding manifest exceeds Inventory Admission: {req.resource_id}"
                )

        final_location = (
            target_node_id
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
