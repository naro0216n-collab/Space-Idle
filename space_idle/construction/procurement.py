from __future__ import annotations

from ..shared import AccountState, CargoOrderId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from ..site import evaluate_site_requirements
from .models import ProjectStatus, LocalSubstitutionTier, BuildComponentRequirement, BuildProject


class ConstructionProcurementMixin:

        def advance_procurement(self, day: int) -> None:
            ordered = sorted(self.projects.values(), key=lambda p: (-p.priority, str(p.id)))
            for project in ordered:
                if project.paused or project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED, ProjectStatus.READY, ProjectStatus.BUILDING}:
                    continue
                recipe = self.recipes[project.facility_def_id]
                if not recipe.prerequisite_technologies.issubset(self.unlocked_technologies):
                    continue
                if self.site_failures(
                    project.facility_def_id, project.location_id, day,
                    self.power.snapshot(project.location_id, self.facilities, day),
                ):
                    continue
                if project.status == ProjectStatus.PLANNED:
                    project.status = ProjectStatus.PROCURING
                    project.procurement_started_day = day

                assert project.procurement_started_day is not None
                waited = day - project.procurement_started_day
                wait_limit = self.sourcing_wait_days[project.sourcing_policy]

                all_ready = True
                for component in recipe.components:
                    state = project.components[component.component_id]
                    local_res, desired_local = self._selected_local_target(project, component, day)
                    if state.import_committed_t is None:
                        state.local_target_t = desired_local
                        if local_res is not None and state.reserved_local_t + 1e-9 < desired_local:
                            need = desired_local - state.reserved_local_t
                            reserved = self.inventory.reserve(EntityId(project.id), project.location_id, local_res, need)
                            if reserved > 0:
                                if state.reserved_local_resource_id not in (None, local_res):
                                    raise RuntimeError("local substitution resource changed after reservation")
                                state.reserved_local_resource_id = local_res
                            state.reserved_local_t += reserved
                        local_met = state.reserved_local_t + 1e-9 >= desired_local
                        if local_met or waited >= wait_limit:
                            import_amount = component.amount_t - state.reserved_local_t
                            state.import_committed_t = max(0.0, import_amount)
                            if import_amount > 1e-9:
                                if project.import_source_id is None:
                                    state.import_committed_t = None
                                    all_ready = False
                                    continue
                                if not self.logistics.can_submit(
                                    project.import_source_id, project.location_id, component.import_resource_id, import_amount, day,
                                    project.import_path, project.import_mode_by_route,
                                ):
                                    state.import_committed_t = None
                                    all_ready = False
                                    continue
                                state.import_order_id = self.logistics.submit_order(
                                    project.import_source_id,
                                    project.location_id,
                                    component.import_resource_id,
                                    import_amount,
                                    project.priority,
                                    "project",
                                    EntityId(project.id),
                                    day=day,
                                    path=project.import_path,
                                    mode_by_route=project.import_mode_by_route,
                                )
                        else:
                            all_ready = False
                            continue

                    if state.import_committed_t is not None and state.import_committed_t > 1e-9:
                        need_import_reserve = state.import_committed_t - state.reserved_import_t
                        if need_import_reserve > 1e-9:
                            got = self.inventory.reserve(
                                EntityId(project.id), project.location_id, component.import_resource_id, need_import_reserve
                            )
                            state.reserved_import_t += got
                        if state.reserved_import_t + 1e-9 < state.import_committed_t:
                            all_ready = False

                    if state.reserved_local_t + state.reserved_import_t + 1e-9 < component.amount_t:
                        all_ready = False

                if all_ready:
                    project.status = ProjectStatus.READY
