from __future__ import annotations

from .execution_requirements import pool_constraint
from .power import PowerSnapshot
from .shared import SpatialNodeId


class ResearchCapacityMixin:
    def _provider_factor(self, facility_id, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int) -> float:
        facility = self.facilities.facilities[facility_id]
        if not self.facilities.is_active_and_compatible(facility, day):
            return 0.0
        snapshot = power_by_location.get(facility.operational_node_id)
        if snapshot is None:
            # Missing allocation data means a nominal query, not permission to
            # run a private Power allocation outside the tick DAG.
            return 1.0
        return max(
            0.0,
            min(
                1.0,
                snapshot.utilization_by_facility.get(facility.id, 1.0)
                * snapshot.maintenance_factor_by_facility.get(facility.id, 1.0),
            ),
        )

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
        snapshots = {} if power_by_location is None else power_by_location
        return sum(
            self.provider_generation(facility.id, snapshots, day)
            for facility in self.facilities.facilities.values()
            if facility.definition_id in self.providers
        )

    def storage_capacity(self, power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None, day: int = 0) -> float:
        snapshots = {} if power_by_location is None else power_by_location
        return sum(
            self.provider_storage_capacity(facility.id, snapshots, day)
            for facility in self.facilities.facilities.values()
            if facility.definition_id in self.providers
        )

    def allocation_pool_capacities(self, day: int):
        """Expose organization-owned finite pools to the common allocator."""
        return {pool_constraint("research_points", scope_id="organization"): self.stored_points}


    def store_generated_points(
        self,
        points: float,
        *,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
        day: int = 0,
    ) -> float:
        """Store newly generated RP without ever deleting already stored RP."""
        if points < -1e-9:
            raise ValueError("generated research points must be non-negative")
        capacity = self.storage_capacity(power_by_location, day)
        free = max(0.0, capacity - self.stored_points)
        accepted = min(max(0.0, points), free)
        self.stored_points += accepted
        return accepted

    def is_over_capacity(self, power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None, day: int = 0) -> bool:
        return self.stored_points > self.storage_capacity(power_by_location, day) + 1e-9
