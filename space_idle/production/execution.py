from __future__ import annotations

from ..facilities import FacilityBook, FacilityState
from ..inventory import InventoryBook
from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, SpatialNodeId
from .models import ProcessSpec, ProcessSnapshot


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
        # Consume all inputs before adding any outputs. Same-day production does
        # not chain through arbitrary process iteration order.
        for snapshot in plan:
            if snapshot.scale <= 1e-12:
                continue
            for resource_id, amount in snapshot.input_rates_per_day.items():
                if amount > 1e-12 and not inventory.take_unreserved(location_id, resource_id, amount):
                    raise RuntimeError("industry input accounting race")
        for snapshot in plan:
            if snapshot.scale <= 1e-12:
                continue
            for resource_id, amount in snapshot.output_rates_per_day.items():
                if amount > 1e-12:
                    inventory.add(location_id, resource_id, amount)
