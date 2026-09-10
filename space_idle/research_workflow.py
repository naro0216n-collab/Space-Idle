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

    def pause_blockers(self, research_id: DefinitionId) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None:
            return (("not_active", "研究は進行中ではありません"),)
        if state.paused:
            return (("already_paused", "研究は既に停止中です"),)
        return ()

    def can_pause(self, research_id: DefinitionId) -> bool:
        return not self.pause_blockers(research_id)

    def resume_blockers(self, research_id: DefinitionId) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None:
            return (("not_active", "研究は進行中ではありません"),)
        if not state.paused:
            return (("not_paused", "研究は停止中ではありません"),)
        return ()

    def can_resume(self, research_id: DefinitionId) -> bool:
        return not self.resume_blockers(research_id)

    def pause(self, research_id: DefinitionId) -> None:
        blockers = self.pause_blockers(research_id)
        if blockers:
            raise ValueError("; ".join(detail for _code, detail in blockers))
        self.active[research_id].paused = True

    def resume(self, research_id: DefinitionId) -> None:
        blockers = self.resume_blockers(research_id)
        if blockers:
            raise ValueError("; ".join(detail for _code, detail in blockers))
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
        blockers = self.prototype_site_blockers(research_id, location_id, day)
        if blockers:
            raise ValueError(
                "prototype site requirements not met: "
                + "; ".join(detail for _code, detail in blockers)
            )
        self.active[research_id].prototype_location_id = location_id

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
        blockers = self.prototype_blockers(research_id, day)
        if blockers:
            raise ValueError("; ".join(detail for _code, detail in blockers))
        state = self.active[research_id]
        definition = self.definitions[research_id]
        prototype = definition.prototype
        if prototype is None or state.prototype_location_id is None:
            raise RuntimeError(f"invalid prototype state: {research_id}")
        location_id = state.prototype_location_id
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
        blockers = self.demonstration_site_blockers(research_id, location_id, day)
        structural_blockers = tuple(
            blocker for blocker in blockers if blocker[0] != "capability:available"
        )
        if structural_blockers:
            raise ValueError(
                "demonstration site requirements not met: "
                + "; ".join(detail for _code, detail in structural_blockers)
            )
        state = self.active[research_id]
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

    def prototype_site_blockers(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        blockers: list[tuple[str, str]] = []
        if state is None or state.status != ResearchPhase.PROTOTYPE:
            blockers.append(("prototype_phase", "研究は試作段階ではありません"))
            return tuple(blockers)
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.prototype_failures(research_id, location_id, day)
        )
        return tuple(blockers)

    def can_select_prototype_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> bool:
        return not self.prototype_site_blockers(research_id, location_id, day)

    def demonstration_site_blockers(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        blockers: list[tuple[str, str]] = []
        if state is None or state.status != ResearchPhase.DEMONSTRATION:
            blockers.append(("demonstration_phase", "研究は実証段階ではありません"))
            return tuple(blockers)
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.demonstration_failures(research_id, location_id, day)
        )
        return tuple(blockers)

    def can_select_demonstration_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> bool:
        return not any(
            code != "capability:available"
            for code, _detail in self.demonstration_site_blockers(research_id, location_id, day)
        )

    def prototype_blockers(
        self,
        research_id: DefinitionId,
        day: int = 0,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        blockers: list[tuple[str, str]] = []
        if state is None or state.status != ResearchPhase.PROTOTYPE:
            return (("prototype_phase", "研究は試作段階ではありません"),)
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        location_id = state.prototype_location_id
        if location_id is None:
            blockers.append(("prototype_site", "試作地点を選択してください"))
            return tuple(blockers)
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.prototype_failures(research_id, location_id, day)
        )
        prototype = self.definitions[research_id].prototype
        if prototype is None:
            raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
        for resource_id, required in sorted(prototype.resources.items(), key=lambda row: str(row[0])):
            demand_id = EntityId(f"demand.research:{research_id}:{resource_id}")
            allocated = self.inventory.reserved_for(demand_id, location_id, resource_id)
            if allocated + 1e-9 < required:
                blockers.append((
                    "prototype_resource",
                    f"prototype resource shortfall: {resource_id}: {allocated:g}/{required:g} t",
                ))
        return tuple(blockers)

    def can_fund_prototype(self, research_id: DefinitionId, day: int = 0) -> bool:
        return not self.prototype_blockers(research_id, day)

    def demonstration_blockers(
        self,
        research_id: DefinitionId,
        day: int = 0,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        blockers: list[tuple[str, str]] = []
        if state is None or state.status != ResearchPhase.DEMONSTRATION:
            return (("demonstration_phase", "研究は実証段階ではありません"),)
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        location_id = state.demonstration_location_id
        if location_id is None:
            blockers.append(("demonstration_site", "実証地点を選択してください"))
            return tuple(blockers)
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.demonstration_failures(research_id, location_id, day)
        )
        return tuple(blockers)

    def current_blockers(
        self,
        research_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None:
            if research_id in self.completed:
                return ()
            return self.start_blockers(
                research_id, day=day, power_by_location=power_by_location
            )
        if state.status == ResearchPhase.PROTOTYPE:
            return self.prototype_blockers(research_id, day)
        if state.status == ResearchPhase.DEMONSTRATION:
            return self.demonstration_blockers(research_id, day)
        return ()

    def _complete(self, research_id: DefinitionId) -> None:
        self.completed.add(research_id)
        state = self.active[research_id]
        state.status = ResearchPhase.COMPLETE
        self.active.pop(research_id, None)
