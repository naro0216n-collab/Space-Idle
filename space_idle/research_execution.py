from __future__ import annotations

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .site import SiteRequirementFailure, evaluate_site_requirements
from .research_models import ResearchDefinition, ResearchProviderSpec, ResearchPhase, ResearchState


class ResearchExecutionMixin:
    def advance_day(self, power_by_location: dict[SpatialNodeId, PowerSnapshot], day: int = 0) -> None:
        theory_states = [
            s for s in self.active.values()
            if s.status == ResearchPhase.THEORY and not s.paused and s.allocation_weight > 0
        ]

        # Research capacity is produced by concrete facilities at concrete sites.
        # A provider can only contribute to projects whose infrastructure
        # prerequisites are satisfied at that provider's own site. This avoids
        # implicitly combining an unrelated laboratory at one location with a
        # prerequisite facility at another location. Each provider splits its
        # finite flow among the projects it can actually support.
        theory_gain: dict[DefinitionId, float] = {state.definition_id: 0.0 for state in theory_states}
        for facility in self.facilities.facilities.values():
            if facility.definition_id not in self.providers:
                continue
            capacity = self._provider_capacity(facility.id, power_by_location, day)
            if capacity <= 1e-12:
                continue
            snapshot = power_by_location.get(facility.location_id)
            if snapshot is None:
                snapshot = self.power.snapshot(facility.location_id, self.facilities, day)
            eligible = [
                state for state in theory_states
                if self._provider_can_support(facility.id, self.definitions[state.definition_id], snapshot, day)
            ]
            weight_total = sum(state.allocation_weight for state in eligible)
            if weight_total <= 1e-12:
                continue
            for state in eligible:
                theory_gain[state.definition_id] += capacity * state.allocation_weight / weight_total

        for state in list(theory_states):
            gain = theory_gain.get(state.definition_id, 0.0)
            if gain <= 1e-12 or state.definition_id not in self.active:
                continue
            definition = self.definitions[state.definition_id]
            state.theory_done += gain
            if state.theory_done + 1e-9 >= definition.theory_points:
                self._finish_theory_phase(state)

        for state in list(self.active.values()):
            if state.paused or state.status != ResearchPhase.DEMONSTRATION or state.demonstration_location_id is None:
                continue
            snapshot = power_by_location.get(state.demonstration_location_id)
            if snapshot is None:
                snapshot = self.power.snapshot(state.demonstration_location_id, self.facilities, day)
            if self.demonstration_failures(state.definition_id, state.demonstration_location_id, day, snapshot):
                continue
            definition = self.definitions[state.definition_id]
            state.demonstration_done_days += 1
            if state.demonstration_done_days >= definition.demonstration_days:
                self._complete(state.definition_id)
