from __future__ import annotations

from ..resource_demand import ResourceDemand
from ..shared import EntityId
from .models import ProjectStatus


class ConstructionProcurementMixin:
    def resource_demands(self, day: int) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for project in sorted(self.projects.values(), key=lambda row: (-row.priority, str(row.id))):
            if project.paused or project.status in {
                ProjectStatus.COMPLETE,
                ProjectStatus.CANCELLED,
                ProjectStatus.READY,
                ProjectStatus.BUILDING,
            }:
                continue
            recipe = self._recipe_for_project(project)
            for component in recipe.components:
                state = project.components[component.component_id]
                if state.import_committed_t is None or state.import_committed_t <= 1e-9:
                    continue
                missing = max(0.0, state.import_committed_t - state.reserved_import_t)
                if missing <= 1e-9 or project.import_source_id is None:
                    continue
                demands.append(ResourceDemand(
                    EntityId(f"demand.project:{project.id}:{component.component_id}"),
                    "project",
                    EntityId(str(project.id)),
                    project.location_id,
                    component.import_resource_id,
                    missing,
                    project.priority,
                    project.import_source_id,
                ))
        return tuple(demands)

    def advance_procurement(self, day: int) -> None:
        ordered = sorted(self.projects.values(), key=lambda project: (-project.priority, str(project.id)))
        for project in ordered:
            if project.paused or project.status in {
                ProjectStatus.COMPLETE,
                ProjectStatus.CANCELLED,
                ProjectStatus.READY,
                ProjectStatus.BUILDING,
            }:
                continue
            recipe = self._recipe_for_project(project)
            if not recipe.prerequisite_technologies.issubset(self.unlocked_technologies):
                continue
            if self.project_site_failures(
                project,
                day,
                self.power.snapshot(project.location_id, self.facilities, day),
            ):
                continue
            if any(
                blocker.code.startswith("upgrade_")
                for blocker in self.blockers(project.id, day)
            ):
                continue
            if project.status == ProjectStatus.PLANNED:
                project.status = ProjectStatus.PROCURING
                project.procurement_started_day = day

            assert project.procurement_started_day is not None
            waited = day - project.procurement_started_day
            wait_limit = self.sourcing_wait_days[project.sourcing_policy]

            all_ready = True
            for component in recipe.components:
                state = project.components[component.component_id]
                local_res, desired_local = self._selected_local_target(project, component, day)
                if state.import_committed_t is None:
                    state.local_target_t = desired_local

                    if local_res is not None and state.reserved_local_t + 1e-9 < desired_local:
                        need = desired_local - state.reserved_local_t
                        reserved = self.inventory.reserve(
                            EntityId(project.id), project.location_id, local_res, need
                        )
                        if reserved > 0:
                            if state.reserved_local_resource_id not in (None, local_res):
                                raise RuntimeError("local substitution resource changed after reservation")
                            state.reserved_local_resource_id = local_res
                        state.reserved_local_t += reserved

                    primary_need = max(
                        0.0,
                        component.amount_t - state.reserved_local_t - state.reserved_primary_t,
                    )
                    if primary_need > 1e-9:
                        state.reserved_primary_t += self.inventory.reserve(
                            EntityId(project.id),
                            project.location_id,
                            component.import_resource_id,
                            primary_need,
                        )

                    covered_on_site = state.reserved_local_t + state.reserved_primary_t
                    local_met = state.reserved_local_t + 1e-9 >= desired_local
                    fully_covered = covered_on_site + 1e-9 >= component.amount_t
                    if fully_covered:
                        state.import_committed_t = 0.0
                    elif local_met or waited >= wait_limit:
                        if project.import_source_id is None:
                            all_ready = False
                            continue
                        state.import_committed_t = max(0.0, component.amount_t - covered_on_site)
                    else:
                        all_ready = False
                        continue

                if state.import_committed_t is not None and state.import_committed_t > 1e-9:
                    need_import_reserve = state.import_committed_t - state.reserved_import_t
                    if need_import_reserve > 1e-9:
                        got = self.inventory.reserve(
                            EntityId(project.id),
                            project.location_id,
                            component.import_resource_id,
                            need_import_reserve,
                        )
                        state.reserved_import_t += got
                    if state.reserved_import_t + 1e-9 < state.import_committed_t:
                        all_ready = False

                if (
                    state.reserved_local_t
                    + state.reserved_primary_t
                    + state.reserved_import_t
                    + 1e-9
                    < component.amount_t
                ):
                    all_ready = False

            if all_ready:
                project.status = ProjectStatus.READY
