from __future__ import annotations

import math

from ..facilities import FacilityBook
from ..inventory import InventoryBook
from ..power import PowerSnapshot
from ..shared import SpatialNodeId


class IndustryExecutionMixin:
    def advance_day(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> None:
        plan = self._plan_site(location_id, facilities, inventory, power, day)

        # Mutate each resource balance once. Planning is simultaneous, so
        # execution must not re-introduce facility registration/order effects
        # through sequential floating-point subtraction or addition.
        input_resource_ids = sorted(
            {resource_id for snapshot in plan for resource_id in snapshot.input_rates_per_day},
            key=str,
        )
        input_totals = {
            resource_id: math.fsum(
                snapshot.input_rates_per_day.get(resource_id, 0.0)
                for snapshot in plan
                if snapshot.scale > 1e-12
            )
            for resource_id in input_resource_ids
        }
        for resource_id in input_resource_ids:
            amount = input_totals[resource_id]
            if amount > 1e-12 and not inventory.take_unreserved(location_id, resource_id, amount):
                raise RuntimeError("industry input accounting race")

        # Consume all inputs before adding any outputs. Same-day production does
        # not chain through arbitrary process iteration order.
        output_resource_ids = sorted(
            {resource_id for snapshot in plan for resource_id in snapshot.output_rates_per_day},
            key=str,
        )
        output_totals = {
            resource_id: math.fsum(
                snapshot.output_rates_per_day.get(resource_id, 0.0)
                for snapshot in plan
                if snapshot.scale > 1e-12
            )
            for resource_id in output_resource_ids
        }
        for resource_id in output_resource_ids:
            amount = output_totals[resource_id]
            if amount > 1e-12:
                inventory.add(location_id, resource_id, amount)
