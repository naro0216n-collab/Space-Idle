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
    FacilityUpgradeTarget, FacilityDecommissionTarget, NewFacilityTarget,
    ProjectStatus, SurfaceCellDevelopmentTarget,
)
from .facilities import FacilityPlacementScope
from .shared import EntityId, SpatialNodeId


class ProjectProjectorMixin:

    @staticmethod
    def _projected_material_readiness_day(
        *, day: int, owner_kind: str, owner_id: str, resources, requirement_rows
    ) -> int | None:
        shortages = [row for row in resources if row.shortage_t > 1e-9]
        if not shortages:
            return day
        by_resource = {
            row.resource_id: row
            for row in requirement_rows
            if row.owner_kind == owner_kind and row.owner_id == owner_id
        }
        readiness_days: list[int] = []
        for resource in shortages:
            requirement = by_resource.get(resource.resource_id)
            if requirement is None:
                return None
            if requirement.external_required_t <= 1e-9:
                readiness_days.append(day)
                continue
            if requirement.remaining_t > 1e-9:
                return None
            if requirement.earliest_confirmed_arrival_day is None:
                return None
            readiness_days.append(requirement.earliest_confirmed_arrival_day)
        return max(readiness_days, default=day)
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
        plan_failures = sim.projects.upgrade_plan_failures(facility.id)
        active_project_id = next(
            (failure.detail for failure in plan_failures if failure.code == "active_upgrade_project"),
            None,
        )
        snapshot = (
            power
            if power is not None
            else self._tick_decision_projection().allocations.power_by_location[facility.operational_node_id]
        )
        site_failures = sim.projects.upgrade_site_failures(
            facility.id, recipe.target_level, sim.day, snapshot
        )
        blockers = tuple(
            ("technology", str(technology))
            for technology in sorted(
                recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                key=str,
            )
        ) + tuple((failure.code, failure.detail) for failure in site_failures)
        for failure in plan_failures:
            row = (failure.code, failure.detail)
            if row not in blockers:
                blockers += (row,)
        return FacilityUpgradeOption(
            target_level=recipe.target_level,
            construction_required=recipe.construction_work,
            resources=self._construction_resource_options(recipe),
            blockers=blockers,
            can_plan=not plan_failures,
            active_project_id=active_project_id,
        )

    def _external_supply_blocker(
        self, requirement, execution_allocation=None
    ) -> tuple[str, str]:
        """Translate Logistics Supply Requirement state into an owning-project blocker.

        Finite project domains own their resource need and sourcing preference;
        Logistics owns whether residual off-site requirement has a usable source/path,
        source stock and active pipeline.  The Application layer combines those public
        contracts without making either domain inspect the other's state.
        """
        sim = self._simulation
        resource_id = str(requirement.resource_id)
        if sim.logistics.requirement_remaining_t(requirement) <= 1e-9:
            return ("import_transit", resource_id)

        options = sim.logistics.supply_planning_options(
            requirement,
            sim.day,
            execution_allocation=execution_allocation,
        )
        if not options.candidate_source_ids:
            return ("import_source", resource_id)
        if not options.operational_source_ids:
            detail = resource_id
            if options.blockers:
                detail += ":" + ";".join(options.blockers)
            return ("import_transport_blocked", detail)
        if not options.stocked_source_ids:
            return ("import_stock", resource_id)
        return ("import_transit", resource_id)

    def _external_requirements(self, owner_kind: str, requirements=None) -> dict[str, object]:
        return {
            str(requirement.id): requirement
            for requirement in (
                self._simulation.supplys()
                if requirements is None else requirements
            )
            if requirement.owner_kind == owner_kind
        }

    def _resource_blockers(
        self,
        blockers,
        *,
        owner_kind: str,
        owner_id: str,
        requirements: dict[str, object],
        execution_allocation=None,
    ) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        for blocker in blockers:
            if blocker.code != "resource_shortage":
                rows.append((blocker.code, blocker.detail))
                continue
            requirement_id = f"requirement.{owner_kind}:{owner_id}:{blocker.detail}"
            requirement = requirements.get(requirement_id)
            rows.append(
                self._external_supply_blocker(requirement, execution_allocation)
                if requirement is not None
                else (blocker.code, blocker.detail)
            )
        return tuple(rows)

    def _project_blockers(
        self, project, power, external_requirements=None, execution_allocation=None
    ) -> tuple[tuple[str, str], ...]:
        sim = self._simulation
        requirements = self._external_requirements("project") if external_requirements is None else external_requirements
        return self._resource_blockers(
            sim.projects.blockers(project.id, sim.day, power),
            owner_kind="project",
            owner_id=str(project.id),
            requirements=requirements,
            execution_allocation=execution_allocation,
        )

    def _project_rows(self, location_id: SpatialNodeId | None) -> tuple[ProjectRow, ...]:
        sim = self._simulation
        decision = self._tick_decision_projection()
        requirement_rows = self._requirement_rows(
            execution_allocation=decision.allocations.transport,
            resolutions=decision.plan.requirement_resolutions,
        )
        external_requirements = self._external_requirements(
            "project", decision.plan.external_requirements
        )
        founding_requirements = self._external_requirements(
            "founding", decision.plan.external_requirements
        )
        powers = decision.allocations.power_by_location
        rows = []
        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if location_id is not None and project.operational_node_id != location_id:
                continue
            recipe = sim.projects.recipe_for_project(project)
            facility_definition_id = sim.projects.target_facility_definition_id(project)
            project_power = powers[project.operational_node_id]
            blockers = self._project_blockers(
                project,
                project_power,
                external_requirements,
                decision.allocations.transport,
            )
            resources = []
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                reserved_t = sim.projects.reserved_resource_t(project, requirement.resource_id)
                shortage = max(0.0, requirement.amount_t - reserved_t - state.committed_t)
                requirement_id = None
                if state.import_committed_t is not None and shortage > 1e-9:
                    requirement_id = f"requirement.project:{project.id}:{requirement.resource_id}"
                resources.append(ProjectResourceRow(
                    str(requirement.resource_id), requirement.amount_t, reserved_t, 0.0, state.committed_t,
                    shortage, state.import_committed_t, requirement_id,
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
            elif isinstance(target, FacilityDecommissionTarget):
                target_kind = "facility_decommission"
                target_facility_id = str(target.facility_id)
                facility_definition_id = target.facility_definition_id
                definition = sim.facilities.definitions[target.facility_definition_id]
                display_name = definition.display_name
            else:
                target_kind = "surface_cell_development"
                target_cell_id = str(target.cell_id)
                target_location_id = str(project.operational_node_id)
                display_name = recipe.display_name

            construction_fulfillment = sim.projects.project_construction_fulfillment(
                project, project_power, decision.allocations.execution,
                decision.allocations.services, sim.day
            )
            limiting_factors = sim.projects.project_limiting_factors(
                project, project_power, decision.allocations.execution,
                decision.allocations.services, sim.day
            )

            rows.append(ProjectRow(
                str(project.id), target_kind, str(project.operational_node_id),
                None if facility_definition_id is None else str(facility_definition_id),
                target_facility_id, target_level, display_name, project.status, project.paused,
                project.priority, project.sourcing_policy,
                (None if (assigned_policy_id := sim.logistics.assigned_policy_id_for("project", EntityId(str(project.id)))) is None else str(assigned_policy_id)),
                (None if (resolved_policy := sim.logistics.resolved_policy_for("project", EntityId(str(project.id)))) is None else str(resolved_policy.id)),
                sim.projects.settings_mutable(project.id), sim.projects.sourcing_mutable(project.id),
                tuple(sim.projects.sourcing_policy_options()),
                tuple(str(row.id) for row in sim.logistics.logistics_policy_rows()),
                project.construction_done, recipe.construction_work,
                project.materials_committed,
                None if project.completed_facility_id is None else str(project.completed_facility_id),
                tuple(resources), blockers,
                None if project.site_cell_id is None else str(project.site_cell_id),
                target_cell_id, target_body_id, target_location_id,
                construction_fulfillment, limiting_factors,
                self._projected_material_readiness_day(
                    day=sim.day,
                    owner_kind="project",
                    owner_id=str(project.id),
                    resources=resources,
                    requirement_rows=requirement_rows,
                ),
                project.irreversible_started,
                tuple(
                    (str(resource_id), amount)
                    for resource_id, amount in sorted(
                        sim.projects.decommission_salvage_for_project(project).items(), key=lambda row: str(row[0])
                    )
                ),
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
                        0.0,
                        status.staged_t,
                        status.committed_t,
                        status.shortage_t,
                        None,
                        None,
                    )
                    for status in sim.founding.project_resource_status(project.id)
                ]
                blockers = self._resource_blockers(
                    sim.founding.blockers(
                        project.id,
                        sim.day,
                        powers[project.staging_node_id],
                    ),
                    owner_kind="founding",
                    owner_id=str(project.id),
                    requirements=founding_requirements,
                    execution_allocation=decision.allocations.transport,
                )
                rows.append(ProjectRow(
                    id=str(project.id),
                    target_kind="location_founding_deployment",
                    operational_node_id=str(project.staging_node_id),
                    facility_definition_id=None,
                    target_facility_id=None,
                    target_level=None,
                    display_name=project.display_name,
                    status=project.status.value,
                    paused=project.paused,
                    priority=project.priority,
                    sourcing_policy="founding",
                    logistics_policy_id=(
                        None if (assigned_policy_id := sim.logistics.assigned_policy_id_for("founding", EntityId(str(project.id)))) is None
                        else str(assigned_policy_id)
                    ),
                    resolved_logistics_policy_id=(
                        None if (resolved_policy := sim.logistics.resolved_policy_for("founding", EntityId(str(project.id)))) is None
                        else str(resolved_policy.id)
                    ),
                    settings_editable=project.status.value == "preparing",
                    sourcing_editable=False,
                    sourcing_policy_options=(),
                    logistics_policy_options=tuple(str(row.id) for row in sim.logistics.logistics_policy_rows()),
                    construction_done=project.preparation_done,
                    construction_required=package.preparation_work,
                    materials_committed=project.inputs_consumed,
                    completed_facility_id=None,
                    resources=tuple(resources),
                    blockers=blockers,
                    site_cell_id=None,
                    target_cell_id=str(project.target_core_cell_id),
                    target_body_id=str(project.target_body_id),
                    target_location_id=str(project.new_location_id),
                    construction_fulfillment=1.0,
                    limiting_factors=(),
                    projected_material_readiness_day=self._projected_material_readiness_day(
                        day=sim.day,
                        owner_kind="founding",
                        owner_id=str(project.id),
                        resources=resources,
                        requirement_rows=requirement_rows,
                    ),
                ))
        return tuple(rows)

    def _build_options_view(self, location_id: SpatialNodeId) -> BuildOptionsView:
        sim = self._simulation
        powers = self._tick_decision_projection().allocations.power_by_location
        rows = []
        for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id)):
            definition = sim.facilities.definitions[recipe.facility_def_id]
            if definition.placement_scope is not FacilityPlacementScope.OPERATIONAL_NODE:
                continue
            plan_failures = sim.projects.build_plan_failures(
                recipe.facility_def_id, location_id
            )
            site_failures = sim.projects.site_failures(
                recipe.facility_def_id, location_id, sim.day, powers[location_id]
            )
            blockers = tuple(
                ("technology", str(technology))
                for technology in sorted(
                    recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                    key=str,
                )
            ) + tuple((failure.code, failure.detail) for failure in site_failures)
            rows.append(BuildOptionRow(
                facility_definition_id=str(recipe.facility_def_id),
                display_name=definition.display_name,
                construction_required=recipe.construction_work,
                self_deploying=recipe.self_deploying,
                resources=self._construction_resource_options(recipe),
                blockers=blockers,
                can_plan=not plan_failures,
            ))
        return BuildOptionsView(
            str(location_id),
            tuple(sim.projects.sourcing_policy_options()),
            tuple(str(row.id) for row in sim.logistics.logistics_policy_rows()),
            tuple(rows),
        )
