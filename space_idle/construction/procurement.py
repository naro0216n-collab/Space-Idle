from __future__ import annotations

from ..resource_claim import ResourceAllocationPlan, ResourceClaim
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
                staged = self._staged_resource_t(project, requirement.resource_id)
                missing = max(0.0, requirement.amount_t - state.committed_t - staged)
                if missing <= 1e-9:
                    continue
                if state.import_committed_t is None:
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

    def resource_claims(self, day: int) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for project in sorted(self.projects.values(), key=lambda row: (-row.priority, str(row.id))):
            if (
                project.paused
                or project.status not in {ProjectStatus.PROCURING, ProjectStatus.READY}
                or project.materials_committed
            ):
                continue
            recipe = self._recipe_for_project(project)
            for requirement in recipe.resources:
                staged = self._staged_resource_t(project, requirement.resource_id)
                missing = max(0.0, requirement.amount_t - staged)
                if missing <= 1e-9:
                    continue
                claims.append(ResourceClaim(
                    self._resource_claim_id(project.id, requirement.resource_id),
                    project.operational_node_id,
                    requirement.resource_id,
                    missing,
                    project.priority,
                    "project",
                    EntityId(str(project.id)),
                    "procurement",
                    demand_id=self._resource_demand_id(project.id, requirement.resource_id),
                ))
        return tuple(claims)

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
            # Boundary policy maturation only checks structural/nominal site
            # viability.  Current Power availability is an allocation result
            # and cannot be recomputed here before the tick DAG runs.
            if self.project_site_failures(project, day, None):
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
                staged = self._staged_resource_t(project, requirement.resource_id)
                if state.import_committed_t is None and state.committed_t + staged + 1e-9 < requirement.amount_t:
                    state.import_committed_t = max(
                        0.0, requirement.amount_t - state.committed_t - staged
                    )

    def finalize_procurement(
        self, allocations: ResourceAllocationPlan, day: int
    ) -> None:
        """Commit this tick's ResourceAllocation into durable project staging."""
        ordered = sorted(self.projects.values(), key=lambda project: (-project.priority, str(project.id)))
        for project in ordered:
            if (
                project.paused
                or project.status not in {ProjectStatus.PROCURING, ProjectStatus.READY}
                or project.materials_committed
            ):
                continue
            recipe = self._recipe_for_project(project)
            self._stage_project_allocations(project, allocations)
            ready = all(
                self._staged_resource_t(project, requirement.resource_id) + 1e-9
                >= requirement.amount_t
                for requirement in recipe.resources
            )
            project.status = ProjectStatus.READY if ready else ProjectStatus.PROCURING
