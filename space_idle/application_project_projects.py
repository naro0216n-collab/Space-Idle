from __future__ import annotations

from .application_views import (
    BuildComponentOption,
    BuildOptionRow,
    BuildOptionsView,
    FacilityUpgradeOption,
    ProjectComponentRow,
    ProjectRow,
)
from .construction.models import FacilityUpgradeTarget, NewFacilityTarget, ProjectStatus
from .shared import SpatialNodeId


class ProjectProjectorMixin:
    @staticmethod
    def _construction_component_options(recipe) -> tuple[BuildComponentOption, ...]:
        return tuple(
            BuildComponentOption(
                component.component_id,
                component.amount_t,
                str(component.import_resource_id),
                tuple(
                    (str(tier.local_resource_id), tier.max_fraction)
                    for tier in component.local_tiers
                ),
            )
            for component in recipe.components
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
        snapshot = power if power is not None else sim.power.snapshot(
            facility.location_id, sim.facilities, sim.day
        )
        failures = sim.projects.upgrade_site_failures(
            facility.id, recipe.target_level, sim.day, snapshot
        )
        return FacilityUpgradeOption(
            recipe.target_level,
            recipe.construction_work,
            self._construction_component_options(recipe),
            tuple(
                sorted(
                    str(technology)
                    for technology in recipe.prerequisite_technologies
                    - sim.projects.unlocked_technologies
                )
            ),
            tuple((failure.code, failure.detail) for failure in failures),
            active_project_id,
        )

    def _project_rows(self, location_id: SpatialNodeId | None) -> tuple[ProjectRow, ...]:
        sim = self._simulation
        rows = []
        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if location_id is not None and project.location_id != location_id:
                continue
            recipe = sim.projects._recipe_for_project(project)
            facility_definition_id = sim.projects._target_facility_def_id(project)
            definition = sim.facilities.definitions[facility_definition_id]
            project_power = sim.power.snapshot(project.location_id, sim.facilities, sim.day)
            blockers = tuple(
                (blocker.code, blocker.detail)
                for blocker in sim.projects.blockers(project.id, sim.day, project_power)
            )
            components = []
            for requirement in recipe.components:
                state = project.components[requirement.component_id]
                max_local_fraction = max(
                    (tier.max_fraction for tier in requirement.local_tiers), default=0.0
                )
                selected_local, _target = sim.projects._selected_local_target(
                    project, requirement, sim.day
                )
                explicit_local = project.local_resource_choices.get(requirement.component_id)
                components.append(
                    ProjectComponentRow(
                        requirement.component_id,
                        requirement.amount_t,
                        str(requirement.import_resource_id),
                        state.local_target_t,
                        state.reserved_local_t,
                        state.reserved_primary_t,
                        state.reserved_import_t,
                        state.committed_local_t,
                        state.committed_primary_t,
                        state.committed_import_t,
                        state.import_committed_t,
                        None if state.import_order_id is None else str(state.import_order_id),
                        project.local_fraction_targets.get(requirement.component_id),
                        None if selected_local is None else str(selected_local),
                        explicit_local is not None,
                        max_local_fraction,
                    )
                )
            if isinstance(project.target, NewFacilityTarget):
                target_kind = "new_facility"
                target_facility_id = None
                target_level = None
            else:
                target_kind = "facility_upgrade"
                target_facility_id = str(project.target.facility_id)
                target_level = project.target.target_level
            rows.append(
                ProjectRow(
                    str(project.id),
                    target_kind,
                    str(project.location_id),
                    str(facility_definition_id),
                    target_facility_id,
                    target_level,
                    definition.display_name,
                    project.status,
                    project.paused,
                    project.priority,
                    project.sourcing_policy,
                    None if project.import_source_id is None else str(project.import_source_id),
                    None if project.import_path is None else tuple(str(x) for x in project.import_path),
                    tuple(
                        (str(route_id), mode_id)
                        for route_id, mode_id in sorted(
                            project.import_mode_by_route.items(), key=lambda row: str(row[0])
                        )
                    ),
                    project.construction_done,
                    recipe.construction_work,
                    project.construction_weight,
                    project.materials_committed,
                    None if project.completed_facility_id is None else str(project.completed_facility_id),
                    tuple(components),
                    blockers,
                )
            )
        return tuple(rows)

    def _build_options_view(self, location_id: SpatialNodeId) -> BuildOptionsView:
        sim = self._simulation
        rows = []
        for recipe in sorted(
            sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id)
        ):
            definition = sim.facilities.definitions[recipe.facility_def_id]
            failures = sim.projects.site_failures(
                recipe.facility_def_id,
                location_id,
                sim.day,
                sim.power.snapshot(location_id, sim.facilities, sim.day),
            )
            rows.append(
                BuildOptionRow(
                    str(recipe.facility_def_id),
                    definition.display_name,
                    recipe.construction_work,
                    recipe.self_deploying,
                    self._construction_component_options(recipe),
                    tuple(
                        sorted(
                            str(technology)
                            for technology in recipe.prerequisite_technologies
                            - sim.projects.unlocked_technologies
                        )
                    ),
                    tuple((failure.code, failure.detail) for failure in failures),
                )
            )
        return BuildOptionsView(str(location_id), tuple(rows))
