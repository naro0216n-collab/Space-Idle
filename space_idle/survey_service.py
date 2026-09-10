from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .exploration_models import KnowledgeLevel, SurveyTarget, SurveyProviderSpec, SurveyCampaign

@dataclass
class SurveyService:
    DEFAULT_ALLOCATION_WEIGHT = 1.0

    targets: dict[tuple[SpatialNodeId, DefinitionId], SurveyTarget]
    providers: dict[DefinitionId, SurveyProviderSpec]
    facilities: FacilityBook
    knowledge_progress: dict[tuple[SpatialNodeId, DefinitionId], float] = field(default_factory=dict)
    campaigns: dict[tuple[SpatialNodeId, DefinitionId], SurveyCampaign] = field(default_factory=dict)

    def start_blockers(
        self, location_id: SpatialNodeId, resource_id: DefinitionId
    ) -> tuple[str, ...]:
        key = (location_id, resource_id)
        if key not in self.targets:
            return ("unknown_target",)
        if self.is_complete(location_id, resource_id):
            return ("survey_complete",)
        if key in self.campaigns:
            return ("already_active",)
        return ()

    def can_start(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> bool:
        return not self.start_blockers(location_id, resource_id)

    def pause_blockers(
        self, location_id: SpatialNodeId, resource_id: DefinitionId
    ) -> tuple[str, ...]:
        key = (location_id, resource_id)
        campaign = self.campaigns.get(key)
        if campaign is None or self.is_complete(location_id, resource_id):
            return ("not_active",)
        if campaign.paused:
            return ("already_paused",)
        return ()

    def can_pause(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> bool:
        return not self.pause_blockers(location_id, resource_id)

    def resume_blockers(
        self, location_id: SpatialNodeId, resource_id: DefinitionId
    ) -> tuple[str, ...]:
        key = (location_id, resource_id)
        campaign = self.campaigns.get(key)
        if campaign is None or self.is_complete(location_id, resource_id):
            return ("not_active",)
        if not campaign.paused:
            return ("not_paused",)
        return ()

    def can_resume(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> bool:
        return not self.resume_blockers(location_id, resource_id)

    def allocation_blockers(
        self, location_id: SpatialNodeId, resource_id: DefinitionId
    ) -> tuple[str, ...]:
        key = (location_id, resource_id)
        if key not in self.campaigns or self.is_complete(location_id, resource_id):
            return ("not_active",)
        return ()

    def can_set_allocation(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> bool:
        return not self.allocation_blockers(location_id, resource_id)

    def blockers(
        self,
        location_id: SpatialNodeId,
        resource_id: DefinitionId,
        power: PowerSnapshot | None = None,
        day: int = 0,
    ) -> tuple[str, ...]:
        key = (location_id, resource_id)
        campaign = self.campaigns.get(key)
        if campaign is None or self.is_complete(location_id, resource_id):
            return ()
        blockers: list[str] = []
        if campaign.paused:
            blockers.append("manual_pause")
        if campaign.allocation_weight <= 1e-12:
            blockers.append("allocation")
        if self.capacity_at(location_id, power, day) <= 1e-12:
            blockers.append("survey_capacity")
        return tuple(blockers)

    def start(
        self,
        location_id: SpatialNodeId,
        resource_id: DefinitionId,
        *,
        allocation_weight: float = DEFAULT_ALLOCATION_WEIGHT,
    ) -> None:
        key = (location_id, resource_id)
        blockers = self.start_blockers(location_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        if allocation_weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.campaigns[key] = SurveyCampaign(
            location_id, resource_id, allocation_weight=allocation_weight
        )

    def initialize_known(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> None:
        """Seed Content-defined prior knowledge without exposing campaign State."""
        key = (location_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        target = self.targets[key]
        self.knowledge_progress[key] = max(
            self.knowledge_progress.get(key, 0.0), target.thresholds[-1]
        )
        self.campaigns.pop(key, None)

    def set_allocation_weight(self, location_id: SpatialNodeId, resource_id: DefinitionId, weight: float) -> None:
        blockers = self.allocation_blockers(location_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        if weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.campaigns[(location_id, resource_id)].allocation_weight = weight

    def pause(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> None:
        blockers = self.pause_blockers(location_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[(location_id, resource_id)].paused = True

    def resume(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> None:
        blockers = self.resume_blockers(location_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[(location_id, resource_id)].paused = False

    def progress(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        key = (location_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        return self.knowledge_progress.get(key, 0.0)

    def knowledge_level(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> KnowledgeLevel:
        key = (location_id, resource_id)
        target = self.targets[key]
        progress = self.knowledge_progress.get(key, 0.0)
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
            maintenance = (
                self.facilities.maintenance_factor(facility.id)
                if power is None
                else power.maintenance_factor_by_facility.get(
                    facility.id, self.facilities.maintenance_factor(facility.id)
                )
            )
            points += provider.points_per_day * utilization * maintenance
        return points

    def advance_day(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0) -> None:
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
                    key = (campaign.location_id, campaign.resource_id)
                    progress = self.knowledge_progress.get(key, 0.0)
                    need = max(0.0, final_threshold - progress)
                    gain = min(proposed[id(campaign)], need)
                    progress += gain
                    self.knowledge_progress[key] = min(progress, final_threshold)
                    consumed += gain
                    if progress + 1e-9 >= final_threshold:
                        completed_this_round.append(campaign)
                remaining_points = max(0.0, remaining_points - consumed)
                if not completed_this_round:
                    break
                active = [c for c in active if c not in completed_this_round]
            for campaign in campaigns:
                if self.is_complete(campaign.location_id, campaign.resource_id):
                    self.campaigns.pop((campaign.location_id, campaign.resource_id), None)
