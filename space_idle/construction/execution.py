from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import SpatialNodeId
from .models import (
    ConstructionProject, FacilityUpgradeTarget, LocationFoundingTarget, NewFacilityTarget,
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
                project.location_id,
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
        elif isinstance(target, LocationFoundingTarget):
            self.facilities.environment.graph.found_location(
                target.new_location_id, target.display_name, target.body_id, target.core_cell_id
            )
        else:
            self.facilities.environment.graph.develop_surface_cell(
                project.location_id, target.cell_id
            )
        project.status = ProjectStatus.COMPLETE

    def _target_ready_for_execution(self, project: ConstructionProject) -> bool:
        target = project.target
        if isinstance(target, FacilityUpgradeTarget):
            facility = self.facilities.facilities.get(target.facility_id)
            return (
                facility is not None
                and facility.location_id == project.location_id
                and facility.level == target.target_level - 1
            )
        if isinstance(target, LocationFoundingTarget):
            graph = self.facilities.environment.graph
            return (
                target.new_location_id not in graph.locations
                and target.new_location_id not in graph.nodes
                and not graph.location_foundation_failures(target.body_id, target.core_cell_id)
            )
        if isinstance(target, SurfaceCellDevelopmentTarget):
            return not self.facilities.environment.graph.surface_cell_development_failures(
                project.location_id, target.cell_id
            )
        return True

    def advance_construction(
        self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0
    ) -> None:
        for project in self.projects.values():
            if not project.paused and project.status == ProjectStatus.READY:
                recipe = self._recipe_for_project(project)
                if not self._target_ready_for_execution(project):
                    continue
                if self.project_site_failures(
                    project,
                    day,
                    power_by_location.get(
                        project.location_id,
                        self.power.snapshot(project.location_id, self.facilities, day),
                    ),
                ):
                    continue
                if recipe.self_deploying or recipe.construction_work <= 1e-12:
                    self._finish_project(project)

        locations = {
            project.location_id
            for project in self.projects.values()
            if not project.paused
            and project.status in {ProjectStatus.READY, ProjectStatus.BUILDING}
        }
        for location_id in sorted(locations, key=str):
            power = power_by_location.get(
                location_id, self.power.snapshot(location_id, self.facilities, day)
            )
            candidates = [
                project
                for project in self.projects.values()
                if project.location_id == location_id
                and not project.paused
                and project.status in {ProjectStatus.READY, ProjectStatus.BUILDING}
                and self._target_ready_for_execution(project)
                and not self._recipe_for_project(project).self_deploying
                and self._recipe_for_project(project).construction_work > 1e-12
                and not self.project_site_failures(project, day, power)
            ]
            if not candidates:
                continue
            capacity = self.construction_capacity_at(location_id, power, day)
            if capacity <= 1e-12:
                continue
            active = [project for project in candidates if project.construction_weight > 1e-12]
            remaining_capacity = capacity
            while active and remaining_capacity > 1e-12:
                total_weight = sum(project.construction_weight for project in active)
                if total_weight <= 1e-12:
                    break
                allocations = {
                    project.id: remaining_capacity * project.construction_weight / total_weight
                    for project in active
                }
                spent_capacity = 0.0
                completed: list[ConstructionProject] = []
                for project in sorted(active, key=lambda row: (-row.priority, str(row.id))):
                    recipe = self._recipe_for_project(project)
                    remaining_work = max(0.0, recipe.construction_work - project.construction_done)
                    if remaining_work <= 1e-12:
                        completed.append(project)
                        continue
                    allocation = allocations[project.id]
                    fulfillment = self.project_construction_fulfillment(project, power, day)
                    if fulfillment <= 1e-12:
                        # The assigned construction flow cannot reach the target
                        # territory. Keep the assignment consumed so another
                        # project does not silently steal the player's explicit
                        # construction weight.
                        spent_capacity += allocation
                        continue
                    capacity_needed = remaining_work / fulfillment
                    spent = min(allocation, capacity_needed)
                    work = spent * fulfillment
                    if work <= 1e-12:
                        spent_capacity += spent
                        continue
                    self._commit_materials(project)
                    project.status = ProjectStatus.BUILDING
                    project.construction_done += work
                    spent_capacity += spent
                    if project.construction_done + 1e-9 >= recipe.construction_work:
                        completed.append(project)
                for project in completed:
                    if project in active:
                        active.remove(project)
                    if project.status != ProjectStatus.COMPLETE:
                        self._finish_project(project)
                if spent_capacity <= 1e-12:
                    break
                remaining_capacity -= spent_capacity
                if not completed:
                    break
