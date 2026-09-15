from __future__ import annotations

from .application_views import (
    ResearchExperienceRow,
    ResearchKnowledgeRow,
    ResearchPrototypeResourceRow,
    ResearchProviderRow,
    ResearchRow,
    ResearchView,
)
from .app_contracts.progression_views import ResearchSiteOptionRow
from .research_models import ResearchStage


class ResearchProgressionProjectorMixin:
    def _research_site_options(
        self,
        definition,
        *,
        demonstration: bool,
        power_by_location,
    ) -> tuple[ResearchSiteOptionRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchSiteOptionRow] = []
        for node in sim.graph.operational_nodes():
            blockers = (
                sim.research.demonstration_site_blockers(
                    definition.id,
                    node.id,
                    sim.day,
                    power_by_location.get(node.id),
                )
                if demonstration
                else sim.research.prototype_site_blockers(
                    definition.id,
                    node.id,
                    sim.day,
                    power_by_location.get(node.id),
                )
            )
            rows.append(ResearchSiteOptionRow(
                str(node.id),
                blockers,
                (
                    sim.research.can_select_demonstration_site(definition.id, node.id, sim.day)
                    if demonstration
                    else sim.research.can_select_prototype_site(definition.id, node.id, sim.day)
                ),
            ))
        return tuple(rows)

    def _research_provider_rows(self, power_by_location) -> tuple[ResearchProviderRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchProviderRow] = []
        for facility in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id)):
            provider = sim.research.providers.get(facility.definition_id)
            if provider is None:
                continue
            blockers = list(sim.facilities.activation_failures(facility, sim.day))
            snapshot = power_by_location[facility.operational_node_id]
            utilization = max(
                0.0,
                min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)),
            )
            if not blockers and utilization <= 1e-12:
                blockers.append(("power", "研究設備への電力供給なし"))
            rows.append(ResearchProviderRow(
                str(facility.id),
                str(facility.definition_id),
                str(facility.operational_node_id),
                provider.tier,
                facility.level,
                sim.research.provider_generation(facility.id, power_by_location, sim.day),
                sim.research.provider_storage_capacity(facility.id, power_by_location, sim.day),
                tuple(blockers),
            ))
        return tuple(rows)

    def _research_view(self) -> ResearchView:
        sim = self._simulation
        if sim.research is None:
            return ResearchView(0.0, 0.0, 0.0, False, (), (), ())
        decision = sim.tick_decision_projection()
        power_by_location = decision.allocations.power_by_location
        generation = sim.research.generation_rate(power_by_location, sim.day)
        capacity = sim.research.storage_capacity(power_by_location, sim.day)
        providers = self._research_provider_rows(power_by_location)
        execution_allocations = decision.allocations.execution
        point_requests, point_allocations = sim.research.point_allocation_projection(
            execution_allocations
        )
        knowledge = tuple(
            ResearchKnowledgeRow(category, value)
            for category, value in sorted(
                sim.research.knowledge_state.experience_by_category.items()
            )
        )

        rows: list[ResearchRow] = []
        for definition in sorted(sim.research.definitions.values(), key=lambda row: str(row.id)):
            state = sim.research.active.get(definition.id)
            complete = definition.id in sim.research.completed
            start_blockers = sim.research.start_blockers(
                definition.id,
                day=sim.day,
                power_by_location=power_by_location,
            )
            if complete:
                status = "complete"
            elif state is None:
                status = (
                    "available"
                    if definition.prerequisites.issubset(sim.research.completed)
                    else "locked"
                )
            else:
                status = state.stage.value

            current_blockers = sim.research.current_blockers(
                definition.id, day=sim.day, power_by_location=power_by_location
            )
            current_blockers = current_blockers + sim.research.allocation_blockers(
                definition.id, execution_allocations
            )
            priority = 3 if state is None else state.priority
            stage_progress = 0.0
            stage_required = 0.0
            execution_requested = 0.0
            execution_allocated = 0.0
            if state is not None:
                execution_requested, execution_allocated = (
                    sim.research.execution_allocation_totals(
                        definition.id, state.stage, execution_allocations
                    )
                )
                if state.stage is ResearchStage.THEORY:
                    stage_progress = state.stage_progress
                    stage_required = definition.research_point_cost
                elif state.stage is ResearchStage.PROTOTYPE:
                    stage_progress = state.stage_progress
                    stage_required = 1.0
                elif state.stage is ResearchStage.DEMONSTRATION:
                    stage_progress = state.stage_progress
                    stage_required = (
                        0.0 if definition.demonstration is None
                        else float(definition.demonstration.days)
                    )
                elif state.stage is ResearchStage.OPERATIONAL_EXPERIENCE:
                    spec = definition.operational_experience
                    if spec is not None:
                        stage_required = sum(spec.requirements.values())
                        stage_progress = sum(
                            min(sim.research.knowledge_state.value(category), required)
                            for category, required in spec.requirements.items()
                        )

            prototype_operational_node_id = (
                None
                if state is None or state.prototype_operational_node_id is None
                else str(state.prototype_operational_node_id)
            )
            demonstration_operational_node_id = (
                None
                if state is None or state.demonstration_operational_node_id is None
                else str(state.demonstration_operational_node_id)
            )
            prototype_sites = (
                self._research_site_options(
                    definition,
                    demonstration=False,
                    power_by_location=power_by_location,
                )
                if status == ResearchStage.PROTOTYPE.value else ()
            )
            demonstration_sites = (
                self._research_site_options(
                    definition,
                    demonstration=True,
                    power_by_location=power_by_location,
                )
                if status == ResearchStage.DEMONSTRATION.value else ()
            )
            prototype_blockers = (
                sim.research.prototype_blockers(
                    definition.id,
                    sim.day,
                    power_by_location=power_by_location,
                )
                if status == ResearchStage.PROTOTYPE.value else ()
            )
            demonstration_blockers = (
                sim.research.demonstration_blockers(
                    definition.id,
                    sim.day,
                    power_by_location=power_by_location,
                )
                if status == ResearchStage.DEMONSTRATION.value else ()
            )

            prototype_resources: list[ResearchPrototypeResourceRow] = []
            if definition.prototype is not None:
                location_id = None if state is None else state.prototype_operational_node_id
                for resource_id, required in sorted(
                    definition.prototype.resources.items(), key=lambda row: str(row[0])
                ):
                    reserved = 0.0
                    requested = 0.0
                    allocated = 0.0
                    pipeline = 0.0
                    if location_id is not None:
                        reserved = sim.research.prototype_reserved_t(
                            definition.id, location_id, resource_id
                        )
                        if state is not None and state.stage is ResearchStage.PROTOTYPE:
                            requested = max(0.0, required - reserved)
                            try:
                                allocated = execution_allocations.allocated(
                                    sim.research.prototype_reservation_requirement_id(
                                        definition.id, resource_id
                                    )
                                )
                            except KeyError:
                                allocated = 0.0
                            pipeline = sim.logistics.cargo_flow_pipeline_t(
                                sim.research.prototype_demand_id(definition.id, resource_id)
                            )
                    prototype_resources.append(ResearchPrototypeResourceRow(
                        str(resource_id),
                        required,
                        reserved,
                        requested,
                        allocated,
                        pipeline,
                        max(0.0, requested - allocated),
                    ))

            experience_rows: list[ResearchExperienceRow] = []
            if definition.operational_experience is not None:
                for category, required in sorted(
                    definition.operational_experience.requirements.items()
                ):
                    current = sim.research.knowledge_state.value(category)
                    experience_rows.append(ResearchExperienceRow(
                        category, required, current, max(0.0, required - current)
                    ))

            rows.append(ResearchRow(
                str(definition.id),
                definition.display_name,
                status,
                tuple(stage.value for stage in definition.stages),
                False if state is None else state.paused,
                priority,
                not start_blockers,
                sim.research.can_pause(definition.id),
                sim.research.can_resume(definition.id),
                state is not None,
                definition.research_point_cost,
                stage_progress,
                stage_required,
                point_requests.get(definition.id, 0.0),
                point_allocations.get(definition.id, 0.0),
                sim.research.theory_remaining(definition.id),
                execution_requested,
                execution_allocated,
                current_blockers,
                start_blockers,
                tuple(prototype_resources),
                prototype_operational_node_id,
                prototype_sites,
                demonstration_operational_node_id,
                demonstration_sites,
                demonstration_blockers,
                prototype_blockers,
                tuple(experience_rows),
                tuple(sorted(str(item) for item in definition.prerequisites)),
            ))
        return ResearchView(
            sim.research.stored_points,
            capacity,
            generation,
            sim.research.stored_points > capacity + 1e-9,
            providers,
            knowledge,
            tuple(rows),
        )
