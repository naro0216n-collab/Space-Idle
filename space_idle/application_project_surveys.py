from __future__ import annotations

from .application_views import (
    SurveyCandidateRow,
    SurveyCampaignRow,
    SurveyCampaignTargetRow,
    SurveyProviderFleetRow,
    SurveyRow,
    SurveysView,
)
from .exploration_models import SurveyCampaignControlState, SurveyProviderSourceKind
from .shared import SpatialNodeId


class SurveyProgressionProjectorMixin:
    def _survey_provider_fleet_rows(
        self, provider_operational_node_id: SpatialNodeId | None
    ) -> tuple[SurveyProviderFleetRow, ...]:
        sim = self._simulation
        if sim.survey is None or provider_operational_node_id is None:
            return ()
        rows: list[SurveyProviderFleetRow] = []
        for provider in sorted(sim.survey.providers.values(), key=lambda row: str(row.id)):
            if provider.source_kind is not SurveyProviderSourceKind.FLEET:
                continue
            assignment = sim.survey.provider_assignment_for(
                provider.id, provider_operational_node_id, provider.source_definition_id
            )
            committed_units = (
                0 if assignment is None
                else sim.survey.provider_assignment_quantity(assignment.id)
            )
            free_units = sim.transport.fleet_free_units(
                provider.source_definition_id, provider_operational_node_id
            )
            max_units = committed_units + free_units
            blockers = ("fleet_unavailable",) if max_units == 0 else ()
            rows.append(SurveyProviderFleetRow(
                provider_definition_id=str(provider.id),
                vehicle_definition_id=str(provider.source_definition_id),
                operational_node_id=str(provider_operational_node_id),
                committed_units=committed_units,
                free_units=free_units,
                max_units=max_units,
                capacity_units_per_day=(
                    committed_units * provider.capacity_units_per_source_per_day
                ),
                blockers=blockers,
                can_set_quantity=(committed_units > 0 or max_units > 0),
            ))
        return tuple(rows)

    def _survey_campaign_row(self, campaign, execution_plan, service_plan, powers) -> SurveyCampaignRow:
        sim = self._simulation
        assert sim.survey is not None
        projection = sim.survey.campaign_projection(campaign, day=sim.day)
        candidate = projection.resolved_candidate
        resolution_blockers = projection.resolution_blockers
        candidates = tuple(
            SurveyCandidateRow(
                provider_operational_node_id=str(row.provider_operational_node_id),
                provider_definition_id=str(row.provider_definition_id),
                provider_source_kind=row.source_kind.value,
                source_definition_id=str(row.source_definition_id),
                observation_mode_id=row.observation_mode_id,
                survey_rate=row.survey_rate,
                max_knowledge_level=int(row.max_knowledge_level),
                estimate_uncertainty_fraction=row.estimate_uncertainty_fraction,
                measurement_precision_fraction=row.measurement_precision_fraction,
                minimum_source_units=row.minimum_source_units,
                assigned_source_units=row.assigned_source_units,
                capacity_units_per_day=service_plan.summary(
                    row.provider_operational_node_id,
                    sim.survey.service_type_for_provider(row.provider_definition_id),
                ).enabled_rate,
                matches_constraints=sim.survey.candidate_matches_constraints(campaign, row),
                viable=row.viable,
                blockers=row.blockers,
            )
            for row in projection.candidates
        )
        target_rows: list[SurveyCampaignTargetRow] = []
        remaining_progress = 0.0
        for cell_id, resource_id in campaign.target_pairs():
            target = sim.survey.targets[(cell_id, resource_id)]
            threshold = target.thresholds[int(campaign.goal_knowledge_level) - 1]
            progress = sim.survey.progress(cell_id, resource_id)
            complete = sim.survey.knowledge_level(cell_id, resource_id) >= campaign.goal_knowledge_level
            if not complete:
                remaining_progress += max(0.0, threshold - progress)
            target_rows.append(SurveyCampaignTargetRow(
                cell_id=str(cell_id),
                resource_id=str(resource_id),
                current_knowledge_level=int(sim.survey.knowledge_level(cell_id, resource_id)),
                goal_knowledge_level=int(campaign.goal_knowledge_level),
                progress=progress,
                target_threshold=threshold,
                complete=complete,
            ))
        requested = 0.0
        allocated = 0.0
        for bundle in execution_plan.bundles:
            if bundle.owner_kind != "survey" or bundle.owner_id != campaign.id:
                continue
            requested += bundle.requested_execution
            allocated += execution_plan.allocated(bundle.id)
        capacity_points = 0.0
        required_fleet = None
        assigned_fleet = None
        projected_days = None
        if candidate is not None:
            mode = sim.survey.observation_mode(
                candidate.provider_definition_id, candidate.observation_mode_id
            )
            capacity_points = service_plan.summary(
                candidate.provider_operational_node_id,
                sim.survey.service_type_for_provider(candidate.provider_definition_id),
            ).enabled_rate * mode.survey_rate
            if candidate.source_kind is SurveyProviderSourceKind.FLEET:
                required_fleet = candidate.minimum_source_units
                assigned_fleet = candidate.assigned_source_units
            actual_progress_rate = allocated * mode.survey_rate
            if actual_progress_rate > 1e-12:
                projected_days = remaining_progress / actual_progress_rate
        blockers = sim.survey.campaign_blockers(
            campaign.id, day=sim.day, execution_allocations=execution_plan
        )
        if not blockers and resolution_blockers:
            blockers = resolution_blockers
        covered = len(target_rows) - len(projection.unfinished_targets)
        constraint = campaign.provider_constraint
        return SurveyCampaignRow(
            id=str(campaign.id),
            status=campaign.control_state.value,
            paused=campaign.control_state is SurveyCampaignControlState.PAUSED,
            priority=campaign.priority,
            target_cell_ids=tuple(map(str, campaign.target_cell_ids)),
            resource_ids=tuple(map(str, campaign.resource_ids)),
            goal_knowledge_level=int(campaign.goal_knowledge_level),
            provider_constraint_definition_id=(
                None if constraint is None else str(constraint.provider_definition_id)
            ),
            provider_constraint_operational_node_id=(
                None if constraint is None else str(constraint.operational_node_id)
            ),
            observation_mode_constraint=campaign.observation_mode_constraint,
            projected_provider_definition_id=(
                None if candidate is None else str(candidate.provider_definition_id)
            ),
            projected_provider_operational_node_id=(
                None if candidate is None else str(candidate.provider_operational_node_id)
            ),
            projected_observation_mode_id=(
                None if candidate is None else candidate.observation_mode_id
            ),
            covered_targets=covered,
            remaining_targets=len(target_rows) - covered,
            requested_service_units_per_day=requested,
            allocated_service_units_per_day=allocated,
            capacity_points_per_day=capacity_points,
            projected_remaining_days=projected_days,
            required_fleet_units=required_fleet,
            assigned_fleet_units=assigned_fleet,
            blockers=blockers,
            can_pause=sim.survey.can_pause(campaign.id),
            can_resume=sim.survey.can_resume(campaign.id),
            can_set_priority=sim.survey.can_set_priority(campaign.id),
            targets=tuple(target_rows),
            candidates=candidates,
        )

    def _surveys_view(self, provider_operational_node_id: SpatialNodeId | None) -> SurveysView:
        sim = self._simulation
        if sim.survey is None:
            return SurveysView((), (), ())
        provider_fleet = self._survey_provider_fleet_rows(provider_operational_node_id)
        decision = self._tick_decision_projection()
        execution_plan = decision.allocations.execution
        service_plan = decision.allocations.services
        powers = decision.allocations.power_by_location
        knowledge_rows: list[SurveyRow] = []
        for (cell_id, resource_id), _target in sorted(
            sim.survey.targets.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            cell = sim.graph.surface_cells[cell_id]
            owner = sim.graph.owner_of_cell(cell_id)
            knowledge_rows.append(SurveyRow(
                cell_id=str(cell_id),
                body_id=str(cell.body_id),
                cell_label=f"{cell.centroid.latitude_deg:+.1f}°, {cell.centroid.longitude_deg:+.1f}°",
                location_id=None if owner is None else str(owner),
                resource_id=str(resource_id),
                resource_name=self._resource_name(resource_id),
                progress=sim.survey.progress(cell_id, resource_id),
                knowledge_level=int(sim.survey.knowledge_level(cell_id, resource_id)),
                presence_probability=sim.survey.visible_presence_probability(cell_id, resource_id),
                visible_potential=sim.survey.visible_potential(cell_id, resource_id),
                visible_potential_precision_fraction=sim.survey.visible_potential_precision_fraction(cell_id, resource_id),
            ))
        campaign_rows = tuple(
            self._survey_campaign_row(campaign, execution_plan, service_plan, powers)
            for campaign in sorted(sim.survey.campaigns.values(), key=lambda row: str(row.id))
        )
        return SurveysView(provider_fleet, tuple(knowledge_rows), campaign_rows)
