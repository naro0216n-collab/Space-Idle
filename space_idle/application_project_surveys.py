from __future__ import annotations

from .application_views import SurveyRow, SurveysView
from .shared import SpatialNodeId


class SurveyProgressionProjectorMixin:
    def _surveys_view(self, provider_location_id: SpatialNodeId | None) -> SurveysView:
        sim = self._simulation
        if sim.survey is None:
            return SurveysView(())
        provider_body_id = (
            None
            if provider_location_id is None
            else sim.graph.operational_node(provider_location_id).body_id
        )
        rows = []
        for (cell_id, resource_id), target in sorted(
            sim.survey.targets.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1])),
        ):
            cell = sim.graph.surface_cells[cell_id]
            if provider_body_id is not None and cell.body_id != provider_body_id:
                continue
            campaign = sim.survey.campaigns.get((cell_id, resource_id))
            active_provider = None if campaign is None else campaign.provider_location_id
            capacity_provider = active_provider if active_provider is not None else provider_location_id
            power = None
            capacity = 0.0
            if capacity_provider is not None:
                power = sim.power.snapshot(capacity_provider, sim.facilities, sim.day)
                capacity = sim.survey.capacity_at(capacity_provider, power, sim.day)
            complete = sim.survey.is_complete(cell_id, resource_id)
            progress = sim.survey.progress(cell_id, resource_id)
            final_threshold = target.thresholds[-1]
            if campaign is not None:
                blockers = sim.survey.blockers(cell_id, resource_id, power, sim.day)
            elif provider_location_id is not None and not complete:
                blockers = sim.survey.start_blockers(provider_location_id, cell_id, resource_id)
            else:
                blockers = ()
            owner = sim.graph.owner_of_cell(cell_id)
            rows.append(
                SurveyRow(
                    str(cell_id),
                    str(cell.body_id),
                    f"{cell.centroid.latitude_deg:+.1f}°, {cell.centroid.longitude_deg:+.1f}°",
                    None if owner is None else str(owner),
                    str(resource_id),
                    self._resource_name(resource_id),
                    campaign is not None,
                    None if active_provider is None else str(active_provider),
                    complete,
                    False if campaign is None else campaign.paused,
                    provider_location_id is not None
                    and sim.survey.can_start(provider_location_id, cell_id, resource_id),
                    sim.survey.can_pause(cell_id, resource_id),
                    sim.survey.can_resume(cell_id, resource_id),
                    sim.survey.can_set_allocation(cell_id, resource_id),
                    progress,
                    1.0 if final_threshold <= 1e-12 else min(1.0, progress / final_threshold),
                    final_threshold,
                    sim.survey.DEFAULT_ALLOCATION_WEIGHT,
                    0.0 if campaign is None else campaign.allocation_weight,
                    sim.survey.knowledge_level(cell_id, resource_id),
                    sim.survey.visible_presence_probability(cell_id, resource_id),
                    sim.survey.visible_potential(cell_id, resource_id),
                    sim.survey.visible_potential_precision_fraction(cell_id, resource_id),
                    capacity,
                    blockers,
                )
            )
        return SurveysView(tuple(rows))
