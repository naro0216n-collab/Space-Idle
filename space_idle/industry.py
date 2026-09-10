from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
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
                None,
                0.0,
                True,
            ))
        return tuple(demands)


__all__ = ["ProcessSpec", "ProcessSnapshot", "IndustryService"]
