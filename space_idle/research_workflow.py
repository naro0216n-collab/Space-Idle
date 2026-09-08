from __future__ import annotations

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .site import SiteRequirementFailure, evaluate_site_requirements
from .research_models import ResearchDefinition, ResearchProviderSpec, ResearchPhase, ResearchState


class ResearchWorkflowMixin:
    def can_start(self, research_id: DefinitionId) -> bool:
        definition = self.definitions[research_id]
        return research_id not in self.completed and research_id not in self.active and definition.prerequisites.issubset(self.completed)

    def start(self, research_id: DefinitionId, *, allocation_weight: float = 1.0) -> None:
        if allocation_weight < 0:
            raise ValueError("allocation weight must be non-negative")
        if not self.can_start(research_id):
            raise ValueError("research prerequisites not met or already active")
        state = ResearchState(research_id, allocation_weight=allocation_weight)
        self.active[research_id] = state
        if self.definitions[research_id].theory_points <= 1e-12:
            self._finish_theory_phase(state)

    def _finish_theory_phase(self, state: ResearchState) -> None:
        definition = self.definitions[state.definition_id]
        state.theory_done = max(state.theory_done, definition.theory_points)
        if definition.prototype_resources:
            state.status = ResearchPhase.PROTOTYPE
        elif definition.demonstration_days > 0:
            state.status = ResearchPhase.DEMONSTRATION
        else:
            self._complete(state.definition_id)

    def set_allocation_weight(self, research_id: DefinitionId, weight: float) -> None:
        if weight < 0:
            raise ValueError("allocation weight must be non-negative")
        self.active[research_id].allocation_weight = weight

    def pause(self, research_id: DefinitionId) -> None:
        self.active[research_id].paused = True

    def resume(self, research_id: DefinitionId) -> None:
        self.active[research_id].paused = False

    def prototype_failures(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        if location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        definition = self.definitions[research_id]
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            definition.prototype_site_requirements,
            location_id, day, self.facilities.environment, self.facilities, snapshot,
        )

    def fund_prototype(self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0) -> None:
        if location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        state = self.active[research_id]
        definition = self.definitions[research_id]
        if state.status != ResearchPhase.PROTOTYPE:
            raise ValueError("research is not awaiting a prototype")
        failures = self.prototype_failures(research_id, location_id, day)
        if failures:
            raise ValueError("prototype site requirements not met: " + "; ".join(f.detail for f in failures))
        for resource_id, amount in definition.prototype_resources.items():
            if self.inventory.available(location_id, resource_id) + 1e-9 < amount:
                raise ValueError(f"prototype resource shortfall: {resource_id}")
        for resource_id, amount in definition.prototype_resources.items():
            if not self.inventory.take_unreserved(location_id, resource_id, amount):
                raise RuntimeError("prototype accounting race")
        state.prototype_location_id = location_id
        if definition.demonstration_days > 0:
            state.status = ResearchPhase.DEMONSTRATION
            # Reuse the prototype site only if it currently satisfies both its
            # physical and delivered-service requirements.
            if not self.demonstration_failures(research_id, location_id, day):
                state.demonstration_location_id = location_id
        else:
            self._complete(research_id)

    def set_demonstration_site(self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0) -> None:
        state = self.active[research_id]
        if state.status != ResearchPhase.DEMONSTRATION:
            raise ValueError("research is not awaiting demonstration")
        failures = self.demonstration_failures(research_id, location_id, day)
        if failures:
            raise ValueError("demonstration site requirements not met: " + "; ".join(f.detail for f in failures))
        state.demonstration_location_id = location_id
        state.demonstration_done_days = 0

    def demonstration_failures(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        definition = self.definitions[research_id]
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            definition.demonstration_site_requirements,
            location_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
        )

    def _complete(self, research_id: DefinitionId) -> None:
        self.completed.add(research_id)
        state = self.active[research_id]
        state.status = ResearchPhase.COMPLETE
        self.active.pop(research_id, None)
