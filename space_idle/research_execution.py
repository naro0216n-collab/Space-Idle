from __future__ import annotations

from .power import PowerSnapshot
from .resource_claim import ResourceAllocationPlan
from .service_capacity import ServiceCapacityAllocationPlan
from .shared import SpatialNodeId
from .research_models import ResearchPhase


class ResearchExecutionMixin:
    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        resource_allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> None:
        for state in list(self.active.values()):
            self._stage_prototype_allocations(state, resource_allocations)

        generated = self.generation_rate(power_by_location, day)
        self.store_generated_points(generated, power_by_location=power_by_location, day=day)

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
            try:
                allocated = service_allocations.allocated(
                    self._demonstration_service_request_id(state.definition_id)
                )
            except KeyError:
                allocated = 0.0
            if allocated + 1e-9 < 1.0:
                continue
            state.demonstration_done_days += 1

    def settle_completions(self) -> None:
        """Apply research completion only after the tick's execution phase."""
        completed = [
            state.definition_id
            for state in self.active.values()
            if (
                state.status is ResearchPhase.DEMONSTRATION
                and self.definitions[state.definition_id].demonstration is not None
                and state.demonstration_done_days
                >= self.definitions[state.definition_id].demonstration.days
            )
        ]
        for research_id in sorted(completed, key=str):
            self._complete(research_id)
