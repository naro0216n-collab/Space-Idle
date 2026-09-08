from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import EntityId, SpatialNodeId
from .models import ConstructionProject, FacilityUpgradeTarget, NewFacilityTarget, ProjectStatus


class ConstructionExecutionMixin:
    def _commit_materials(self, project: ConstructionProject) -> None:
        if project.materials_committed:
            return
        recipe = self._recipe_for_project(project)
        for component in recipe.components:
            state = project.components[component.component_id]
            if state.reserved_local_t > 1e-9:
                if state.reserved_local_resource_id is None:
                    raise RuntimeError("lost local resource type")
                self.inventory.consume_reserved(
                    EntityId(project.id), project.location_id,
                    state.reserved_local_resource_id, state.reserved_local_t,
                )
                state.committed_local_t = state.reserved_local_t
                state.committed_local_resource_id = state.reserved_local_resource_id
                state.reserved_local_t = 0.0
                state.reserved_local_resource_id = None
            if state.reserved_import_t > 1e-9:
                self.inventory.consume_reserved(
                    EntityId(project.id), project.location_id,
                    component.import_resource_id, state.reserved_import_t,
                )
                state.committed_import_t = state.reserved_import_t
                state.reserved_import_t = 0.0
        project.materials_committed = True

    def _finish_project(self, project: ConstructionProject) -> None:
        self._commit_materials(project)
        target = project.target
        if isinstance(target, NewFacilityTarget):
            project.completed_facility_id = self.facilities.install(
                target.facility_def_id, project.location_id
            )
        else:
            self.facilities.upgrade_to(target.facility_id, target.target_level)
            project.completed_facility_id = target.facility_id
        project.status = ProjectStatus.COMPLETE

    def _target_ready_for_execution(self, project: ConstructionProject) -> bool:
        if not isinstance(project.target, FacilityUpgradeTarget):
            return True
        facility = self.facilities.facilities.get(project.target.facility_id)
        return (
            facility is not None
            and facility.location_id == project.location_id
            and facility.level == project.target.target_level - 1
        )

    def advance_construction(
        self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0
    ) -> None:
        for project in self.projects.values():
            if not project.paused and project.status == ProjectStatus.READY:
                recipe = self._recipe_for_project(project)
                if not self._target_ready_for_execution(project):
                    continue
                if self.project_site_failures(
                    project, day,
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
                used = 0.0
                completed: list[ConstructionProject] = []
                for project in sorted(active, key=lambda row: (-row.priority, str(row.id))):
                    recipe = self._recipe_for_project(project)
                    remaining_work = max(
                        0.0, recipe.construction_work - project.construction_done
                    )
                    work = min(allocations[project.id], remaining_work)
                    if work <= 1e-12:
                        completed.append(project)
                        continue
                    self._commit_materials(project)
                    project.status = ProjectStatus.BUILDING
                    project.construction_done += work
                    used += work
                    if project.construction_done + 1e-9 >= recipe.construction_work:
                        completed.append(project)
                for project in completed:
                    if project in active:
                        active.remove(project)
                    if project.status != ProjectStatus.COMPLETE:
                        self._finish_project(project)
                if used <= 1e-12:
                    break
                remaining_capacity -= used
                if not completed:
                    break
