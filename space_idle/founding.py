from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import math
from typing import Callable

from .facilities import FacilityBook, FacilityPlacementScope
from .inventory import InventoryBook
from .logistics import LogisticsService
from .power import PowerService, PowerSnapshot
from .resource_demand import ResourceDemand
from .shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements, evaluate_site_requirements
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
    resources: tuple[FoundingResourceRequirement, ...]
    deployed_facilities: tuple[FoundingFacilityDeployment, ...]
    preparation_work: float
    preparation_capability_id: str
    operations: tuple[TransportOperationRequirement, ...]
    transit_days: int
    site_requirements: SiteRequirements = SiteRequirements()
    minimum_survey_knowledge_level: int = 0
    required_units: int = 1

    def __post_init__(self) -> None:
        if not self.display_name:
            raise ValueError("founding package display name must not be empty")
        if self.preparation_work < 0:
            raise ValueError("founding preparation work must be non-negative")
        if not self.preparation_capability_id:
            raise ValueError("founding preparation capability must not be empty")
        if self.transit_days <= 0:
            raise ValueError("founding transit must be positive")
        if not 0 <= self.minimum_survey_knowledge_level <= 4:
            raise ValueError("founding survey knowledge must be within 0..4")
        if self.required_units <= 0:
            raise ValueError("founding required units must be positive")

    @property
    def payload_t(self) -> float:
        return math.fsum(req.amount_t for req in self.resources)

    @property
    def payload_t_per_unit(self) -> float:
        return self.payload_t / self.required_units

    def investment_totals(self) -> dict[DefinitionId, float]:
        totals: dict[DefinitionId, float] = {}
        for deployment in self.deployed_facilities:
            for req in deployment.invested_resources:
                totals[req.resource_id] = totals.get(req.resource_id, 0.0) + req.amount_t
        return totals


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
    priority: int = 50
    preferred_source_id: SpatialNodeId | None = None
    status: FoundingStatus = FoundingStatus.PREPARING
    preparation_done: float = 0.0
    inputs_consumed: bool = False
    paused: bool = False
    departure_day: int | None = None
    arrival_day: int | None = None
    completed_day: int | None = None


@dataclass(frozen=True)
class FoundingBlocker:
    code: str
    detail: str


