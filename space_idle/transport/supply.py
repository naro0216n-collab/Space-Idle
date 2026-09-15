from __future__ import annotations

from ..shared import SpatialNodeId
from ..priority import DEFAULT_ACTIVITY_PRIORITY
from .models import (
    TransportOperationDependencyProjection,
    TransportServiceSupply,
)


class TransportSupplyMixin:
    """Publish Transport-owned service and operation dependency projections.

    Logistics consumes these immutable projections instead of reading Fleet,
    Vehicle, Route, or external-service state directly. Transport remains the
    sole interpreter of those definitions and commitments; Logistics remains
    responsible for path selection and shared-capacity allocation.
    """

    def transport_service_supplies(self, day: int) -> tuple[TransportServiceSupply, ...]:
        supplies: list[TransportServiceSupply] = []
        for allocation in sorted(
            self.transport_allocations.values(),
            key=lambda row: (
                str(row.vehicle_definition_id),
                str(row.anchor_node_id),
                str(row.destination_id),
                str(row.id),
            ),
        ):
            plan = self.derive_transport_service_plan(allocation.id, day)
            if (
                not plan.feasible
                or allocation.paused
                or self.transport_active_units(allocation.id) <= 0
            ):
                continue
            snapshot = self.transport_capacity_snapshot(allocation.id, day=day)
            definition = self.vehicle_defs[allocation.vehicle_definition_id]
            propellant_id = definition.propellant_resource_id
            empty_propellant = sum(
                amount
                for _location_id, resource_id, amount in plan.resource_t_per_empty_cycle_day
                if resource_id == propellant_id
            )
            forward_increment = sum(
                amount
                for _location_id, resource_id, amount
                in plan.resource_t_per_forward_payload_increment_day
                if resource_id == propellant_id
            )
            reverse_increment = sum(
                amount
                for _location_id, resource_id, amount
                in plan.resource_t_per_reverse_payload_increment_day
                if resource_id == propellant_id
            )
            forward_propellant_per_t = (
                0.0
                if plan.nominal_per_unit.forward_t_per_day <= 1e-12
                else (empty_propellant + forward_increment)
                / plan.nominal_per_unit.forward_t_per_day
            )
            reverse_propellant_per_t = (
                0.0
                if plan.nominal_per_unit.reverse_t_per_day <= 1e-12
                else (empty_propellant + reverse_increment)
                / plan.nominal_per_unit.reverse_t_per_day
            )
            if snapshot.available.forward_t_per_day > 1e-12:
                supplies.append(
                    TransportServiceSupply(
                        key=f"allocation:{allocation.id}:forward",
                        source_id=allocation.anchor_node_id,
                        destination_id=allocation.destination_id,
                        capacity_t_per_day=snapshot.available.forward_t_per_day,
                        latency_days=max(1, plan.forward_latency_days),
                        route_path=plan.forward_path,
                        allocation_id=allocation.id,
                        direction="forward",
                        propellant_t_per_t=forward_propellant_per_t,
                    )
                )
            if snapshot.available.reverse_t_per_day > 1e-12 and plan.reverse_path:
                supplies.append(
                    TransportServiceSupply(
                        key=f"allocation:{allocation.id}:reverse",
                        source_id=allocation.destination_id,
                        destination_id=allocation.anchor_node_id,
                        capacity_t_per_day=snapshot.available.reverse_t_per_day,
                        latency_days=max(1, plan.reverse_latency_days or 1),
                        route_path=plan.reverse_path,
                        allocation_id=allocation.id,
                        direction="reverse",
                        propellant_t_per_t=reverse_propellant_per_t,
                    )
                )

        for service in sorted(self.external_services.values(), key=lambda row: str(row.id)):
            if service.capacity_t_per_day <= 1e-12:
                continue
            for route in sorted(self.routes.values(), key=lambda row: str(row.id)):
                if self.service_route_failures(route.id, service.id, day):
                    continue
                supplies.append(
                    TransportServiceSupply(
                        key=f"external:{service.id}:{route.id}",
                        source_id=route.origin_id,
                        destination_id=route.destination_id,
                        capacity_t_per_day=service.capacity_t_per_day,
                        latency_days=self.performance_route_transit_days(
                            route,
                            service.performance,
                            transit_multiplier=service.transit_time_multiplier,
                        ),
                        route_path=(route.id,),
                        external_service_id=service.id,
                        cost_musd_per_t=service.cost_musd_per_t,
                    )
                )
        return tuple(supplies)

    def transport_operation_dependencies(
        self, day: int
    ) -> tuple[TransportOperationDependencyProjection, ...]:
        rows: list[TransportOperationDependencyProjection] = []
        for allocation in sorted(self.transport_allocations.values(), key=lambda row: str(row.id)):
            definition = self.vehicle_defs[allocation.vehicle_definition_id]
            service_plan = self.derive_transport_service_plan(allocation.id, day)
            surface_locations: set[SpatialNodeId] = set()
            for route_id in service_plan.forward_path + service_plan.reverse_path:
                geometry = self.route_geometry(route_id)
                for endpoint in (geometry.origin, geometry.destination):
                    if endpoint.surface_cell_id is not None:
                        surface_locations.add(endpoint.node_id)
            rows.append(
                TransportOperationDependencyProjection(
                    allocation_id=allocation.id,
                    priority=DEFAULT_ACTIVITY_PRIORITY,
                    anchor_node_id=allocation.anchor_node_id,
                    turnaround_service_type=definition.turnaround_service_type,
                    turnaround_request_id=(
                        None
                        if definition.turnaround_service_type is None
                        else self.transport_service_request_id(allocation.id)
                    ),
                    surface_service_locations=tuple(sorted(surface_locations, key=str)),
                )
            )
        return tuple(rows)
