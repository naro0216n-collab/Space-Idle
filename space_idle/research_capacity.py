from __future__ import annotations

from .power import PowerSnapshot
from .shared import SpatialNodeId


class ResearchCapacityMixin:
    def _power_by_location(self, day: int) -> dict[SpatialNodeId, PowerSnapshot]:
        locations = {
            facility.location_id
            for facility in self.facilities.facilities.values()
            if facility.definition_id in self.providers
        }
        return {
            location_id: self.power.snapshot(location_id, self.facilities, day)
            for location_id in sorted(locations, key=str)
        }

    def _provider_factor(self, facility_id, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int) -> float:
        facility = self.facilities.facilities[facility_id]
        if not self.facilities.is_active_and_compatible(facility, day):
            return 0.0
        snapshot = power_by_location.get(facility.location_id)
        if snapshot is None:
            snapshot = self.power.snapshot(facility.location_id, self.facilities, day)
        return max(0.0, min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)))

    def _provider_level_spec(self, facility_id):
        facility = self.facilities.facilities[facility_id]
        provider = self.providers.get(facility.definition_id)
        return None if provider is None else provider.level_spec(facility.level)

    def provider_generation(self, facility_id, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int) -> float:
        spec = self._provider_level_spec(facility_id)
        if spec is None:
            return 0.0
        return spec.generation_points_per_day * self._provider_factor(facility_id, power_by_location, day)

    def provider_storage_capacity(self, facility_id, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int) -> float:
        spec = self._provider_level_spec(facility_id)
        if spec is None:
            return 0.0
        return spec.storage_capacity_points * self._provider_factor(facility_id, power_by_location, day)

    def generation_rate(self, power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None, day: int = 0) -> float:
        snapshots = self._power_by_location(day) if power_by_location is None else power_by_location
        return sum(
            self.provider_generation(facility.id, snapshots, day)
            for facility in self.facilities.facilities.values()
            if facility.definition_id in self.providers
        )

    def storage_capacity(self, power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None, day: int = 0) -> float:
        snapshots = self._power_by_location(day) if power_by_location is None else power_by_location
        return sum(
            self.provider_storage_capacity(facility.id, snapshots, day)
            for facility in self.facilities.facilities.values()
            if facility.definition_id in self.providers
        )

    def is_over_capacity(self, power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None, day: int = 0) -> bool:
        return self.stored_points > self.storage_capacity(power_by_location, day) + 1e-9
