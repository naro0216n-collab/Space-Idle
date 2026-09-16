from __future__ import annotations

from .execution_requirements import ExecutionAllocationPlan
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .research_models import ResearchStage


class ResearchExecutionMixin:
    def execution_allocation_totals(
        self,
        research_id: DefinitionId,
        stage: ResearchStage,
        execution_allocations: ExecutionAllocationPlan,
    ) -> tuple[float, float]:
        owner_id = self._project_owner_id(research_id)
        bundle_ids = {
            bundle.id
            for bundle in execution_allocations.bundles
            if bundle.owner_kind == "research_project"
            and bundle.owner_id == owner_id
            and bundle.purpose == stage.value
        }
        requested = sum(
            bundle.requested_execution
            for bundle in execution_allocations.bundles
            if bundle.id in bundle_ids
        )
        allocated = sum(
            row.allocated_execution
            for row in execution_allocations.allocations
            if row.bundle_id in bundle_ids
        )
        return requested, allocated

    def point_allocation_projection(
        self, execution_allocations: ExecutionAllocationPlan
    ) -> tuple[dict[DefinitionId, float], dict[DefinitionId, float]]:
        requested: dict[DefinitionId, float] = {}
        allocated: dict[DefinitionId, float] = {}
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.stage is not ResearchStage.THEORY:
                continue
            req, alloc = self.execution_allocation_totals(
                research_id, ResearchStage.THEORY, execution_allocations
            )
            requested[research_id] = req
            allocated[research_id] = alloc
        return requested, allocated

    def finalize_reservation_acquisition(
        self, execution_allocations: ExecutionAllocationPlan
    ) -> None:
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            site = state.prototype_execution_site
            if (
                state.paused
                or state.stage is not ResearchStage.PROTOTYPE
                or site is None
            ):
                continue
            prototype = self.definitions[research_id].prototype
            if prototype is None:
                raise RuntimeError(
                    f"prototype state has no prototype definition: {research_id}"
                )
            owner_id = self._prototype_reservation_owner_id(research_id)
            location_id = site.operational_node_id
            for resource_id, required in sorted(
                prototype.resources.items(), key=lambda row: str(row[0])
            ):
                missing = max(
                    0.0,
                    required
                    - self.prototype_reserved_t(research_id, location_id, resource_id),
                )
                if missing <= 1e-12:
                    continue
                requirement_id = self.prototype_reservation_requirement_id(
                    research_id, resource_id
                )
                try:
                    allocated = execution_allocations.allocated(requirement_id)
                except KeyError:
                    allocated = 0.0
                amount = min(missing, max(0.0, allocated))
                if amount <= 1e-12:
                    continue
                reserved = self.inventory.reserve(
                    owner_id, location_id, resource_id, amount
                )
                if reserved + 1e-9 < amount:
                    raise RuntimeError(
                        "allocated prototype reservation stock changed before execution"
                    )

    def _refresh_allocation_projections(
        self, execution_allocations: ExecutionAllocationPlan
    ) -> None:
        self.last_execution_requests = {}
        self.last_execution_allocations = {}
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused:
                continue
            requested, allocated = self.execution_allocation_totals(
                research_id, state.stage, execution_allocations
            )
            self.last_execution_requests[research_id] = requested
            self.last_execution_allocations[research_id] = allocated
        self.last_point_requests, self.last_point_allocations = (
            self.point_allocation_projection(execution_allocations)
        )

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        execution_allocations: ExecutionAllocationPlan,
        day: int = 0,
    ) -> None:
        # Reservation acquisition is an execution result, but newly acquired
        # material cannot make a prototype executable retroactively in this tick:
        # prototype execution bundles were created from the start-of-tick snapshot.
        self.finalize_reservation_acquisition(execution_allocations)
        self._refresh_allocation_projections(execution_allocations)

        theory_consumed = 0.0
        for research_id, amount in self.last_point_allocations.items():
            state = self.active.get(research_id)
            if state is None or state.stage is not ResearchStage.THEORY:
                continue
            theory_consumed += amount
            state.stage_progress += amount
        if theory_consumed > self.stored_points + 1e-8:
            raise RuntimeError("research point allocation exceeded stored pool")
        self.stored_points = max(0.0, self.stored_points - theory_consumed)

        for research_id, state in list(self.active.items()):
            if state.paused:
                continue
            if state.stage is ResearchStage.PROTOTYPE:
                site = state.prototype_execution_site
                prototype = self.definitions[research_id].prototype
                if site is None or prototype is None:
                    continue
                location_id = site.operational_node_id
                snapshot = power_by_location[location_id]
                if self.prototype_failures(
                    research_id,
                    location_id,
                    day,
                    snapshot,
                    site.surface_cell_id,
                ):
                    continue
                resources_ready = all(
                    self.prototype_reserved_t(research_id, location_id, resource_id)
                    + 1e-9
                    >= required
                    for resource_id, required in prototype.resources.items()
                )
                if not resources_ready:
                    continue
                bundle_id = self._stage_bundle_id(
                    research_id, ResearchStage.PROTOTYPE, site
                )
                try:
                    allocated = execution_allocations.allocated(bundle_id)
                except KeyError:
                    allocated = 0.0
                if allocated + 1e-9 >= 1.0:
                    state.stage_progress = 1.0
            elif state.stage is ResearchStage.DEMONSTRATION:
                site = state.demonstration_execution_site
                demonstration = self.definitions[research_id].demonstration
                if site is None or demonstration is None:
                    continue
                location_id = site.operational_node_id
                snapshot = power_by_location[location_id]
                if self.demonstration_failures(
                    research_id,
                    location_id,
                    day,
                    snapshot,
                    site.surface_cell_id,
                ):
                    continue
                bundle_id = self._stage_bundle_id(
                    research_id, ResearchStage.DEMONSTRATION, site
                )
                try:
                    allocated = execution_allocations.allocated(bundle_id)
                except KeyError:
                    allocated = 0.0
                if allocated + 1e-9 >= 1.0:
                    state.stage_progress += 1.0

        # Generation is an execution output. It is stored only after Theory has
        # consumed the start-of-tick pool, so it cannot feed the same tick.
        generated = self.generation_rate(power_by_location, day)
        self.store_generated_points(
            generated, power_by_location=power_by_location, day=day
        )

    def settle_completions(self, day: int) -> None:
        """Advance completed stages only at the tick state-transition boundary."""
        for research_id in sorted(tuple(self.active), key=str):
            while research_id in self.active:
                state = self.active[research_id]
                definition = self.definitions[research_id]
                if state.paused:
                    break
                if state.stage is ResearchStage.THEORY:
                    complete = (
                        state.stage_progress + 1e-9 >= definition.research_point_cost
                    )
                elif state.stage is ResearchStage.PROTOTYPE:
                    complete = state.stage_progress + 1e-9 >= 1.0
                elif state.stage is ResearchStage.DEMONSTRATION:
                    spec = definition.demonstration
                    complete = (
                        spec is not None
                        and state.stage_progress + 1e-9 >= spec.days
                    )
                elif state.stage is ResearchStage.OPERATIONAL_EXPERIENCE:
                    complete = not self.operational_experience_blockers(research_id)
                else:
                    complete = False
                if not complete:
                    break
                self._advance_stage(research_id, day)
