from __future__ import annotations

from .application_views import (
    BuildResourceOption,
    BuildOptionRow,
    BuildOptionsView,
    FacilityUpgradeOption,
    ProjectResourceRow,
    ProjectRow,
)
from .construction.models import (
    FacilityUpgradeTarget, NewFacilityTarget,
    ProjectStatus, SurfaceCellDevelopmentTarget,
)
from .facilities import FacilityPlacementScope
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
        snapshot = power if power is not None else sim.power.snapshot(facility.operational_node_id, sim.facilities, sim.day)
        failures = sim.projects.upgrade_site_failures(facility.id, recipe.target_level, sim.day, snapshot)
        return FacilityUpgradeOption(
            recipe.target_level,
            recipe.construction_work,
            self._construction_resource_options(recipe),
            tuple(sorted(str(technology) for technology in recipe.prerequisite_technologies - sim.projects.unlocked_technologies)),
            tuple((failure.code, failure.detail) for failure in failures),
            active_project_id,
        )

    def _external_supply_blocker(self, demand) -> tuple[str, str]:
        """Translate Logistics demand state into an owning-project blocker.

        Finite project domains own their resource need and sourcing preference;
        Logistics owns whether residual off-site demand has a usable lane, source
        stock and active pipeline.  The Application layer combines those public
        contracts without making either domain inspect the other's state.
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

    def _external_demands(self, owner_kind: str) -> dict[str, object]:
        return {
            str(demand.id): demand
            for demand in self._simulation.resource_demands()
            if demand.owner_kind == owner_kind
        }

    def _resource_blockers(
        self, blockers, *, owner_kind: str, owner_id: str, demands: dict[str, object]
    ) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        for blocker in blockers:
            if blocker.code != "resource_shortage":
                rows.append((blocker.code, blocker.detail))
                continue
            demand_id = f"demand.{owner_kind}:{owner_id}:{blocker.detail}"
            demand = demands.get(demand_id)
            rows.append(
                self._external_supply_blocker(demand)
                if demand is not None
                else (blocker.code, blocker.detail)
            )
        return tuple(rows)

    def _project_blockers(self, project, power, external_demands=None) -> tuple[tuple[str, str], ...]:
        sim = self._simulation
        demands = self._external_demands("project") if external_demands is None else external_demands
        return self._resource_blockers(
            sim.projects.blockers(project.id, sim.day, power),
            owner_kind="project",
            owner_id=str(project.id),
            demands=demands,
        )

    def _project_rows(self, location_id: SpatialNodeId | None) -> tuple[ProjectRow, ...]:
        sim = self._simulation
        external_demands = self._external_demands("project")
        founding_demands = self._external_demands("founding")
        rows = []
        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if location_id is not None and project.operational_node_id != location_id:
                continue
            recipe = sim.projects.recipe_for_project(project)
            facility_definition_id = sim.projects.target_facility_definition_id(project)
            project_power = sim.power.snapshot(project.operational_node_id, sim.facilities, sim.day)
            blockers = self._project_blockers(project, project_power, external_demands)
            resources = []
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                staged_t = sim.projects.staged_resource_t(project, requirement.resource_id)
                shortage = max(0.0, requirement.amount_t - staged_t - state.committed_t)
                demand_id = None
                if state.import_committed_t is not None and shortage > 1e-9:
                    demand_id = f"demand.project:{project.id}:{requirement.resource_id}"
                resources.append(ProjectResourceRow(
                    str(requirement.resource_id), requirement.amount_t, staged_t, state.committed_t,
                    shortage, state.import_committed_t, demand_id,
                ))

            target_facility_id = None
            target_level = None
            target_cell_id = None
            target_body_id = None
            target_location_id = None
            target = project.target
            if isinstance(target, NewFacilityTarget):
                target_kind = "new_facility"
                definition = sim.facilities.definitions[target.facility_def_id]
                display_name = definition.display_name
            elif isinstance(target, FacilityUpgradeTarget):
                target_kind = "facility_upgrade"
                target_facility_id = str(target.facility_id)
                target_level = target.target_level
                definition = sim.facilities.definitions[facility_definition_id]
                display_name = definition.display_name
            else:
                target_kind = "surface_cell_development"
                target_cell_id = str(target.cell_id)
                target_location_id = str(project.operational_node_id)
                display_name = recipe.display_name

            construction_fulfillment = sim.projects.project_construction_fulfillment(
                project, project_power, sim.day
            )
            limiting_factors = sim.projects.project_limiting_factors(
                project, project_power, sim.day
            )

            rows.append(ProjectRow(
                str(project.id), target_kind, str(project.operational_node_id),
                None if facility_definition_id is None else str(facility_definition_id),
                target_facility_id, target_level, display_name, project.status, project.paused,
                project.priority, project.sourcing_policy,
                None if project.import_source_id is None else str(project.import_source_id),
                sim.projects.settings_mutable(project.id), sim.projects.sourcing_mutable(project.id),
                tuple(sim.projects.sourcing_policy_options()),
                tuple(str(source_id) for source_id in sim.projects.import_source_options(project.id)),
                project.construction_done, recipe.construction_work, project.construction_weight,
                project.materials_committed,
                None if project.completed_facility_id is None else str(project.completed_facility_id),
                tuple(resources), blockers,
                None if project.site_cell_id is None else str(project.site_cell_id),
                target_cell_id, target_body_id, target_location_id,
                construction_fulfillment, limiting_factors,
            ))
        if sim.founding is not None:
            for project in sorted(sim.founding.projects.values(), key=lambda row: str(row.id)):
                if location_id is not None and project.staging_node_id != location_id:
                    continue
                package = sim.founding.packages[project.founding_package_id]
                resources = [
                    ProjectResourceRow(
                        str(status.resource_id),
                        status.required_t,
                        status.staged_t,
                        status.committed_t,
                        status.shortage_t,
                        None,
                        None,
                    )
                    for status in sim.founding.project_resource_status(project.id)
                ]
                blockers = self._resource_blockers(
                    sim.founding.blockers(project.id, sim.day),
                    owner_kind="founding",
                    owner_id=str(project.id),
                    demands=founding_demands,
                )
                rows.append(ProjectRow(
                    str(project.id), "location_founding_deployment", str(project.staging_node_id),
                    None, None, None, project.display_name, project.status.value, project.paused,
                    project.priority, "founding",
                    None if project.preferred_source_id is None else str(project.preferred_source_id),
                    project.status.value == "preparing", False, (), (),
                    project.preparation_done, package.preparation_work, 1.0, project.inputs_consumed,
                    None, tuple(resources), blockers, None, str(project.target_core_cell_id),
                    str(project.target_body_id), str(project.new_location_id), 1.0, (),
                ))
        return tuple(rows)

    def _build_options_view(self, location_id: SpatialNodeId) -> BuildOptionsView:
        sim = self._simulation
        rows = []
        for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id)):
            definition = sim.facilities.definitions[recipe.facility_def_id]
            if definition.placement_scope is not FacilityPlacementScope.OPERATIONAL_NODE:
                continue
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
