from __future__ import annotations

from .application_views import (
    ResearchExperienceRow, ResearchKnowledgeRow, ResearchPrototypeResourceRow,
    ResearchProviderRow, ResearchRow, ResearchView,
)
from .app_contracts.progression_views import ResearchExecutionSiteRow, ResearchSiteOptionRow
from .research_models import (
    ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
    ResearchProviderSourceKind,
)
from .site import requires_surface_cell_context


class ResearchProgressionProjectorMixin:
    def _research_site_options(self, definition, spec, *, power_by_location) -> tuple[ResearchSiteOptionRow, ...]:
        sim = self._simulation
        if sim.research is None or not isinstance(spec, (ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)):
            return ()
        requires_cell = requires_surface_cell_context(spec.site_requirements)
        rows: list[ResearchSiteOptionRow] = []
        for node in sim.graph.operational_nodes():
            location = sim.graph.locations.get(node.id)
            cell_ids = tuple(sorted(location.developed_cell_ids, key=str)) if location is not None and requires_cell else (None,)
            for surface_cell_id in cell_ids:
                if isinstance(spec, ResearchPrototypeStageSpec):
                    blockers = sim.research.prototype_site_blockers(definition.id, node.id, sim.day, power_by_location.get(node.id), surface_cell_id)
                    can_select = sim.research.can_select_prototype_site(definition.id, node.id, sim.day, surface_cell_id)
                else:
                    blockers = sim.research.demonstration_site_blockers(definition.id, node.id, sim.day, power_by_location.get(node.id), surface_cell_id)
                    can_select = sim.research.can_select_demonstration_site(definition.id, node.id, sim.day, surface_cell_id)
                rows.append(ResearchSiteOptionRow(
                    str(node.id), None if surface_cell_id is None else str(surface_cell_id), blockers, can_select
                ))
        return tuple(rows)

    def _research_provider_rows(self, power_by_location) -> tuple[ResearchProviderRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchProviderRow] = []
        provider_by_facility_def = {
            provider.source_definition_id: provider
            for provider in sim.research.providers.values()
            if provider.source_kind is ResearchProviderSourceKind.FACILITY
        }
        for facility in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id)):
            provider = provider_by_facility_def.get(facility.definition_id)
            if provider is None:
                continue
            blockers = list(sim.facilities.activation_failures(facility, sim.day))
            snapshot = power_by_location[facility.operational_node_id]
            utilization = max(0.0, min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)))
            if not blockers and utilization <= 1e-12:
                blockers.append(("power", "研究設備への電力供給なし"))
            rows.append(ResearchProviderRow(
                str(facility.id), str(facility.definition_id), str(facility.operational_node_id),
                provider.tier, facility.level,
                sim.research.provider_generation(facility.id, power_by_location, sim.day),
                sim.research.provider_storage_capacity(facility.id, power_by_location, sim.day),
                tuple(blockers),
            ))
        return tuple(rows)

    @staticmethod
    def _site_row(site):
        if site is None:
            return None
        return ResearchExecutionSiteRow(
            str(site.operational_node_id),
            None if site.surface_cell_id is None else str(site.surface_cell_id),
        )

    def _research_view(self) -> ResearchView:
        sim = self._simulation
        if sim.research is None:
            return ResearchView(0.0, 0.0, 0.0, False, (), (), ())
        decision = self._tick_decision_projection()
        power_by_location = decision.allocations.power_by_location
        generation = sim.research.generation_rate(power_by_location, sim.day)
        capacity = sim.research.storage_capacity(power_by_location, sim.day)
        providers = self._research_provider_rows(power_by_location)
        execution_allocations = decision.allocations.execution
        point_requests, point_allocations = sim.research.point_allocation_projection(execution_allocations)
        knowledge = tuple(
            ResearchKnowledgeRow(category, value)
            for category, value in sorted(sim.research.knowledge_state.experience_by_category.items())
        )

        rows: list[ResearchRow] = []
        for definition in sorted(sim.research.definitions.values(), key=lambda row: str(row.id)):
            state = sim.research.active.get(definition.id)
            complete = definition.id in sim.research.completed
            start_blockers = sim.research.start_blockers(definition.id, day=sim.day, power_by_location=power_by_location)
            current_spec = None if state is None else sim.research.current_stage_spec(definition.id)
            if complete:
                status = "complete"
            elif state is None:
                status = "available" if definition.prerequisites.issubset(sim.research.completed) else "locked"
            else:
                status = current_spec.stage_type.value

            current_blockers = sim.research.current_blockers(definition.id, day=sim.day, power_by_location=power_by_location)
            current_blockers += sim.research.allocation_blockers(definition.id, execution_allocations)
            priority = 3 if state is None else state.priority
            stage_progress = 0.0
            stage_required = 0.0
            execution_requested = execution_allocated = 0.0
            prototype_resources: list[ResearchPrototypeResourceRow] = []
            experience_rows: list[ResearchExperienceRow] = []
            prototype_sites = demonstration_sites = ()
            prototype_blockers = demonstration_blockers = ()
            prototype_execution_site = demonstration_execution_site = None

            if state is not None and current_spec is not None:
                execution_requested, execution_allocated = sim.research.execution_allocation_totals(
                    definition.id, state.current_stage_id, execution_allocations
                )
                stage_progress = state.stage_progress or 0.0
                if isinstance(current_spec, ResearchTheoryStageSpec):
                    stage_required = current_spec.research_point_cost
                elif isinstance(current_spec, ResearchPrototypeStageSpec):
                    stage_required = current_spec.required_work
                    prototype_execution_site = self._site_row(state.execution_context)
                    prototype_sites = self._research_site_options(definition, current_spec, power_by_location=power_by_location)
                    prototype_blockers = sim.research.prototype_blockers(definition.id, sim.day, power_by_location=power_by_location)
                    location_id = None if state.execution_context is None else state.execution_context.operational_node_id
                    for resource_id, required in sorted(current_spec.resources.items(), key=lambda row: str(row[0])):
                        reserved = requested = allocated = pipeline = 0.0
                        if location_id is not None:
                            reserved = sim.research.prototype_reserved_t(definition.id, current_spec.stage_id, location_id, resource_id)
                            requested = max(0.0, required - reserved)
                            try:
                                allocated = execution_allocations.allocated(
                                    sim.research.prototype_reservation_requirement_id(definition.id, current_spec.stage_id, resource_id)
                                )
                            except KeyError:
                                allocated = 0.0
                            pipeline = sim.logistics.cargo_flow_pipeline_t(
                                sim.research.prototype_requirement_id(definition.id, current_spec.stage_id, resource_id)
                            )
                        prototype_resources.append(ResearchPrototypeResourceRow(
                            str(resource_id), required, reserved, requested, allocated, pipeline,
                            max(0.0, requested - allocated),
                        ))
                elif isinstance(current_spec, ResearchDemonstrationStageSpec):
                    stage_required = current_spec.required_work
                    demonstration_execution_site = self._site_row(state.execution_context)
                    demonstration_sites = self._research_site_options(definition, current_spec, power_by_location=power_by_location)
                    demonstration_blockers = sim.research.demonstration_blockers(definition.id, sim.day, power_by_location=power_by_location)
                elif isinstance(current_spec, ResearchOperationalExperienceStageSpec):
                    stage_required = sum(current_spec.requirements.values())
                    stage_progress = sum(min(sim.research.knowledge_state.value(category), required) for category, required in current_spec.requirements.items())
                    for category, required in sorted(current_spec.requirements.items()):
                        current = sim.research.knowledge_state.value(category)
                        experience_rows.append(ResearchExperienceRow(category, required, current, max(0.0, required - current)))

            total_theory_cost = sum(
                spec.research_point_cost for spec in definition.stage_specs
                if isinstance(spec, ResearchTheoryStageSpec)
            )
            rows.append(ResearchRow(
                id=str(definition.id), display_name=definition.display_name, status=status,
                stages=tuple(spec.stage_type.value for spec in definition.stage_specs),
                stage_ids=tuple(spec.stage_id for spec in definition.stage_specs),
                current_stage_id=None if state is None else state.current_stage_id,
                current_stage_type=None if current_spec is None else current_spec.stage_type.value,
                paused=False if state is None else state.paused, priority=priority,
                can_start=not start_blockers, can_pause=sim.research.can_pause(definition.id),
                can_resume=sim.research.can_resume(definition.id), can_set_priority=state is not None,
                research_point_cost=total_theory_cost, stage_progress=stage_progress,
                stage_required=stage_required, rp_requested=point_requests.get(definition.id, 0.0),
                rp_allocated=point_allocations.get(definition.id, 0.0),
                rp_remaining=sim.research.theory_remaining(definition.id),
                execution_requested=execution_requested, execution_allocated=execution_allocated,
                current_blockers=current_blockers, start_blockers=start_blockers,
                prototype_resources=tuple(prototype_resources), prototype_execution_site=prototype_execution_site,
                prototype_sites=prototype_sites, demonstration_execution_site=demonstration_execution_site,
                demonstration_sites=demonstration_sites, demonstration_blockers=demonstration_blockers,
                prototype_blockers=prototype_blockers, operational_experience=tuple(experience_rows),
                prerequisites=tuple(sorted(str(item) for item in definition.prerequisites)),
            ))
        return ResearchView(
            sim.research.stored_points, capacity, generation,
            sim.research.stored_points > capacity + 1e-9, providers, knowledge, tuple(rows),
        )
