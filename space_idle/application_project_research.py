from __future__ import annotations

from .application_constraints import constraints_from_pairs
from .application_comparison import project_comparison_axes
from .app_contracts.ui_reports import ComparisonValueRow
from .execution_requirements import ServiceCapacityRequirement
from .service_capacity import ServiceCapacityScope
from .application_views import (
    ResearchExperienceRow, ResearchKnowledgeRow, ResearchPrototypeResourceRow,
    ResearchProviderFleetRow, ResearchProviderRow, ResearchStageRow, ResearchUnlockRow,
    ResearchRow, ResearchView,
)
from .app_contracts.progression_views import ResearchExecutionSiteRow, ResearchSiteOptionRow
from .research_models import (
    ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
    ResearchProviderSourceKind,
)
from .site import requires_surface_cell_context


class ResearchProgressionProjectorMixin:
    def _research_unlock_rows_by_id(self) -> dict[object, tuple[ResearchUnlockRow, ...]]:
        """Reverse player-facing Research prerequisites once per Research projection."""
        sim = self._simulation
        if sim.research is None:
            return {}
        completed = set(sim.research.completed)
        rows_by_id: dict[object, list[ResearchUnlockRow]] = {
            research_id: [] for research_id in sim.research.definitions
        }

        def append(kind: str, row_id: str, display_name: str, prerequisites) -> None:
            prerequisite_set = set(prerequisites)
            for research_id in prerequisite_set:
                if research_id not in rows_by_id:
                    continue
                remaining = tuple(sorted(
                    str(item)
                    for item in (prerequisite_set - completed - {research_id})
                ))
                rows_by_id[research_id].append(
                    ResearchUnlockRow(kind, row_id, display_name, remaining)
                )

        for definition in sim.research.definitions.values():
            append(
                "research", str(definition.id), definition.display_name,
                definition.prerequisites,
            )
        for recipe in sim.projects.recipes.values():
            definition = sim.facilities.definitions[recipe.facility_def_id]
            append(
                "facility", str(recipe.facility_def_id), definition.display_name,
                recipe.prerequisite_technologies,
            )
        for (facility_id, target_level), recipe in sim.projects.upgrade_recipes.items():
            definition = sim.facilities.definitions[facility_id]
            append(
                "facility_upgrade", f"{facility_id}:level:{target_level}",
                f"{definition.display_name} Lv {target_level} 更新",
                recipe.prerequisite_technologies,
            )
        for facility_id, recipe in sim.projects.decommission_recipes.items():
            definition = sim.facilities.definitions[facility_id]
            append(
                "facility_decommission", f"{facility_id}:decommission",
                f"{definition.display_name} 撤去",
                recipe.prerequisite_technologies,
            )
        for recipe_id, recipe in sim.projects.spatial_recipes.items():
            append(
                "surface_development", str(recipe_id), recipe.display_name,
                recipe.prerequisite_technologies,
            )

        kind_order = {
            "research": 0,
            "facility": 1,
            "facility_upgrade": 2,
            "surface_development": 3,
            "facility_decommission": 4,
        }
        return {
            research_id: tuple(sorted(
                rows,
                key=lambda row: (
                    bool(row.remaining_prerequisite_ids),
                    kind_order.get(row.kind, 99),
                    row.display_name,
                    row.id,
                ),
            ))
            for research_id, rows in rows_by_id.items()
        }

    def _research_site_options(self, definition, spec, *, remaining_work, power_by_location, service_plan) -> tuple[ResearchSiteOptionRow, ...]:
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
                resource_required = sum(spec.resources.values()) if isinstance(spec, ResearchPrototypeStageSpec) else 0.0
                resource_available = (
                    sum(sim.inventory.available(node.id, resource_id) for resource_id in spec.resources)
                    if isinstance(spec, ResearchPrototypeStageSpec) else 0.0
                )
                service_requirements = tuple(
                    requirement for requirement in spec.execution_requirements
                    if isinstance(requirement, ServiceCapacityRequirement)
                    and requirement.amount_per_execution > 1e-12
                )
                service_work_capacity = 1.0
                if service_requirements:
                    service_work_capacity = min(
                        (
                            sum(
                                max(0.0, service_plan.summary(supply_node_id, requirement.service_type).spare_rate)
                                for supply_node_id, service_type in service_plan.supply_enabled
                                if service_type == requirement.service_type
                            )
                            if requirement.scope is ServiceCapacityScope.ORGANIZATION
                            else max(
                                0.0,
                                service_plan.summary(
                                    requirement.constraint_node(node.id), requirement.service_type
                                ).spare_rate,
                            )
                        ) / requirement.amount_per_execution
                        for requirement in service_requirements
                    )
                    service_work_capacity = min(1.0, service_work_capacity)
                committed_fleet = sum(
                    sim.research.provider_assignment_quantity(assignment.id)
                    for assignment in sim.research.provider_assignments.values()
                    if assignment.operational_node_id == node.id
                )
                estimated_days = None if service_work_capacity <= 1e-12 else float(remaining_work) / service_work_capacity
                comparison_values = (
                    ComparisonValueRow("location", text_value=str(node.display_name)),
                    ComparisonValueRow("fleet_commitment", number_value=float(committed_fleet)),
                    ComparisonValueRow("resource_required_t", number_value=float(resource_required)),
                    ComparisonValueRow("resource_available_t", number_value=float(resource_available)),
                    ComparisonValueRow("service_work_capacity", number_value=float(service_work_capacity)),
                    ComparisonValueRow("estimated_days", number_value=None if estimated_days is None else float(estimated_days)),
                )
                rows.append(ResearchSiteOptionRow(
                    str(node.id), None if surface_cell_id is None else str(surface_cell_id),
                    constraints_from_pairs(
                        blockers,
                        affected_action="select_research_execution_site",
                        related_entity_kind="research",
                        related_entity_id=str(definition.id),
                    ),
                    can_select,
                    comparison_key=f"{node.id}|{surface_cell_id or ''}",
                    comparison_values=comparison_values,
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
                    blockers=constraints_from_pairs(
                        blockers,
                        affected_action="set_research_provider_fleet",
                        related_entity_kind="research_provider",
                        related_entity_id=str(provider.id),
                    ),
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
                blockers=constraints_from_pairs(
                    blockers,
                    affected_action="operate_research_provider",
                    related_entity_kind="facility",
                    related_entity_id=str(facility.id),
                ),
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
                blockers=constraints_from_pairs(
                    blockers,
                    affected_action="operate_research_provider",
                    related_entity_kind="research_provider_assignment",
                    related_entity_id=str(assignment_id),
                ),
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
        service_plan = decision.allocations.services
        providers = self._research_provider_rows(power_by_location, execution_allocations)
        provider_fleet = self._research_provider_fleet_rows()
        admitted_generation = sum(row.admitted_generation_points_per_day for row in providers)
        point_requests, point_allocations = sim.research.point_allocation_projection(execution_allocations)
        knowledge = tuple(
            ResearchKnowledgeRow(category, value)
            for category, value in sorted(sim.research.knowledge_state.experience_by_category.items())
        )

        rows: list[ResearchRow] = []
        unlocks_by_id = self._research_unlock_rows_by_id()
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
            execution_context_comparison_axes = ()
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
                    execution_context_options = self._research_site_options(
                        definition, current_spec, remaining_work=max(0.0, current_spec.required_work - stage_progress),
                        power_by_location=power_by_location, service_plan=service_plan,
                    )
                    execution_context_comparison_axes = project_comparison_axes((
                        ("location", "Location", "text", None),
                        ("fleet_commitment", "研究Fleet拘束", "integer", "機"),
                        ("resource_required_t", "必要Resource", "number", "t"),
                        ("resource_available_t", "現地利用可能Resource", "number", "t"),
                        ("service_work_capacity", "Service供給による実行能力", "number", "work/日"),
                        ("estimated_days", "推定所要時間", "number", "日"),
                    ), (option.comparison_values for option in execution_context_options))
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
                    execution_context_options = self._research_site_options(
                        definition, current_spec, remaining_work=max(0.0, current_spec.required_work - stage_progress),
                        power_by_location=power_by_location, service_plan=service_plan,
                    )
                    execution_context_comparison_axes = project_comparison_axes((
                        ("location", "Location", "text", None),
                        ("fleet_commitment", "研究Fleet拘束", "integer", "機"),
                        ("resource_required_t", "必要Resource", "number", "t"),
                        ("resource_available_t", "現地利用可能Resource", "number", "t"),
                        ("service_work_capacity", "Service供給による実行能力", "number", "work/日"),
                        ("estimated_days", "推定所要時間", "number", "日"),
                    ), (option.comparison_values for option in execution_context_options))
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
                current_blockers=constraints_from_pairs(
                    current_blockers,
                    affected_action="progress_research",
                    related_entity_kind="research",
                    related_entity_id=str(definition.id),
                ),
                start_blockers=constraints_from_pairs(
                    start_blockers,
                    affected_action="start_research",
                    related_entity_kind="research",
                    related_entity_id=str(definition.id),
                ),
                stage_resources=tuple(stage_resources), execution_context=execution_context,
                execution_context_options=execution_context_options,
                execution_context_comparison_axes=execution_context_comparison_axes,
                operational_experience=tuple(experience_rows),
                prerequisites=tuple(sorted(str(item) for item in definition.prerequisites)),
                progression_stage=definition.progression_stage,
                category=definition.category,
                series=definition.series,
                unlocks=unlocks_by_id.get(definition.id, ()),
            ))
        return ResearchView(
            sim.research.stored_points, capacity, generation, admitted_generation,
            sim.research.stored_points > capacity + 1e-9, providers,
            provider_fleet, knowledge, tuple(rows),
        )
