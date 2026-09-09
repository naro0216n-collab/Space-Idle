from __future__ import annotations

from .power import PowerSnapshot
from .shared import SpatialNodeId
from .research_models import ResearchPhase


class ResearchExecutionMixin:
    def advance_day(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0) -> None:
        capacity = self.storage_capacity(power_by_location, day)
        if self.stored_points < capacity - 1e-9:
            generated = self.generation_rate(power_by_location, day)
            self.stored_points = min(capacity, self.stored_points + generated)

        for state in list(self.active.values()):
            if state.paused or state.status != ResearchPhase.DEMONSTRATION or state.demonstration_location_id is None:
                continue
            snapshot = power_by_location.get(state.demonstration_location_id)
            if snapshot is None:
                snapshot = self.power.snapshot(state.demonstration_location_id, self.facilities, day)
            if self.demonstration_failures(state.definition_id, state.demonstration_location_id, day, snapshot):
                continue
            demonstration = self.definitions[state.definition_id].demonstration
            if demonstration is None:
                raise RuntimeError(f"demonstration state has no demonstration definition: {state.definition_id}")
            state.demonstration_done_days += 1
            if state.demonstration_done_days >= demonstration.days:
                self._complete(state.definition_id)
