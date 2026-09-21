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

        input_resource_ids = sorted(
            {resource_id for snapshot in plan for resource_id in snapshot.input_rates_per_day},
            key=str,
        )
        for resource_id in input_resource_ids:
            amount = math.fsum(
                snapshot.input_rates_per_day.get(resource_id, 0.0)
                for snapshot in plan if snapshot.scale > 1e-12
            )
            if amount > 1e-12:
                inventory.consume_allocated(location_id, resource_id, amount)

        output_resource_ids = sorted(
            {resource_id for snapshot in plan for resource_id in snapshot.output_rates_per_day},
            key=str,
        )
        for resource_id in output_resource_ids:
            amount = math.fsum(
                snapshot.output_rates_per_day.get(resource_id, 0.0)
                for snapshot in plan if snapshot.scale > 1e-12
            )
            if amount > 1e-12:
                admission = inventory.admit(location_id, resource_id, amount)
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
