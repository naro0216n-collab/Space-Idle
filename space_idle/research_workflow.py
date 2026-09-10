from __future__ import annotations

from .power import PowerSnapshot
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, SpatialNodeId
from .site import SiteRequirementFailure, evaluate_site_requirements
from .research_models import ResearchPhase, ResearchState


class ResearchWorkflowMixin:
    def start_blockers(
        self,
        research_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        definition = self.definitions[research_id]
        blockers: list[tuple[str, str]] = []
        if research_id in self.completed:
            blockers.append(("already_complete", "研究は完了済み"))
        if research_id in self.active:
            blockers.append(("already_active", "研究は進行中"))
        missing = sorted(definition.prerequisites - self.completed, key=str)
        if missing:
            blockers.append(("prerequisite", ",".join(str(item) for item in missing)))

        capacity = self.storage_capacity(power_by_location, day)
        if capacity + 1e-9 < definition.research_point_cost:
            blockers.append((
                "rp_storage_capacity",
                f"Research Point貯蔵容量不足: {capacity:g}/{definition.research_point_cost:g}",
            ))
        if self.stored_points + 1e-9 < definition.research_point_cost:
            blockers.append((
                "research_points",
                f"Research Point不足: {self.stored_points:g}/{definition.research_point_cost:g}",
            ))
        return tuple(blockers)

    def can_start(
        self,
        research_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> bool:
        return not self.start_blockers(research_id, day=day, power_by_location=power_by_location)

    def start(self, research_id: DefinitionId, *, day: int = 0) -> None:
        blockers = self.start_blockers(research_id, day=day)
        if blockers:
            raise ValueError("; ".join(detail for _code, detail in blockers))
        definition = self.definitions[research_id]
        self.stored_points = max(0.0, self.stored_points - definition.research_point_cost)
        if definition.prototype is not None:
            self.active[research_id] = ResearchState(research_id, ResearchPhase.PROTOTYPE)
        elif definition.demonstration is not None:
            self.active[research_id] = ResearchState(research_id, ResearchPhase.DEMONSTRATION)
        else:
            self.completed.add(research_id)

    def pause(self, research_id: DefinitionId) -> None:
        self.active[research_id].paused = True

    def resume(self, research_id: DefinitionId) -> None:
        self.active[research_id].paused = False

    def prototype_failures(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        if location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        definition = self.definitions[research_id]
        prototype = definition.prototype
        if prototype is None:
            raise ValueError("research has no prototype phase")
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            prototype.site_requirements,
            location_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
        )

    def set_prototype_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> None:
        state = self.active[research_id]
        if state.status != ResearchPhase.PROTOTYPE:
            raise ValueError("research is not awaiting a prototype")
        if state.paused:
            raise ValueError("research is paused")
        failures = self.prototype_failures(research_id, location_id, day)
        if failures:
            raise ValueError(
                "prototype site requirements not met: " + "; ".join(f.detail for f in failures)
            )
        state.prototype_location_id = location_id

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.status != ResearchPhase.PROTOTYPE:
                continue
            location_id = state.prototype_location_id
            if location_id is None:
                continue
            prototype = self.definitions[research_id].prototype
            if prototype is None:
                raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
            for resource_id, required_t in sorted(
                prototype.resources.items(), key=lambda row: str(row[0])
            ):
                if required_t <= 1e-9:
                    continue
                demands.append(ResourceDemand(
                    EntityId(f"demand.research:{research_id}:{resource_id}"),
                    "research",
                    EntityId(f"research:{research_id}"),
                    location_id,
                    resource_id,
                    required_t,
                    60,
                    None,
                    required_t,
                    True,
                ))
        return tuple(demands)

    def fund_prototype(self, research_id: DefinitionId, day: int = 0) -> None:
        state = self.active[research_id]
        definition = self.definitions[research_id]
        prototype = definition.prototype
        if state.status != ResearchPhase.PROTOTYPE or prototype is None:
            raise ValueError("research is not awaiting a prototype")
        if state.paused:
            raise ValueError("research is paused")
        location_id = state.prototype_location_id
        if location_id is None:
            raise ValueError("prototype site is not selected")
        failures = self.prototype_failures(research_id, location_id, day)
        if failures:
            raise ValueError(
                "prototype site requirements not met: " + "; ".join(f.detail for f in failures)
            )
        for resource_id, amount in prototype.resources.items():
            demand_id = EntityId(f"demand.research:{research_id}:{resource_id}")
            allocated = self.inventory.reserved_for(demand_id, location_id, resource_id)
            if allocated + 1e-9 < amount:
                raise ValueError(f"prototype resource shortfall: {resource_id}")
        for resource_id, amount in prototype.resources.items():
            demand_id = EntityId(f"demand.research:{research_id}:{resource_id}")
            self.inventory.consume_reserved(demand_id, location_id, resource_id, amount)
        if definition.demonstration is not None:
            state.status = ResearchPhase.DEMONSTRATION
            if not self.demonstration_failures(research_id, location_id, day):
                state.demonstration_location_id = location_id
        else:
            self._complete(research_id)

    def set_demonstration_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> None:
        state = self.active[research_id]
        if state.status != ResearchPhase.DEMONSTRATION:
            raise ValueError("research is not awaiting demonstration")
        if state.paused:
            raise ValueError("research is paused")
        failures = self.demonstration_failures(research_id, location_id, day)
        structural_failures = tuple(
            failure for failure in failures if failure.code != "capability:available"
        )
        if structural_failures:
            raise ValueError(
                "demonstration site requirements not met: "
                + "; ".join(f.detail for f in structural_failures)
            )
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
        demonstration = definition.demonstration
        if demonstration is None:
            raise ValueError("research has no demonstration phase")
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            demonstration.site_requirements,
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
