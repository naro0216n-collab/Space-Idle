from __future__ import annotations

from .application_views import (
    BuildResourceOption,
    BuildOptionRow,
    BuildOptionsView,
    FacilityUpgradeOption,
    ProjectResourceRow,
    ProjectRow,
)
from .construction.models import FacilityUpgradeTarget, NewFacilityTarget, ProjectStatus
from .shared import SpatialNodeId


class ProjectProjectorMixin:
    @staticmethod
    def _construction_resource_options(recipe) -> tuple[BuildResourceOption, ...]:
        return tuple(
            BuildResourceOption(str(requirement.resource_id), requirement.amount_t)
            for requirement in recipe.resources
        )

    def _facility_upgrade_option(self, facility, power=None) -> FacilityUpgradeOption | None:
        sim = self._simulation
        recipe = sim.projects.next_upgrade_recipe(facility.id)
        if recipe is None:
            return None
        active_project_id = next(
            (
                str(project.id)
                for project in sim.projects.projects.values()
                if isinstance(project.target, FacilityUpgradeTarget)
                and project.target.facility_id == facility.id
                and project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}
            ),
            None,
        )
        snapshot = power if power is not None else sim.power.snapshot(facility.location_id, sim.facilities, sim.day)
        failures = sim.projects.upgrade_site_failures(facility.id, recipe.target_level, sim.day, snapshot)
        return FacilityUpgradeOption(
            recipe.target_level,
            recipe.construction_work,
            self._construction_resource_options(recipe),
            tuple(sorted(str(technology) for technology in recipe.prerequisite_technologies - sim.projects.unlocked_technologies)),
            tuple((failure.code, failure.detail) for failure in failures),
            active_project_id,
        )

    def _project_external_supply_blocker(self, demand) -> tuple[str, str]:
        """Translate Logistics demand state into a project-facing blocker.

        Construction owns the need and sourcing policy; Logistics owns whether
        the residual off-site demand has a usable lane, source stock and active
        pipeline. The Application layer combines those contracts for the UI
        without making Construction inspect Logistics state directly.
        """
        sim = self._simulation
        resource_id = str(demand.resource_id)
        if sim.logistics.demand_remaining_t(demand) <= 1e-9:
            return ("import_transit", resource_id)

        options = sim.logistics.demand_supply_options(demand, sim.day)
        if not options.eligible_lane_ids:
            return ("import_lane", resource_id)
        if not options.operational_lane_ids:
            detail = resource_id
            if options.blockers:
                detail += ":" + ";".join(options.blockers)
            return ("import_lane_blocked", detail)
        if not options.stocked_source_ids:
            return ("import_stock", resource_id)
        return ("import_transit", resource_id)

    def _project_external_demands(self) -> dict[str, object]:
        return {
            str(demand.id): demand
            for demand in self._simulation.resource_demands()
            if demand.owner_kind == "project"
        }

    def _project_blockers(self, project, power, external_demands=None) -> tuple[tuple[str, str], ...]:
        sim = self._simulation
        demands = self._project_external_demands() if external_demands is None else external_demands
        blockers: list[tuple[str, str]] = []
        for blocker in sim.projects.blockers(project.id, sim.day, power):
            if blocker.code != "resource_shortage":
                blockers.append((blocker.code, blocker.detail))
                continue
            demand_id = f"demand.project:{project.id}:{blocker.detail}"
            demand = demands.get(demand_id)
            blockers.append(
                self._project_external_supply_blocker(demand)
                if demand is not None
                else (blocker.code, blocker.detail)
            )
        return tuple(blockers)

    def _project_rows(self, location_id: SpatialNodeId | None) -> tuple[ProjectRow, ...]:
        sim = self._simulation
        external_demands = self._project_external_demands()
        rows = []
        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if location_id is not None and project.location_id != location_id:
                continue
            recipe = sim.projects.recipe_for_project(project)
            facility_definition_id = sim.projects.target_facility_definition_id(project)
            definition = sim.facilities.definitions[facility_definition_id]
            project_power = sim.power.snapshot(project.location_id, sim.facilities, sim.day)
            blockers = self._project_blockers(project, project_power, external_demands)
            resources = []
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                reserved_t = sim.projects.reserved_resource_t(project, requirement.resource_id)
                shortage = max(0.0, requirement.amount_t - reserved_t - state.committed_t)
                demand_id = None
                if state.import_committed_t is not None and shortage > 1e-9:
                    demand_id = f"demand.project:{project.id}:{requirement.resource_id}"
                resources.append(ProjectResourceRow(
                    str(requirement.resource_id),
                    requirement.amount_t,
                    reserved_t,
                    state.committed_t,
                    shortage,
                    state.import_committed_t,
                    demand_id,
                ))
            if isinstance(project.target, NewFacilityTarget):
                target_kind = "new_facility"; target_facility_id = None; target_level = None
            else:
                target_kind = "facility_upgrade"; target_facility_id = str(project.target.facility_id); target_level = project.target.target_level
            rows.append(ProjectRow(
                str(project.id), target_kind, str(project.location_id), str(facility_definition_id),
                target_facility_id, target_level, definition.display_name, project.status, project.paused,
                project.priority, project.sourcing_policy,
                None if project.import_source_id is None else str(project.import_source_id),
                sim.projects.settings_mutable(project.id),
                sim.projects.sourcing_mutable(project.id),
                tuple(sim.projects.sourcing_policy_options()),
                tuple(str(source_id) for source_id in sim.projects.import_source_options(project.id)),
                project.construction_done, recipe.construction_work, project.construction_weight,
                project.materials_committed,
                None if project.completed_facility_id is None else str(project.completed_facility_id),
                tuple(resources), blockers,
            ))
        return tuple(rows)

    def _build_options_view(self, location_id: SpatialNodeId) -> BuildOptionsView:
        sim = self._simulation
        rows = []
        for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id)):
            definition = sim.facilities.definitions[recipe.facility_def_id]
            failures = sim.projects.site_failures(
                recipe.facility_def_id, location_id, sim.day,
                sim.power.snapshot(location_id, sim.facilities, sim.day),
            )
            rows.append(BuildOptionRow(
                str(recipe.facility_def_id), definition.display_name, recipe.construction_work,
                recipe.self_deploying, self._construction_resource_options(recipe),
                tuple(sorted(str(technology) for technology in recipe.prerequisite_technologies - sim.projects.unlocked_technologies)),
                tuple((failure.code, failure.detail) for failure in failures),
            ))
        return BuildOptionsView(
            str(location_id),
            tuple(sim.projects.sourcing_policy_options()),
            tuple(str(source_id) for source_id in sim.projects.import_source_options_for_location(location_id)),
            tuple(rows),
        )
