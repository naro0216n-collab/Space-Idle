from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Mapping

from .application_views import BuildComponentOption, BuildOptionRow, BuildOptionsView, ProjectComponentRow, ProjectRow
from .contracts import CapabilityContractTemplate, CargoContractTemplate
from .shared import ContractId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from .site import evaluate_site_requirements


class ProjectProjectorMixin:
    def _project_rows(self, location_id: SpatialNodeId | None) -> tuple[ProjectRow, ...]:
        sim = self._simulation
        rows = []
        for project in sorted(sim.projects.projects.values(), key=lambda p: str(p.id)):
            if location_id is not None and project.location_id != location_id:
                continue
            recipe = sim.projects.recipes[project.facility_def_id]
            definition = sim.facilities.definitions[project.facility_def_id]
            project_power = sim.power.snapshot(project.location_id, sim.facilities, sim.day)
            blockers = tuple((b.code, b.detail) for b in sim.projects.blockers(project.id, sim.day, project_power))
            components = []
            for requirement in recipe.components:
                state = project.components[requirement.component_id]
                max_local_fraction = max((tier.max_fraction for tier in requirement.local_tiers), default=0.0)
                selected_local, _target = sim.projects._selected_local_target(project, requirement, sim.day)
                explicit_local = project.local_resource_choices.get(requirement.component_id)
                components.append(ProjectComponentRow(
                    requirement.component_id, requirement.amount_t, str(requirement.import_resource_id),
                    state.local_target_t, state.reserved_local_t, state.reserved_import_t,
                    state.committed_local_t, state.committed_import_t,
                    state.import_committed_t, None if state.import_order_id is None else str(state.import_order_id),
                    project.local_fraction_targets.get(requirement.component_id),
                    None if selected_local is None else str(selected_local), explicit_local is not None, max_local_fraction,
                ))
            rows.append(ProjectRow(
                str(project.id), str(project.location_id), str(project.facility_def_id), definition.display_name,
                project.status, project.paused, project.priority, project.sourcing_policy,
                None if project.import_source_id is None else str(project.import_source_id),
                None if project.import_path is None else tuple(str(x) for x in project.import_path),
                tuple((str(route_id), mode_id) for route_id, mode_id in sorted(project.import_mode_by_route.items(), key=lambda row: str(row[0]))),
                project.construction_done, recipe.construction_work, project.construction_weight,
                project.materials_committed, tuple(components), blockers,
            ))
        return tuple(rows)

    def _build_options_view(self, location_id: SpatialNodeId) -> BuildOptionsView:
        sim = self._simulation
        # Build options expose why a definition cannot currently be established
        # at a site; they do not hide generic facilities behind location IDs.
        rows = []
        for recipe in sorted(sim.projects.recipes.values(), key=lambda r: str(r.facility_def_id)):
            definition = sim.facilities.definitions[recipe.facility_def_id]
            components = tuple(
                BuildComponentOption(
                    component.component_id,
                    component.amount_t,
                    str(component.import_resource_id),
                    tuple((str(t.local_resource_id), t.max_fraction) for t in component.local_tiers),
                )
                for component in recipe.components
            )
            failures = sim.projects.site_failures(
                recipe.facility_def_id, location_id, sim.day,
                sim.power.snapshot(location_id, sim.facilities, sim.day),
            )
            rows.append(BuildOptionRow(
                str(recipe.facility_def_id),
                definition.display_name,
                recipe.construction_work,
                recipe.self_deploying,
                components,
                tuple(sorted(str(x) for x in recipe.prerequisite_technologies - sim.projects.unlocked_technologies)),
                tuple((f.code, f.detail) for f in failures),
            ))
        return BuildOptionsView(str(location_id), tuple(rows))
