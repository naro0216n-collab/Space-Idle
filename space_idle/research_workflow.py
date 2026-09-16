from __future__ import annotations

from .power import PowerSnapshot
from .execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    PoolRequirement,
    ReservationAcquisitionRequirement,
    ServiceCapacityRequirement as ExecutionServiceRequirement,
)
from .service_capacity import ServiceCapacityScope
from .supply import SupplyRequirement
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .site import (
    SiteRequirementFailure,
    SiteRequirements,
    evaluate_site_requirements,
    requires_surface_cell_context,
)
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .research_models import ResearchExecutionSite, ResearchStage, ResearchState


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

    def _execution_site_failures(
        self,
        requirements: SiteRequirements,
        site: ResearchExecutionSite,
        day: int,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        graph = self.facilities.environment.graph
        location_id = site.operational_node_id
        if not graph.has_operational_node(location_id):
            raise KeyError(location_id)

        failures: list[SiteRequirementFailure] = []
        local_site_required = (
            location_id in graph.locations and requires_surface_cell_context(requirements)
        )
        if site.surface_cell_id is None:
            if local_site_required:
                failures.append(
                    SiteRequirementFailure(
                        "surface_cell:required", "局所環境を評価するSurface Cellが必要"
                    )
                )
        else:
            location = graph.locations.get(location_id)
            if location is None:
                failures.append(
                    SiteRequirementFailure(
                        "surface_cell:non_surface_node", "Surface CellはSurface Locationでのみ指定可能"
                    )
                )
            elif site.surface_cell_id not in location.developed_cell_ids:
                failures.append(
                    SiteRequirementFailure(
                        "surface_cell:developed", "実行地点は所属Locationのdeveloped cellである必要がある"
                    )
                )
            elif not local_site_required:
                failures.append(
                    SiteRequirementFailure(
                        "surface_cell:not_required", "この研究段階はCell-local execution siteを要求しない"
                    )
                )

        context_id = site.surface_cell_id or location_id
        if not failures:
            failures.extend(
                evaluate_site_requirements(
                    requirements,
                    location_id,
                    day,
                    self.facilities.environment,
                    self.facilities,
                    power,
                    environment_context_id=context_id,
                )
            )
        return tuple(failures)

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
        self, research_id: DefinitionId, *, day: int = 0, priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    ) -> None:
        blockers = self.start_blockers(research_id, day=day)
        if blockers:
            raise ValueError("; ".join(detail for _code, detail in blockers))
        definition = self.definitions[research_id]
        self.active[research_id] = ResearchState(
            research_id, definition.stages[0], priority=priority, stage_started_day=day
        )

    def set_priority(self, research_id: DefinitionId, priority: ActivityPriority) -> None:
        if research_id not in self.active:
            raise ValueError("研究は進行中ではありません")
        self.active[research_id].priority = ActivityPriority(priority)

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
        surface_cell_id: SurfaceCellId | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        prototype = self.definitions[research_id].prototype
        if prototype is None:
            raise ValueError("research has no prototype stage")
        return self._execution_site_failures(
            prototype.site_requirements,
            ResearchExecutionSite(location_id, surface_cell_id),
            day,
            power,
        )

    @staticmethod
    def prototype_requirement_id(
        research_id: DefinitionId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"requirement.research:{research_id}:{resource_id}")

    @staticmethod
    def _prototype_reservation_owner_id(research_id: DefinitionId) -> EntityId:
        return EntityId(f"research.prototype:{research_id}")

    @staticmethod
    def prototype_reservation_requirement_id(
        research_id: DefinitionId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"reservation.research:{research_id}:{resource_id}")

    def prototype_reserved_t(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        resource_id: DefinitionId,
    ) -> float:
        return self.inventory.reserved_for(
            self._prototype_reservation_owner_id(research_id), location_id, resource_id
        )

    def _release_prototype_reservations(self, research_id: DefinitionId) -> None:
        self.inventory.release_reservation(self._prototype_reservation_owner_id(research_id))

    def _consume_prototype_reservations(self, research_id: DefinitionId) -> None:
        state = self.active[research_id]
        site = state.prototype_execution_site
        location_id = None if site is None else site.operational_node_id
        prototype = self.definitions[research_id].prototype
        if location_id is None or prototype is None:
            return
        owner_id = self._prototype_reservation_owner_id(research_id)
        for resource_id, required in prototype.resources.items():
            if required > 1e-12:
                self.inventory.consume_reserved(owner_id, location_id, resource_id, required)

    def set_prototype_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> None:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.PROTOTYPE:
            raise ValueError("研究は試作段階ではありません")
        structural = self._structural_site_blockers(
            self.prototype_site_blockers(
                research_id, location_id, day, surface_cell_id=surface_cell_id
            )
        )
        if structural:
            raise ValueError(
                "prototype site requirements not met: "
                + "; ".join(detail for _code, detail in structural)
            )
        previous = state.prototype_execution_site
        site = ResearchExecutionSite(location_id, surface_cell_id)
        if previous is not None and previous != site:
            self._release_prototype_reservations(research_id)
        state.prototype_execution_site = site

    def supplys(self, day: int = 0) -> tuple[SupplyRequirement, ...]:
        requirements: list[SupplyRequirement] = []
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.stage is not ResearchStage.PROTOTYPE:
                continue
            site = state.prototype_execution_site
            location_id = None if site is None else site.operational_node_id
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
                    required_t - self.prototype_reserved_t(
                        research_id, location_id, resource_id
                    ),
                )
                if remaining <= 1e-9:
                    continue
                requirements.append(SupplyRequirement(
                    self.prototype_requirement_id(research_id, resource_id),
                    "research",
                    self._project_owner_id(research_id),
                    location_id,
                    resource_id,
                    remaining,
                    state.priority,
                ))
        return tuple(requirements)

    def reservation_acquisition_requirements(
        self, day: int = 0
    ) -> tuple[ReservationAcquisitionRequirement, ...]:
        del day
        requirements: list[ReservationAcquisitionRequirement] = []
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused or state.stage is not ResearchStage.PROTOTYPE:
                continue
            site = state.prototype_execution_site
            location_id = None if site is None else site.operational_node_id
            if location_id is None:
                continue
            prototype = self.definitions[research_id].prototype
            if prototype is None:
                raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
            owner_id = self._prototype_reservation_owner_id(research_id)
            for resource_id, required_t in sorted(prototype.resources.items(), key=lambda row: str(row[0])):
                missing = max(0.0, required_t - self.prototype_reserved_t(research_id, location_id, resource_id))
                if missing <= 1e-9:
                    continue
                requirements.append(ReservationAcquisitionRequirement(
                    self.prototype_reservation_requirement_id(research_id, resource_id),
                    owner_id,
                    location_id,
                    resource_id,
                    missing,
                    state.priority,
                    "research_prototype",
                ))
        return tuple(requirements)

    @staticmethod
    def _theory_bundle_id(research_id: DefinitionId) -> EntityId:
        return EntityId(f"execution.research:theory:{research_id}")

    @staticmethod
    def _stage_bundle_id(
        research_id: DefinitionId, stage: ResearchStage, site: ResearchExecutionSite
    ) -> EntityId:
        suffix = (
            str(site.operational_node_id)
            if site.surface_cell_id is None
            else f"{site.operational_node_id}:{site.surface_cell_id}"
        )
        return EntityId(f"execution.research:{stage.value}:{research_id}:{suffix}")

    def execution_requirement_bundles(
        self, day: int = 0
    ) -> tuple[ExecutionRequirementBundle, ...]:
        bundles: list[ExecutionRequirementBundle] = []
        for research_id, state in sorted(self.active.items(), key=lambda row: str(row[0])):
            if state.paused:
                continue
            definition = self.definitions[research_id]
            if state.stage is ResearchStage.THEORY:
                remaining = max(0.0, definition.research_point_cost - state.stage_progress)
                if remaining <= 1e-12:
                    continue
                bundles.append(ExecutionRequirementBundle(
                    self._theory_bundle_id(research_id),
                    "research_project",
                    self._project_owner_id(research_id),
                    ResearchStage.THEORY.value,
                    None,
                    remaining,
                    state.priority,
                    (
                        ExecutionServiceRequirement(
                            self.RESEARCH_EXECUTION_SERVICE,
                            1.0,
                            scope=ServiceCapacityScope.ORGANIZATION,
                        ),
                        PoolRequirement("research_points", 1.0, "organization"),
                    ),
                ))
                continue

            if state.stage is ResearchStage.PROTOTYPE:
                site = state.prototype_execution_site
                spec = definition.prototype
                if site is None or spec is None:
                    continue
                location_id = site.operational_node_id
                if self._structural_site_blockers(
                    self.prototype_site_blockers(
                        research_id,
                        location_id,
                        day,
                        surface_cell_id=site.surface_cell_id,
                    )
                ):
                    continue
                resources_ready = all(
                    self.prototype_reserved_t(research_id, location_id, resource_id) + 1e-9 >= required
                    for resource_id, required in spec.resources.items()
                )
                if not resources_ready:
                    continue
            elif state.stage is ResearchStage.DEMONSTRATION:
                site = state.demonstration_execution_site
                spec = definition.demonstration
                if site is None or spec is None:
                    continue
                location_id = site.operational_node_id
                if self._structural_site_blockers(
                    self.demonstration_site_blockers(
                        research_id,
                        location_id,
                        day,
                        surface_cell_id=site.surface_cell_id,
                    )
                ):
                    continue
            else:
                continue

            requirements = tuple(
                ExecutionServiceRequirement(req.service_type, req.minimum_rate)
                for req in spec.site_requirements.service_capacity_requirements
                if req.minimum_rate > 1e-12
            )
            bundles.append(ExecutionRequirementBundle(
                self._stage_bundle_id(research_id, state.stage, site),
                "research_project",
                self._project_owner_id(research_id),
                state.stage.value,
                location_id,
                1.0,
                state.priority,
                requirements,
                atomic=True,
                wait_started_day=state.stage_started_day,
            ))
        return tuple(bundles)

    def set_demonstration_site(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> None:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.DEMONSTRATION:
            raise ValueError("研究は実証段階ではありません")
        structural = self._structural_site_blockers(
            self.demonstration_site_blockers(
                research_id, location_id, day, surface_cell_id=surface_cell_id
            )
        )
        if structural:
            raise ValueError(
                "demonstration site requirements not met: "
                + "; ".join(detail for _code, detail in structural)
            )
        state.demonstration_execution_site = ResearchExecutionSite(
            location_id, surface_cell_id
        )
        state.stage_progress = 0.0

    def demonstration_failures(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        demonstration = self.definitions[research_id].demonstration
        if demonstration is None:
            raise ValueError("research has no demonstration stage")
        return self._execution_site_failures(
            demonstration.site_requirements,
            ResearchExecutionSite(location_id, surface_cell_id),
            day,
            power,
        )

    def prototype_site_blockers(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.PROTOTYPE:
            return (("prototype_stage", "研究は試作段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.prototype_failures(
                research_id, location_id, day, power, surface_cell_id
            )
        )
        return tuple(blockers)

    def can_select_prototype_site(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> bool:
        state = self.active.get(research_id)
        return (
            state is not None
            and state.stage is ResearchStage.PROTOTYPE
            and not self._structural_site_blockers(
                self.prototype_site_blockers(
                    research_id, location_id, day, surface_cell_id=surface_cell_id
                )
            )
        )

    def demonstration_site_blockers(
        self,
        research_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.DEMONSTRATION:
            return (("demonstration_stage", "研究は実証段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.demonstration_failures(
                research_id, location_id, day, power, surface_cell_id
            )
        )
        return tuple(blockers)

    def can_select_demonstration_site(
        self, research_id: DefinitionId, location_id: SpatialNodeId, day: int = 0,
        surface_cell_id: SurfaceCellId | None = None,
    ) -> bool:
        state = self.active.get(research_id)
        return (
            state is not None
            and state.stage is ResearchStage.DEMONSTRATION
            and not self._structural_site_blockers(
                self.demonstration_site_blockers(
                    research_id, location_id, day, surface_cell_id=surface_cell_id
                )
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
        self,
        research_id: DefinitionId,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.PROTOTYPE:
            return (("prototype_stage", "研究は試作段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        site = state.prototype_execution_site
        if site is None:
            blockers.append(("prototype_site", "試作地点を選択してください"))
            return tuple(blockers)
        location_id = site.operational_node_id
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.prototype_failures(
                research_id,
                location_id,
                day,
                None if power_by_location is None else power_by_location.get(location_id),
                site.surface_cell_id,
            )
        )
        prototype = self.definitions[research_id].prototype
        if prototype is None:
            raise RuntimeError(f"prototype state has no prototype definition: {research_id}")
        for resource_id, required in sorted(
            prototype.resources.items(), key=lambda row: str(row[0])
        ):
            reserved = self.prototype_reserved_t(research_id, location_id, resource_id)
            if reserved + 1e-9 < required:
                blockers.append((
                    "prototype_resource",
                    f"prototype resource shortfall: {resource_id}: {reserved:g}/{required:g} t",
                ))
        return tuple(blockers)

    def demonstration_blockers(
        self,
        research_id: DefinitionId,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.stage is not ResearchStage.DEMONSTRATION:
            return (("demonstration_stage", "研究は実証段階ではありません"),)
        blockers: list[tuple[str, str]] = []
        if state.paused:
            blockers.append(("manual_pause", "研究が手動停止中"))
        site = state.demonstration_execution_site
        if site is None:
            blockers.append(("demonstration_site", "実証地点を選択してください"))
            return tuple(blockers)
        location_id = site.operational_node_id
        blockers.extend(
            (failure.code, failure.detail)
            for failure in self.demonstration_failures(
                research_id,
                location_id,
                day,
                None if power_by_location is None else power_by_location.get(location_id),
                site.surface_cell_id,
            )
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
            return tuple(blockers)
        if state.stage is ResearchStage.PROTOTYPE:
            return self.prototype_blockers(
                research_id, day, power_by_location=power_by_location
            )
        if state.stage is ResearchStage.DEMONSTRATION:
            return self.demonstration_blockers(
                research_id, day, power_by_location=power_by_location
            )
        if state.stage is ResearchStage.OPERATIONAL_EXPERIENCE:
            return self.operational_experience_blockers(research_id)
        return ()


    def allocation_blockers(
        self,
        research_id: DefinitionId,
        execution_allocations: ExecutionAllocationPlan,
    ) -> tuple[tuple[str, str], ...]:
        state = self.active.get(research_id)
        if state is None or state.paused:
            return ()
        owner_id = self._project_owner_id(research_id)
        blockers: list[tuple[str, str]] = []
        for allocation in execution_allocations.allocations_for_owner(
            "research_project", owner_id
        ):
            bundle = execution_allocations.bundle(allocation.bundle_id)
            if bundle.purpose != state.stage.value or allocation.unmet_execution <= 1e-9:
                continue
            for constraint in allocation.limiting_constraints:
                if constraint.kind == "pool" and constraint.name == "research_points":
                    code = "research_points:allocation"
                else:
                    code = f"{constraint.kind}:allocation"
                detail = (
                    f"{constraint.name}: {allocation.allocated_execution:g}/"
                    f"{allocation.requested_execution:g}"
                )
                row = (code, detail)
                if row not in blockers:
                    blockers.append(row)
        return tuple(blockers)

    def _complete(self, research_id: DefinitionId) -> None:
        self.completed.add(research_id)
        self.active.pop(research_id, None)

    def _advance_stage(self, research_id: DefinitionId, day: int) -> None:
        state = self.active[research_id]
        definition = self.definitions[research_id]
        index = definition.stages.index(state.stage)
        if state.stage is ResearchStage.PROTOTYPE:
            self._consume_prototype_reservations(research_id)
        if index + 1 >= len(definition.stages):
            self._complete(research_id)
            return
        state.stage = definition.stages[index + 1]
        state.stage_progress = 0.0
        state.stage_started_day = day
        if state.stage is ResearchStage.DEMONSTRATION:
            state.demonstration_execution_site = None
