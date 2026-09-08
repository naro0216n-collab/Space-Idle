from __future__ import annotations

from ..shared import AccountState, CargoOrderId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from ..site import evaluate_site_requirements
from .models import ProjectStatus, BuildProject


class ConstructionExecutionMixin:

        def _commit_materials(self, project: BuildProject) -> None:
            if project.materials_committed:
                return
            recipe = self.recipes[project.facility_def_id]
            for component in recipe.components:
                state = project.components[component.component_id]
                if state.reserved_local_t > 1e-9:
                    if state.reserved_local_resource_id is None:
                        raise RuntimeError("lost local resource type")
                    self.inventory.consume_reserved(
                        EntityId(project.id), project.location_id, state.reserved_local_resource_id, state.reserved_local_t
                    )
                    state.committed_local_t = state.reserved_local_t
                    state.committed_local_resource_id = state.reserved_local_resource_id
                    state.reserved_local_t = 0.0
                    state.reserved_local_resource_id = None
                if state.reserved_import_t > 1e-9:
                    self.inventory.consume_reserved(
                        EntityId(project.id), project.location_id, component.import_resource_id, state.reserved_import_t
                    )
                    state.committed_import_t = state.reserved_import_t
                    state.reserved_import_t = 0.0
            project.materials_committed = True

        def _finish_project(self, project: BuildProject) -> None:
            self._commit_materials(project)
            recipe = self.recipes[project.facility_def_id]
            project.installed_facility_id = self.facilities.install(project.facility_def_id, project.location_id)
            project.status = ProjectStatus.COMPLETE

        def advance_construction(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0) -> None:
            # Self-deploying packages become operational once their cargo has arrived.
            for project in self.projects.values():
                if not project.paused and project.status == ProjectStatus.READY:
                    recipe = self.recipes[project.facility_def_id]
                    if self.site_failures(
                        project.facility_def_id, project.location_id, day,
                        power_by_location.get(project.location_id, self.power.snapshot(project.location_id, self.facilities, day)),
                    ):
                        continue
                    if recipe.self_deploying or recipe.construction_work <= 1e-12:
                        self._finish_project(project)

            locations = {p.location_id for p in self.projects.values() if not p.paused and p.status in {ProjectStatus.READY, ProjectStatus.BUILDING}}
            for location_id in sorted(locations, key=str):
                candidates = [
                    p for p in self.projects.values()
                    if p.location_id == location_id and not p.paused and p.status in {ProjectStatus.READY, ProjectStatus.BUILDING}
                    and not self.recipes[p.facility_def_id].self_deploying
                    and self.recipes[p.facility_def_id].construction_work > 1e-12
                    and not self.site_failures(
                        p.facility_def_id, p.location_id, day,
                        power_by_location.get(p.location_id, self.power.snapshot(p.location_id, self.facilities, day)),
                    )
                ]
                if not candidates:
                    continue
                power = power_by_location[location_id]
                capacity = self.construction_capacity_at(location_id, power, day)
                if capacity <= 1e-12:
                    continue
                active = [p for p in candidates if p.construction_weight > 1e-12]
                remaining_capacity = capacity
                # Redistribute any share a project cannot use because it finishes
                # during this tick. This preserves construction capacity as a true
                # flow instead of silently discarding it at project boundaries.
                while active and remaining_capacity > 1e-12:
                    total_weight = sum(p.construction_weight for p in active)
                    if total_weight <= 1e-12:
                        break
                    allocations = {
                        p.id: remaining_capacity * p.construction_weight / total_weight
                        for p in active
                    }
                    used = 0.0
                    completed: list[BuildProject] = []
                    for project in sorted(active, key=lambda p: (-p.priority, str(p.id))):
                        recipe = self.recipes[project.facility_def_id]
                        remaining_work = max(0.0, recipe.construction_work - project.construction_done)
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
