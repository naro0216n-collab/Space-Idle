from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256

from .facilities import FacilityBook, FacilityPlacementScope
from .inventory import InventoryBook
from .logistics import LogisticsService
from .resource_demand import ResourceDemand
from .shared import CelestialBodyId, DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements, evaluate_site_requirements
from .spatial import SpatialGraph
from .storage import StorageService
from .survey import SurveyService
from .transport.models import (
    FleetReservationKind,
    OperationAssetDisposition,
    TransportOperationRequirement,
)


@dataclass(frozen=True)
class FoundingFacilityDeployment:
    facility_definition_id: DefinitionId
    invested_resources: tuple[tuple[DefinitionId, float], ...]
    place_at_core_cell: bool = False

    def __post_init__(self) -> None:
        if any(amount <= 0 for _resource_id, amount in self.invested_resources):
            raise ValueError("founding facility investment must be positive")
        resource_ids = [resource_id for resource_id, _amount in self.invested_resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("founding facility investment contains duplicate resource")


class FoundingStagingRelation(str, Enum):
    ANY = "any"
    SAME_BODY = "same_body"


@dataclass(frozen=True)
class FoundingPackageDefinition:
    id: DefinitionId
    display_name: str
    facilities: tuple[FoundingFacilityDeployment, ...]
    operations: tuple[TransportOperationRequirement, ...]
    transit_days: int
    preparation_work: float = 0.0
    initial_inventory: tuple[tuple[DefinitionId, float], ...] = ()
    required_units: int = 1
    minimum_survey_knowledge_level: int = 1
    staging_requirements: SiteRequirements = SiteRequirements()
    target_requirements: SiteRequirements = SiteRequirements()
    staging_relation: FoundingStagingRelation = FoundingStagingRelation.ANY

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("founding package display name must not be empty")
        if not self.facilities:
            raise ValueError("founding package must deploy at least one facility")
        if not self.operations:
            raise ValueError("founding package must define deployment operations")
        if self.transit_days <= 0:
            raise ValueError("founding package transit days must be positive")
        if self.preparation_work < 0:
            raise ValueError("founding package preparation work must be non-negative")
        if self.required_units <= 0:
            raise ValueError("founding package required units must be positive")
        if not 0 <= self.minimum_survey_knowledge_level <= 4:
            raise ValueError("founding package survey knowledge level must be within 0..4")
        if self.target_requirements.capability_requirements:
            raise ValueError(
                "pre-founding target requirements cannot require destination capabilities"
            )
        if any(amount <= 0 for _resource_id, amount in self.initial_inventory):
            raise ValueError("founding initial inventory must be positive")
        inventory_ids = [resource_id for resource_id, _amount in self.initial_inventory]
        if len(inventory_ids) != len(set(inventory_ids)):
            raise ValueError("founding initial inventory contains duplicate resource")

    @property
    def resource_requirements(self) -> tuple[tuple[DefinitionId, float], ...]:
        totals: dict[DefinitionId, float] = {}
        for deployment in self.facilities:
            for resource_id, amount in deployment.invested_resources:
                totals[resource_id] = totals.get(resource_id, 0.0) + amount
        for resource_id, amount in self.initial_inventory:
            totals[resource_id] = totals.get(resource_id, 0.0) + amount
        return tuple(sorted(totals.items(), key=lambda row: str(row[0])))

    @property
    def payload_t(self) -> float:
        return sum(amount for _resource_id, amount in self.resource_requirements)


class FoundingProjectStatus(str, Enum):
    PREPARING = "preparing"
    DEPLOYING = "deploying"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


@dataclass
class LocationFoundingProject:
    id: EntityId
    package_id: DefinitionId
    staging_location_id: SpatialNodeId
    target_cell_id: SurfaceCellId
    new_location_id: SpatialNodeId
    display_name: str
    vehicle_definition_id: DefinitionId
    priority: int = 50
    status: FoundingProjectStatus = FoundingProjectStatus.PREPARING
    preparation_done: float = 0.0
    progress_days: float = 0.0
    inputs_consumed: bool = False
    paused: bool = False
    created_day: int = 0
    completed_facility_ids: tuple[EntityId, ...] = ()


@dataclass
class LocationFoundingService:
    definitions: dict[DefinitionId, FoundingPackageDefinition]
    graph: SpatialGraph
    facilities: FacilityBook
    inventory: InventoryBook
    storage: StorageService
    logistics: LogisticsService
    survey: SurveyService | None = None
    projects: dict[EntityId, LocationFoundingProject] = field(default_factory=dict)
    _counter: int = 0

    @staticmethod
    def _reservation_id(project_id: EntityId) -> EntityId:
        return EntityId(f"location_founding:{project_id}")

    @staticmethod
    def _resource_demand_id(project_id: EntityId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"demand.location_founding:{project_id}:{resource_id}")

    def _generated_location_id(
        self, body_id: CelestialBodyId, core_cell_id: SurfaceCellId
    ) -> SpatialNodeId:
        digest = sha256(f"{body_id}\0{core_cell_id}".encode("utf-8")).hexdigest()[:24]
        base = f"player.location.{digest}"
        occupied = set(self.graph.operational_node_ids())
        occupied.update(project.new_location_id for project in self.projects.values())
        candidate = SpatialNodeId(base)
        suffix = 2
        while candidate in occupied:
            candidate = SpatialNodeId(f"{base}.{suffix}")
            suffix += 1
        return candidate

    def active_project_for_cell(self, cell_id: SurfaceCellId) -> LocationFoundingProject | None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.target_cell_id == cell_id
                and project.status not in {FoundingProjectStatus.COMPLETE, FoundingProjectStatus.CANCELLED}
            ):
                return project
        return None

    def _survey_level(self, cell_id: SurfaceCellId) -> int:
        if self.survey is None:
            return 0
        return self.survey.cell_knowledge_level(cell_id)

    def definition_failures(
        self,
        package_id: DefinitionId,
        staging_location_id: SpatialNodeId,
        target_cell_id: SurfaceCellId,
        vehicle_definition_id: DefinitionId,
        *,
        day: int = 0,
        check_fleet_availability: bool = True,
        exclude_project_id: EntityId | None = None,
    ) -> tuple[tuple[str, str], ...]:
        failures: list[tuple[str, str]] = []
        package = self.definitions.get(package_id)
        if package is None:
            return (("founding_package", f"unknown package: {package_id}"),)
        if not self.graph.has_operational_node(staging_location_id):
            failures.append(("staging_node", f"unknown operational node: {staging_location_id}"))
            return tuple(failures)
        target = self.graph.surface_cells.get(target_cell_id)
        if target is None:
            failures.append(("target_cell", f"unknown surface cell: {target_cell_id}"))
            return tuple(failures)
        staging = self.graph.operational_node(staging_location_id)
        if (
            package.staging_relation is FoundingStagingRelation.SAME_BODY
            and staging.body_id != target.body_id
        ):
            failures.append((
                "staging_relation",
                f"package requires same-body staging: {staging.body_id}!={target.body_id}",
            ))
        failures.extend(self.graph.location_foundation_failures(target.body_id, target_cell_id))
        active = self.active_project_for_cell(target_cell_id)
        if active is not None and active.id != exclude_project_id:
            failures.append(("active_founding_project", str(active.id)))
        actual_level = self._survey_level(target_cell_id)
        if actual_level < package.minimum_survey_knowledge_level:
            failures.append((
                "survey_knowledge",
                f"level={actual_level}/{package.minimum_survey_knowledge_level}",
            ))
        for failure in evaluate_site_requirements(
            package.target_requirements,
            staging_location_id,
            day,
            self.facilities.environment,
            self.facilities,
            None,
            environment_context_id=target_cell_id,
        ):
            failures.append((failure.code, failure.detail))
        for failure in self.logistics.deployment_failures(
            vehicle_definition_id,
            staging_location_id,
            target_cell_id,
            package.operations,
            package.transit_days,
            package.payload_t,
            staging_requirements=package.staging_requirements,
            target_requirements=package.target_requirements,
            day=day,
        ):
            failures.append(("transport", failure))
        if check_fleet_availability and vehicle_definition_id in self.logistics.vehicle_defs:
            free = self.logistics.fleet_free_units(vehicle_definition_id, staging_location_id)
            if free < package.required_units:
                failures.append(("fleet_units", f"{free}/{package.required_units}"))
        return tuple(dict.fromkeys(failures))

    def compatible_vehicle_options(
        self,
        package_id: DefinitionId,
        staging_location_id: SpatialNodeId,
        target_cell_id: SurfaceCellId,
        *,
        day: int = 0,
    ) -> tuple[tuple[DefinitionId, tuple[tuple[str, str], ...]], ...]:
        return tuple(
            (
                vehicle_definition_id,
                self.definition_failures(
                    package_id,
                    staging_location_id,
                    target_cell_id,
                    vehicle_definition_id,
                    day=day,
                ),
            )
            for vehicle_definition_id in sorted(self.logistics.vehicle_defs, key=str)
        )

    def start(
        self,
        package_id: DefinitionId,
        staging_location_id: SpatialNodeId,
        target_cell_id: SurfaceCellId,
        display_name: str,
        vehicle_definition_id: DefinitionId,
        *,
        priority: int = 50,
        day: int = 0,
    ) -> EntityId:
        if not display_name.strip():
            raise ValueError("location display name must not be empty")
        if not 0 <= priority <= 100:
            raise ValueError("founding priority must be within 0..100")
        failures = self.definition_failures(
            package_id,
            staging_location_id,
            target_cell_id,
            vehicle_definition_id,
            day=day,
        )
        if failures:
            raise ValueError("; ".join(f"{code}: {detail}" for code, detail in failures))
        package = self.definitions[package_id]
        body_id = self.graph.surface_cells[target_cell_id].body_id
        self._counter += 1
        project_id = EntityId(f"founding.{self._counter}")
        location_id = self._generated_location_id(body_id, target_cell_id)
        reservation_id = self._reservation_id(project_id)
        self.logistics.reserve_fleet_units(
            reservation_id,
            project_id,
            FleetReservationKind.SPECIAL_MISSION,
            vehicle_definition_id,
            staging_location_id,
            package.required_units,
        )
        self.projects[project_id] = LocationFoundingProject(
            id=project_id,
            package_id=package_id,
            staging_location_id=staging_location_id,
            target_cell_id=target_cell_id,
            new_location_id=location_id,
            display_name=display_name.strip(),
            vehicle_definition_id=vehicle_definition_id,
            priority=priority,
            created_day=day,
        )
        return project_id

    def set_priority(self, project_id: EntityId, priority: int) -> None:
        if not 0 <= priority <= 100:
            raise ValueError("founding project priority must be within 0..100")
        project = self.projects[project_id]
        if project.status is not FoundingProjectStatus.PREPARING:
            raise ValueError("only preparing founding projects can be reprioritized")
        project.priority = priority

    def pause(self, project_id: EntityId) -> None:
        project = self.projects[project_id]
        if project.status in {FoundingProjectStatus.COMPLETE, FoundingProjectStatus.CANCELLED}:
            raise ValueError("completed/cancelled founding project cannot be paused")
        project.paused = True

    def resume(self, project_id: EntityId) -> None:
        project = self.projects[project_id]
        if project.status in {FoundingProjectStatus.COMPLETE, FoundingProjectStatus.CANCELLED}:
            raise ValueError("completed/cancelled founding project cannot be resumed")
        project.paused = False

    def cancel(self, project_id: EntityId, *, day: int = 0) -> None:
        project = self.projects[project_id]
        if project.status is FoundingProjectStatus.COMPLETE:
            raise ValueError("completed founding project cannot be cancelled")
        if project.status is FoundingProjectStatus.CANCELLED:
            return
        if project.inputs_consumed or project.status is FoundingProjectStatus.DEPLOYING:
            raise ValueError("launched founding deployment cannot be cancelled")
        self.inventory.release_reservations_by_owner_prefix(f"demand.location_founding:{project_id}:")
        reservation_id = self._reservation_id(project_id)
        if self.logistics.fleet_reservation_snapshot(reservation_id) is not None:
            self.logistics.release_fleet_reservation(reservation_id, day=day)
        project.status = FoundingProjectStatus.CANCELLED

    def deployment_resource_requirements(
        self, package_id: DefinitionId, vehicle_definition_id: DefinitionId
    ) -> tuple[tuple[DefinitionId, float], ...]:
        package = self.definitions[package_id]
        totals = dict(package.resource_requirements)
        propellant_resource_id, propellant_t = self.logistics.deployment_propellant_t(
            vehicle_definition_id, package.operations, package.payload_t
        )
        if propellant_resource_id is not None and propellant_t > 1e-12:
            totals[propellant_resource_id] = totals.get(propellant_resource_id, 0.0) + propellant_t
        return tuple(sorted(totals.items(), key=lambda row: str(row[0])))

    def _resource_requirements(
        self, project: LocationFoundingProject
    ) -> tuple[tuple[DefinitionId, float], ...]:
        return self.deployment_resource_requirements(
            project.package_id, project.vehicle_definition_id
        )

    def resource_requirements(self, project_id: EntityId) -> tuple[tuple[DefinitionId, float], ...]:
        return self._resource_requirements(self.projects[project_id])

    def reserved_resource_t(self, project_id: EntityId, resource_id: DefinitionId) -> float:
        project = self.projects[project_id]
        return self.inventory.reserved_for(
            self._resource_demand_id(project.id, resource_id),
            project.staging_location_id,
            resource_id,
        )

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.status is not FoundingProjectStatus.PREPARING
                or project.paused
                or project.inputs_consumed
            ):
                continue
            for resource_id, amount_t in self._resource_requirements(project):
                if amount_t <= 1e-12:
                    continue
                demands.append(ResourceDemand(
                    self._resource_demand_id(project.id, resource_id),
                    "location_founding",
                    project.id,
                    project.staging_location_id,
                    resource_id,
                    amount_t,
                    project.priority,
                ))
        return tuple(demands)

    def blockers(self, project_id: EntityId, *, day: int = 0) -> tuple[tuple[str, str], ...]:
        project = self.projects[project_id]
        if project.status in {FoundingProjectStatus.COMPLETE, FoundingProjectStatus.CANCELLED}:
            return ()
        package = self.definitions[project.package_id]
        blockers: list[tuple[str, str]] = []
        if project.paused:
            blockers.append(("manual_pause", "project paused"))
        if project.status is FoundingProjectStatus.PREPARING:
            for resource_id, amount_t in self._resource_requirements(project):
                demand_id = self._resource_demand_id(project.id, resource_id)
                reserved = self.inventory.reserved_for(
                    demand_id, project.staging_location_id, resource_id
                )
                if reserved + 1e-9 < amount_t:
                    blockers.append(("resource", f"{resource_id}:{reserved:g}/{amount_t:g}"))
            blockers.extend(
                self.definition_failures(
                    project.package_id,
                    project.staging_location_id,
                    project.target_cell_id,
                    project.vehicle_definition_id,
                    day=day,
                    check_fleet_availability=False,
                    exclude_project_id=project.id,
                )
            )
            reservation = self.logistics.fleet_reservation_snapshot(
                self._reservation_id(project.id)
            )
            if reservation is None:
                blockers.append(("fleet_reservation", "reserved deployment Fleet is missing"))
        elif project.status is FoundingProjectStatus.DEPLOYING:
            if project.progress_days + 1e-9 >= package.transit_days:
                blockers.append(("completion_pending", "deployment completion is pending"))
        return tuple(dict.fromkeys(blockers))

    def _consume_inputs(self, project: LocationFoundingProject) -> bool:
        requirements = self._resource_requirements(project)
        if not all(
            self.inventory.reserved_for(
                self._resource_demand_id(project.id, resource_id),
                project.staging_location_id,
                resource_id,
            ) + 1e-9 >= amount_t
            for resource_id, amount_t in requirements
        ):
            return False
        for resource_id, amount_t in requirements:
            self.inventory.consume_reserved(
                self._resource_demand_id(project.id, resource_id),
                project.staging_location_id,
                resource_id,
                amount_t,
            )
        project.inputs_consumed = True
        project.status = FoundingProjectStatus.DEPLOYING
        return True

    def advance_day(self, day: int) -> None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.status in {FoundingProjectStatus.COMPLETE, FoundingProjectStatus.CANCELLED}
                or project.paused
            ):
                continue
            package = self.definitions[project.package_id]
            if project.status is FoundingProjectStatus.PREPARING:
                if self.blockers(project.id, day=day):
                    continue
                project.preparation_done = min(
                    package.preparation_work, project.preparation_done + 1.0
                )
                if project.preparation_done + 1e-9 < package.preparation_work:
                    continue
                if not self._consume_inputs(project):
                    continue
            project.progress_days = min(
                float(package.transit_days), project.progress_days + 1.0
            )
            if project.progress_days + 1e-9 >= package.transit_days:
                self._complete(project, day)

    def _complete(self, project: LocationFoundingProject, day: int) -> None:
        if project.status is FoundingProjectStatus.COMPLETE:
            return
        package = self.definitions[project.package_id]
        body_id = self.graph.surface_cells[project.target_cell_id].body_id
        self.graph.found_location(
            project.new_location_id,
            project.display_name,
            body_id,
            project.target_cell_id,
        )
        installed: list[EntityId] = []
        for deployment in package.facilities:
            definition = self.facilities.definitions[deployment.facility_definition_id]
            site_cell_id = None
            if definition.placement_scope is FacilityPlacementScope.SURFACE_CELL:
                if not deployment.place_at_core_cell:
                    raise RuntimeError(
                        f"founding package surface-cell facility lacks placement: {definition.id}"
                    )
                site_cell_id = project.target_cell_id
            elif deployment.place_at_core_cell:
                raise RuntimeError(
                    f"founding package location facility unexpectedly requests a cell: {definition.id}"
                )
            installed.append(self.facilities.install(
                deployment.facility_definition_id,
                project.new_location_id,
                site_cell_id=site_cell_id,
                invested_resources=dict(deployment.invested_resources),
            ))
        project.completed_facility_ids = tuple(installed)
        location_power = self.logistics.power.snapshot(
            project.new_location_id, self.facilities, day
        )
        self.storage.refresh(day, {project.new_location_id: location_power})
        for resource_id, amount_t in package.initial_inventory:
            self.inventory.add(project.new_location_id, resource_id, amount_t)

        performance = self.logistics.vehicle_defs[project.vehicle_definition_id].performance
        disposition = OperationAssetDisposition.DESTINATION
        for operation in package.operations:
            current = performance.operation_asset_disposition(operation.operation_type)
            if current is not None:
                disposition = current
                if current is OperationAssetDisposition.ORIGIN:
                    break
        final_location = (
            project.new_location_id
            if disposition is OperationAssetDisposition.DESTINATION
            else project.staging_location_id
        )
        self.logistics.complete_fleet_reservation(
            self._reservation_id(project.id),
            final_location_id=final_location,
            day=day,
        )
        project.status = FoundingProjectStatus.COMPLETE
        self.logistics.synchronize_surface_access_routes()
