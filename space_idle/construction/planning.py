from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, ProjectId, SpatialNodeId
from .models import (
    ConstructionProject,
    ConstructionTarget,
    FacilityUpgradeTarget,
    NewFacilityTarget,
    ProjectBlocker,
    ProjectComponentState,
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
        components = {
            component.component_id: ProjectComponentState()
            for component in recipe.components
        }
        self.projects[project_id] = ConstructionProject(
            project_id,
            target,
            location_id,
            priority,
            sourcing_policy,
            import_source_id,
            components=components,
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

    def set_priority(self, project_id: ProjectId, priority: int) -> None:
        self.projects[project_id].priority = priority

    def _ensure_sourcing_mutable(self, project: ConstructionProject) -> None:
        if project.status not in {ProjectStatus.PLANNED, ProjectStatus.PROCURING}:
            raise ValueError("sourcing can only change before construction readiness")
        if any((state.import_committed_t or 0.0) > 1e-9 for state in project.components.values()):
            raise ValueError("sourcing cannot change after import commitment")

    def set_sourcing_policy(self, project_id: ProjectId, sourcing_policy: SourcingPolicy) -> None:
        if sourcing_policy not in self.sourcing_wait_days:
            raise ValueError(f"unknown sourcing policy: {sourcing_policy}")
        project = self.projects[project_id]
        self._ensure_sourcing_mutable(project)
        self.inventory.release_reservation(EntityId(project.id))
        for state in project.components.values():
            state.reserved_local_t = 0.0
            state.reserved_local_resource_id = None
            state.reserved_primary_t = 0.0
            state.reserved_import_t = 0.0
            state.local_target_t = 0.0
        project.sourcing_policy = sourcing_policy
        project.procurement_started_day = None
        project.status = ProjectStatus.PLANNED

    def set_construction_weight(self, project_id: ProjectId, weight: float) -> None:
        if weight < 0:
            raise ValueError("construction weight must be non-negative")
        self.projects[project_id].construction_weight = weight

    def set_import_source(self, project_id: ProjectId, location_id: SpatialNodeId | None) -> None:
        project = self.projects[project_id]
        if location_id is not None and location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        if location_id == project.location_id:
            raise ValueError("import source must differ from project location")
        self._ensure_sourcing_mutable(project)
        project.import_source_id = location_id

    def set_local_resource_choice(
        self,
        project_id: ProjectId,
        component_id: str,
        resource_id: DefinitionId | None,
        day: int = 0,
    ) -> None:
        project = self.projects[project_id]
        self._ensure_sourcing_mutable(project)
        if component_id not in project.components:
            raise KeyError(component_id)
        state = project.components[component_id]
        component = next(
            component
            for component in self._recipe_for_project(project).components
            if component.component_id == component_id
        )
        if resource_id is not None and resource_id not in {
            tier.local_resource_id for tier in component.local_tiers
        }:
            raise ValueError("resource is not a valid local substitution for this component")
        if state.reserved_local_t > 1e-12:
            if state.reserved_local_resource_id is None:
                raise RuntimeError("local reservation lacks resource type")
            self.inventory.release_reserved_amount(
                EntityId(project.id), project.location_id,
                state.reserved_local_resource_id, state.reserved_local_t,
            )
            state.reserved_local_t = 0.0
            state.reserved_local_resource_id = None
        if resource_id is None:
            project.local_resource_choices.pop(component_id, None)
        else:
            project.local_resource_choices[component_id] = resource_id
        _resource, desired_local = self._selected_local_target(project, component, day)
        state.local_target_t = desired_local

    def set_local_fraction_target(
        self,
        project_id: ProjectId,
        component_id: str,
        fraction: float,
        day: int = 0,
    ) -> None:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("local fraction must be between 0 and 1")
        project = self.projects[project_id]
        self._ensure_sourcing_mutable(project)
        if component_id not in project.components:
            raise KeyError(component_id)
        state = project.components[component_id]
        project.local_fraction_targets[component_id] = fraction
        component = next(
            component
            for component in self._recipe_for_project(project).components
            if component.component_id == component_id
        )
        _resource, desired_local = self._selected_local_target(project, component, day)
        if state.reserved_local_t > desired_local + 1e-9 and state.reserved_local_resource_id is not None:
            release = state.reserved_local_t - desired_local
            self.inventory.release_reserved_amount(
                EntityId(project.id), project.location_id,
                state.reserved_local_resource_id, release,
            )
            state.reserved_local_t = desired_local
        state.local_target_t = desired_local

    def cancel(self, project_id: ProjectId) -> None:
        project = self.projects[project_id]
        if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
            raise ValueError("project cannot be cancelled")
        if not project.materials_committed:
            self.inventory.release_reservation(EntityId(project.id))
            for state in project.components.values():
                state.reserved_local_t = 0.0
                state.reserved_local_resource_id = None
                state.reserved_primary_t = 0.0
                state.reserved_import_t = 0.0
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

    def _matching_import_lanes(self, project: ConstructionProject):
        return tuple(
            lane
            for lane in self.logistics.lanes.values()
            if lane.destination_id == project.location_id
            and (project.import_source_id is None or lane.source_id == project.import_source_id)
        )

    def _import_lane_blocker(
        self,
        project: ConstructionProject,
        component,
        state,
        day: int,
    ) -> ProjectBlocker | None:
        lanes = self._matching_import_lanes(project)
        if not lanes:
            return ProjectBlocker("import_lane", component.component_id)
        if all(self.logistics.lane_effective_capacity_t_per_day(lane.id, day) <= 1e-12 for lane in lanes):
            details = tuple(
                blocker
                for lane in lanes
                for blocker in self.logistics.lane_blockers(lane.id, day)
            )
            return ProjectBlocker(
                "import_lane_blocked",
                component.component_id + (":" + ";".join(dict.fromkeys(details)) if details else ""),
            )
        if all(
            self.inventory.available(lane.source_id, component.import_resource_id) <= 1e-12
            for lane in lanes
        ):
            return ProjectBlocker("import_stock", component.component_id)
        if state.reserved_import_t + 1e-9 < (state.import_committed_t or 0.0):
            return ProjectBlocker("import_transit", component.component_id)
        return None

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
        if project.status == ProjectStatus.PROCURING:
            waited = 0 if project.procurement_started_day is None else day - project.procurement_started_day
            wait_limit = self.sourcing_wait_days[project.sourcing_policy]
            for component in recipe.components:
                state = project.components[component.component_id]
                if state.import_committed_t is not None:
                    blocker = self._import_lane_blocker(project, component, state, day)
                    if blocker is not None:
                        blockers.append(blocker)
                    continue
                _local_resource, desired_local = self._selected_local_target(project, component, day)
                covered_on_site = state.reserved_local_t + state.reserved_primary_t
                if covered_on_site + 1e-9 >= component.amount_t:
                    continue
                local_shortfall = max(0.0, desired_local - state.reserved_local_t)
                if local_shortfall > 1e-9 and waited < wait_limit:
                    blockers.append(ProjectBlocker("local_supply_wait", component.component_id))
                    continue
                if not self._matching_import_lanes(project):
                    blockers.append(ProjectBlocker("import_lane", component.component_id))
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
                ]
                resource_capacity = any(
                    self.inventory.available(project.location_id, resource_id) > 1e-12
                    and spec.work_per_t_per_day > 0
                    for resource_id, spec in self.construction_resource_providers.items()
                )
                if not providers and not resource_capacity:
                    blockers.append(ProjectBlocker("construction_capacity", "no construction provider"))
        return tuple(blockers)
