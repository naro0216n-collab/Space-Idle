from __future__ import annotations

import math

from ..power import PowerSnapshot
from ..shared import DefinitionId, RouteId, SpatialNodeId, SurfaceCellId
from ..site import SiteRequirements, evaluate_site_requirements
from ..spatial import AtmosphereField, GravityField, SurfaceField
from .endpoints import resolve_route_endpoint, route_geometry
from .models import (
    OperationAssetDisposition,
    TransportOperationRequirement,
    OperationSupportLocation,
    RouteDef,
    TransportPerformanceProfile,
    SurfaceTransportCapability,
    SURFACE_TRANSPORT,
)
from .operations import OperationEvaluationContext
from .surface_routes import (
    DERIVED_SURFACE_ACCESS_ROUTE_PREFIX,
    build_derived_surface_access_routes,
)


class TransportCompatibilityMixin:
    def synchronize_surface_access_routes(self) -> None:
        """Refresh derived same-body surface Routes from authoritative Location state."""
        derived = build_derived_surface_access_routes(
            self.facilities.environment.graph, self.surface_access_route_rules
        )
        stale = tuple(
            route_id
            for route_id in self.routes
            if str(route_id).startswith(DERIVED_SURFACE_ACCESS_ROUTE_PREFIX)
            and route_id not in derived
        )
        for route_id in stale:
            del self.routes[route_id]
        self.routes.update(derived)

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
            if not self._has_available_capability(
                location_id,
                requirement.infrastructure_capability_id,
                day,
                power=power,
            ):
                failures.append(
                    f"infrastructure:{location_id}:{requirement.infrastructure_capability_id}"
                )
        return tuple(dict.fromkeys(failures))

    def route_failures(self, route_id: RouteId, day: int = 0) -> tuple[str, ...]:
        """Return endpoint/site blockers intrinsic to the route itself.

        Research IDs are deliberately not route gates. Whether a destination can
        actually be reached is derived from endpoint requirements plus a real
        vehicle/service performance profile and its operational support.
        """
        route = self.routes[route_id]
        failures: list[str] = []
        for prefix, endpoint, requirements in (
            ("origin", route.origin, route.origin_requirements),
            ("destination", route.destination, route.destination_requirements),
        ):
            try:
                resolved = resolve_route_endpoint(endpoint, self.facilities)
            except ValueError as exc:
                failures.append(f"{prefix}:endpoint:{exc}")
                continue
            power = self.power.snapshot(endpoint.location_id, self.facilities, day)
            if endpoint.surface_interface_id is not None:
                interface = self.facilities.facilities[endpoint.surface_interface_id]
                for code, detail in self.facilities.activation_failures(interface, day):
                    failures.append(f"{prefix}:interface:{code}:{detail}")
                if not interface.paused and not self.facilities.environment_failures(interface, day):
                    maintenance = power.maintenance_factor_by_facility.get(
                        interface.id, self.facilities.maintenance_factor(interface.id)
                    )
                    if maintenance <= 1e-12:
                        failures.append(f"{prefix}:interface:maintenance:facility unavailable")
                    utilization = power.utilization_by_facility.get(interface.id, 1.0)
                    if utilization <= 1e-12:
                        failures.append(f"{prefix}:interface:power:facility unavailable")
            for failure in evaluate_site_requirements(
                requirements,
                endpoint.location_id,
                day,
                self.facilities.environment,
                self.facilities,
                power,
                environment_context_id=resolved.environment_context_id,
            ):
                failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(failures)

    def route_available(self, route_id: RouteId, day: int = 0) -> bool:
        return not self.route_failures(route_id, day)

    def route_surface_access_factors(
        self, route_id: RouteId, day: int = 0
    ) -> tuple[tuple[SpatialNodeId, SurfaceCellId, float], ...]:
        """Return aggregate intra-Location access fulfillment for surface endpoints.

        The Route remains Location-to-Location.  Surface Infrastructure only
        constrains handoff between that economic node and the physical access
        cell/interface used by the Route; it never creates Cell cargo nodes.
        """
        provider = self.surface_access_factor_provider
        if provider is None:
            return ()
        geometry = route_geometry(self.routes[route_id], self.facilities)
        rows: list[tuple[SpatialNodeId, SurfaceCellId, float]] = []
        for endpoint in (geometry.origin, geometry.destination):
            if endpoint.surface_cell_id is None:
                continue
            factor = max(
                0.0,
                min(1.0, provider(endpoint.location_id, endpoint.surface_cell_id, day)),
            )
            rows.append((endpoint.location_id, endpoint.surface_cell_id, factor))
        return tuple(rows)

    def route_geometry(self, route_id: RouteId):
        return route_geometry(self.routes[route_id], self.facilities)

    def performance_route_transit_days(
        self,
        route: RouteDef,
        performance: TransportPerformanceProfile,
        *,
        transit_multiplier: float | None = None,
    ) -> int:
        multiplier = performance.transit_time_multiplier if transit_multiplier is None else transit_multiplier
        if any(operation.operation_type == SURFACE_TRANSPORT for operation in route.operations):
            capability = performance.capability_for(SURFACE_TRANSPORT)
            geometry = route_geometry(route, self.facilities)
            if isinstance(capability, SurfaceTransportCapability) and geometry.distance_km is not None:
                return max(1, math.ceil(geometry.distance_km * multiplier / capability.speed_km_per_day))
        return max(1, round(route.transit_days * multiplier))

    def _surface_environment(self, context_id, day: int) -> tuple[float, float] | None:
        environment = self.facilities.environment
        if environment.get(context_id, SurfaceField, day) is None:
            return None
        gravity = environment.get(context_id, GravityField, day)
        atmosphere = environment.get(context_id, AtmosphereField, day)
        return (
            0.0 if gravity is None else gravity.local_acceleration_m_s2,
            0.0 if atmosphere is None else atmosphere.pressure_pa,
        )

    def performance_route_failures(
        self,
        route: RouteDef,
        performance: TransportPerformanceProfile,
        day: int = 0,
        *,
        transit_multiplier: float | None = None,
        include_operation_support: bool = True,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        try:
            origin_endpoint = resolve_route_endpoint(route.origin, self.facilities)
            destination_endpoint = resolve_route_endpoint(route.destination, self.facilities)
            geometry = route_geometry(route, self.facilities)
        except ValueError as exc:
            return (f"route_endpoint:{exc}",)
        context = OperationEvaluationContext(
            transit_days=self.performance_route_transit_days(
                route, performance, transit_multiplier=transit_multiplier
            ),
            origin_surface=self._surface_environment(origin_endpoint.environment_context_id, day),
            destination_surface=self._surface_environment(destination_endpoint.environment_context_id, day),
            surface_distance_km=geometry.distance_km if geometry.same_body_surface else None,
        )
        present_operations: set[str] = set()
        for index, operation in enumerate(route.operations):
            present_operations.add(operation.operation_type)
            capability = performance.capability_for(operation.operation_type)
            failures.extend(self.operation_registry.evaluate(operation, capability, context))
            if (
                capability is not None
                and getattr(capability, "asset_disposition", OperationAssetDisposition.DESTINATION)
                is OperationAssetDisposition.ORIGIN
                and index < len(route.operations) - 1
            ):
                failures.append(
                    f"operation:{operation.operation_type}:asset_returns_before_route_complete"
                )

        failures.extend(performance.endurance_failures(context.transit_days))

        if include_operation_support:
            for support in performance.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    route.origin_id
                    if support.location is OperationSupportLocation.ORIGIN
                    else route.destination_id
                )
                snapshot = None if power_by_location is None else power_by_location.get(location_id)
                if not self._has_available_capability(
                    location_id, support.capability_id, day, power=snapshot
                ):
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


    def deployment_propellant_t(
        self,
        vehicle_definition_id: DefinitionId,
        operations: tuple[TransportOperationRequirement, ...],
        payload_t: float,
    ) -> tuple[DefinitionId | None, float]:
        """Return propellant consumed by one pre-Location deployment operation."""
        performance = self.vehicle_defs[vehicle_definition_id].performance
        delta_v = sum(operation.delta_v_km_s for operation in operations)
        amount = (
            performance.propellant_t_per_total_t_per_km_s
            * (performance.dry_mass_t + payload_t)
            * delta_v
        )
        return performance.propellant_resource_id, max(0.0, amount)

    def deployment_failures(
        self,
        vehicle_definition_id: DefinitionId,
        staging_location_id: SpatialNodeId,
        target_cell_id: SurfaceCellId,
        operations: tuple[TransportOperationRequirement, ...],
        transit_days: int,
        payload_t: float,
        *,
        staging_requirements: SiteRequirements = SiteRequirements(),
        target_requirements: SiteRequirements = SiteRequirements(),
        day: int = 0,
    ) -> tuple[str, ...]:
        """Evaluate a one-time deployment to a Surface Cell before a Location exists.

        The target cell is a physical endpoint only: this path deliberately does
        not invent a destination Inventory, Route node, or Facility container.
        """
        failures: list[str] = []
        graph = self.facilities.environment.graph
        if vehicle_definition_id not in self.vehicle_defs:
            return ("unknown_vehicle_definition",)
        if not graph.has_operational_node(staging_location_id):
            return (f"unknown_staging_node:{staging_location_id}",)
        if target_cell_id not in graph.surface_cells:
            return (f"unknown_target_cell:{target_cell_id}",)
        if transit_days <= 0:
            failures.append("deployment_transit_days")
        if payload_t < -1e-9:
            failures.append("deployment_payload_negative")

        vehicle = self.vehicle_defs[vehicle_definition_id]
        performance = vehicle.performance
        if payload_t > performance.payload_t + 1e-9:
            failures.append(f"payload:{payload_t:g}/{performance.payload_t:g}")

        effective_days = max(1, round(max(1, transit_days) * performance.transit_time_multiplier))
        context = OperationEvaluationContext(
            transit_days=effective_days,
            origin_surface=self._surface_environment(staging_location_id, day),
            destination_surface=self._surface_environment(target_cell_id, day),
        )
        present_operations: set[str] = set()
        for index, operation in enumerate(operations):
            present_operations.add(operation.operation_type)
            capability = performance.capability_for(operation.operation_type)
            failures.extend(self.operation_registry.evaluate(operation, capability, context))
            if (
                capability is not None
                and getattr(capability, "asset_disposition", OperationAssetDisposition.DESTINATION)
                is OperationAssetDisposition.ORIGIN
                and index < len(operations) - 1
            ):
                failures.append(
                    f"operation:{operation.operation_type}:asset_returns_before_deployment_complete"
                )
        failures.extend(performance.endurance_failures(effective_days))

        staging_power = self.power.snapshot(staging_location_id, self.facilities, day)
        for failure in evaluate_site_requirements(
            staging_requirements,
            staging_location_id,
            day,
            self.facilities.environment,
            self.facilities,
            staging_power,
        ):
            failures.append(f"staging:{failure.code}:{failure.detail}")
        # Founding target capabilities cannot exist yet; target requirements are
        # therefore restricted to environment and validated as such by Content.
        for failure in evaluate_site_requirements(
            target_requirements,
            staging_location_id,
            day,
            self.facilities.environment,
            self.facilities,
            staging_power,
            environment_context_id=target_cell_id,
        ):
            failures.append(f"target:{failure.code}:{failure.detail}")

        for support in performance.operation_support_requirements:
            if support.operation_type not in present_operations:
                continue
            if support.location is OperationSupportLocation.DESTINATION:
                failures.append(
                    f"operation_support:{support.operation_type}:destination:unavailable_before_founding"
                )
                continue
            if not self._has_available_capability(
                staging_location_id, support.capability_id, day, power=staging_power
            ):
                failures.append(
                    f"operation_support:{support.operation_type}:origin:{support.capability_id}"
                )

        propellant_resource_id, propellant_t = self.deployment_propellant_t(
            vehicle_definition_id, operations, payload_t
        )
        if propellant_t > performance.propellant_capacity_t + 1e-9:
            failures.append(f"propellant_capacity:{propellant_t:g}/{performance.propellant_capacity_t:g}")
        if propellant_resource_id is not None and propellant_t > 1e-12:
            failures.extend(
                f"propellant_support:{failure}"
                for failure in self.resource_support_failures(
                    performance,
                    staging_location_id,
                    propellant_resource_id,
                    day,
                    power=staging_power,
                )
            )
        return tuple(dict.fromkeys(failures))

    def vehicle_route_physical_failures(
        self, route_id: RouteId, vehicle_definition_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        return self.performance_route_failures(
            self.routes[route_id],
            self.vehicle_defs[vehicle_definition_id].performance,
            day,
            include_operation_support=False,
        )

    def vehicle_route_failures(
        self, route_id: RouteId, vehicle_definition_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        return self.performance_route_failures(
            self.routes[route_id], self.vehicle_defs[vehicle_definition_id].performance, day
        )

    def service_route_failures(
        self, route_id: RouteId, service_id: DefinitionId, day: int = 0
    ) -> tuple[str, ...]:
        route = self.routes[route_id]
        service = self.external_services[service_id]
        failures = list(
            self.performance_route_failures(
                route,
                service.performance,
                day,
                transit_multiplier=service.transit_time_multiplier,
            )
        )
        for prefix, endpoint, requirements in (
            ("origin", route.origin, service.origin_requirements),
            ("destination", route.destination, service.destination_requirements),
        ):
            try:
                resolved = resolve_route_endpoint(endpoint, self.facilities)
            except ValueError as exc:
                failures.append(f"{prefix}:endpoint:{exc}")
                continue
            power = self.power.snapshot(endpoint.location_id, self.facilities, day)
            for failure in evaluate_site_requirements(
                requirements,
                endpoint.location_id,
                day,
                self.facilities.environment,
                self.facilities,
                power,
                environment_context_id=resolved.environment_context_id,
            ):
                failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(failures)

    def _available_capability(
        self,
        location_id: SpatialNodeId,
        capability_id: str,
        day: int,
        *,
        power: PowerSnapshot | None = None,
    ) -> float:
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        return self.facilities.available_capability_capacity_at(
            location_id, capability_id, snapshot, day
        )

    def _has_available_capability(
        self,
        location_id: SpatialNodeId,
        capability_id: str,
        day: int,
        *,
        power: PowerSnapshot | None = None,
    ) -> bool:
        return self._available_capability(
            location_id, capability_id, day, power=power
        ) > 1e-12
