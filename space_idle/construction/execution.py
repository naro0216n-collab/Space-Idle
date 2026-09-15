from __future__ import annotations

from ..execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ServiceCapacityRequirement,
)
from ..power import PowerSnapshot
from ..shared import EntityId, SpatialNodeId
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
    def construction_execution_bundle_id(project_id) -> EntityId:
        return EntityId(f"execution.construction:{project_id}")

    def _surface_development_incremental_service(self, project: ConstructionProject) -> float:
        service = self.surface_infrastructure
        if service is None or not isinstance(project.target, SurfaceCellDevelopmentTarget):
            return 0.0
        location = service.graph.locations[project.operational_node_id]
        cells = set(location.developed_cell_ids)
        cells.add(project.target.cell_id)
        prospective = sum(
            row.demand
            for row in service.load_sources_for_cells(project.operational_node_id, cells)
        )
        return max(0.0, prospective - service.demand(project.operational_node_id))

    def execution_requirement_bundles(
        self, day: int = 0
    ) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
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
            if self.project_site_failures(project, day, None):
                continue
            remaining_work = max(0.0, recipe.construction_work - project.construction_done)
            if remaining_work <= 1e-12:
                continue
            requirements = [
                ServiceCapacityRequirement(CONSTRUCTION_SERVICE_TYPE, remaining_work)
            ]
            incremental = self._surface_development_incremental_service(project)
            if incremental > 1e-12 and self.surface_infrastructure is not None:
                requirements.append(
                    ServiceCapacityRequirement(self.surface_infrastructure.service_type, incremental)
                )
            rows.append(ExecutionRequirementBundle(
                id=self.construction_execution_bundle_id(project.id),
                owner_kind="construction",
                owner_id=EntityId(str(project.id)),
                purpose="construction_work",
                operational_node_id=project.operational_node_id,
                requested_execution=1.0,
                priority=project.priority,
                requirements=tuple(requirements),
            ))
        return tuple(rows)

    def advance_construction(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        execution_allocations: ExecutionAllocationPlan,
        day: int = 0,
    ) -> None:
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
            power = power_by_location[project.operational_node_id]
            if self.project_site_failures(project, day, power):
                continue
            try:
                scale = execution_allocations.allocated(
                    self.construction_execution_bundle_id(project.id)
                )
            except KeyError:
                scale = 0.0
            if scale <= 1e-12:
                continue
            remaining_work = max(0.0, recipe.construction_work - project.construction_done)
            work = min(remaining_work, remaining_work * min(1.0, scale))
            if work <= 1e-12:
                continue
            self._commit_materials(project)
            project.status = ProjectStatus.BUILDING
            project.construction_done += work
            if project.construction_done + 1e-9 >= recipe.construction_work:
                project.construction_done = recipe.construction_work

    def settle_completions(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int = 0,
    ) -> None:
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if (
                project.paused
                or project.status not in {ProjectStatus.READY, ProjectStatus.BUILDING}
                or not self._target_ready_for_execution(project)
            ):
                continue
            recipe = self._recipe_for_project(project)
            power = power_by_location[project.operational_node_id]
            if self.project_site_failures(project, day, power):
                continue
            if recipe.self_deploying or recipe.construction_work <= 1e-12:
                self._finish_project(project)
                continue
            if project.construction_done + 1e-9 >= recipe.construction_work:
                self._finish_project(project)
