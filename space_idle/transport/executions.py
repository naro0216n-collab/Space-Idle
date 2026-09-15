from __future__ import annotations

from dataclasses import replace

from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import (
    MovementExecution,
    MovementExecutionKind,
    MovementExecutionLeg,
    MovementExecutionResourceRequirement,
    MovementPlan,
    OperationAssetDisposition,
)


class MovementExecutionMixin:
    """Start and own finite Movement snapshots independently of their owner Domain."""

    def movement_resource_requirements_for_plans(
        self,
        vehicle_definition_id: DefinitionId,
        units: int,
        plans: tuple[MovementPlan, ...],
        *,
        payload_t_per_unit: float = 0.0,
    ) -> tuple[MovementExecutionResourceRequirement, ...]:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if units <= 0:
            raise ValueError("movement resource requirements need positive units")
        vehicle = self.vehicle_defs[vehicle_definition_id]
        if vehicle.propellant_resource_id is None:
            return ()
        totals: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for plan in plans:
            origin_id = plan.origin.operational_node_id
            if origin_id is None:
                raise ValueError("movement operation resources require an Operational Node origin")
            amount = vehicle.propellant_t(plan, payload_t_per_unit) * units
            if amount <= 1e-12:
                continue
            key = (origin_id, vehicle.propellant_resource_id)
            totals[key] = totals.get(key, 0.0) + amount
        return tuple(
            MovementExecutionResourceRequirement(node_id, resource_id, amount)
            for (node_id, resource_id), amount in sorted(
                totals.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
            )
        )

    def _movement_execution_from_plans(
        self,
        execution_id: EntityId,
        owner_id: EntityId,
        kind: MovementExecutionKind,
        vehicle_definition_id: DefinitionId,
        units: int,
        plans: tuple[MovementPlan, ...],
        *,
        payload_t_per_unit: float = 0.0,
        day: int = 0,
    ) -> MovementExecution:
        if execution_id in self.movement_executions:
            raise ValueError(f"movement execution already exists: {execution_id}")
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if units <= 0:
            raise ValueError("movement execution units must be positive")
        if not plans:
            raise ValueError("movement execution requires a movement plan")

        vehicle = self.vehicle_defs[vehicle_definition_id]
        legs: list[MovementExecutionLeg] = []
        expected_origin = plans[0].origin
        for index, plan in enumerate(plans):
            if index > 0:
                prior = plans[index - 1]
                if prior.destination.operational_node_id != plan.origin.operational_node_id:
                    raise ValueError("movement execution path is discontinuous")
                if prior.destination.locator_id != plan.origin.locator_id and (
                    prior.destination.operational_node_id is None
                    or prior.destination.operational_node_id != plan.origin.operational_node_id
                ):
                    raise ValueError("movement execution path endpoint mismatch")
            failures = list(self.movement_plan_failures(plan.id, day))
            failures.extend(
                self.performance_movement_failures(plan, vehicle.performance, day)
            )
            if failures:
                raise ValueError(
                    f"movement plan is not executable: {plan.id}: "
                    + "; ".join(dict.fromkeys(failures))
                )
            payload_capacity = vehicle.max_cargo_for_movement(plan)
            if payload_t_per_unit > payload_capacity + 1e-9:
                raise ValueError(
                    f"movement payload exceeds capacity: {payload_capacity:g}/{payload_t_per_unit:g}"
                )
            latency = self.performance_movement_transit_days(plan, vehicle.performance)
            leg_resources: tuple[MovementExecutionResourceRequirement, ...] = ()
            if vehicle.propellant_resource_id is not None:
                origin_id = plan.origin.operational_node_id
                if origin_id is None:
                    raise ValueError(
                        "movement operation resources require an Operational Node origin"
                    )
                required_t = vehicle.propellant_t(plan, payload_t_per_unit) * units
                if required_t > 1e-12:
                    leg_resources = (
                        MovementExecutionResourceRequirement(
                            origin_id, vehicle.propellant_resource_id, required_t
                        ),
                    )
            legs.append(
                MovementExecutionLeg(
                    movement_plan_id=plan.id,
                    origin=plan.origin,
                    destination=plan.destination,
                    operations=plan.operations,
                    latency_days=latency,
                    payload_capacity_t=max(0.0, payload_capacity),
                    propellant_t_per_unit=vehicle.propellant_t(plan, payload_t_per_unit),
                    asset_disposition=vehicle.movement_asset_disposition(plan),
                    resource_requirements=leg_resources,
                )
            )

        latency_days = sum(leg.latency_days for leg in legs)
        execution = MovementExecution(
            id=execution_id,
            owner_id=owner_id,
            kind=kind,
            vehicle_definition_id=vehicle_definition_id,
            units=units,
            legs=tuple(legs),
            payload_t_per_unit=payload_t_per_unit,
            started_day=day,
            completion_day=day + max(1, latency_days),
        )
        self.movement_executions[execution_id] = execution
        return execution

    def start_movement_execution_for_path(
        self,
        execution_id: EntityId,
        owner_id: EntityId,
        kind: MovementExecutionKind,
        vehicle_definition_id: DefinitionId,
        units: int,
        path: tuple[RouteId, ...],
        *,
        payload_t_per_unit: float = 0.0,
        day: int = 0,
    ) -> MovementExecution:
        plans = tuple(self.require_movement_plan(plan_id) for plan_id in path)
        return self._movement_execution_from_plans(
            execution_id,
            owner_id,
            kind,
            vehicle_definition_id,
            units,
            plans,
            payload_t_per_unit=payload_t_per_unit,
            day=day,
        )

    def start_movement_execution_for_plan(
        self,
        execution_id: EntityId,
        owner_id: EntityId,
        kind: MovementExecutionKind,
        vehicle_definition_id: DefinitionId,
        units: int,
        plan: MovementPlan,
        *,
        payload_t_per_unit: float = 0.0,
        day: int = 0,
    ) -> MovementExecution:
        # Physical-target plans are ephemeral and intentionally need not be
        # recoverable from the regular Operational Node Movement graph later.
        self._movement_plan_cache[plan.id] = plan
        return self._movement_execution_from_plans(
            execution_id,
            owner_id,
            kind,
            vehicle_definition_id,
            units,
            (plan,),
            payload_t_per_unit=payload_t_per_unit,
            day=day,
        )

    def movement_execution_snapshot(
        self, execution_id: EntityId
    ) -> MovementExecution | None:
        execution = self.movement_executions.get(execution_id)
        return None if execution is None else replace(execution)

    def movement_execution_snapshots(self) -> tuple[MovementExecution, ...]:
        return tuple(
            replace(execution)
            for execution in sorted(self.movement_executions.values(), key=lambda row: str(row.id))
        )

    def finish_movement_execution(self, execution_id: EntityId) -> MovementExecution:
        try:
            return self.movement_executions.pop(execution_id)
        except KeyError as exc:
            raise KeyError(execution_id) from exc
