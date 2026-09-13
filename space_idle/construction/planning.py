from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, ProjectId, SpatialNodeId
from .models import (
    ConstructionProject,
    ConstructionTarget,
    FacilityUpgradeTarget,
    NewFacilityTarget,
    ProjectBlocker,
    ProjectResourceState,
    ProjectStatus,
    SourcingPolicy,
)


class ConstructionPlanningMixin:
    def _create_project(
        self,
        target: ConstructionTarget,
        location_id: SpatialNodeId,
        priority: int,
        sourcing_policy: SourcingPolicy,
        import_source_id: SpatialNodeId | None,
    ) -> ProjectId:
        if location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        if sourcing_policy not in self.sourcing_wait_days:
            raise ValueError(f"unknown sourcing policy: {sourcing_policy}")
        if import_source_id is not None and import_source_id not in self.facilities.environment.graph.nodes:
            raise KeyError(import_source_id)
        if import_source_id == location_id:
            raise ValueError("import source must differ from project location")

        if isinstance(target, NewFacilityTarget):
            recipe = self.recipes[target.facility_def_id]
        else:
            facility = self.facilities.facilities[target.facility_id]
            recipe = self.upgrade_recipes[(facility.definition_id, target.target_level)]

        self._counter += 1
        project_id = ProjectId(f"project.{self._counter}")
        resources = {
            requirement.resource_id: ProjectResourceState()
            for requirement in recipe.resources
        }
        self.projects[project_id] = ConstructionProject(
            project_id,
            target,
            location_id,
            priority,
            sourcing_policy,
            import_source_id,
            resources=resources,
        )
        return project_id

    def plan_build(
        self,
        facility_def_id: DefinitionId,
        location_id: SpatialNodeId,
        priority: int,
        sourcing_policy: SourcingPolicy,
        day: int = 0,
        import_source_id: SpatialNodeId | None = None,
    ) -> ProjectId:
        if facility_def_id not in self.recipes:
            raise KeyError(facility_def_id)
        return self._create_project(
            NewFacilityTarget(facility_def_id), location_id, priority, sourcing_policy, import_source_id
        )

    def plan_upgrade(
        self,
        facility_id: EntityId,
        priority: int,
        sourcing_policy: SourcingPolicy,
        day: int = 0,
        import_source_id: SpatialNodeId | None = None,
    ) -> ProjectId:
        facility = self.facilities.facilities[facility_id]
        target_level = facility.level + 1
        if (facility.definition_id, target_level) not in self.upgrade_recipes:
            raise ValueError("facility has no next upgrade recipe")
        if any(
            isinstance(project.target, FacilityUpgradeTarget)
            and project.target.facility_id == facility_id
            and project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}
            for project in self.projects.values()
        ):
            raise ValueError("facility already has an active upgrade project")
        return self._create_project(
            FacilityUpgradeTarget(facility_id, target_level),
            facility.location_id,
            priority,
            sourcing_policy,
            import_source_id,
        )

    def settings_mutable(self, project_id: ProjectId) -> bool:
        return self.projects[project_id].status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}

    def set_priority(self, project_id: ProjectId, priority: int) -> None:
        if not self.settings_mutable(project_id):
            raise ValueError("completed or cancelled project settings cannot change")
        self.projects[project_id].priority = priority

    def sourcing_mutable(self, project_id: ProjectId) -> bool:
        project = self.projects[project_id]
        return (
            project.status in {ProjectStatus.PLANNED, ProjectStatus.PROCURING}
            and not any(
                state.import_committed_t is not None
                for state in project.resources.values()
            )
        )

    def sourcing_policy_options(self) -> tuple[SourcingPolicy, ...]:
        return tuple(self.sourcing_wait_days)

    def import_source_options_for_location(self, location_id: SpatialNodeId) -> tuple[SpatialNodeId, ...]:
        if location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        return tuple(
            sorted(
                (
                    candidate_id
                    for candidate_id in self.facilities.environment.graph.nodes
                    if candidate_id != location_id
                ),
                key=str,
            )
        )

    def import_source_options(self, project_id: ProjectId) -> tuple[SpatialNodeId, ...]:
        return self.import_source_options_for_location(self.projects[project_id].location_id)

    def _ensure_sourcing_mutable(self, project: ConstructionProject) -> None:
        if not self.sourcing_mutable(project.id):
            if project.status not in {ProjectStatus.PLANNED, ProjectStatus.PROCURING}:
                raise ValueError("sourcing can only change before construction readiness")
            raise ValueError("sourcing cannot change after import commitment")

    def _release_project_reservations(self, project: ConstructionProject) -> None:
        self._release_project_resource_reservations(project)

    def set_sourcing_policy(self, project_id: ProjectId, sourcing_policy: SourcingPolicy) -> None:
        if sourcing_policy not in self.sourcing_wait_days:
            raise ValueError(f"unknown sourcing policy: {sourcing_policy}")
        project = self.projects[project_id]
        self._ensure_sourcing_mutable(project)
        self._release_project_reservations(project)
        for state in project.resources.values():
            state.import_committed_t = None
        project.sourcing_policy = sourcing_policy
        project.procurement_started_day = None
        project.status = ProjectStatus.PLANNED

    def set_construction_weight(self, project_id: ProjectId, weight: float) -> None:
        if weight < 0:
            raise ValueError("construction weight must be non-negative")
        if not self.settings_mutable(project_id):
            raise ValueError("completed or cancelled project settings cannot change")
        self.projects[project_id].construction_weight = weight

    def set_import_source(self, project_id: ProjectId, location_id: SpatialNodeId | None) -> None:
        project = self.projects[project_id]
        if location_id is not None and location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        if location_id == project.location_id:
            raise ValueError("import source must differ from project location")
        self._ensure_sourcing_mutable(project)
        project.import_source_id = location_id

    def cancel(self, project_id: ProjectId) -> None:
        project = self.projects[project_id]
        if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
            raise ValueError("project cannot be cancelled")
        if not project.materials_committed:
            self._release_project_reservations(project)
        project.status = ProjectStatus.CANCELLED
        project.paused = False
        project.pause_started_day = None

    def pause(self, project_id: ProjectId, day: int) -> None:
        project = self.projects[project_id]
        if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
            raise ValueError("project cannot be paused")
        if project.paused:
            return
        project.paused = True
        project.pause_started_day = day

    def resume(self, project_id: ProjectId, day: int) -> None:
        project = self.projects[project_id]
        if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
            raise ValueError("project cannot be resumed")
        if not project.paused:
            return
        if project.procurement_started_day is not None and project.pause_started_day is not None:
            project.procurement_started_day += max(0, day - project.pause_started_day)
        project.paused = False
        project.pause_started_day = None

    def blockers(
        self,
        project_id: ProjectId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[ProjectBlocker, ...]:
        project = self.projects[project_id]
        if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
            return ()
        recipe = self._recipe_for_project(project)
        blockers: list[ProjectBlocker] = []
        if project.paused:
            blockers.append(ProjectBlocker("manual_pause", "建設案件が手動停止中"))
        if isinstance(project.target, FacilityUpgradeTarget):
            facility = self.facilities.facilities.get(project.target.facility_id)
            if facility is None:
                blockers.append(ProjectBlocker("upgrade_target_missing", str(project.target.facility_id)))
            elif facility.location_id != project.location_id:
                blockers.append(ProjectBlocker("upgrade_target_location", str(project.target.facility_id)))
            elif facility.level != project.target.target_level - 1:
                blockers.append(ProjectBlocker(
                    "upgrade_level_conflict",
                    f"current={facility.level}, target={project.target.target_level}",
                ))
        missing_tech = recipe.prerequisite_technologies - self.unlocked_technologies
        if missing_tech:
            blockers.append(ProjectBlocker("technology", ",".join(sorted(map(str, missing_tech)))))
        site_power = power if power is not None else self.power.snapshot(project.location_id, self.facilities, day)
        for failure in self.project_site_failures(project, day, site_power):
            blockers.append(ProjectBlocker(failure.code, failure.detail))
        if project.status in {ProjectStatus.PROCURING, ProjectStatus.READY} and not project.materials_committed:
            waited = 0 if project.procurement_started_day is None else day - project.procurement_started_day
            wait_limit = self.sourcing_wait_days[project.sourcing_policy]
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                if self._reserved_resource_t(project, requirement.resource_id) + 1e-9 >= requirement.amount_t:
                    continue
                if state.import_committed_t is None:
                    if waited < wait_limit:
                        blockers.append(ProjectBlocker("destination_supply_wait", str(requirement.resource_id)))
                    continue
                blockers.append(ProjectBlocker("resource_shortage", str(requirement.resource_id)))
        if (
            project.status in {ProjectStatus.READY, ProjectStatus.BUILDING}
            and not recipe.self_deploying
            and recipe.construction_work > 0
        ):
            if project.construction_weight <= 1e-12:
                blockers.append(ProjectBlocker("construction_allocation", "construction weight is zero"))
            if power is not None:
                if self.construction_capacity_at(project.location_id, power, day) <= 1e-12:
                    blockers.append(ProjectBlocker("construction_capacity", "no usable construction flow"))
            else:
                providers = [
                    facility
                    for facility in self.facilities.active_compatible_at(project.location_id, day)
                    if facility.definition_id in self.construction_providers
                    and self.facilities.maintenance_factor(facility.id) > 1e-12
                ]
                resource_capacity = any(
                    self.inventory.available(project.location_id, resource_id) > 1e-12
                    and spec.work_per_t_per_day > 0
                    for resource_id, spec in self.construction_resource_providers.items()
                )
                if not providers and not resource_capacity:
                    blockers.append(ProjectBlocker("construction_capacity", "no construction provider"))
        return tuple(blockers)
