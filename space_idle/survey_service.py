from __future__ import annotations

from dataclasses import dataclass, field
import math

from .facilities import FacilityBook
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId, SurfaceCellId
from .spatial import SpatialGraph
from .exploration_models import KnowledgeLevel, SurveyCoverage, SurveyTarget, SurveyProviderSpec, SurveyCampaign


@dataclass
class SurveyService:
    DEFAULT_ALLOCATION_WEIGHT = 1.0

    targets: dict[tuple[SurfaceCellId, DefinitionId], SurveyTarget]
    providers: dict[DefinitionId, SurveyProviderSpec]
    facilities: FacilityBook
    graph: SpatialGraph
    knowledge_progress: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    campaigns: dict[tuple[SurfaceCellId, DefinitionId], SurveyCampaign] = field(default_factory=dict)

    def _provider_covers_target(
        self, provider_location_id: SpatialNodeId, spec: SurveyProviderSpec, cell_id: SurfaceCellId
    ) -> bool:
        if not self.graph.has_operational_node(provider_location_id):
            return False
        target = self.graph.surface_cells.get(cell_id)
        if target is None:
            return False
        provider_node = self.graph.operational_node(provider_location_id)
        if provider_node.body_id != target.body_id:
            return False
        if spec.coverage is SurveyCoverage.BODY_REMOTE:
            return True
        if spec.coverage is SurveyCoverage.LOCATION_TERRITORY:
            location = self.graph.locations.get(provider_location_id)
            return location is not None and cell_id in location.developed_cell_ids
        return False

    def _provider_facilities_for_target(
        self, provider_location_id: SpatialNodeId, cell_id: SurfaceCellId, *, active_only: bool, day: int = 0
    ):
        facilities = (
            self.facilities.active_compatible_at(provider_location_id, day)
            if active_only
            else self.facilities.all_at(provider_location_id)
        )
        result = []
        for facility in facilities:
            spec = self.providers.get(facility.definition_id)
            if spec is not None and self._provider_covers_target(provider_location_id, spec, cell_id):
                result.append((facility, spec))
        return result

    def reachable_knowledge_level(
        self, provider_location_id: SpatialNodeId, cell_id: SurfaceCellId, *, day: int = 0
    ) -> KnowledgeLevel:
        levels = [
            spec.max_knowledge_level
            for _facility, spec in self._provider_facilities_for_target(
                provider_location_id, cell_id, active_only=False, day=day
            )
        ]
        return max(levels, default=0)  # type: ignore[return-value]

    def start_blockers(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        day: int = 0,
    ) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        if key not in self.targets:
            return ("unknown_target",)
        if not self.graph.has_operational_node(provider_location_id):
            return ("unknown_provider_location",)
        provider_specs = [
            self.providers.get(f.definition_id)
            for f in self.facilities.all_at(provider_location_id)
            if self.providers.get(f.definition_id) is not None
        ]
        if not provider_specs:
            return ("survey_provider",)
        provider_body = self.graph.operational_node(provider_location_id).body_id
        target_body = self.graph.surface_cells[cell_id].body_id
        if provider_body != target_body:
            return ("different_body",)
        reachable_level = self.reachable_knowledge_level(provider_location_id, cell_id, day=day)
        if reachable_level <= 0:
            return ("survey_coverage",)
        if self.is_complete(cell_id, resource_id):
            return ("survey_complete",)
        if self.knowledge_level(cell_id, resource_id) >= reachable_level:
            return ("survey_provider_limit",)
        if key in self.campaigns:
            return ("already_active",)
        return ()

    def can_start(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        day: int = 0,
    ) -> bool:
        return not self.start_blockers(provider_location_id, cell_id, resource_id, day)

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
        if campaign is None or self.knowledge_level(cell_id, resource_id) >= campaign.target_knowledge_level:
            return ()
        blockers: list[str] = []
        if campaign.paused:
            blockers.append("manual_pause")
        if campaign.allocation_weight <= 1e-12:
            blockers.append("allocation")
        if self.capacity_for_target(
            campaign.provider_location_id, cell_id, resource_id, power, day
        ) <= 1e-12:
            blockers.append("survey_capacity")
        return tuple(blockers)

    def start(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        *,
        allocation_weight: float = DEFAULT_ALLOCATION_WEIGHT,
        day: int = 0,
    ) -> None:
        blockers = self.start_blockers(provider_location_id, cell_id, resource_id, day)
        if blockers:
            raise ValueError("; ".join(blockers))
        if allocation_weight < 0:
            raise ValueError("allocation weight must be non-negative")
        target_level = self.reachable_knowledge_level(provider_location_id, cell_id, day=day)
        self.campaigns[(cell_id, resource_id)] = SurveyCampaign(
            provider_location_id,
            cell_id,
            resource_id,
            target_knowledge_level=target_level,
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

    def cell_knowledge_level(self, cell_id: SurfaceCellId) -> KnowledgeLevel:
        """Highest geological knowledge level available for a Surface Cell.

        Spatial-development requirements depend on whether the site has been
        surveyed at all, not on a particular Resource being privileged by Core.
        Resource-specific decisions continue to use ``knowledge_level``.
        """
        levels = [
            self.knowledge_level(target_cell_id, resource_id)
            for target_cell_id, resource_id in self.targets
            if target_cell_id == cell_id
        ]
        return max(levels, default=0)  # type: ignore[return-value]

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

    def _facility_survey_capacity(
        self, facility, spec: SurveyProviderSpec, power: PowerSnapshot | None
    ) -> float:
        utilization = 1.0 if power is None else power.utilization_by_facility.get(facility.id, 1.0)
        maintenance = (
            self.facilities.maintenance_factor(facility.id)
            if power is None
            else power.maintenance_factor_by_facility.get(
                facility.id, self.facilities.maintenance_factor(facility.id)
            )
        )
        return spec.points_per_day * utilization * maintenance

    def capacity_at(
        self, provider_location_id: SpatialNodeId, power: PowerSnapshot | None = None, day: int = 0
    ) -> float:
        points = 0.0
        for facility in self.facilities.active_compatible_at(provider_location_id, day):
            provider = self.providers.get(facility.definition_id)
            if provider is None:
                continue
            points += self._facility_survey_capacity(facility, provider, power)
        return points

    def capacity_for_target(
        self,
        provider_location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        power: PowerSnapshot | None = None,
        day: int = 0,
    ) -> float:
        current_level = self.knowledge_level(cell_id, resource_id)
        points = 0.0
        for facility, spec in self._provider_facilities_for_target(
            provider_location_id, cell_id, active_only=True, day=day
        ):
            if spec.max_knowledge_level <= current_level:
                continue
            points += self._facility_survey_capacity(facility, spec, power)
        return points

    def advance_day(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0) -> None:
        by_provider: dict[SpatialNodeId, list[SurveyCampaign]] = {}
        for campaign in self.campaigns.values():
            if (
                not campaign.paused
                and campaign.allocation_weight > 0
                and self.knowledge_level(campaign.cell_id, campaign.resource_id) < campaign.target_knowledge_level
            ):
                by_provider.setdefault(campaign.provider_location_id, []).append(campaign)

        for provider_location_id, campaigns in by_provider.items():
            power = power_by_location.get(provider_location_id)
            providers = sorted(
                self._provider_facilities_for_target_for_any_campaign(
                    provider_location_id, campaigns, day
                ),
                key=lambda row: str(row[0].id),
            )
            for facility, spec in providers:
                remaining_points = self._facility_survey_capacity(facility, spec, power)
                active = [
                    campaign
                    for campaign in campaigns
                    if self._provider_covers_target(provider_location_id, spec, campaign.cell_id)
                    and self.knowledge_level(campaign.cell_id, campaign.resource_id)
                    < min(campaign.target_knowledge_level, spec.max_knowledge_level)
                ]
                while active and remaining_points > 1e-12:
                    weight_total = sum(c.allocation_weight for c in active)
                    if weight_total <= 1e-12:
                        break
                    proposed = {
                        id(c): remaining_points * c.allocation_weight / weight_total
                        for c in active
                    }
                    capped: list[SurveyCampaign] = []
                    consumed = 0.0
                    for campaign in active:
                        key = (campaign.cell_id, campaign.resource_id)
                        cap_level = min(campaign.target_knowledge_level, spec.max_knowledge_level)
                        cap_threshold = self.targets[key].thresholds[cap_level - 1]
                        progress = self.knowledge_progress.get(key, 0.0)
                        need = max(0.0, cap_threshold - progress)
                        gain = min(proposed[id(campaign)], need)
                        if gain > 0:
                            self.knowledge_progress[key] = min(progress + gain, cap_threshold)
                        consumed += gain
                        if self.knowledge_progress.get(key, progress) + 1e-9 >= cap_threshold:
                            capped.append(campaign)
                    remaining_points = max(0.0, remaining_points - consumed)
                    if not capped or consumed <= 1e-12:
                        break
                    active = [campaign for campaign in active if campaign not in capped]

            for campaign in campaigns:
                if self.knowledge_level(campaign.cell_id, campaign.resource_id) >= campaign.target_knowledge_level:
                    self.campaigns.pop((campaign.cell_id, campaign.resource_id), None)

    def _provider_facilities_for_target_for_any_campaign(
        self, provider_location_id: SpatialNodeId, campaigns: list[SurveyCampaign], day: int
    ):
        result = []
        for facility in self.facilities.active_compatible_at(provider_location_id, day):
            spec = self.providers.get(facility.definition_id)
            if spec is None:
                continue
            if any(
                self._provider_covers_target(provider_location_id, spec, campaign.cell_id)
                for campaign in campaigns
            ):
                result.append((facility, spec))
        return result
