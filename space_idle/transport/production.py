from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..power import PowerSnapshot
from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from ..resource_claim import ResourceAllocationPlan, ResourceClaim
from ..supply import SupplyRequirement
from ..service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityRequest
from ..shared import DefinitionId, EntityId, SpatialNodeId
from ..site import SiteRequirementFailure, evaluate_site_requirements


class VehicleProductionPhase(str, Enum):
    AWAITING_INPUTS = "awaiting_inputs"
    BUILDING = "building"
    COMPLETE = "complete"


@dataclass
class VehicleProductionState:
    id: EntityId
    vehicle_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    progress_days: float = 0.0
    phase: VehicleProductionPhase = VehicleProductionPhase.AWAITING_INPUTS
    paused: bool = False
    completed_units: int = 0
    created_day: int = 0

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.progress_days < -1e-9:
            raise ValueError("vehicle production progress must be non-negative")


class VehicleProductionMixin:
    """Vehicle construction lifecycle owned by the Transport/Vehicle Domain."""

    def plan_vehicle_production(
        self,
        vehicle_definition_id: DefinitionId,
        location_id: SpatialNodeId,
        *,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        day: int = 0,
    ) -> EntityId:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if not self.facilities.environment.graph.has_operational_node(location_id):
            raise KeyError(location_id)
        definition = self.vehicle_defs[vehicle_definition_id]
        production = definition.production
        if production.service_type is None or production.days <= 1e-12:
            raise ValueError("vehicle has no time-based production definition")
        if not production.resources:
            raise ValueError("vehicle production requires physical resource inputs")

        failures = self.vehicle_production_plan_failures(
            vehicle_definition_id, location_id, day=day
        )
        if failures:
            raise ValueError(
                "vehicle production site requirements not met: "
                + "; ".join(failure.detail for failure in failures)
            )

        self._vehicle_production_counter += 1
        project_id = EntityId(f"vehicle_production.{self._vehicle_production_counter}")
        self.vehicle_production_projects[project_id] = VehicleProductionState(
            project_id,
            vehicle_definition_id,
            location_id,
            priority,
            created_day=day,
        )
        return project_id

    def pause_vehicle_production(self, project_id: EntityId) -> None:
        state = self.vehicle_production_projects[project_id]
        if state.phase is VehicleProductionPhase.COMPLETE:
            raise ValueError("completed vehicle production cannot be paused")
        state.paused = True

    def resume_vehicle_production(self, project_id: EntityId) -> None:
        state = self.vehicle_production_projects[project_id]
        if state.phase is VehicleProductionPhase.COMPLETE:
            raise ValueError("completed vehicle production cannot be resumed")
        state.paused = False

    def vehicle_production_priority_editable(self, project_id: EntityId) -> bool:
        return (
            self.vehicle_production_projects[project_id].phase
            is VehicleProductionPhase.AWAITING_INPUTS
        )

    def set_vehicle_production_settings(
        self,
        project_id: EntityId,
        *,
        priority: ActivityPriority | None = None,
    ) -> None:
        state = self.vehicle_production_projects[project_id]
        if priority is not None:
            if not self.vehicle_production_priority_editable(project_id):
                raise ValueError(
                    "vehicle production priority can only change before inputs are consumed"
                )
            state.priority = ActivityPriority(priority)

    def vehicle_production_plan_failures(
        self,
        vehicle_definition_id: DefinitionId,
        location_id: SpatialNodeId,
        *,
        day: int = 0,
    ) -> tuple[SiteRequirementFailure, ...]:
        return tuple(
            failure
            for failure in self.vehicle_production_site_failures(
                vehicle_definition_id, location_id, day=day
            )
            if not failure.code.startswith("service:enabled")
        )

    def vehicle_production_site_failures(
        self,
        vehicle_definition_id: DefinitionId,
        location_id: SpatialNodeId,
        *,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        definition = self.vehicle_defs[vehicle_definition_id]
        production = definition.production
        failures = list(
            evaluate_site_requirements(
                production.site_requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
                power,
            )
        )
        if production.service_type is not None:
            enabled = (
                self.facilities.nominal_service_capacity_at(
                    location_id, production.service_type, day
                )
                if power is None
                else self.facilities.enabled_service_capacity_at(
                    location_id, production.service_type, power, day
                )
            )
            if enabled <= 1e-12:
                failures.append(
                    SiteRequirementFailure(
                        "service:enabled",
                        f"{production.service_type}:{enabled:g}/positive",
                    )
                )
        return tuple(failures)

    @staticmethod
    def _vehicle_production_demand_id(
        project_id: EntityId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"demand.{project_id}:{resource_id}")

    @staticmethod
    def _vehicle_production_claim_id(
        project_id: EntityId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"claim.vehicle_production:{project_id}:{resource_id}")

    @staticmethod
    def _vehicle_production_staging_owner_id(project_id: EntityId) -> EntityId:
        return EntityId(f"vehicle_production.materials:{project_id}")

    def _vehicle_production_staged_t(
        self, state: VehicleProductionState, resource_id: DefinitionId
    ) -> float:
        return self.inventory.staged_for(
            self._vehicle_production_staging_owner_id(state.id),
            state.operational_node_id,
            resource_id,
        )

    def _stage_vehicle_production_allocations(
        self, state: VehicleProductionState, allocations: ResourceAllocationPlan
    ) -> None:
        if state.phase is not VehicleProductionPhase.AWAITING_INPUTS:
            return
        definition = self.vehicle_defs[state.vehicle_definition_id]
        staging_owner = self._vehicle_production_staging_owner_id(state.id)
        for resource_id, required_t in definition.production.resources:
            if required_t <= 1e-12:
                continue
            staged = self._vehicle_production_staged_t(state, resource_id)
            missing = max(0.0, required_t - staged)
            if missing <= 1e-12:
                continue
            try:
                allocated = allocations.allocated(
                    self._vehicle_production_claim_id(state.id, resource_id)
                )
            except KeyError:
                allocated = 0.0
            amount = min(missing, max(0.0, allocated))
            if amount <= 1e-12:
                continue
            self.inventory.stage_allocated(
                staging_owner, state.operational_node_id, resource_id, amount
            )

    def _consume_staged_vehicle_production_inputs(
        self, state: VehicleProductionState
    ) -> None:
        definition = self.vehicle_defs[state.vehicle_definition_id]
        staging_owner = self._vehicle_production_staging_owner_id(state.id)
        for resource_id, required_t in definition.production.resources:
            if required_t <= 1e-12:
                continue
            staged = self._vehicle_production_staged_t(state, resource_id)
            if staged + 1e-9 < required_t:
                raise RuntimeError(
                    f"vehicle production inputs are not fully staged: {state.id}/{resource_id}"
                )
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    staging_owner, state.operational_node_id, resource_id, staged
                )

    def vehicle_production_supplys(
        self, day: int = 0
    ) -> tuple[SupplyRequirement, ...]:
        demands: list[SupplyRequirement] = []
        for state in sorted(
            self.vehicle_production_projects.values(), key=lambda row: str(row.id)
        ):
            if state.phase is not VehicleProductionPhase.AWAITING_INPUTS or state.paused:
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            for resource_id, required_t in sorted(
                definition.production.resources, key=lambda row: str(row[0])
            ):
                remaining = max(
                    0.0,
                    required_t
                    - self._vehicle_production_staged_t(state, resource_id),
                )
                if remaining <= 1e-12:
                    continue
                demands.append(
                    SupplyRequirement(
                        self._vehicle_production_demand_id(state.id, resource_id),
                        "vehicle_production",
                        state.id,
                        state.operational_node_id,
                        resource_id,
                        remaining,
                        state.priority,
                    )
                )
        return tuple(demands)

    def vehicle_production_resource_claims(
        self, day: int = 0
    ) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for state in sorted(
            self.vehicle_production_projects.values(), key=lambda row: (-row.priority, str(row.id))
        ):
            if state.phase is not VehicleProductionPhase.AWAITING_INPUTS or state.paused:
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            for resource_id, required_t in sorted(
                definition.production.resources, key=lambda row: str(row[0])
            ):
                staged = self._vehicle_production_staged_t(state, resource_id)
                remaining = max(0.0, required_t - staged)
                if remaining <= 1e-12:
                    continue
                claims.append(ResourceClaim(
                    self._vehicle_production_claim_id(state.id, resource_id),
                    state.operational_node_id,
                    resource_id,
                    remaining,
                    state.priority,
                    "vehicle_production",
                    state.id,
                    "production_inputs",
                    demand_id=self._vehicle_production_demand_id(state.id, resource_id),
                ))
        return tuple(claims)

    def _consume_ready_vehicle_production_inputs(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        resource_allocations: ResourceAllocationPlan,
        day: int,
    ) -> None:
        waiting = sorted(
            (
                state
                for state in self.vehicle_production_projects.values()
                if state.phase is VehicleProductionPhase.AWAITING_INPUTS
                and not state.paused
            ),
            key=lambda row: (-row.priority, str(row.id)),
        )
        for state in waiting:
            self._stage_vehicle_production_allocations(state, resource_allocations)
            power = power_by_location[state.operational_node_id]
            if self.vehicle_production_blockers(
                state.id,
                day=day,
                power=power,
            ):
                continue
            self._consume_staged_vehicle_production_inputs(state)
            state.phase = VehicleProductionPhase.BUILDING

    @staticmethod
    def vehicle_production_service_request_id(project_id: EntityId) -> EntityId:
        return EntityId(f"service.vehicle_production:{project_id}")

    def vehicle_production_service_requests(
        self, day: int = 0
    ) -> tuple[ServiceCapacityRequest, ...]:
        requests: list[ServiceCapacityRequest] = []
        for state in sorted(
            self.vehicle_production_projects.values(), key=lambda row: str(row.id)
        ):
            if state.phase is VehicleProductionPhase.COMPLETE or state.paused:
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            service_type = definition.production.service_type
            if service_type is None or definition.production.days <= 1e-12:
                continue
            remaining = max(0.0, definition.production.days - state.progress_days)
            if remaining <= 1e-12:
                continue
            requests.append(
                ServiceCapacityRequest(
                    self.vehicle_production_service_request_id(state.id),
                    state.operational_node_id,
                    service_type,
                    min(1.0, remaining),
                    state.priority,
                    "vehicle_production",
                    state.id,
                    "production_work",
                )
            )
        return tuple(requests)

    def advance_vehicle_production_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        resource_allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int,
    ) -> None:
        self._consume_ready_vehicle_production_inputs(
            power_by_location, resource_allocations, day
        )

        for state in sorted(
            self.vehicle_production_projects.values(), key=lambda row: str(row.id)
        ):
            if state.phase is not VehicleProductionPhase.BUILDING or state.paused:
                continue
            power = power_by_location[state.operational_node_id]
            blockers = tuple(
                blocker
                for blocker in self.vehicle_production_blockers(
                    state.id, day=day, power=power
                )
                if not blocker.startswith("service:enabled")
            )
            if blockers:
                continue
            try:
                allocated = service_allocations.allocated(
                    self.vehicle_production_service_request_id(state.id)
                )
            except KeyError:
                allocated = 0.0
            remaining = max(
                0.0,
                self.vehicle_defs[state.vehicle_definition_id].production.days
                - state.progress_days,
            )
            state.progress_days += min(remaining, max(0.0, allocated))

        completed = sorted(
            (
                state
                for state in self.vehicle_production_projects.values()
                if state.phase is VehicleProductionPhase.BUILDING
                and state.progress_days + 1e-9
                >= self.vehicle_defs[state.vehicle_definition_id].production.days
            ),
            key=lambda row: str(row.id),
        )
        for state in completed:
            self.add_fleet_units(
                state.vehicle_definition_id, 1, state.operational_node_id, day=day
            )
            state.phase = VehicleProductionPhase.COMPLETE
            state.completed_units = 1

    def vehicle_production_blockers(
        self,
        project_id: EntityId,
        *,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[str, ...]:
        state = self.vehicle_production_projects[project_id]
        if state.phase is VehicleProductionPhase.COMPLETE:
            return ()
        blockers: list[str] = []
        if state.paused:
            blockers.append("manual_pause")
        definition = self.vehicle_defs[state.vehicle_definition_id]
        if state.phase is VehicleProductionPhase.AWAITING_INPUTS:
            for resource_id, required_t in definition.production.resources:
                allocated = self._vehicle_production_staged_t(state, resource_id)
                if allocated + 1e-9 < required_t:
                    blockers.append(
                        f"resource:{resource_id}:{allocated:g}/{required_t:g}"
                    )
        blockers.extend(
            f"{failure.code}:{failure.detail}"
            for failure in self.vehicle_production_site_failures(
                state.vehicle_definition_id,
                state.operational_node_id,
                day=day,
                power=power,
            )
        )
        return tuple(blockers)
