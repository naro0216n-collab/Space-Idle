from __future__ import annotations

from ..execution_requirements import (
    ExecutionAllocationPlan,
    ReservationAcquisitionRequirement,
)
from ..resource_demand import ResourceDemand
from ..shared import EntityId
from .models import ProjectStatus, FacilityUpgradeTarget


class ConstructionProcurementMixin:

    def _activate_procurement_if_eligible(self, project, day: int) -> bool:
        """Enter procurement when current authoritative conditions allow it.

        Player Commands are applied after Boundary settlement and before the
        Physical snapshot, so a newly planned eligible project must be able to
        generate same-day procurement intent without waiting for the next day
        boundary. Projects blocked by technology/site state remain PLANNED.
        """
        if project.paused or project.status is not ProjectStatus.PLANNED:
            return project.status is ProjectStatus.PROCURING
        recipe = self._recipe_for_project(project)
        if not recipe.prerequisite_technologies.issubset(self.unlocked_technologies):
            return False
        if self.project_site_failures(project, day, None):
            return False
        if isinstance(project.target, FacilityUpgradeTarget) and any(
            blocker.code.startswith("upgrade_") for blocker in self.blockers(project.id, day)
        ):
            return False
        project.status = ProjectStatus.PROCURING
        project.procurement_started_day = day
        return True

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
                reserved = self._reserved_resource_t(project, requirement.resource_id)
                missing = max(0.0, requirement.amount_t - state.committed_t - reserved)
                if missing <= 1e-9 or state.import_committed_t is None:
                    continue
                demands.append(ResourceDemand(
                    self._resource_demand_id(project.id, requirement.resource_id),
                    "project",
                    EntityId(str(project.id)),
                    project.operational_node_id,
                    requirement.resource_id,
                    missing,
                    project.priority,
                    project.import_source_id,
                ))
        return tuple(demands)

    def reservation_acquisition_requirements(
        self, day: int
    ) -> tuple[ReservationAcquisitionRequirement, ...]:
        del day
        rows: list[ReservationAcquisitionRequirement] = []
        for project in sorted(self.projects.values(), key=lambda row: (-row.priority, str(row.id))):
            if (
                project.paused
                or project.status not in {ProjectStatus.PROCURING, ProjectStatus.READY}
                or project.materials_committed
            ):
                continue
            recipe = self._recipe_for_project(project)
            for requirement in recipe.resources:
                reserved = self._reserved_resource_t(project, requirement.resource_id)
                missing = max(0.0, requirement.amount_t - reserved)
                if missing <= 1e-9:
                    continue
                rows.append(ReservationAcquisitionRequirement(
                    id=self._reservation_acquisition_id(project.id, requirement.resource_id),
                    owner_id=self._resource_reservation_owner_id(project.id),
                    operational_node_id=project.operational_node_id,
                    resource_id=requirement.resource_id,
                    requested_amount=missing,
                    priority=project.priority,
                    purpose="construction_materials",
                ))
        return tuple(rows)

    def advance_procurement(self, day: int) -> None:
        """Advance sourcing policy without consuming or reserving inventory."""
        ordered = sorted(self.projects.values(), key=lambda project: (-project.priority, str(project.id)))
        for project in ordered:
            if project.paused or project.status in {
                ProjectStatus.COMPLETE,
                ProjectStatus.CANCELLED,
                ProjectStatus.READY,
                ProjectStatus.BUILDING,
            }:
                continue
            if project.status is ProjectStatus.PLANNED and not self._activate_procurement_if_eligible(project, day):
                continue

            recipe = self._recipe_for_project(project)
            assert project.procurement_started_day is not None
            waited = day - project.procurement_started_day
            wait_limit = self.sourcing_wait_days[project.sourcing_policy]
            if waited < wait_limit:
                continue
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                reserved = self._reserved_resource_t(project, requirement.resource_id)
                if state.import_committed_t is None and state.committed_t + reserved + 1e-9 < requirement.amount_t:
                    state.import_committed_t = max(
                        0.0, requirement.amount_t - state.committed_t - reserved
                    )

    def finalize_procurement(
        self, allocations: ExecutionAllocationPlan, day: int
    ) -> None:
        del day
        ordered = sorted(self.projects.values(), key=lambda project: (-project.priority, str(project.id)))
        for project in ordered:
            if (
                project.paused
                or project.status not in {ProjectStatus.PROCURING, ProjectStatus.READY}
                or project.materials_committed
            ):
                continue
            recipe = self._recipe_for_project(project)
            self._acquire_project_reservations(project, allocations)
            ready = all(
                self._reserved_resource_t(project, requirement.resource_id) + 1e-9
                >= requirement.amount_t
                for requirement in recipe.resources
            )
            project.status = ProjectStatus.READY if ready else ProjectStatus.PROCURING
