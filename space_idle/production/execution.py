from __future__ import annotations
import math

from ..execution_requirements import ExecutionAllocationPlan
from ..facilities import FacilityBook
from ..inventory import InventoryBook
from ..knowledge import DomainActivity
from ..shared import SpatialNodeId


class IndustryExecutionMixin:
    def advance_day(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[DomainActivity, ...]:
        plan = self._plan_site(
            location_id, facilities, inventory, day, execution_allocations,
        )

        # All inputs settle before any output, so no same-day output can be
        # spent by a concurrent Process. Settle each real Facility allocation
        # separately to preserve causal ownership of the actual amounts; the
        # shared Allocation has already resolved resource and storage contention.
        for snapshot in plan:
            if snapshot.scale <= 1e-12:
                continue
            activity = f"industry_process:{snapshot.facility_id}:{snapshot.process_id}"
            for resource_id, amount in sorted(snapshot.input_rates_per_day.items()):
                if amount > 1e-12:
                    inventory.consume_allocated(
                        location_id, resource_id, amount,
                        destination_owner=f"process:{snapshot.facility_id}", activity_id=activity,
                    )
        for snapshot in plan:
            if snapshot.scale <= 1e-12:
                continue
            activity = f"industry_process:{snapshot.facility_id}:{snapshot.process_id}"
            for resource_id, amount in sorted(snapshot.output_rates_per_day.items()):
                if amount > 1e-12:
                    admission = inventory.admit(
                        location_id, resource_id, amount,
                        source_owner=f"process:{snapshot.facility_id}", activity_id=activity,
                    )
                    if not admission.fully_admitted:
                        raise RuntimeError("allocated industry output exceeded Inventory Admission")

        activities: list[DomainActivity] = []
        for snapshot in plan:
            output = math.fsum(snapshot.output_rates_per_day.values())
            if output > 1e-12:
                activities.append(DomainActivity(
                    "manufacturing", output, "industry_process", snapshot.facility_id, location_id
                ))
        return tuple(activities)
