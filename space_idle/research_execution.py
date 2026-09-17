from __future__ import annotations

from .execution_requirements import ExecutionAllocationPlan
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .research_models import (
    ResearchTheoryStageSpec,
    ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec,
)


class ResearchExecutionMixin:
    def execution_allocation_totals(
        self,
        research_id: DefinitionId,
        stage_id: str,
        execution_allocations: ExecutionAllocationPlan,
    ) -> tuple[float, float]:
        owner_id = self._project_owner_id(research_id)
        bundle_ids = {
            bundle.id
            for bundle in execution_allocations.bundles
            if bundle.owner_kind == "research_project"
            and bundle.owner_id == owner_id
            and bundle.purpose == stage_id
        }
        requested = sum(bundle.requested_execution for bundle in execution_allocations.bundles if bundle.id in bundle_ids)
        allocated = sum(row.allocated_execution for row in execution_allocations.allocations if row.bundle_id in bundle_ids)
        return requested, allocated

    def point_allocation_projection(
        self, execution_allocations: ExecutionAllocationPlan
    ) -> tuple[dict[DefinitionId, float], dict[DefinitionId, float]]:
        requested: dict[DefinitionId, float] = {}
        allocated: dict[DefinitionId, float] = {}
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or not isinstance(self.current_stage_spec(research_id), ResearchTheoryStageSpec):
                continue
            req, alloc = self.execution_allocation_totals(research_id, state.current_stage_id, execution_allocations)
            requested[research_id] = req
            allocated[research_id] = alloc
        return requested, allocated

    def finalize_reservation_acquisition(self, execution_allocations: ExecutionAllocationPlan) -> None:
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            spec = self.current_stage_spec(research_id)
            site = state.execution_context
            if state.paused or not isinstance(spec, ResearchPrototypeStageSpec) or site is None:
                continue
            owner_id = self._prototype_reservation_owner_id(research_id, spec.stage_id)
            location_id = site.operational_node_id
            for resource_id, required in sorted(spec.resources.items(), key=lambda row: str(row[0])):
                missing = max(0.0, required - self.prototype_reserved_t(research_id, spec.stage_id, location_id, resource_id))
                if missing <= 1e-12:
                    continue
                requirement_id = self.prototype_reservation_requirement_id(research_id, spec.stage_id, resource_id)
                try:
                    allocated = execution_allocations.allocated(requirement_id)
                except KeyError:
                    allocated = 0.0
                amount = min(missing, max(0.0, allocated))
                if amount <= 1e-12:
                    continue
                reserved = self.inventory.reserve(owner_id, location_id, resource_id, amount)
                if reserved + 1e-9 < amount:
                    raise RuntimeError("allocated prototype reservation stock changed before execution")

    def _refresh_allocation_projections(self, execution_allocations: ExecutionAllocationPlan) -> None:
        self.last_execution_requests = {}
        self.last_execution_allocations = {}
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused:
                continue
            requested, allocated = self.execution_allocation_totals(
                research_id, state.current_stage_id, execution_allocations
            )
            self.last_execution_requests[research_id] = requested
            self.last_execution_allocations[research_id] = allocated
        self.last_point_requests, self.last_point_allocations = self.point_allocation_projection(execution_allocations)

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        execution_allocations: ExecutionAllocationPlan,
        day: int = 0,
    ) -> None:
        self.finalize_reservation_acquisition(execution_allocations)
        self._refresh_allocation_projections(execution_allocations)

        theory_consumed = 0.0
        for research_id, amount in self.last_point_allocations.items():
            state = self.active.get(research_id)
            if state is None or not isinstance(self.current_stage_spec(research_id), ResearchTheoryStageSpec):
                continue
            theory_consumed += amount
            state.stage_progress = (state.stage_progress or 0.0) + amount
        if theory_consumed > self.stored_points + 1e-8:
            raise RuntimeError("research point allocation exceeded stored pool")
        self.stored_points = max(0.0, self.stored_points - theory_consumed)

        for research_id, state in list(self.active.items()):
            if state.paused:
                continue
            spec = self.current_stage_spec(research_id)
            if not isinstance(spec, (ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)):
                continue
            site = state.execution_context
            if site is None:
                continue
            snapshot = power_by_location[site.operational_node_id]
            failures = (
                self.prototype_failures(research_id, site.operational_node_id, day, snapshot, site.surface_cell_id)
                if isinstance(spec, ResearchPrototypeStageSpec)
                else self.demonstration_failures(research_id, site.operational_node_id, day, snapshot, site.surface_cell_id)
            )
            if failures:
                continue
            if isinstance(spec, ResearchPrototypeStageSpec) and not all(
                self.prototype_reserved_t(research_id, spec.stage_id, site.operational_node_id, resource_id) + 1e-9 >= required
                for resource_id, required in spec.resources.items()
            ):
                continue
            bundle_id = self._stage_bundle_id(research_id, spec.stage_id, spec.stage_type, site)
            try:
                allocated = execution_allocations.allocated(bundle_id)
            except KeyError:
                allocated = 0.0
            state.stage_progress = (state.stage_progress or 0.0) + max(0.0, allocated)

        # Research Point production is settled separately through its common
        # admission allocation. This method only consumes Project allocations.

    def settle_completions(self, day: int) -> None:
        for research_id in sorted(tuple(self.active), key=str):
            while research_id in self.active:
                state = self.active[research_id]
                if state.paused:
                    break
                spec = self.current_stage_spec(research_id)
                if isinstance(spec, ResearchTheoryStageSpec):
                    complete = (state.stage_progress or 0.0) + 1e-9 >= spec.research_point_cost
                elif isinstance(spec, ResearchPrototypeStageSpec):
                    complete = (state.stage_progress or 0.0) + 1e-9 >= spec.required_work
                elif isinstance(spec, ResearchDemonstrationStageSpec):
                    complete = (state.stage_progress or 0.0) + 1e-9 >= spec.required_work
                else:
                    complete = not self.operational_experience_blockers(research_id)
                if not complete:
                    break
                self._advance_stage(research_id, day)
