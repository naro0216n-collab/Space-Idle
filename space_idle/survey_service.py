from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .exploration_models import KnowledgeLevel, SurveyTarget, SurveyProviderSpec, SurveyCampaign

@dataclass
class SurveyService:
    targets: dict[tuple[SpatialNodeId, DefinitionId], SurveyTarget]
    providers: dict[DefinitionId, SurveyProviderSpec]
    facilities: FacilityBook
    campaigns: dict[tuple[SpatialNodeId, DefinitionId], SurveyCampaign] = field(default_factory=dict)

    def start(self, location_id: SpatialNodeId, resource_id: DefinitionId, *, allocation_weight: float = 1.0) -> None:
        key = (location_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        if allocation_weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.campaigns.setdefault(key, SurveyCampaign(location_id, resource_id, 0.0, allocation_weight))

    def set_allocation_weight(self, location_id: SpatialNodeId, resource_id: DefinitionId, weight: float) -> None:
        if weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.campaigns[(location_id, resource_id)].allocation_weight = weight

    def pause(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> None:
        self.campaigns[(location_id, resource_id)].paused = True

    def resume(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> None:
        self.campaigns[(location_id, resource_id)].paused = False

    def knowledge_level(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> KnowledgeLevel:
        key = (location_id, resource_id)
        target = self.targets[key]
        progress = self.campaigns.get(key, SurveyCampaign(location_id, resource_id)).progress
        level = 0
        for index, threshold in enumerate(target.thresholds, start=1):
            if progress + 1e-9 >= threshold:
                level = index
        return level  # type: ignore[return-value]

    def is_complete(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> bool:
        return self.knowledge_level(location_id, resource_id) >= 4

    def visible_presence_probability(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        if self.knowledge_level(location_id, resource_id) < 1:
            return None
        return self.targets[(location_id, resource_id)].prior_presence_probability

    def visible_concentration(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        level = self.knowledge_level(location_id, resource_id)
        if level < 2:
            return None
        target = self.targets[(location_id, resource_id)]
        if level == 2:
            return round(target.actual_concentration, 2)
        return target.actual_concentration

    def visible_reserve(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float | None:
        if self.knowledge_level(location_id, resource_id) < 4:
            return None
        return self.targets[(location_id, resource_id)].reserve_t

    def capacity_at(
        self, location_id: SpatialNodeId, power: PowerSnapshot | None = None, day: int = 0
    ) -> float:
        points = 0.0
        for facility in self.facilities.active_compatible_at(location_id, day):
            provider = self.providers.get(facility.definition_id)
            if provider is None:
                continue
            utilization = 1.0 if power is None else power.utilization_by_facility.get(facility.id, 1.0)
            points += provider.points_per_day * utilization
        return points

    def advance_day(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0) -> None:
        # Survey capability at a site is a finite flow. Completed campaigns stop
        # consuming it automatically. If one campaign reaches its final threshold
        # part-way through a day, unused capacity is redistributed to the remaining
        # campaigns rather than being discarded.
        by_location: dict[SpatialNodeId, list[SurveyCampaign]] = {}
        for campaign in self.campaigns.values():
            if (
                not campaign.paused
                and campaign.allocation_weight > 0
                and not self.is_complete(campaign.location_id, campaign.resource_id)
            ):
                by_location.setdefault(campaign.location_id, []).append(campaign)
        for location_id, campaigns in by_location.items():
            remaining_points = self.capacity_at(location_id, power_by_location.get(location_id), day)
            active = list(campaigns)
            while active and remaining_points > 1e-12:
                weight_total = sum(c.allocation_weight for c in active)
                if weight_total <= 1e-12:
                    break
                proposed = {
                    id(c): remaining_points * c.allocation_weight / weight_total
                    for c in active
                }
                completed_this_round: list[SurveyCampaign] = []
                consumed = 0.0
                for campaign in active:
                    final_threshold = self.targets[(campaign.location_id, campaign.resource_id)].thresholds[-1]
                    need = max(0.0, final_threshold - campaign.progress)
                    gain = min(proposed[id(campaign)], need)
                    campaign.progress += gain
                    consumed += gain
                    if campaign.progress + 1e-9 >= final_threshold:
                        campaign.progress = max(campaign.progress, final_threshold)
                        completed_this_round.append(campaign)
                remaining_points = max(0.0, remaining_points - consumed)
                if not completed_this_round:
                    break
                active = [c for c in active if c not in completed_this_round]
