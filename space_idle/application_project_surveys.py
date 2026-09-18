from __future__ import annotations

from .application_views import SurveyRow, SurveyStartOption, SurveysView
from .exploration_models import KnowledgeLevel, SurveyProviderSourceKind
from .shared import SpatialNodeId


class SurveyProgressionProjectorMixin:
    def _survey_start_options(self, provider_operational_node_id, cell_id, resource_id, powers):
        sim = self._simulation
        if provider_operational_node_id is None or sim.survey is None:
            return ()
        current = sim.survey.knowledge_level(cell_id, resource_id)
        power = powers[provider_operational_node_id]
        rows = []
        for provider in sorted(sim.survey.providers.values(), key=lambda row: str(row.id)):
            for mode in sorted(provider.observation_modes, key=lambda row: row.id):
                for level_value in range(int(current) + 1, int(mode.max_knowledge_level) + 1):
                    level = KnowledgeLevel(level_value)
                    blockers = sim.survey.start_blockers(
                        provider_operational_node_id, provider.id, mode.id, cell_id, resource_id, level, sim.day
                    )
                    if provider.source_kind is SurveyProviderSourceKind.FACILITY:
                        capacity = sim.survey.provider_capacity_at(
                            provider.id, provider_operational_node_id, power, sim.day
                        ) * mode.survey_rate
                    else:
                        capacity = (
                            provider.capacity_units_per_source_per_day
                            * mode.required_fleet_units
                            * mode.survey_rate
                        )
                    rows.append(SurveyStartOption(
                        provider_operational_node_id=str(provider_operational_node_id),
                        provider_definition_id=str(provider.id),
                        provider_source_kind=provider.source_kind.value,
                        observation_mode_id=mode.id,
                        target_knowledge_level=int(level),
                        max_knowledge_level=int(mode.max_knowledge_level),
                        survey_rate=mode.survey_rate,
                        capacity_points_per_day=capacity,
                        estimate_uncertainty_fraction=mode.estimate_uncertainty_fraction,
                        measurement_precision_fraction=mode.measurement_precision_fraction,
                        required_fleet_units=mode.required_fleet_units,
                        blockers=blockers,
                        can_start=not blockers,
                    ))
        return tuple(rows)

    def _surveys_view(self, provider_operational_node_id: SpatialNodeId | None) -> SurveysView:
        sim = self._simulation
        if sim.survey is None:
            return SurveysView(())
        provider_body_id = (
            None if provider_operational_node_id is None
            else sim.graph.operational_node(provider_operational_node_id).body_id
        )
        decision = self._tick_decision_projection()
        execution_plan = decision.allocations.execution
        powers = decision.allocations.power_by_location
        rows = []
        for (cell_id, resource_id), target in sorted(
            sim.survey.targets.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            cell = sim.graph.surface_cells[cell_id]
            if provider_body_id is not None and cell.body_id != provider_body_id:
                continue
            campaign = sim.survey.campaigns.get((cell_id, resource_id))
            active_provider_node = None if campaign is None else campaign.provider_operational_node_id
            complete = sim.survey.is_complete(cell_id, resource_id)
            progress = sim.survey.progress(cell_id, resource_id)
            if campaign is None:
                target_level = sim.survey.knowledge_level(cell_id, resource_id)
                progress_threshold = (
                    target.thresholds[-1]
                    if complete
                    else target.thresholds[0]
                    if target_level is KnowledgeLevel.UNKNOWN
                    else target.thresholds[int(target_level) - 1]
                )
                requested_service = 0.0
                allocated_service = 0.0
                blockers = ()
                capacity = 0.0
                provider_definition_id = None
                provider_source_kind = None
                observation_mode_id = None
                fleet_commitment_id = None
            else:
                target_level = campaign.target_knowledge_level
                progress_threshold = target.thresholds[int(target_level) - 1]
                power = powers[campaign.provider_operational_node_id]
                capacity = sim.survey.capacity_for_campaign(campaign, power, sim.day)
                bundle_id = sim.survey.execution_bundle_id(cell_id, resource_id)
                try:
                    bundle = execution_plan.bundle(bundle_id)
                    requested_service = bundle.requested_execution
                    allocated_service = execution_plan.allocated(bundle_id)
                except KeyError:
                    requested_service = 0.0
                    allocated_service = 0.0
                blockers = sim.survey.blockers(cell_id, resource_id, power, sim.day, execution_plan)
                provider = sim.survey.provider(campaign.provider_definition_id)
                provider_definition_id = str(provider.id)
                provider_source_kind = provider.source_kind.value
                observation_mode_id = campaign.observation_mode_id
                fleet_commitment_id = None if campaign.fleet_commitment_ref is None else str(campaign.fleet_commitment_ref)
            start_options = self._survey_start_options(
                provider_operational_node_id, cell_id, resource_id, powers
            ) if campaign is None and not complete else ()
            owner = sim.graph.owner_of_cell(cell_id)
            rows.append(SurveyRow(
                cell_id=str(cell_id), body_id=str(cell.body_id),
                cell_label=f"{cell.centroid.latitude_deg:+.1f}°, {cell.centroid.longitude_deg:+.1f}°",
                location_id=None if owner is None else str(owner),
                resource_id=str(resource_id), resource_name=self._resource_name(resource_id),
                active=campaign is not None,
                provider_operational_node_id=None if active_provider_node is None else str(active_provider_node),
                provider_definition_id=provider_definition_id, provider_source_kind=provider_source_kind,
                observation_mode_id=observation_mode_id, fleet_commitment_id=fleet_commitment_id,
                complete=complete, paused=False if campaign is None else campaign.paused,
                can_start=any(option.can_start for option in start_options),
                can_pause=sim.survey.can_pause(cell_id, resource_id),
                can_resume=sim.survey.can_resume(cell_id, resource_id),
                can_set_priority=sim.survey.can_set_priority(cell_id, resource_id),
                progress=progress, progress_fraction=(1.0 if progress_threshold <= 1e-12 else min(1.0, progress / progress_threshold)),
                target_knowledge_level=int(target_level), target_threshold=progress_threshold,
                priority=sim.survey.DEFAULT_PRIORITY if campaign is None else campaign.priority,
                requested_service_points_per_day=requested_service, allocated_service_points_per_day=allocated_service,
                knowledge_level=int(sim.survey.knowledge_level(cell_id, resource_id)),
                presence_probability=sim.survey.visible_presence_probability(cell_id, resource_id),
                visible_potential=sim.survey.visible_potential(cell_id, resource_id),
                visible_potential_precision_fraction=sim.survey.visible_potential_precision_fraction(cell_id, resource_id),
                capacity_points_per_day=capacity, blockers=blockers, start_options=start_options,
            ))
        return SurveysView(tuple(rows))
