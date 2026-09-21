from __future__ import annotations

import math

from ..power import PowerSnapshot
from ..shared import DefinitionId, MovementPlanId, SpatialNodeId
from ..site import evaluate_physical_site_requirements, evaluate_site_requirements
from ..spatial import AtmosphereField, GravityField
from .endpoints import movement_geometry, resolve_movement_endpoint
from .models import (
    OperationAssetDisposition,
    OperationSupportLocation,
    MovementPlan,
    TransportPerformanceProfile,
    SurfaceTransportCapability,
    SURFACE_TRANSPORT,
)
from .operations import OperationEvaluationContext

class TransportCompatibilityMixin:
    def resource_support_failures(
        self,
        performance: TransportPerformanceProfile,
        location_id: SpatialNodeId,
        resource_id: DefinitionId,
        day: int = 0,
        *,
        power: PowerSnapshot | None = None,
    ) -> tuple[str, ...]:
        """Return current support blockers for replenishing a vehicle resource."""
        failures: list[str] = []
        vehicle_capabilities = set(performance.generic_capabilities)
        for requirement in performance.support_requirements_for_resource(resource_id):
            if (
                requirement.vehicle_capability_id is not None
                and requirement.vehicle_capability_id not in vehicle_capabilities
            ):
                failures.append(f"vehicle_capability:{requirement.vehicle_capability_id}")
            if not self._has_active_capability(
                location_id,
                requirement.infrastructure_capability_id,
                day,
                power=power,
            ):
                failures.append(
                    f"infrastructure:{location_id}:{requirement.infrastructure_capability_id}"
                )
        return tuple(dict.fromkeys(failures))

    def movement_plan_failures(self, movement_plan_id: MovementPlanId, day: int = 0) -> tuple[str, ...]:
        """Return endpoint/site blockers intrinsic to the Movement Plan itself.

        Research IDs are deliberately not Movement gates. Whether a destination can
        actually be reached is derived from endpoint requirements plus a real
        vehicle/service performance profile and its operational support.
        """
        plan = self.movement_plan(movement_plan_id)
        if plan is None:
            return (f"movement_plan:{movement_plan_id}:unknown",)
        failures: list[str] = []
        for prefix, endpoint, requirements in (
            ("origin", plan.origin, plan.origin_requirements),
            ("destination", plan.destination, plan.destination_requirements),
        ):
            try:
                resolved = resolve_movement_endpoint(endpoint, self.facilities)
            except ValueError as exc:
                failures.append(f"{prefix}:endpoint:{exc}")
                continue
            if endpoint.surface_interface_id is not None:
                interface = self.facilities.facilities[endpoint.surface_interface_id]
                for code, detail in self.facilities.activation_failures(interface, day):
                    failures.append(f"{prefix}:interface:{code}:{detail}")
            if endpoint.operational_node_id is None:
                for failure in evaluate_physical_site_requirements(
                    requirements, resolved.environment_context_id, day, self.facilities.environment
                ):
                    failures.append(f"{prefix}:{failure.code}:{failure.detail}")
                for requirement in requirements.capability_requirements:
                    failures.append(
                        f"{prefix}:capability:{requirement.required_state.value.lower()}:"
                        f"{requirement.capability_id}"
                    )
            else:
                for failure in evaluate_site_requirements(
                    requirements,
                    endpoint.node_id,
                    day,
                    self.facilities.environment,
                    self.facilities,
                    environment_context_id=resolved.environment_context_id,
                ):
                    failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(failures)

    def movement_plan_available(self, movement_plan_id: MovementPlanId, day: int = 0) -> bool:
        return not self.movement_plan_failures(movement_plan_id, day)

    def movement_geometry(self, movement_plan_id: MovementPlanId):
        plan = self.movement_plan(movement_plan_id)
        if plan is None:
            raise KeyError(movement_plan_id)
        return movement_geometry(plan, self.facilities)

    def performance_movement_transit_days(
        self,
        plan: MovementPlan,
        performance: TransportPerformanceProfile,
        *,
        transit_multiplier: float | None = None,
    ) -> int:
        multiplier = performance.transit_time_multiplier if transit_multiplier is None else transit_multiplier
        if any(operation.operation_type == SURFACE_TRANSPORT for operation in plan.operations):
            capability = performance.capability_for(SURFACE_TRANSPORT)
            geometry = movement_geometry(plan, self.facilities)
            if isinstance(capability, SurfaceTransportCapability) and geometry.distance_km is not None:
                return max(1, math.ceil(geometry.distance_km * multiplier / capability.speed_km_per_day))
        return max(1, math.ceil(plan.transit_days * multiplier - 1e-12))

    def _surface_environment(self, context_id, day: int) -> tuple[float, float] | None:
        environment = self.facilities.environment
        if not environment.graph.is_surface_context(context_id):
            return None
        gravity = environment.get(context_id, GravityField, day)
        atmosphere = environment.get(context_id, AtmosphereField, day)
        return (
            0.0 if gravity is None else gravity.local_acceleration_m_s2,
            0.0 if atmosphere is None else atmosphere.pressure_pa,
        )

    def performance_movement_failures(
        self,
        plan: MovementPlan,
        performance: TransportPerformanceProfile,
        day: int = 0,
        *,
        transit_multiplier: float | None = None,
        include_operation_support: bool = True,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        try:
            origin_endpoint = resolve_movement_endpoint(plan.origin, self.facilities)
            destination_endpoint = resolve_movement_endpoint(plan.destination, self.facilities)
            geometry = movement_geometry(plan, self.facilities)
        except ValueError as exc:
            return (f"movement_endpoint:{exc}",)
        context = OperationEvaluationContext(
            transit_days=self.performance_movement_transit_days(
                plan, performance, transit_multiplier=transit_multiplier
            ),
            origin_surface=self._surface_environment(origin_endpoint.environment_context_id, day),
            destination_surface=self._surface_environment(destination_endpoint.environment_context_id, day),
            surface_distance_km=geometry.distance_km if geometry.same_body_surface else None,
        )
        present_operations: set[str] = set()
        for index, operation in enumerate(plan.operations):
            present_operations.add(operation.operation_type)
            capability = performance.capability_for(operation.operation_type)
            failures.extend(self.operation_registry.evaluate(operation, capability, context))
            if (
                capability is not None
                and getattr(capability, "asset_disposition", OperationAssetDisposition.DESTINATION)
                is OperationAssetDisposition.ORIGIN
                and index < len(plan.operations) - 1
            ):
                failures.append(
                    f"operation:{operation.operation_type}:asset_returns_before_movement_complete"
                )

        failures.extend(performance.endurance_failures(context.transit_days))

        if include_operation_support:
            for support in performance.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    plan.origin_id
                    if support.location is OperationSupportLocation.ORIGIN
                    else plan.destination_id
                )
                snapshot = None if power_by_location is None else power_by_location.get(location_id)
                if not self._has_active_capability(
                    location_id, support.capability_id, day, power=snapshot
                ):
                    failures.append(
                        f"operation_support:{support.operation_type}:{support.location.value}:{support.capability_id}"
                    )

        if performance.propellant_t_per_total_t_per_km_s > 1e-12:
            minimum_propellant = performance.propellant_t(plan, 0.0)
            if minimum_propellant > performance.propellant_capacity_t + 1e-9:
                failures.append(
                    f"propellant_capacity:{minimum_propellant:g}/{performance.propellant_capacity_t:g}"
                )
        return tuple(failures)

    def vehicle_movement_physical_failures(
        self, plan_id: MovementPlanId, vehicle_definition_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        plan = self.movement_plan(plan_id)
        if plan is None:
            return (f"movement_plan:{plan_id}:unknown",)
        return self.performance_movement_failures(
            plan,
            self.vehicle_defs[vehicle_definition_id].performance,
            day,
            include_operation_support=False,
        )

    def vehicle_movement_failures(
        self, plan_id: MovementPlanId, vehicle_definition_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        plan = self.movement_plan(plan_id)
        if plan is None:
            return (f"movement_plan:{plan_id}:unknown",)
        return self.performance_movement_failures(
            plan, self.vehicle_defs[vehicle_definition_id].performance, day
        )

    def _has_active_capability(
        self,
        location_id: SpatialNodeId,
        capability_id: str,
        day: int,
        *,
        power: PowerSnapshot | None = None,
    ) -> bool:
        # Capability is categorical. Finite throughput is represented by a
        # separate Service Capacity request/allocation contract.
        return self.facilities.active_capability_at(location_id, capability_id, day)
