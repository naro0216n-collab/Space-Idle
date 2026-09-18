from __future__ import annotations

from .application_views import (
    ResearchExperienceRow, ResearchKnowledgeRow, ResearchPrototypeResourceRow,
    ResearchProviderFleetRow, ResearchProviderRow, ResearchStageRow, ResearchRow, ResearchView,
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

    def _research_provider_fleet_rows(self) -> tuple[ResearchProviderFleetRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchProviderFleetRow] = []
        fleet_providers = tuple(
            provider for provider in sim.research.providers.values()
            if provider.source_kind is ResearchProviderSourceKind.FLEET
        )
        for provider in sorted(fleet_providers, key=lambda row: str(row.id)):
            for node in sorted(sim.graph.operational_nodes(), key=lambda row: str(row.id)):
                assignment = sim.research.provider_assignment_for(
                    provider.id, node.id, provider.source_definition_id
                )
                committed_units = (
                    0 if assignment is None
                    else sim.research.provider_assignment_quantity(assignment.id)
                )
                free_units = sim.transport.fleet_free_units(
                    provider.source_definition_id, node.id
                )
                failures = sim.research.provider_assignment_site_failures(
                    provider.id, node.id, day=sim.day
                )
                blocker_rows = [(failure.code, failure.detail) for failure in failures]
                if committed_units == 0 and free_units == 0:
                    blocker_rows.append((
                        "fleet_unavailable",
                        "No free compatible Fleet units are available at this operational node",
                    ))
                blockers = tuple(blocker_rows)
                max_units = committed_units if failures else committed_units + free_units
                rows.append(ResearchProviderFleetRow(
                    provider_definition_id=str(provider.id),
                    vehicle_definition_id=str(provider.source_definition_id),
                    operational_node_id=str(node.id),
                    tier=provider.tier,
                    assignment_id=None if assignment is None else str(assignment.id),
                    committed_units=committed_units,
                    free_units=free_units,
                    max_units=max_units,
                    blockers=blockers,
                    can_set_quantity=(committed_units > 0 or max_units > 0),
                ))
        return tuple(rows)

    def _research_provider_rows(self, power_by_location, execution_allocations) -> tuple[ResearchProviderRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchProviderRow] = []
        for facility in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id)):
            provider = sim.research.facility_provider_spec(facility.id)
            if provider is None:
                continue
            blockers = sim.research.facility_provider_blockers(
                facility.id, power_by_location, sim.day
            )
            requested = sim.research.provider_generation(facility.id, power_by_location, sim.day)
            try:
                admitted = execution_allocations.allocated(
                    sim.research._facility_generation_bundle_id(facility.id)
                )
            except KeyError:
                admitted = 0.0
            level_spec = provider.level_spec(facility.level)
            execution_supply = (
                level_spec.research_execution_per_day
                * sim.research._provider_factor(facility.id, power_by_location, sim.day)
            )
            rows.append(ResearchProviderRow(
                id=str(facility.id),
                provider_definition_id=str(provider.id),
                source_kind=provider.source_kind.value,
                source_definition_id=str(provider.source_definition_id),
                operational_node_id=str(facility.operational_node_id),
                tier=provider.tier,
                level=facility.level,
                committed_units=None,
                fleet_commitment_id=None,
                paused=False,
                priority=facility.activity_priority,
                generation_points_per_day=requested,
                admitted_generation_points_per_day=admitted,
                storage_capacity_points=sim.research.provider_storage_capacity(
                    facility.id, power_by_location, sim.day
                ),
                research_execution_per_day=execution_supply,
                blockers=tuple(blockers),
                can_pause=False,
                can_resume=False,
                facility_id=str(facility.id),
                facility_definition_id=str(facility.definition_id),
            ))

        for assignment_id, assignment in sorted(
            sim.research.provider_assignments.items(), key=lambda row: str(row[0])
        ):
            provider = sim.research.providers[assignment.provider_definition_id]
            quantity = sim.research.provider_assignment_quantity(assignment_id)
            requested, capacity = sim.research._fleet_assignment_rates(assignment_id, day=sim.day)
            try:
                admitted = execution_allocations.allocated(
                    sim.research._assignment_generation_bundle_id(assignment_id)
                )
            except KeyError:
                admitted = 0.0
            execution_supply = sim.research.provider_assignment_research_execution(
                assignment_id, day=sim.day
            )
            blockers = sim.research.provider_assignment_blockers(assignment_id, day=sim.day)
            rows.append(ResearchProviderRow(
                id=str(assignment_id),
                provider_definition_id=str(provider.id),
                source_kind=provider.source_kind.value,
                source_definition_id=str(assignment.vehicle_definition_id),
                operational_node_id=str(assignment.operational_node_id),
                tier=provider.tier,
                level=None,
                committed_units=quantity,
                fleet_commitment_id=str(assignment.fleet_commitment_ref),
                paused=assignment.paused,
                priority=assignment.priority,
                generation_points_per_day=requested,
                admitted_generation_points_per_day=admitted,
                storage_capacity_points=capacity,
                research_execution_per_day=execution_supply,
                blockers=blockers,
                can_pause=not assignment.paused,
                can_resume=assignment.paused,
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
            return ResearchView(0.0, 0.0, 0.0, 0.0, False, (), (), (), ())
        decision = self._tick_decision_projection()
        power_by_location = decision.allocations.power_by_location
        generation = sim.research.generation_rate(power_by_location, sim.day)
        capacity = sim.research.storage_capacity(power_by_location, sim.day)
        execution_allocations = decision.allocations.execution
        providers = self._research_provider_rows(power_by_location, execution_allocations)
        provider_fleet = self._research_provider_fleet_rows()
        admitted_generation = sum(row.admitted_generation_points_per_day for row in providers)
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
            stage_resources: list[ResearchPrototypeResourceRow] = []
            experience_rows: list[ResearchExperienceRow] = []
            execution_context_options = ()
            execution_context = None

            if state is not None and current_spec is not None:
                execution_requested, execution_allocated = sim.research.execution_allocation_totals(
                    definition.id, state.current_stage_id, execution_allocations
                )
                stage_progress = state.stage_progress or 0.0
                if isinstance(current_spec, ResearchTheoryStageSpec):
                    stage_required = current_spec.research_point_cost
                elif isinstance(current_spec, ResearchPrototypeStageSpec):
                    stage_required = current_spec.required_work
                    execution_context = self._site_row(state.execution_context)
                    execution_context_options = self._research_site_options(definition, current_spec, power_by_location=power_by_location)
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
                        stage_resources.append(ResearchPrototypeResourceRow(
                            str(resource_id), required, reserved, requested, allocated, pipeline,
                            max(0.0, requested - allocated),
                        ))
                elif isinstance(current_spec, ResearchDemonstrationStageSpec):
                    stage_required = current_spec.required_work
                    execution_context = self._site_row(state.execution_context)
                    execution_context_options = self._research_site_options(definition, current_spec, power_by_location=power_by_location)
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
                stages=tuple(ResearchStageRow(spec.stage_id, spec.stage_type.value) for spec in definition.stage_specs),
                current_stage_id=None if state is None else state.current_stage_id,
                current_stage_type=None if current_spec is None else current_spec.stage_type.value,
                paused=False if state is None else state.paused, priority=priority,
                can_start=not start_blockers, can_pause=sim.research.can_pause(definition.id),
                can_resume=sim.research.can_resume(definition.id), can_set_priority=state is not None,
                total_theory_research_point_cost=total_theory_cost, stage_progress=stage_progress,
                stage_required=stage_required, rp_requested=point_requests.get(definition.id, 0.0),
                rp_allocated=point_allocations.get(definition.id, 0.0),
                rp_remaining=sim.research.theory_remaining(definition.id),
                execution_requested=execution_requested, execution_allocated=execution_allocated,
                current_blockers=current_blockers, start_blockers=start_blockers,
                stage_resources=tuple(stage_resources), execution_context=execution_context,
                execution_context_options=execution_context_options,
                operational_experience=tuple(experience_rows),
                prerequisites=tuple(sorted(str(item) for item in definition.prerequisites)),
            ))
        return ResearchView(
            sim.research.stored_points, capacity, generation, admitted_generation,
            sim.research.stored_points > capacity + 1e-9, providers,
            provider_fleet, knowledge, tuple(rows),
        )