@dataclass
class LocationFoundingService:
    packages: dict[DefinitionId, FoundingPackageDefinition]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    logistics: LogisticsService
    surface_knowledge_level_provider: Callable[[SurfaceCellId], int] | None = None
    external_cell_claim_provider: Callable[[SurfaceCellId], EntityId | None] | None = None
    projects: dict[ProjectId, LocationFoundingProject] = field(default_factory=dict)
    _counter: int = 0

    def _generated_location_id(self, body_id: CelestialBodyId, cell_id: SurfaceCellId) -> SpatialNodeId:
        digest = sha256(f"{body_id}\0{cell_id}".encode("utf-8")).hexdigest()[:24]
        base = f"player.location.{digest}"
        occupied = set(self.facilities.environment.graph.operational_node_ids())
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
        snapshot = power if power is not None else self.power.snapshot(staging_node_id, self.facilities, day)
        if self.facilities.available_capability_capacity_at(staging_node_id, package.preparation_capability_id, snapshot, day) <= 1e-12:
            failures.append(FoundingBlocker("staging_capability", package.preparation_capability_id))
        for failure in evaluate_site_requirements(
            package.site_requirements,
            staging_node_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
            environment_context_id=cell_id,
        ):
            failures.append(FoundingBlocker(failure.code, failure.detail))
        if vehicle_definition_id not in self.logistics.vehicle_defs:
            failures.append(FoundingBlocker("vehicle_definition", str(vehicle_definition_id)))
            return tuple(failures)
        failures.extend(
            FoundingBlocker("deployment_vehicle", detail)
            for detail in self.logistics.deployment_vehicle_failures(
                vehicle_definition_id,
                staging_node_id,
                cell_id,
                package.operations,
                package.payload_t_per_unit,
                package.transit_days,
                day=day,
            )
        )
        free = self.logistics.fleet_free_units(vehicle_definition_id, staging_node_id)
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
        priority: int = 50,
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
        self.logistics.reserve_fleet_units(
            self.fleet_reservation_id(project_id),
            EntityId(project_id),
            FleetReservationKind.SPECIAL_MISSION,
            vehicle_definition_id,
            staging_node_id,
            package.required_units,
        )
        return project_id

    def _required_resources(self, project: LocationFoundingProject) -> dict[DefinitionId, float]:
        package = self.packages[project.founding_package_id]
        totals: dict[DefinitionId, float] = {}
        for req in package.resources:
            totals[req.resource_id] = totals.get(req.resource_id, 0.0) + req.amount_t
        propellant = self.logistics.deployment_propellant_t(
            project.vehicle_definition_id,
            package.operations,
            package.payload_t_per_unit,
        ) * package.required_units
        perf = self.logistics.vehicle_defs[project.vehicle_definition_id].performance
        if perf.propellant_resource_id is not None and propellant > 1e-12:
            totals[perf.propellant_resource_id] = totals.get(perf.propellant_resource_id, 0.0) + propellant
        return totals

    def resource_demands(self) -> tuple[ResourceDemand, ...]:
        rows: list[ResourceDemand] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is not FoundingStatus.PREPARING or project.inputs_consumed:
                continue
            for resource_id, amount in sorted(self._required_resources(project).items(), key=lambda row: str(row[0])):
                rows.append(ResourceDemand(
                    self.demand_id(project.id, resource_id),
                    "founding",
                    EntityId(project.id),
                    project.staging_node_id,
                    resource_id,
                    amount,
                    project.priority,
                    project.preferred_source_id,
                    amount,
                ))
        return tuple(rows)

    def _try_consume_inputs(self, project: LocationFoundingProject) -> bool:
        required = self._required_resources(project)
        for resource_id, amount in required.items():
            demand_id = self.demand_id(project.id, resource_id)
            if self.inventory.reserved_for(demand_id, project.staging_node_id, resource_id) + 1e-9 < amount:
                return False
        for resource_id, amount in required.items():
            self.inventory.consume_reserved(
                self.demand_id(project.id, resource_id), project.staging_node_id, resource_id, amount
            )
        project.inputs_consumed = True
        return True

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
            snapshot = power if power is not None else self.power.snapshot(project.staging_node_id, self.facilities, day)
            if self.facilities.available_capability_capacity_at(project.staging_node_id, package.preparation_capability_id, snapshot, day) <= 1e-12:
                failures.append(FoundingBlocker("staging_capability", package.preparation_capability_id))
            if not project.inputs_consumed:
                for resource_id, amount in self._required_resources(project).items():
                    reserved = self.inventory.reserved_for(self.demand_id(project.id, resource_id), project.staging_node_id, resource_id)
                    if reserved + 1e-9 < amount:
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

    def set_priority(self, project_id: ProjectId, priority: int) -> None:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            raise ValueError("founding priority can only change during preparation")
        project.priority = priority

    def cancel(self, project_id: ProjectId, day: int = 0) -> None:
        project = self.projects[project_id]
        if project.status is not FoundingStatus.PREPARING:
            raise ValueError("founding cannot be cancelled after deployment begins")
        reservation_id = self.fleet_reservation_id(project_id)
        if reservation_id in self.logistics.fleet_reservations:
            self.logistics.release_fleet_reservation(reservation_id, day=day)
        project.status = FoundingStatus.CANCELLED
        project.paused = False

    def advance_day(self, day: int) -> None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status is FoundingStatus.PREPARING:
                if project.paused:
                    continue
                if self.blockers(project.id, day):
                    # Resource shortages are expected until reconciliation can reserve them.
                    non_resource = [b for b in self.blockers(project.id, day) if b.code != "resource_shortage"]
                    if non_resource:
                        continue
                if not project.inputs_consumed and not self._try_consume_inputs(project):
                    continue
                package = self.packages[project.founding_package_id]
                snapshot = self.power.snapshot(project.staging_node_id, self.facilities, day)
                capacity = self.facilities.available_capability_capacity_at(
                    project.staging_node_id, package.preparation_capability_id, snapshot, day
                )
                remaining = max(0.0, package.preparation_work - project.preparation_done)
                project.preparation_done += min(remaining, max(0.0, capacity))
                if project.preparation_done + 1e-9 >= package.preparation_work:
                    project.preparation_done = package.preparation_work
                    project.status = FoundingStatus.DEPLOYING
                    project.departure_day = day
                    project.arrival_day = day + package.transit_days
            elif project.status is FoundingStatus.DEPLOYING:
                if project.arrival_day is not None and day >= project.arrival_day:
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
        reservation_id = self.fleet_reservation_id(project.id)
        if reservation_id in self.logistics.fleet_reservations:
            disposition = self.logistics.deployment_asset_disposition(
                project.vehicle_definition_id, package.operations
            )
            final_location = (
                project.new_location_id
                if disposition is OperationAssetDisposition.DESTINATION
                else project.staging_node_id
            )
            self.logistics.complete_fleet_reservation(
                reservation_id, final_location_id=final_location, day=day
            )
        project.status = FoundingStatus.COMPLETE
        project.completed_day = day
        project.paused = False
