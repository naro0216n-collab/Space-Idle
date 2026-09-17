from __future__ import annotations

from dataclasses import dataclass

from ..execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ResourceRequirement,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
)
from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from ..shared import DefinitionId, EntityId, SpatialNodeId
from ..site import evaluate_site_requirements
from .models import FleetReservation, FleetReservationKind, FleetRetirementPhase, FleetRetirementState

_EPS = 1e-9


class FleetRetirementMixin:
    @staticmethod
    def _retirement_reservation_id(retirement_id: EntityId) -> EntityId:
        return EntityId(f"fleet.retirement:{retirement_id}")

    @staticmethod
    def _retirement_bundle_id(retirement_id: EntityId) -> EntityId:
        return EntityId(f"execution.fleet_retirement:{retirement_id}")

    @staticmethod
    def _retirement_salvage_bundle_id(retirement_id: EntityId) -> EntityId:
        return EntityId(f"execution.fleet_retirement_salvage:{retirement_id}")

    def plan_fleet_retirement(
        self,
        vehicle_definition_id: DefinitionId,
        units: int,
        operational_node_id: SpatialNodeId,
        *,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        day: int = 0,
    ) -> EntityId:
        definition = self.vehicle_definition(vehicle_definition_id)
        if definition is None:
            raise ValueError(f"unknown Vehicle definition: {vehicle_definition_id}")
        if units <= 0:
            raise ValueError("retirement units must be positive")
        spec = definition.retirement
        if not spec.enabled:
            raise ValueError(f"Vehicle has no retirement definition: {vehicle_definition_id}")
        if not self.facilities.environment.graph.has_operational_node(operational_node_id):
            raise KeyError(operational_node_id)
        failures = evaluate_site_requirements(
            spec.site_requirements, operational_node_id, day,
            self.facilities.environment, self.facilities,
        )
        if failures:
            raise ValueError(
                "fleet retirement site requirements not met: "
                + "; ".join(failure.detail for failure in failures)
            )
        if self.fleet_free_units(vehicle_definition_id, operational_node_id) < units:
            raise ValueError("retirement requires free Fleet units")
        self._fleet_retirement_counter += 1
        retirement_id = EntityId(f"fleet_retirement:{self._fleet_retirement_counter}")
        state = FleetRetirementState(
            id=retirement_id,
            vehicle_definition_id=vehicle_definition_id,
            operational_node_id=operational_node_id,
            units=units,
            priority=ActivityPriority(priority),
            created_day=day,
        )
        self.fleet_retirements[retirement_id] = state
        reservation_id = self._retirement_reservation_id(retirement_id)
        self.fleet_reservations[reservation_id] = FleetReservation(
            reservation_id,
            retirement_id,
            FleetReservationKind.RETIREMENT,
            vehicle_definition_id,
            operational_node_id,
            units,
        )
        return retirement_id

    def cancel_fleet_retirement(self, retirement_id: EntityId) -> None:
        state = self.fleet_retirements[retirement_id]
        if state.irreversible_started:
            raise ValueError("fleet retirement cannot be cancelled after dismantling starts")
        if state.phase in {FleetRetirementPhase.COMPLETE, FleetRetirementPhase.CANCELLED}:
            raise ValueError("fleet retirement is no longer active")
        state.phase = FleetRetirementPhase.CANCELLED
        self.fleet_reservations.pop(self._retirement_reservation_id(retirement_id), None)

    def set_fleet_retirement_priority(
        self, retirement_id: EntityId, priority: ActivityPriority
    ) -> None:
        state = self.fleet_retirements[retirement_id]
        if state.phase in {FleetRetirementPhase.COMPLETE, FleetRetirementPhase.CANCELLED}:
            raise ValueError("fleet retirement is no longer active")
        state.priority = ActivityPriority(priority)

    def fleet_retirement_snapshots(self) -> tuple[FleetRetirementState, ...]:
        return tuple(sorted(self.fleet_retirements.values(), key=lambda row: str(row.id)))

    def _retirement_total_work(self, state: FleetRetirementState) -> float:
        definition = self.vehicle_defs[state.vehicle_definition_id]
        return definition.retirement.work_days_per_unit * state.units

    def _retirement_salvage(self, state: FleetRetirementState) -> tuple[tuple[DefinitionId, float], ...]:
        definition = self.vehicle_defs[state.vehicle_definition_id]
        return tuple(
            (resource_id, amount_per_unit * state.units)
            for resource_id, amount_per_unit in definition.retirement.recovery_resources_per_unit
            if amount_per_unit * state.units > _EPS
        )

    def fleet_retirement_blockers(self, retirement_id: EntityId, *, day: int = 0) -> tuple[str, ...]:
        state = self.fleet_retirements[retirement_id]
        if state.phase in {FleetRetirementPhase.COMPLETE, FleetRetirementPhase.CANCELLED}:
            return ()
        definition = self.vehicle_defs[state.vehicle_definition_id]
        spec = definition.retirement
        blockers: list[str] = []
        total_work = self._retirement_total_work(state)
        remaining_work = max(0.0, total_work - state.progress_work)
        if remaining_work > _EPS:
            failures = evaluate_site_requirements(
                spec.site_requirements, state.operational_node_id, day,
                self.facilities.environment, self.facilities,
            )
            blockers.extend(f"site:{failure.code}:{failure.detail}" for failure in failures)
            if spec.service_type is not None:
                power = self.power.snapshot(state.operational_node_id, self.facilities, day)
                available_service = self.service_capacity_registry.available_at(
                    state.operational_node_id,
                    spec.service_type,
                    self.facilities,
                    power,
                    day,
                )
                if available_service <= _EPS:
                    blockers.append(f"service:{spec.service_type}")
            fraction_remaining = remaining_work / total_work
            for resource_id, amount_per_unit in spec.resources_per_unit:
                required = amount_per_unit * state.units * fraction_remaining
                if required > self.inventory.available(state.operational_node_id, resource_id) + _EPS:
                    blockers.append(f"resource:{resource_id}")
            return tuple(blockers)

        salvage_by_pool: dict[str, float] = {}
        for resource_id, amount_t in self._retirement_salvage(state):
            storage_class = self.inventory.resource_storage_class.get(resource_id)
            if storage_class is None:
                continue
            salvage_by_pool[storage_class] = salvage_by_pool.get(storage_class, 0.0) + amount_t
        for storage_class, amount_t in sorted(salvage_by_pool.items()):
            admission = self.inventory.admission_state_for_class(
                state.operational_node_id, storage_class
            )
            if admission.admission_capacity_t is not None and admission.admission_capacity_t + _EPS < amount_t:
                blockers.append(f"salvage_admission:{storage_class}")
        return tuple(blockers)

    def fleet_retirement_execution_requirement_bundles(
        self, day: int = 0
    ) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for state in self.fleet_retirement_snapshots():
            if state.phase in {FleetRetirementPhase.COMPLETE, FleetRetirementPhase.CANCELLED}:
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            spec = definition.retirement
            total_work = self._retirement_total_work(state)
            remaining_work = max(0.0, total_work - state.progress_work)
            if remaining_work > _EPS:
                site_failures = evaluate_site_requirements(
                    spec.site_requirements, state.operational_node_id, day,
                    self.facilities.environment, self.facilities,
                )
                if site_failures:
                    continue
                fraction_remaining = remaining_work / total_work
                requirements = []
                if spec.service_type is not None:
                    requirements.append(ServiceCapacityRequirement(spec.service_type, remaining_work))
                requirements.extend(
                    ResourceRequirement(resource_id, amount_per_unit * state.units * fraction_remaining)
                    for resource_id, amount_per_unit in spec.resources_per_unit
                    if amount_per_unit * state.units * fraction_remaining > _EPS
                )
                rows.append(ExecutionRequirementBundle(
                    id=self._retirement_bundle_id(state.id),
                    owner_kind="fleet_retirement",
                    owner_id=state.id,
                    purpose="dismantling",
                    operational_node_id=state.operational_node_id,
                    requested_execution=1.0,
                    priority=state.priority,
                    requirements=tuple(requirements),
                ))
                continue
            salvage = self._retirement_salvage(state)
            admission_by_pool: dict[str, float] = {}
            for resource_id, amount_t in salvage:
                pool_id = self.inventory.resource_storage_class.get(resource_id)
                if pool_id is None:
                    continue
                admission_by_pool[pool_id] = admission_by_pool.get(pool_id, 0.0) + amount_t
            requirements = tuple(
                StockOrPoolAdmissionRequirement(pool_id, amount_t)
                for pool_id, amount_t in sorted(admission_by_pool.items())
            )
            rows.append(ExecutionRequirementBundle(
                id=self._retirement_salvage_bundle_id(state.id),
                owner_kind="fleet_retirement",
                owner_id=state.id,
                purpose="salvage_admission",
                operational_node_id=state.operational_node_id,
                requested_execution=1.0,
                priority=state.priority,
                requirements=requirements,
                minimum_execution=1.0,
                atomic=True,
                wait_started_day=state.salvage_wait_started_day if state.salvage_wait_started_day is not None else day,
            ))
        return tuple(rows)

    def advance_fleet_retirements(
        self, allocations: ExecutionAllocationPlan, day: int = 0
    ) -> None:
        for state in self.fleet_retirement_snapshots():
            if state.phase in {FleetRetirementPhase.COMPLETE, FleetRetirementPhase.CANCELLED}:
                continue
            definition = self.vehicle_defs[state.vehicle_definition_id]
            spec = definition.retirement
            total_work = self._retirement_total_work(state)
            remaining_work = max(0.0, total_work - state.progress_work)
            if remaining_work > _EPS:
                try:
                    factor = allocations.fulfillment(self._retirement_bundle_id(state.id))
                except KeyError:
                    factor = 0.0
                if factor <= _EPS:
                    continue
                if not state.irreversible_started:
                    state.irreversible_started = True
                    state.phase = FleetRetirementPhase.DISMANTLING
                fraction_remaining = remaining_work / total_work
                for resource_id, amount_per_unit in spec.resources_per_unit:
                    amount = amount_per_unit * state.units * fraction_remaining * factor
                    if amount > _EPS:
                        self.inventory.consume_allocated(state.operational_node_id, resource_id, amount)
                state.progress_work = min(total_work, state.progress_work + remaining_work * factor)
                if total_work - state.progress_work <= _EPS:
                    state.progress_work = total_work
                    state.salvage_wait_started_day = day
                continue
            try:
                factor = allocations.fulfillment(self._retirement_salvage_bundle_id(state.id))
            except KeyError:
                factor = 0.0
            if factor < 1.0 - _EPS:
                continue
            salvage = self._retirement_salvage(state)
            pool = self.fleet_pools[(state.vehicle_definition_id, state.operational_node_id)]
            if pool.total_units < state.units:
                raise RuntimeError("retirement would make Fleet total negative")
            for resource_id, amount_t in salvage:
                self.inventory.admit(state.operational_node_id, resource_id, amount_t)
            pool.total_units -= state.units
            self.fleet_reservations.pop(self._retirement_reservation_id(state.id), None)
            state.phase = FleetRetirementPhase.COMPLETE
