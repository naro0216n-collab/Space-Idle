from __future__ import annotations

from ..execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
)
from ..power import PowerSnapshot
from ..shared import EntityId, SpatialNodeId
from .models import (
    CONSTRUCTION_SERVICE_TYPE, ConstructionProject, FacilityDecommissionTarget, FacilityUpgradeTarget, NewFacilityTarget,
    ProjectStatus, SurfaceCellDevelopmentTarget,
)


class ConstructionExecutionMixin:

    @staticmethod
    def decommission_salvage_bundle_id(project_id) -> EntityId:
        return EntityId(f"execution.decommission_salvage:{project_id}")

    def decommission_salvage_for_project(self, project: ConstructionProject) -> dict:
        if not isinstance(project.target, FacilityDecommissionTarget):
            return {}
        if project.target.facility_id not in self.facilities.facilities:
            return {}
        return self.facilities.decommission_salvage(project.target.facility_id)

    def _decommission_admission_requirements(self, project: ConstructionProject):
        by_class: dict[str, float] = {}
        for resource_id, amount in self.decommission_salvage_for_project(project).items():
            storage_class = self.inventory.resource_storage_class.get(resource_id)
            if storage_class is None or amount <= 1e-12:
                continue
            by_class[storage_class] = by_class.get(storage_class, 0.0) + amount
        return tuple(
            StockOrPoolAdmissionRequirement(storage_class, amount)
            for storage_class, amount in sorted(by_class.items())
        )

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
        elif isinstance(target, FacilityDecommissionTarget):
            facility = self.facilities.facilities[target.facility_id]
            salvage = self.facilities.decommission_salvage(target.facility_id)
            for resource_id, amount in salvage.items():
                result = self.inventory.admit(facility.operational_node_id, resource_id, amount)
                if not result.fully_admitted:
                    raise RuntimeError("allocated decommission salvage admission changed before settlement")
            if self.decommission_finalizer is not None:
                self.decommission_finalizer(target.facility_id)
            self.facilities.finalize_decommission(target.facility_id)
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
        if isinstance(target, FacilityDecommissionTarget):
            facility = self.facilities.facilities.get(target.facility_id)
            return facility is not None and facility.operational_node_id == project.operational_node_id
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
                if isinstance(project.target, FacilityDecommissionTarget) and project.irreversible_started:
                    requirements = self._decommission_admission_requirements(project)
                    rows.append(ExecutionRequirementBundle(
                        id=self.decommission_salvage_bundle_id(project.id),
                        owner_kind="construction",
                        owner_id=EntityId(str(project.id)),
                        purpose="decommission_salvage_admission",
                        operational_node_id=project.operational_node_id,
                        requested_execution=1.0,
                        priority=project.priority,
                        requirements=requirements,
                        minimum_execution=1.0,
                        atomic=True,
                        wait_started_day=day,
                    ))
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
            if isinstance(project.target, FacilityDecommissionTarget) and not project.irreversible_started:
                blockers = self._decommission_irreversible_blockers(project.target.facility_id)
                if blockers:
                    continue
                self.facilities.begin_decommission(project.target.facility_id)
                project.irreversible_started = True
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
        execution_allocations: ExecutionAllocationPlan,
        day: int = 0,
    ) -> bool:
        physical_state_changed = False
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
                physical_state_changed = True
                continue
            if project.construction_done + 1e-9 >= recipe.construction_work:
                if isinstance(project.target, FacilityDecommissionTarget):
                    if not project.irreversible_started:
                        continue
                    try:
                        admitted = execution_allocations.allocated(
                            self.decommission_salvage_bundle_id(project.id)
                        )
                    except KeyError:
                        admitted = 0.0
                    if admitted < 1.0 - 1e-9:
                        continue
                self._finish_project(project)
                physical_state_changed = True
        return physical_state_changed
