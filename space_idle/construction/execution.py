from __future__ import annotations

from ..power import PowerSnapshot
from ..service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityRequest
from ..shared import EntityId
from ..shared import SpatialNodeId
from .models import (
    CONSTRUCTION_SERVICE_TYPE, ConstructionProject, FacilityUpgradeTarget, NewFacilityTarget,
    ProjectStatus, SurfaceCellDevelopmentTarget,
)


class ConstructionExecutionMixin:

    def _finish_project(self, project: ConstructionProject) -> None:
        self._commit_materials(project)
        invested = self._committed_resources(project)
        target = project.target
        if isinstance(target, NewFacilityTarget):
            project.completed_facility_id = self.facilities.install(
                target.facility_def_id,
                project.operational_node_id,
                site_cell_id=project.site_cell_id,
                invested_resources=invested,
            )
        elif isinstance(target, FacilityUpgradeTarget):
            self.facilities.upgrade_to(
                target.facility_id,
                target.target_level,
                invested_resources=invested,
            )
            project.completed_facility_id = target.facility_id
        else:
            self.facilities.environment.graph.develop_surface_cell(
                project.operational_node_id, target.cell_id
            )
        project.status = ProjectStatus.COMPLETE

    def _target_ready_for_execution(self, project: ConstructionProject) -> bool:
        target = project.target
        if isinstance(target, FacilityUpgradeTarget):
            facility = self.facilities.facilities.get(target.facility_id)
            return (
                facility is not None
                and facility.operational_node_id == project.operational_node_id
                and facility.level == target.target_level - 1
            )
        if isinstance(target, SurfaceCellDevelopmentTarget):
            return not self.facilities.environment.graph.surface_cell_development_failures(
                project.operational_node_id, target.cell_id
            )
        return True

    @staticmethod
    def construction_service_request_id(project_id) -> EntityId:
        return EntityId(f"service.construction:{project_id}")

    def construction_service_requests(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int = 0,
    ) -> tuple[ServiceCapacityRequest, ...]:
        requests: list[ServiceCapacityRequest] = []
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.paused
                or project.status not in {ProjectStatus.READY, ProjectStatus.BUILDING}
                or not self._target_ready_for_execution(project)
            ):
                continue
            recipe = self._recipe_for_project(project)
            if recipe.self_deploying or recipe.construction_work <= 1e-12:
                continue
            power = power_by_location.get(project.operational_node_id)
            if power is None:
                power = self.power.snapshot(
                    project.operational_node_id, self.facilities, day
                )
            if self.project_site_failures(project, day, power):
                continue
            fulfillment = self.project_construction_fulfillment(project, power, day)
            if fulfillment <= 1e-12:
                continue
            remaining_work = max(
                0.0, recipe.construction_work - project.construction_done
            )
            if remaining_work <= 1e-12:
                continue
            requests.append(
                ServiceCapacityRequest(
                    self.construction_service_request_id(project.id),
                    project.operational_node_id,
                    CONSTRUCTION_SERVICE_TYPE,
                    remaining_work / fulfillment,
                    project.priority,
                    "construction",
                    EntityId(str(project.id)),
                    "construction_work",
                )
            )
        return tuple(requests)

    def advance_construction(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        service_allocations: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> None:
        for project in self.projects.values():
            if not project.paused and project.status == ProjectStatus.READY:
                recipe = self._recipe_for_project(project)
                if not self._target_ready_for_execution(project):
                    continue
                power = power_by_location.get(
                    project.operational_node_id,
                    self.power.snapshot(
                        project.operational_node_id, self.facilities, day
                    ),
                )
                if self.project_site_failures(project, day, power):
                    continue
                if recipe.self_deploying or recipe.construction_work <= 1e-12:
                    self._finish_project(project)

        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.paused
                or project.status not in {ProjectStatus.READY, ProjectStatus.BUILDING}
                or not self._target_ready_for_execution(project)
            ):
                continue
            recipe = self._recipe_for_project(project)
            if recipe.self_deploying or recipe.construction_work <= 1e-12:
                continue
            power = power_by_location.get(
                project.operational_node_id,
                self.power.snapshot(project.operational_node_id, self.facilities, day),
            )
            if self.project_site_failures(project, day, power):
                continue
            fulfillment = self.project_construction_fulfillment(project, power, day)
            if fulfillment <= 1e-12:
                continue
            try:
                allocated_capacity = service_allocations.allocated(
                    self.construction_service_request_id(project.id)
                )
            except KeyError:
                allocated_capacity = 0.0
            if allocated_capacity <= 1e-12:
                continue
            remaining_work = max(
                0.0, recipe.construction_work - project.construction_done
            )
            work = min(remaining_work, allocated_capacity * fulfillment)
            if work <= 1e-12:
                continue
            self._commit_materials(project)
            project.status = ProjectStatus.BUILDING
            project.construction_done += work
            if project.construction_done + 1e-9 >= recipe.construction_work:
                project.construction_done = recipe.construction_work
                self._finish_project(project)
