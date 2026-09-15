from __future__ import annotations

from .application_views import SurveyRow, SurveysView
from .shared import SpatialNodeId


class SurveyProgressionProjectorMixin:
    def _surveys_view(self, provider_operational_node_id: SpatialNodeId | None) -> SurveysView:
        sim = self._simulation
        if sim.survey is None:
            return SurveysView(())
        provider_body_id = (
            None
            if provider_operational_node_id is None
            else sim.graph.operational_node(provider_operational_node_id).body_id
        )
        decision = sim.tick_decision_projection()
        execution_plan = decision.allocations.execution
        powers = decision.allocations.power_by_location
        rows = []
        for (cell_id, resource_id), target in sorted(
            sim.survey.targets.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1])),
        ):
            cell = sim.graph.surface_cells[cell_id]
            if provider_body_id is not None and cell.body_id != provider_body_id:
                continue
            campaign = sim.survey.campaigns.get((cell_id, resource_id))
            active_provider = None if campaign is None else campaign.provider_operational_node_id
            capacity_provider = active_provider if active_provider is not None else provider_operational_node_id
            power = None
            capacity = 0.0
            if capacity_provider is not None:
                power = powers[capacity_provider]
                capacity = sim.survey.capacity_for_target(
                    capacity_provider, cell_id, resource_id, power, sim.day
                )
            complete = sim.survey.is_complete(cell_id, resource_id)
            progress = sim.survey.progress(cell_id, resource_id)
            reachable_level = (
                campaign.target_knowledge_level
                if campaign is not None
                else (
                    0
                    if provider_operational_node_id is None
                    else sim.survey.reachable_knowledge_level(
                        provider_operational_node_id, cell_id, day=sim.day
                    )
                )
            )
            progress_threshold = (
                target.thresholds[-1]
                if reachable_level <= 0
                else target.thresholds[reachable_level - 1]
            )
            requested_service = 0.0
            allocated_service = 0.0
            if campaign is not None:
                bundle_id = sim.survey.execution_bundle_id(cell_id, resource_id)
                try:
                    bundle = execution_plan.bundle(bundle_id)
                    requested_service = bundle.requested_execution
                    allocated_service = execution_plan.allocated(bundle_id)
                except KeyError:
                    pass
                blockers = sim.survey.blockers(
                    cell_id, resource_id, power, sim.day, execution_plan
                )
            elif provider_operational_node_id is not None and not complete:
                blockers = sim.survey.start_blockers(
                    provider_operational_node_id, cell_id, resource_id, sim.day
                )
            else:
                blockers = ()
            owner = sim.graph.owner_of_cell(cell_id)
            rows.append(
                SurveyRow(
                    cell_id=str(cell_id),
                    body_id=str(cell.body_id),
                    cell_label=f"{cell.centroid.latitude_deg:+.1f}°, {cell.centroid.longitude_deg:+.1f}°",
                    location_id=None if owner is None else str(owner),
                    resource_id=str(resource_id),
                    resource_name=self._resource_name(resource_id),
                    active=campaign is not None,
                    provider_operational_node_id=None if active_provider is None else str(active_provider),
                    complete=complete,
                    paused=False if campaign is None else campaign.paused,
                    can_start=provider_operational_node_id is not None
                    and sim.survey.can_start(
                        provider_operational_node_id, cell_id, resource_id, sim.day
                    ),
                    can_pause=sim.survey.can_pause(cell_id, resource_id),
                    can_resume=sim.survey.can_resume(cell_id, resource_id),
                    can_set_priority=sim.survey.can_set_priority(cell_id, resource_id),
                    progress=progress,
                    progress_fraction=(
                        1.0
                        if progress_threshold <= 1e-12
                        else min(1.0, progress / progress_threshold)
                    ),
                    target_knowledge_level=reachable_level,
                    target_threshold=progress_threshold,
                    priority=sim.survey.DEFAULT_PRIORITY if campaign is None else campaign.priority,
                    requested_service_points_per_day=requested_service,
                    allocated_service_points_per_day=allocated_service,
                    knowledge_level=sim.survey.knowledge_level(cell_id, resource_id),
                    presence_probability=sim.survey.visible_presence_probability(cell_id, resource_id),
                    visible_potential=sim.survey.visible_potential(cell_id, resource_id),
                    visible_potential_precision_fraction=sim.survey.visible_potential_precision_fraction(
                        cell_id, resource_id
                    ),
                    capacity_points_per_day=capacity,
                    blockers=blockers,
                )
            )
        return SurveysView(tuple(rows))
