from __future__ import annotations

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .site import SiteRequirementFailure, evaluate_site_requirements
from .research_models import ResearchDefinition, ResearchProviderSpec, ResearchPhase, ResearchState


class ResearchCapacityMixin:
    def _provider_capacity(self, facility_id, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int) -> float:
        facility = self.facilities.facilities[facility_id]
        if not self.facilities.is_active_and_compatible(facility, day):
            return 0.0
        provider = self.providers.get(facility.definition_id)
        if provider is None:
            return 0.0
        snapshot = power_by_location.get(facility.location_id)
        if snapshot is None:
            snapshot = self.power.snapshot(facility.location_id, self.facilities, day)
        factor = max(0.0, min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)))
        return provider.points_per_day * factor

    def _provider_can_support(
        self, facility_id, definition: ResearchDefinition, power: PowerSnapshot, day: int
    ) -> bool:
        facility = self.facilities.facilities[facility_id]
        return not evaluate_site_requirements(
            definition.theory_site_requirements,
            facility.location_id, day, self.facilities.environment, self.facilities, power,
        )

    def research_capacity(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int) -> float:
        return sum(
            self._provider_capacity(facility.id, power_by_location, day)
            for facility in self.facilities.facilities.values()
            if facility.definition_id in self.providers
        )

    def theory_capacity_for(
        self, research_id: DefinitionId, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int
    ) -> float:
        definition = self.definitions[research_id]
        total = 0.0
        for facility in self.facilities.facilities.values():
            if facility.definition_id not in self.providers:
                continue
            snapshot = power_by_location.get(facility.location_id)
            if snapshot is None:
                snapshot = self.power.snapshot(facility.location_id, self.facilities, day)
            if self._provider_can_support(facility.id, definition, snapshot, day):
                total += self._provider_capacity(facility.id, power_by_location, day)
        return total
