from __future__ import annotations

from dataclasses import dataclass, field
import math

from .facilities import FacilityBook
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId, SurfaceCellId
from .spatial import SpatialGraph
from .exploration_models import KnowledgeLevel, SurveyTarget, SurveyProviderSpec, SurveyCampaign


@dataclass
class SurveyService:
    DEFAULT_ALLOCATION_WEIGHT = 1.0

    targets: dict[tuple[SurfaceCellId, DefinitionId], SurveyTarget]
    providers: dict[DefinitionId, SurveyProviderSpec]
    facilities: FacilityBook
    graph: SpatialGraph
    knowledge_progress: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    campaigns: dict[tuple[SurfaceCellId, DefinitionId], SurveyCampaign] = field(default_factory=dict)

    def start_blockers(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
    ) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        if key not in self.targets:
            return ("unknown_target",)
        if not self.graph.has_operational_node(provider_location_id):
            return ("unknown_provider_location",)
        provider_body = self.graph.operational_node(provider_location_id).body_id
        target_body = self.graph.surface_cells[cell_id].body_id
        if provider_body != target_body:
            return ("different_body",)
        if self.is_complete(cell_id, resource_id):
            return ("survey_complete",)
        if key in self.campaigns:
            return ("already_active",)
        return ()

    def can_start(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
    ) -> bool:
        return not self.start_blockers(provider_location_id, cell_id, resource_id)

    def pause_blockers(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        campaign = self.campaigns.get(key)
        if campaign is None or self.is_complete(cell_id, resource_id):
            return ("not_active",)
        if campaign.paused:
            return ("already_paused",)
        return ()

    def can_pause(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return not self.pause_blockers(cell_id, resource_id)

    def resume_blockers(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        campaign = self.campaigns.get(key)
        if campaign is None or self.is_complete(cell_id, resource_id):
            return ("not_active",)
        if not campaign.paused:
            return ("not_paused",)
        return ()

    def can_resume(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return not self.resume_blockers(cell_id, resource_id)

    def allocation_blockers(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        if key not in self.campaigns or self.is_complete(cell_id, resource_id):
            return ("not_active",)
        return ()

    def can_set_allocation(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return not self.allocation_blockers(cell_id, resource_id)

    def blockers(
        self,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        power: PowerSnapshot | None = None,
        day: int = 0,
    ) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        campaign = self.campaigns.get(key)
        if campaign is None or self.is_complete(cell_id, resource_id):
            return ()
        blockers: list[str] = []
        if campaign.paused:
            blockers.append("manual_pause")
        if campaign.allocation_weight <= 1e-12:
            blockers.append("allocation")
        if self.capacity_at(campaign.provider_location_id, power, day) <= 1e-12:
            blockers.append("survey_capacity")
        return tuple(blockers)

    def start(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        *,
        allocation_weight: float = DEFAULT_ALLOCATION_WEIGHT,
    ) -> None:
        blockers = self.start_blockers(provider_location_id, cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        if allocation_weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.campaigns[(cell_id, resource_id)] = SurveyCampaign(
            provider_location_id,
            cell_id,
            resource_id,
            allocation_weight=allocation_weight,
        )

    def initialize_known(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> None:
        """Seed Content-defined geological knowledge without creating Campaign State."""
        key = (cell_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        target = self.targets[key]
        self.knowledge_progress[key] = max(
            self.knowledge_progress.get(key, 0.0), target.thresholds[-1]
        )
        self.campaigns.pop(key, None)

    def set_allocation_weight(self, cell_id: SurfaceCellId, resource_id: DefinitionId, weight: float) -> None:
        blockers = self.allocation_blockers(cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        if weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.campaigns[(cell_id, resource_id)].allocation_weight = weight

    def pause(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> None:
        blockers = self.pause_blockers(cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[(cell_id, resource_id)].paused = True

    def resume(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> None:
        blockers = self.resume_blockers(cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[(cell_id, resource_id)].paused = False

    def progress(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float:
        key = (cell_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        return self.knowledge_progress.get(key, 0.0)

    def knowledge_level(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> KnowledgeLevel:
        key = (cell_id, resource_id)
        target = self.targets[key]
        progress = self.knowledge_progress.get(key, 0.0)
        level = 0
        for index, threshold in enumerate(target.thresholds, start=1):
            if progress + 1e-9 >= threshold:
                level = index
        return level  # type: ignore[return-value]

    def is_complete(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return self.knowledge_level(cell_id, resource_id) >= 4

    def actual_potential(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float:
        if (cell_id, resource_id) not in self.targets:
            raise KeyError((cell_id, resource_id))
        return float(self.graph.surface_cells[cell_id].resource_potential_by_resource.get(resource_id, 0.0))

    def visible_presence_probability(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float | None:
        if self.knowledge_level(cell_id, resource_id) < 1:
            return None
        return self.targets[(cell_id, resource_id)].prior_presence_probability

    @staticmethod
    def _round_significant(value: float, digits: int) -> float:
        if value == 0.0:
            return 0.0
        magnitude = math.floor(math.log10(abs(value)))
        return round(value, digits - magnitude - 1)

    def visible_potential(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float | None:
        level = self.knowledge_level(cell_id, resource_id)
        if level < 2:
            return None
        potential = self.actual_potential(cell_id, resource_id)
        if level == 2:
            return self._round_significant(potential, 1)
        if level == 3:
            return self._round_significant(potential, 2)
        return potential

    def visible_potential_precision_fraction(
        self, cell_id: SurfaceCellId, resource_id: DefinitionId
    ) -> float | None:
        level = self.knowledge_level(cell_id, resource_id)
        if level < 2:
            return None
        if level == 2:
            return 0.5
        if level == 3:
            return 0.15
        return 0.0

    def capacity_at(
        self, provider_location_id: SpatialNodeId, power: PowerSnapshot | None = None, day: int = 0
    ) -> float:
        points = 0.0
        for facility in self.facilities.active_compatible_at(provider_location_id, day):
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
        by_provider: dict[SpatialNodeId, list[SurveyCampaign]] = {}
        for campaign in self.campaigns.values():
            if (
                not campaign.paused
                and campaign.allocation_weight > 0
                and not self.is_complete(campaign.cell_id, campaign.resource_id)
            ):
                by_provider.setdefault(campaign.provider_location_id, []).append(campaign)
        for provider_location_id, campaigns in by_provider.items():
            remaining_points = self.capacity_at(
                provider_location_id, power_by_location.get(provider_location_id), day
            )
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
                    key = (campaign.cell_id, campaign.resource_id)
                    final_threshold = self.targets[key].thresholds[-1]
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
                if self.is_complete(campaign.cell_id, campaign.resource_id):
                    self.campaigns.pop((campaign.cell_id, campaign.resource_id), None)
