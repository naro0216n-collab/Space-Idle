from __future__ import annotations

from ..resource_demand import ResourceDemand
from ..shared import EntityId
from .models import ProjectStatus, FacilityUpgradeTarget


class ConstructionProcurementMixin:

    def resource_demands(self, day: int) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for project in sorted(self.projects.values(), key=lambda row: (-row.priority, str(row.id))):
            if (
                project.paused
                or project.status not in {ProjectStatus.PROCURING, ProjectStatus.READY}
                or project.materials_committed
            ):
                continue
            recipe = self._recipe_for_project(project)
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                missing = max(0.0, requirement.amount_t - state.committed_t)
                if missing <= 1e-9:
                    continue
                demands.append(ResourceDemand(
                    self._resource_demand_id(project.id, requirement.resource_id),
                    "project",
                    EntityId(str(project.id)),
                    project.location_id,
                    requirement.resource_id,
                    missing,
                    project.priority,
                    project.import_source_id,
                    missing,
                    state.import_committed_t is not None,
                ))
        return tuple(demands)

    def advance_procurement(self, day: int) -> None:
        """Advance sourcing policy without independently claiming shared stock."""
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
            if isinstance(project.target, FacilityUpgradeTarget) and any(
                blocker.code.startswith("upgrade_") for blocker in self.blockers(project.id, day)
            ):
                continue
            if project.status == ProjectStatus.PLANNED:
                project.status = ProjectStatus.PROCURING
                project.procurement_started_day = day

            assert project.procurement_started_day is not None
            waited = day - project.procurement_started_day
            wait_limit = self.sourcing_wait_days[project.sourcing_policy]
            if waited < wait_limit:
                continue
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                if state.import_committed_t is None and state.committed_t + 1e-9 < requirement.amount_t:
                    state.import_committed_t = max(0.0, requirement.amount_t - state.committed_t)

    def finalize_procurement(self, day: int) -> None:
        """Synchronize readiness with the shared allocation without consuming it.

        READY means every required material is currently reserved for the project.
        Physical consumption belongs to construction execution, so a project blocked
        by capacity, allocation, or site conditions can remain READY without losing
        material from Inventory.
        """
        ordered = sorted(self.projects.values(), key=lambda project: (-project.priority, str(project.id)))
        for project in ordered:
            if (
                project.paused
                or project.status not in {ProjectStatus.PROCURING, ProjectStatus.READY}
                or project.materials_committed
            ):
                continue
            recipe = self._recipe_for_project(project)
            ready = all(
                self._reserved_resource_t(project, requirement.resource_id) + 1e-9
                >= requirement.amount_t
                for requirement in recipe.resources
            )
            project.status = ProjectStatus.READY if ready else ProjectStatus.PROCURING
