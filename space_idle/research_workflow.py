from __future__ import annotations

from .power import PowerSnapshot
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .resource_demand import ResourceDemand
from .service_capacity import ServiceCapacityRequest
from .shared import DefinitionId, EntityId, SpatialNodeId
from .site import SiteRequirementFailure, evaluate_site_requirements
from .research_models import ResearchStage, ResearchState


class ResearchWorkflowMixin:
    RESEARCH_EXECUTION_SERVICE = "research_execution"
    _TRANSIENT_SITE_BLOCKERS = frozenset({
        "manual_pause",
        "capability:active",
        "service_capacity:available",
    })

    @staticmethod
    def _project_owner_id(research_id: DefinitionId) -> EntityId:
        return EntityId(f"research:{research_id}")

    @staticmethod
    def _stage_service_request_id(
        research_id: DefinitionId,
        stage: ResearchStage,
        service_type: str,
        location_id: SpatialNodeId,
    ) -> EntityId:
        return EntityId(
            f"service.research:{stage.value}:{research_id}:{location_id}:{service_type}"
        )

    def _research_execution_supply_weights(
        self,
        day: int,
    ) -> tuple[tuple[SpatialNodeId, float], ...]:
        locations = sorted(
            self.facilities.environment.graph.operational_node_ids(), key=str
        )
        nominal: list[tuple[SpatialNodeId, float]] = []
        for location_id in locations:
            nominal_rate = self.facilities.nominal_service_capacity_at(
                location_id, self.RESEARCH_EXECUTION_SERVICE, day
            )
            if nominal_rate > 1e-12:
                nominal.append((location_id, nominal_rate))
        return tuple(nominal)

    def service_requests(
        self,
        day: int = 0,
    ) -> tuple[ServiceCapacityRequest, ...]:
        requests: list[ServiceCapacityRequest] = []
        theory_supply = self._research_execution_supply_weights(day)
        theory_supply_total = sum(rate for _location_id, rate in theory_supply)
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused:
                continue
            definition = self.definitions[research_id]
            if state.stage is ResearchStage.THEORY:
                remaining = max(0.0, definition.research_point_cost - state.stage_progress)
                if remaining <= 1e-12 or theory_supply_total <= 1e-12:
                    continue
                for location_id, weight in theory_supply:
                    requested = remaining * weight / theory_supply_total
                    requests.append(ServiceCapacityRequest(
                        self._stage_service_request_id(
                            research_id,
                            ResearchStage.THEORY,
                            self.RESEARCH_EXECUTION_SERVICE,
                            location_id,
                        ),
                        location_id,
                        self.RESEARCH_EXECUTION_SERVICE,
                        requested,
                        state.priority,
                        "research_project",
                        self._project_owner_id(research_id),
                        ResearchStage.THEORY.value,
                    ))
                continue

            if state.stage is ResearchStage.PROTOTYPE:
                location_id = state.prototype_operational_node_id
                spec = definition.prototype
            elif state.stage is ResearchStage.DEMONSTRATION:
                location_id = state.demonstration_operational_node_id
                spec = definition.demonstration
            else:
                continue
            if location_id is None or spec is None:
                continue
            for requirement in spec.site_requirements.service_capacity_requirements:
                requests.append(ServiceCapacityRequest(
                    self._stage_service_request_id(
                        research_id, state.stage, requirement.service_type, location_id
                    ),
                    location_id,
                    requirement.service_type,
                    requirement.minimum_rate,
                    state.priority,
                    "research_project",
                    self._project_owner_id(research_id),
                    state.stage.value,
                    minimum_rate=requirement.minimum_rate,
                    atomic=True,
                ))
        return tuple(requests)

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
        return tuple(blockers)

    def can_start(
        self,
        research_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> bool:
        return not self.start_blockers(
            research_id, day=day, power_by_location=power_by_location
        )

    def start(
        self, research_id: DefinitionId, *, day: int = 0, priority: int = 50
    ) -> None:
        blockers = self.start_blockers(research_id, day=day)
        if blockers:
            raise ValueError("; ".join(detail for _code, detail in blockers))
        definition = self.definitions[research_id]
        self.active[research_id] = ResearchState(
            research_id, definition.stages[0], priority=priority
        )

    def set_priority(self, research_id: DefinitionId, priority: int) -> None:
        if research_id not in self.active:
            raise ValueError("研究は進行中ではありません")
        self.active[research_id].priority = int(priority)

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
        if not self.facilities.environment.graph.has_operational_node(location_id):
            raise KeyError(location_id)
        prototype = self.definitions[research_id].prototype
        if prototype is None:
            raise ValueError("research has no prototype stage")
        snapshot = power or self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            prototype.site_requirements,
            location_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
        )

    @staticmethod
    def prototype_demand_id(
        research_id: DefinitionId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"demand.research:{research_id}:{resource_id}")

    @staticmethod
    def _prototype_staging_owner_id(research_id: DefinitionId) -> EntityId:
        return EntityId(f"research.prototype:{research_id}")

    def prototype_staged_t(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        resource_id: DefinitionId,
    ) -> float:
        return self.inventory.staged_for(
            self._prototype_staging_owner_id(research_id), location_id, resource_id
        )

    @staticmethod
    def prototype_claim_id(
        research_id: DefinitionId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"claim.research:{research_id}:{resource_id}")

    def _stage_prototype_allocations(
        self, state: ResearchState, allocations: ResourceAllocationPlan
    ) -> None:
        if (
            state.stage is not ResearchStage.PROTOTYPE
            or state.paused
            or state.prototype_operational_node_id is None
        ):
            return
        research_id = state.definition_id
        prototype = self.definitions[research_id].prototype
        if prototype is None:
            raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
        location_id = state.prototype_operational_node_id
        staging_owner = self._prototype_staging_owner_id(research_id)
        for resource_id, required_t in prototype.resources.items():
            staged = self.prototype_staged_t(research_id, location_id, resource_id)
            missing = max(0.0, required_t - staged)
            if missing <= 1e-12:
                continue
            try:
                allocated = allocations.allocated(
                    self.prototype_claim_id(research_id, resource_id)
                )
            except KeyError:
                allocated = 0.0
            amount = min(missing, max(0.0, allocated))
            if amount > 1e-12:
                self.inventory.stage_allocated(
                    staging_owner, location_id, resource_id, amount
                )

    def _restore_prototype_staging(
        self, research_id: DefinitionId, location_id: SpatialNodeId
    ) -> None:
        prototype = self.definitions[research_id].prototype
        if prototype is None:
            return
        staging_owner = self._prototype_staging_owner_id(research_id)
        for resource_id in prototype.resources:
            staged = self.prototype_staged_t(research_id, location_id, resource_id)
            if staged > 1e-12:
                self.inventory.unstage_to_stock(
                    staging_owner, location_id, resource_id, staged
                )

    def _consume_prototype_staging(self, research_id: DefinitionId) -> None:
        state = self.active[research_id]
        location_id = state.prototype_operational_node_id
        prototype = self.definitions[research_id].prototype
        if location_id is None or prototype is None:
            return
        staging_owner = self._prototype_staging_owner_id(research_id)
        for resource_id in prototype.resources:
            staged = self.prototype_staged_t(research_id, location_id, resource_id)
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    staging_owner, location_id, resource_id, staged
                )

    def set_prototype_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> None:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.PROTOTYPE:
            raise ValueError("研究は試作段階ではありません")
        structural = self._structural_site_blockers(
            self.prototype_site_blockers(research_id, location_id, day)
        )
        if structural:
            raise ValueError(
                "prototype site requirements not met: "
                + "; ".join(detail for _code, detail in structural)
            )
        previous = state.prototype_operational_node_id
        if previous is not None and previous != location_id:
            self._restore_prototype_staging(research_id, previous)
        state.prototype_operational_node_id = location_id

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.stage is not ResearchStage.PROTOTYPE:
                continue
            location_id = state.prototype_operational_node_id
            if location_id is None:
                continue
            prototype = self.definitions[research_id].prototype
            if prototype is None:
                raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
            for resource_id, required_t in sorted(
                prototype.resources.items(), key=lambda row: str(row[0])
            ):
                remaining = max(
                    0.0,
                    required_t
                    - self.prototype_staged_t(research_id, location_id, resource_id),
                )
                if remaining <= 1e-9:
                    continue
                demands.append(ResourceDemand(
                    self.prototype_demand_id(research_id, resource_id),
                    "research",
                    self._project_owner_id(research_id),
                    location_id,
                    resource_id,
                    remaining,
                    state.priority,
                ))
        return tuple(demands)

    def resource_claims(self, day: int = 0) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.stage is not ResearchStage.PROTOTYPE:
                continue
            location_id = state.prototype_operational_node_id
            if location_id is None:
                continue
            prototype = self.definitions[research_id].prototype
            if prototype is None:
                raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
            for resource_id, required_t in sorted(
                prototype.resources.items(), key=lambda row: str(row[0])
            ):
                staged = self.prototype_staged_t(research_id, location_id, resource_id)
                remaining = max(0.0, required_t - staged)
                if remaining <= 1e-9:
                    continue
                claims.append(ResourceClaim(
                    self.prototype_claim_id(research_id, resource_id),
                    location_id,
                    resource_id,
                    remaining,
                    state.priority,
                    "research",
                    self._project_owner_id(research_id),
                    "prototype",
                    demand_id=self.prototype_demand_id(research_id, resource_id),
                ))
        return tuple(claims)

    def set_demonstration_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
    ) -> None:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.DEMONSTRATION:
            raise ValueError("研究は実証段階ではありません")
        structural = self._structural_site_blockers(
            self.demonstration_site_blockers(research_id, location_id, day)
        )
        if structural:
            raise ValueError(
                "demonstration site requirements not met: "
                + "; ".join(detail for _code, detail in structural)
            )
        state.demonstration_operational_node_id = location_id
        state.stage_progress = 0.0

    def demonstration_failures(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        demonstration = self.definitions[research_id].demonstration
        if demonstration is None:
            raise ValueError("research has no demonstration stage")
        snapshot = power or self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            demonstration.site_requirements,
            location_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
        )

    def prototype_site_blockers(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.PROTOTYPE:
            return (("prototype_stage", "研究は試作段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.prototype_failures(research_id, location_id, day)
        )
        return tuple(blockers)

    def can_select_prototype_site(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0
    ) -> bool:
        state = self.active.get(research_id)
        return (
            state is not None
            and state.stage is ResearchStage.PROTOTYPE
            and not self._structural_site_blockers(
                self.prototype_site_blockers(research_id, location_id, day)
            )
        )

    def demonstration_site_blockers(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.DEMONSTRATION:
            return (("demonstration_stage", "研究は実証段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.demonstration_failures(research_id, location_id, day)
        )
        return tuple(blockers)

    def can_select_demonstration_site(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0
    ) -> bool:
        state = self.active.get(research_id)
        return (
            state is not None
            and state.stage is ResearchStage.DEMONSTRATION
            and not self._structural_site_blockers(
                self.demonstration_site_blockers(research_id, location_id, day)
            )
        )

    @classmethod
    def _structural_site_blockers(
        cls, blockers: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            blocker for blocker in blockers if blocker[0] not in cls._TRANSIENT_SITE_BLOCKERS
        )

    def prototype_blockers(
        self, research_id: DefinitionId, day: int = 0
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.PROTOTYPE:
            return (("prototype_stage", "研究は試作段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        location_id = state.prototype_operational_node_id
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
        for resource_id, required in sorted(
            prototype.resources.items(), key=lambda row: str(row[0])
        ):
            staged = self.prototype_staged_t(research_id, location_id, resource_id)
            if staged + 1e-9 < required:
                blockers.append((
                    "prototype_resource",
                    f"prototype resource shortfall: {resource_id}: {staged:g}/{required:g} t",
                ))
        return tuple(blockers)

    def demonstration_blockers(
        self, research_id: DefinitionId, day: int = 0
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.DEMONSTRATION:
            return (("demonstration_stage", "研究は実証段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        location_id = state.demonstration_operational_node_id
        if location_id is None:
            blockers.append(("demonstration_site", "実証地点を選択してください"))
            return tuple(blockers)
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.demonstration_failures(research_id, location_id, day)
        )
        return tuple(blockers)

    def operational_experience_blockers(
        self, research_id: DefinitionId
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.OPERATIONAL_EXPERIENCE:
            return (("operational_experience_stage", "研究は運用経験段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        spec = self.definitions[research_id].operational_experience
        if spec is None:
            raise RuntimeError(f"operational experience state has no definition: {research_id}")
        for category, required in sorted(spec.requirements.items()):
            current = self.knowledge_state.value(category)
            if current + 1e-9 < required:
                blockers.append((
                    "operational_experience",
                    f"{category}: {current:g}/{required:g}",
                ))
        return tuple(blockers)

    def theory_remaining(self, research_id: DefinitionId) -> float:
        state = self.active.get(research_id)
        definition = self.definitions[research_id]
        if state is None:
            return 0.0 if research_id in self.completed else definition.research_point_cost
        stage_index = definition.stages.index(state.stage)
        theory_index = (
            definition.stages.index(ResearchStage.THEORY)
            if ResearchStage.THEORY in definition.stages
            else None
        )
        if theory_index is None:
            return 0.0
        if stage_index > theory_index:
            return 0.0
        if state.stage is ResearchStage.THEORY:
            return max(0.0, definition.research_point_cost - state.stage_progress)
        return definition.research_point_cost

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
        if state.paused:
            return (("manual_pause", "研究が手動停止中"),)
        if state.stage is ResearchStage.THEORY:
            blockers: list[tuple[str, str]] = []
            if self.stored_points <= 1e-12:
                blockers.append(("research_points", "Research Point不足"))
            if not self._research_execution_supply_weights(day):
                blockers.append(("research_execution", "Research execution能力なし"))
            return tuple(blockers)
        if state.stage is ResearchStage.PROTOTYPE:
            return self.prototype_blockers(research_id, day)
        if state.stage is ResearchStage.DEMONSTRATION:
            return self.demonstration_blockers(research_id, day)
        if state.stage is ResearchStage.OPERATIONAL_EXPERIENCE:
            return self.operational_experience_blockers(research_id)
        return ()


    def allocation_blockers(
        self,
        research_id: DefinitionId,
        service_allocations,
        point_requests: dict[DefinitionId, float] | None = None,
        point_allocations: dict[DefinitionId, float] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.paused:
            return ()
        blockers: list[tuple[str, str]] = []
        owner_id = self._project_owner_id(research_id)
        stage_requests = tuple(
            request
            for request in service_allocations.requests
            if request.owner_kind == "research_project"
            and request.owner_id == owner_id
            and request.purpose == state.stage.value
        )
        allocations_by_id = {row.request_id: row.allocated_rate for row in service_allocations.allocations}
        for request in stage_requests:
            allocated = allocations_by_id.get(request.id, 0.0)
            if allocated + 1e-9 < request.requested_rate:
                blockers.append((
                    "service_capacity:allocation",
                    f"{request.service_type}: {allocated:g}/{request.requested_rate:g}",
                ))
        if state.stage is ResearchStage.THEORY:
            requested = (point_requests or {}).get(research_id, 0.0)
            allocated = (point_allocations or {}).get(research_id, 0.0)
            if requested > 1e-12 and allocated + 1e-9 < requested:
                blockers.append((
                    "research_points:allocation",
                    f"Research Point: {allocated:g}/{requested:g}",
                ))
        return tuple(blockers)

    def _complete(self, research_id: DefinitionId) -> None:
        self.completed.add(research_id)
        self.active.pop(research_id, None)

    def _advance_stage(self, research_id: DefinitionId) -> None:
        state = self.active[research_id]
        definition = self.definitions[research_id]
        index = definition.stages.index(state.stage)
        if state.stage is ResearchStage.PROTOTYPE:
            self._consume_prototype_staging(research_id)
        if index + 1 >= len(definition.stages):
            self._complete(research_id)
            return
        state.stage = definition.stages[index + 1]
        state.stage_progress = 0.0
        if state.stage is ResearchStage.DEMONSTRATION:
            state.demonstration_operational_node_id = None
