from __future__ import annotations

from .application_views import SurveyRow, SurveysView
from .shared import SpatialNodeId


class SurveyProgressionProjectorMixin:
    def _surveys_view(self, location_id: SpatialNodeId | None) -> SurveysView:
        sim = self._simulation
        if sim.survey is None:
            return SurveysView(())
        rows = []
        for (loc, resource_id), _target in sorted(
            sim.survey.targets.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1])),
        ):
            if location_id is not None and loc != location_id:
                continue
            campaign = sim.survey.campaigns.get((loc, resource_id))
            power = sim.power.snapshot(loc, sim.facilities, sim.day)
            capacity = sim.survey.capacity_at(loc, power, sim.day)
            blockers: list[str] = []
            if campaign is not None:
                if campaign.paused:
                    blockers.append("manual_pause")
                if campaign.allocation_weight <= 1e-12:
                    blockers.append("allocation")
                if capacity <= 1e-12:
                    blockers.append("survey_capacity")
            visible_reserve = sim.survey.visible_reserve(loc, resource_id)
            if visible_reserve is not None and sim.extraction is not None:
                visible_reserve = sim.extraction.remaining_reserve_t.get(
                    (loc, resource_id),
                    visible_reserve,
                )
            rows.append(
                SurveyRow(
                    str(loc),
                    str(resource_id),
                    self._resource_name(resource_id),
                    campaign is not None,
                    sim.survey.is_complete(loc, resource_id),
                    False if campaign is None else campaign.paused,
                    0.0 if campaign is None else campaign.progress,
                    0.0 if campaign is None else campaign.allocation_weight,
                    sim.survey.knowledge_level(loc, resource_id),
                    sim.survey.visible_presence_probability(loc, resource_id),
                    sim.survey.visible_concentration(loc, resource_id),
                    visible_reserve,
                    capacity,
                    tuple(blockers),
                )
            )
        return SurveysView(tuple(rows))
