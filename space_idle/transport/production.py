from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..power import PowerSnapshot
from ..resource_demand import ResourceDemand
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
    location_id: SpatialNodeId
    priority: int = 50
    allocation_weight: float = 1.0
    progress_days: float = 0.0
    phase: VehicleProductionPhase = VehicleProductionPhase.AWAITING_INPUTS
    paused: bool = False
    completed_units: int = 0
    created_day: int = 0

    def __post_init__(self) -> None:
        if self.allocation_weight <= 0:
            raise ValueError("vehicle production allocation weight must be positive")
        if self.progress_days < -1e-9:
            raise ValueError("vehicle production progress must be non-negative")


class VehicleProductionMixin:
    """Vehicle construction lifecycle owned by the Transport/Vehicle Domain."""

    def plan_vehicle_production(
        self,
        vehicle_definition_id: DefinitionId,
        location_id: SpatialNodeId,
        *,
        priority: int = 50,
        allocation_weight: float = 1.0,
        day: int = 0,
    ) -> EntityId:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(location_id)
        definition = self.vehicle_defs[vehicle_definition_id]
        production = definition.production
        if production.capability_id is None or production.days <= 1e-12:
            raise ValueError("vehicle has no time-based production definition")
        if not production.resources:
            raise ValueError("vehicle production requires physical resource inputs")
        if allocation_weight <= 0:
            raise ValueError("vehicle production allocation weight must be positive")

        failures = self.vehicle_production_site_failures(
            vehicle_definition_id, location_id, day=day
        )
        structural = tuple(
            failure
            for failure in failures
            if not failure.code.startswith("capability:available")
        )
        if structural:
            raise ValueError(
                "vehicle production site requirements not met: "
                + "; ".join(failure.detail for failure in structural)
            )

        self._vehicle_production_counter += 1
        project_id = EntityId(f"vehicle_production.{self._vehicle_production_counter}")
        self.vehicle_production_projects[project_id] = VehicleProductionState(
            project_id,
            vehicle_definition_id,
            location_id,
            priority,
            allocation_weight,
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

    def vehicle_production_allocation_editable(self, project_id: EntityId) -> bool:
        return (
            self.vehicle_production_projects[project_id].phase
            is not VehicleProductionPhase.COMPLETE
        )

    def set_vehicle_production_settings(
        self,
        project_id: EntityId,
        *,
        priority: int | None = None,
        allocation_weight: float | None = None,
    ) -> None:
        state = self.vehicle_production_projects[project_id]
        if priority is not None:
            if not self.vehicle_production_priority_editable(project_id):
                raise ValueError(
                    "vehicle production priority can only change before inputs are consumed"
                )
            state.priority = priority
        if allocation_weight is not None:
            if allocation_weight <= 0:
                raise ValueError("vehicle production allocation weight must be positive")
            if not self.vehicle_production_allocation_editable(project_id):
                raise ValueError("completed vehicle production allocation cannot change")
            state.allocation_weight = allocation_weight

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
        snapshot = (
            power
            if power is not None
            else self.power.snapshot(location_id, self.facilities, day)
        )
        failures = list(
            evaluate_site_requirements(
                production.site_requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
                snapshot,
            )
        )
        if production.capability_id is not None:
            available = self.facilities.available_capability_capacity_at(
                location_id, production.capability_id, snapshot, day
            )
            if available <= 1e-12:
                failures.append(
                    SiteRequirementFailure(
                        "capability:available",
                        f"{production.capability_id}:{available:g}/positive",
                    )
                )
        return tuple(failures)

    @staticmethod
    def _vehicle_production_demand_id(
        project_id: EntityId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"demand.{project_id}:{resource_id}")

    def vehicle_production_resource_demands(
        self, day: int = 0
    ) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for state in sorted(
            self.vehicle_production_projects.values(), key=lambda row: str(row.id)
        ):
            if state.phase is not VehicleProductionPhase.AWAITING_INPUTS or state.paused:
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            for resource_id, required_t in sorted(
                definition.production.resources, key=lambda row: str(row[0])
            ):
                if required_t <= 1e-12:
                    continue
                demands.append(
                    ResourceDemand(
                        self._vehicle_production_demand_id(state.id, resource_id),
                        "vehicle_production",
                        state.id,
                        state.location_id,
                        resource_id,
                        required_t,
                        state.priority,
                    )
                )
        return tuple(demands)

    def _consume_ready_vehicle_production_inputs(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
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
            definition = self.vehicle_defs[state.vehicle_definition_id]
            resources = tuple(
                (resource_id, amount_t)
                for resource_id, amount_t in definition.production.resources
                if amount_t > 1e-12
            )
            power = power_by_location.get(state.location_id)
            if power is None:
                power = self.power.snapshot(state.location_id, self.facilities, day)
            if self.vehicle_production_blockers(
                state.id,
                day=day,
                power=power,
            ):
                continue
            for resource_id, amount_t in resources:
                self.inventory.consume_reserved(
                    self._vehicle_production_demand_id(state.id, resource_id),
                    state.location_id,
                    resource_id,
                    amount_t,
                )
            state.phase = VehicleProductionPhase.BUILDING

    def advance_vehicle_production_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> None:
        self._consume_ready_vehicle_production_inputs(power_by_location, day)

        pools: dict[tuple[SpatialNodeId, str], list[VehicleProductionState]] = {}
        for state in self.vehicle_production_projects.values():
            if state.phase is not VehicleProductionPhase.BUILDING or state.paused:
                continue
            power = power_by_location.get(state.location_id)
            if power is None:
                power = self.power.snapshot(state.location_id, self.facilities, day)
            if self.vehicle_production_blockers(state.id, day=day, power=power):
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            capability_id = definition.production.capability_id
            if capability_id is None:
                continue
            pools.setdefault((state.location_id, capability_id), []).append(state)

        for (location_id, capability_id), states in sorted(
            pools.items(), key=lambda row: (str(row[0][0]), row[0][1])
        ):
            power = power_by_location.get(location_id)
            if power is None:
                power = self.power.snapshot(location_id, self.facilities, day)
            available = self.facilities.available_capability_capacity_at(
                location_id, capability_id, power, day
            )
            if available <= 1e-12:
                continue

            active = sorted(states, key=lambda row: str(row.id))
            remaining = available
            allocations = {state.id: 0.0 for state in active}
            while active and remaining > 1e-12:
                total_weight = sum(state.allocation_weight for state in active)
                if total_weight <= 1e-12:
                    break
                saturated: list[VehicleProductionState] = []
                used = 0.0
                for state in active:
                    room = max(0.0, 1.0 - allocations[state.id])
                    proposed = remaining * state.allocation_weight / total_weight
                    grant = min(room, proposed)
                    allocations[state.id] += grant
                    used += grant
                    if allocations[state.id] >= 1.0 - 1e-12:
                        saturated.append(state)
                remaining = max(0.0, remaining - used)
                if not saturated or used <= 1e-12:
                    break
                active = [state for state in active if state not in saturated]
            for state in states:
                state.progress_days += allocations[state.id]

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
            self.add_fleet_units(state.vehicle_definition_id, 1, state.location_id)
            state.phase = VehicleProductionPhase.COMPLETE
            state.completed_units = 1
            self.reconcile_fleet_allocations(day)

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
                allocated = self.inventory.reserved_for(
                    self._vehicle_production_demand_id(state.id, resource_id),
                    state.location_id,
                    resource_id,
                )
                if allocated + 1e-9 < required_t:
                    blockers.append(
                        f"resource:{resource_id}:{allocated:g}/{required_t:g}"
                    )
        blockers.extend(
            f"{failure.code}:{failure.detail}"
            for failure in self.vehicle_production_site_failures(
                state.vehicle_definition_id,
                state.location_id,
                day=day,
                power=power,
            )
        )
        return tuple(blockers)
