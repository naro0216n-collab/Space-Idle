from __future__ import annotations

from .power import PowerSnapshot
from .resource_claim import ResourceAllocationPlan
from .service_capacity import ServiceCapacityAllocationPlan
from .shared import DefinitionId, SpatialNodeId
from .research_models import ResearchStage


class ResearchExecutionMixin:
    def service_allocation_totals(
        self,
        research_id: DefinitionId,
        stage: ResearchStage,
        service_allocations: ServiceCapacityAllocationPlan,
    ) -> tuple[float, float]:
        owner_id = self._project_owner_id(research_id)
        request_ids = {
            request.id
            for request in service_allocations.requests
            if request.owner_kind == "research_project"
            and request.owner_id == owner_id
            and request.purpose == stage.value
        }
        requested = sum(
            request.requested_rate
            for request in service_allocations.requests
            if request.id in request_ids
        )
        allocated = sum(
            row.allocated_rate
            for row in service_allocations.allocations
            if row.request_id in request_ids
        )
        return requested, allocated

    def _stage_services_fulfilled(
        self,
        research_id: DefinitionId,
        stage: ResearchStage,
        service_allocations: ServiceCapacityAllocationPlan,
    ) -> bool:
        state = self.active[research_id]
        definition = self.definitions[research_id]
        spec = (
            definition.prototype
            if stage is ResearchStage.PROTOTYPE
            else definition.demonstration
        )
        if spec is None:
            return False
        location_id = (
            state.prototype_location_id
            if stage is ResearchStage.PROTOTYPE
            else state.demonstration_location_id
        )
        if location_id is None:
            return False
        for requirement in spec.site_requirements.service_capacity_requirements:
            request_id = self._stage_service_request_id(
                research_id, stage, requirement.service_type, location_id
            )
            try:
                allocated = service_allocations.allocated(request_id)
            except KeyError:
                allocated = 0.0
            if allocated + 1e-9 < requirement.minimum_rate:
                return False
        return True

    def point_allocation_projection(
        self, service_allocations: ServiceCapacityAllocationPlan
    ) -> tuple[dict[DefinitionId, float], dict[DefinitionId, float]]:
        requests: dict[DefinitionId, float] = {}
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.stage is not ResearchStage.THEORY:
                continue
            _requested_execution, allocated_execution = self.service_allocation_totals(
                research_id, state.stage, service_allocations
            )
            remaining = max(
                0.0,
                self.definitions[research_id].research_point_cost - state.stage_progress,
            )
            requests[research_id] = min(remaining, max(0.0, allocated_execution))

        available = max(0.0, self.stored_points)
        allocated: dict[DefinitionId, float] = {rid: 0.0 for rid in requests}
        by_priority: dict[int, list[DefinitionId]] = {}
        for research_id in requests:
            by_priority.setdefault(self.active[research_id].priority, []).append(research_id)
        for priority in sorted(by_priority, reverse=True):
            ids = sorted(by_priority[priority], key=str)
            total_need = sum(requests[rid] for rid in ids)
            if available <= 1e-12 or total_need <= 1e-12:
                continue
            take = min(available, total_need)
            for research_id in ids:
                if requests[research_id] > 1e-12:
                    allocated[research_id] = take * requests[research_id] / total_need
            available -= take
        return requests, allocated

    def _allocate_theory_points(
        self, service_allocations: ServiceCapacityAllocationPlan
    ) -> dict[DefinitionId, float]:
        self.last_execution_requests = {}
        self.last_execution_allocations = {}
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused:
                continue
            requested, allocated = self.service_allocation_totals(
                research_id, state.stage, service_allocations
            )
            self.last_execution_requests[research_id] = requested
            self.last_execution_allocations[research_id] = allocated

        requests, allocated = self.point_allocation_projection(service_allocations)
        self.last_point_requests = requests
        self.last_point_allocations = allocated
        return allocated

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        resource_allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> None:
        for state in list(self.active.values()):
            self._stage_prototype_allocations(state, resource_allocations)

        point_allocations = self._allocate_theory_points(service_allocations)
        consumed = sum(point_allocations.values())
        if consumed > self.stored_points + 1e-8:
            raise RuntimeError("research point allocation exceeded stored pool")
        self.stored_points = max(0.0, self.stored_points - consumed)
        for research_id, amount in point_allocations.items():
            state = self.active.get(research_id)
            if state is not None and state.stage is ResearchStage.THEORY:
                state.stage_progress += amount

        for research_id, state in list(self.active.items()):
            if state.paused:
                continue
            if state.stage is ResearchStage.PROTOTYPE:
                location_id = state.prototype_location_id
                prototype = self.definitions[research_id].prototype
                if location_id is None or prototype is None:
                    continue
                snapshot = power_by_location.get(location_id)
                if snapshot is None:
                    snapshot = self.power.snapshot(location_id, self.facilities, day)
                if self.prototype_failures(research_id, location_id, day, snapshot):
                    continue
                resources_ready = all(
                    self.prototype_staged_t(research_id, location_id, resource_id)
                    + 1e-9 >= required
                    for resource_id, required in prototype.resources.items()
                )
                if resources_ready and self._stage_services_fulfilled(
                    research_id, ResearchStage.PROTOTYPE, service_allocations
                ):
                    state.stage_progress = 1.0
            elif state.stage is ResearchStage.DEMONSTRATION:
                location_id = state.demonstration_location_id
                demonstration = self.definitions[research_id].demonstration
                if location_id is None or demonstration is None:
                    continue
                snapshot = power_by_location.get(location_id)
                if snapshot is None:
                    snapshot = self.power.snapshot(location_id, self.facilities, day)
                if self.demonstration_failures(research_id, location_id, day, snapshot):
                    continue
                if self._stage_services_fulfilled(
                    research_id, ResearchStage.DEMONSTRATION, service_allocations
                ):
                    state.stage_progress += 1.0

        # Generation is an execution output.  It is stored only after Theory has
        # consumed the start-of-tick RP pool, so it cannot feed the same tick.
        generated = self.generation_rate(power_by_location, day)
        self.store_generated_points(
            generated, power_by_location=power_by_location, day=day
        )

    def settle_completions(self) -> None:
        """Advance completed stages only at the tick state-transition boundary."""
        for research_id in sorted(tuple(self.active), key=str):
            while research_id in self.active:
                state = self.active[research_id]
                definition = self.definitions[research_id]
                if state.paused:
                    break
                if state.stage is ResearchStage.THEORY:
                    complete = state.stage_progress + 1e-9 >= definition.research_point_cost
                elif state.stage is ResearchStage.PROTOTYPE:
                    complete = state.stage_progress + 1e-9 >= 1.0
                elif state.stage is ResearchStage.DEMONSTRATION:
                    spec = definition.demonstration
                    complete = spec is not None and state.stage_progress + 1e-9 >= spec.days
                elif state.stage is ResearchStage.OPERATIONAL_EXPERIENCE:
                    complete = not self.operational_experience_blockers(research_id)
                else:
                    complete = False
                if not complete:
                    break
                self._advance_stage(research_id)
