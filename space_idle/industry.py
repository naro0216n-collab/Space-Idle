from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, SpatialNodeId
from .production import (
    ProcessSpec, ProcessSnapshot, ProcessSelectionMixin,
    IndustryPlanningMixin, IndustryExecutionMixin,
)


@dataclass
class IndustryService(ProcessSelectionMixin, IndustryPlanningMixin, IndustryExecutionMixin):
    processes: dict[DefinitionId, ProcessSpec]
    selected_process_by_facility: dict[EntityId, DefinitionId] = field(default_factory=dict)

    def resource_demands(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> tuple[ResourceDemand, ...]:
        """Declare one-day input replenishment needs for active processes.

        Industry owns the desired input rate. Logistics only sees material need
        at a destination and may satisfy it through any eligible lane.
        """
        required: dict[DefinitionId, float] = {}
        for facility in facilities.active_compatible_at(location_id, day):
            process = self.process_for(facility)
            if process is None:
                continue
            utilization = max(
                0.0,
                min(
                    1.0,
                    power.utilization_by_facility.get(facility.id, 1.0)
                    * power.maintenance_factor_by_facility.get(
                        facility.id, facilities.maintenance_factor(facility.id)
                    ),
                ),
            )
            for resource_id, amount_t in process.inputs_per_day.items():
                if amount_t > 1e-12:
                    required[resource_id] = required.get(resource_id, 0.0) + amount_t * utilization

        owner_id = EntityId(f"industry.site:{location_id}")
        demands: list[ResourceDemand] = []
        for resource_id, target_t in sorted(required.items(), key=lambda row: str(row[0])):
            if target_t <= 1e-9:
                continue
            demands.append(ResourceDemand(
                EntityId(f"demand.industry:{location_id}:{resource_id}"),
                "industry",
                owner_id,
                location_id,
                resource_id,
                target_t,
                50,
            ))
        return tuple(demands)

    @staticmethod
    def _resource_claim_id(facility_id: EntityId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"claim.industry:{facility_id}:{resource_id}")

    def resource_claims(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for facility in sorted(
            facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            process = self.process_for(facility)
            if process is None:
                continue
            utilization = max(
                0.0,
                min(
                    1.0,
                    power.utilization_by_facility.get(facility.id, 1.0)
                    * power.maintenance_factor_by_facility.get(
                        facility.id, facilities.maintenance_factor(facility.id)
                    ),
                ),
            )
            for resource_id, amount_t in sorted(
                process.inputs_per_day.items(), key=lambda row: str(row[0])
            ):
                requested = amount_t * utilization
                if requested <= 1e-12:
                    continue
                claims.append(ResourceClaim(
                    self._resource_claim_id(facility.id, resource_id),
                    location_id,
                    resource_id,
                    requested,
                    50,
                    "industry_process",
                    facility.id,
                    f"process:{process.id}",
                    demand_id=EntityId(f"demand.industry:{location_id}:{resource_id}"),
                ))
        return tuple(claims)


__all__ = ["ProcessSpec", "ProcessSnapshot", "IndustryService"]
