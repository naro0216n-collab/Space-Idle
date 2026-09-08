from __future__ import annotations

from ..shared import DefinitionId, RouteId, SpatialNodeId
from ..site import evaluate_site_requirements
from ..spatial import AtmosphereField, GravityField, SurfaceField
from .models import (
    OperationSupportLocation,
    RouteDef,
    TransportPerformanceProfile,
)
from .operations import OperationEvaluationContext


class TransportCompatibilityMixin:
    def route_failures(self, route_id: RouteId, day: int = 0) -> tuple[str, ...]:
        route = self.routes[route_id]
        failures: list[str] = []
        missing = route.required_technologies - self.unlocked_technologies
        if missing:
            failures.append("technology:" + ",".join(sorted(map(str, missing))))
        for prefix, location_id, requirements in (
            ("origin", route.origin_id, route.origin_requirements),
            ("destination", route.destination_id, route.destination_requirements),
        ):
            power = self.power.snapshot(location_id, self.facilities, day)
            for failure in evaluate_site_requirements(
                requirements, location_id, day, self.facilities.environment, self.facilities, power
            ):
                failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(failures)

    def route_available(self, route_id: RouteId, day: int = 0) -> bool:
        return not self.route_failures(route_id, day)

    def _surface_environment(self, location_id: SpatialNodeId, day: int) -> tuple[float, float] | None:
        environment = self.facilities.environment
        if environment.get(location_id, SurfaceField, day) is None:
            return None
        gravity = environment.get(location_id, GravityField, day)
        atmosphere = environment.get(location_id, AtmosphereField, day)
        return (
            0.0 if gravity is None else gravity.local_acceleration_m_s2,
            0.0 if atmosphere is None else atmosphere.pressure_pa,
        )

    def _performance_route_failures(
        self,
        route: RouteDef,
        performance: TransportPerformanceProfile,
        day: int = 0,
        *,
        transit_multiplier: float | None = None,
        include_operation_support: bool = True,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        multiplier = performance.transit_time_multiplier if transit_multiplier is None else transit_multiplier
        context = OperationEvaluationContext(
            transit_days=max(1, round(route.transit_days * multiplier)),
            origin_surface=self._surface_environment(route.origin_id, day),
            destination_surface=self._surface_environment(route.destination_id, day),
        )
        present_operations: set[str] = set()
        for operation in route.operations:
            present_operations.add(operation.operation_type)
            capability = performance.capability_for(operation.operation_type)
            failures.extend(self.operation_registry.evaluate(operation, capability, context))

        if include_operation_support:
            for support in performance.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    route.origin_id
                    if support.location is OperationSupportLocation.ORIGIN
                    else route.destination_id
                )
                if not self._has_available_capability(location_id, support.capability_id, day):
                    failures.append(
                        f"operation_support:{support.operation_type}:{support.location.value}:{support.capability_id}"
                    )

        if performance.propellant_t_per_total_t_per_km_s > 1e-12:
            minimum_propellant = performance.propellant_t(route, 0.0)
            if minimum_propellant > performance.propellant_capacity_t + 1e-9:
                failures.append(
                    f"propellant_capacity:{minimum_propellant:g}/{performance.propellant_capacity_t:g}"
                )
        return tuple(failures)

    def vehicle_route_physical_failures(
        self, route_id: RouteId, vehicle_definition_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        return self._performance_route_failures(
            self.routes[route_id],
            self.vehicle_defs[vehicle_definition_id].performance,
            day,
            include_operation_support=False,
        )

    def vehicle_route_failures(
        self, route_id: RouteId, vehicle_definition_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        return self._performance_route_failures(
            self.routes[route_id], self.vehicle_defs[vehicle_definition_id].performance, day
        )

    def service_route_failures(
        self, route_id: RouteId, service_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        route = self.routes[route_id]
        service = self.external_services[service_id]
        failures = list(
            self._performance_route_failures(
                route,
                service.performance,
                day,
                transit_multiplier=service.transit_time_multiplier,
            )
        )
        for prefix, location_id, requirements in (
            ("origin", route.origin_id, service.origin_requirements),
            ("destination", route.destination_id, service.destination_requirements),
        ):
            power = self.power.snapshot(location_id, self.facilities, day)
            for failure in evaluate_site_requirements(
                requirements, location_id, day, self.facilities.environment, self.facilities, power
            ):
                failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(failures)

    def _available_capability(self, location_id: SpatialNodeId, capability_id: str, day: int) -> float:
        power = self.power.snapshot(location_id, self.facilities, day)
        return self.facilities.available_capability_capacity_at(location_id, capability_id, power, day)

    def _has_available_capability(self, location_id: SpatialNodeId, capability_id: str, day: int) -> bool:
        return self._available_capability(location_id, capability_id, day) > 1e-12
