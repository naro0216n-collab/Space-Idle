from __future__ import annotations

from .application_transport_support import infrastructure_requirement_rows, vehicle_concept
from .application_views import (
    DirectionalCapacityRow,
    RouteEndpointRow,
    RouteModeRow,
    RouteRow,
    RoutesView,
    TransportAllocationOptionRow,
    TransportAllocationOptionsView,
)
from .logistics import PathPolicy


class LogisticsRouteProjectorMixin:
    @staticmethod
    def _directional_capacity_row(value) -> DirectionalCapacityRow:
        return DirectionalCapacityRow(
            value.forward_t_per_day, value.reverse_t_per_day
        )

    def _route_mode_rows(self, route) -> tuple[RouteModeRow, ...]:
        sim = self._simulation
        rows: list[RouteModeRow] = []

        for definition in sorted(
            sim.logistics.vehicle_defs.values(), key=lambda row: str(row.id)
        ):
            plan = sim.logistics.transport_service_plan_for(
                definition.id,
                route.origin_id,
                route.destination_id,
                day=sim.day,
                path=(route.id,),
            )
            fleet = sim.logistics.fleet_pool_snapshot(
                definition.id, route.origin_id
            )
            full_load_propellant = None
            if definition.propellant_resource_id is not None:
                full_load_propellant = definition.propellant_t(
                    route, max(0.0, plan.forward_payload_t)
                )
            rows.append(
                RouteModeRow(
                    id=str(definition.id),
                    display_name=definition.display_name,
                    kind=vehicle_concept(definition),
                    vehicle_definition_id=str(definition.id),
                    fleet_total_units=fleet.total_units,
                    fleet_free_units=fleet.free_units,
                    nominal_capacity=self._directional_capacity_row(
                        plan.nominal_per_unit
                    ),
                    cycle_days=plan.cycle_days,
                    forward_latency_days=plan.forward_latency_days,
                    reverse_latency_days=plan.reverse_latency_days,
                    cost_musd_per_t=definition.operating_cost_musd_per_cargo_t,
                    propellant_resource_id=(
                        None
                        if definition.propellant_resource_id is None
                        else str(definition.propellant_resource_id)
                    ),
                    full_load_propellant_t=full_load_propellant,
                    service_feasible=plan.feasible,
                    infrastructure_requirements=infrastructure_requirement_rows(plan),
                    blockers=plan.blockers,
                )
            )

        for service in sorted(
            sim.logistics.external_services.values(), key=lambda row: str(row.id)
        ):
            blockers = tuple(
                dict.fromkeys(
                    sim.logistics.route_failures(route.id, sim.day)
                    + sim.logistics.service_route_failures(
                        route.id, service.id, sim.day
                    )
                )
            )
            rows.append(
                RouteModeRow(
                    id=str(service.id),
                    display_name=service.display_name,
                    kind="external_service",
                    vehicle_definition_id=None,
                    fleet_total_units=0,
                    fleet_free_units=0,
                    nominal_capacity=DirectionalCapacityRow(
                        service.capacity_t_per_day, 0.0
                    ),
                    cycle_days=None,
                    forward_latency_days=sim.logistics.performance_route_transit_days(
                        route,
                        service.performance,
                        transit_multiplier=service.transit_time_multiplier,
                    ),
                    reverse_latency_days=None,
                    cost_musd_per_t=service.cost_musd_per_t,
                    propellant_resource_id=None,
                    full_load_propellant_t=None,
                    service_feasible=(
                        service.capacity_t_per_day > 1e-12 and not blockers
                    ),
                    infrastructure_requirements=(),
                    blockers=blockers,
                )
            )
        return tuple(rows)

    def _route_rows(
        self,
        *,
        origin_id: str | None = None,
        destination_id: str | None = None,
        route_id: str | None = None,
        include_modes: bool = True,
    ) -> tuple[RouteRow, ...]:
        sim = self._simulation
        sim.logistics.synchronize_surface_access_routes()
        rows: list[RouteRow] = []
        for route in sorted(sim.logistics.routes.values(), key=lambda row: str(row.id)):
            if origin_id is not None and str(route.origin_id) != origin_id:
                continue
            if destination_id is not None and str(route.destination_id) != destination_id:
                continue
            if route_id is not None and str(route.id) != route_id:
                continue
            route_blockers = sim.logistics.route_failures(route.id, sim.day)
            mode_rows = self._route_mode_rows(route)
            try:
                geometry = sim.logistics.route_geometry(route.id)
                origin_endpoint = RouteEndpointRow(
                    str(geometry.origin.location_id), geometry.origin.locator_kind,
                    geometry.origin.locator_id,
                    None if geometry.origin.surface_cell_id is None else str(geometry.origin.surface_cell_id),
                )
                destination_endpoint = RouteEndpointRow(
                    str(geometry.destination.location_id), geometry.destination.locator_kind,
                    geometry.destination.locator_id,
                    None if geometry.destination.surface_cell_id is None else str(geometry.destination.surface_cell_id),
                )
                same_body_surface = geometry.same_body_surface
                distance_km = geometry.distance_km
            except ValueError:
                origin_endpoint = RouteEndpointRow(
                    str(route.origin_id), route.origin.locator_kind, route.origin.locator_id, None
                )
                destination_endpoint = RouteEndpointRow(
                    str(route.destination_id), route.destination.locator_kind, route.destination.locator_id, None
                )
                same_body_surface = False
                distance_km = None
            rows.append(
                RouteRow(
                    id=str(route.id),
                    display_name=route.display_name or str(route.id),
                    origin_id=str(route.origin_id),
                    destination_id=str(route.destination_id),
                    origin_endpoint=origin_endpoint,
                    destination_endpoint=destination_endpoint,
                    same_body_surface=same_body_surface,
                    distance_km=distance_km,
                    available=not route_blockers,
                    service_feasible_now=any(
                        row.service_feasible for row in mode_rows
                    ),
                    transit_days=route.transit_days,
                    delta_v_km_s=route.delta_v_km_s,
                    operations=tuple(
                        (operation.operation_type, operation.delta_v_km_s)
                        for operation in route.operations
                    ),
                    blockers=route_blockers,
                    modes=mode_rows if include_modes else (),
                )
            )
        return tuple(rows)

    def _routes_view(self, query) -> RoutesView:
        rows = self._route_rows(
            origin_id=query.origin_id,
            destination_id=query.destination_id,
            route_id=query.route_id,
            include_modes=query.include_modes,
        )
        if query.route_id is not None and not rows:
            raise KeyError(query.route_id)
        return RoutesView(rows)

    def _transport_allocation_options_view(
        self, source_id, destination_id
    ) -> TransportAllocationOptionsView:
        sim = self._simulation
        sim.logistics.synchronize_surface_access_routes()
        options: list[TransportAllocationOptionRow] = []
        for definition in sorted(
            sim.logistics.vehicle_defs.values(), key=lambda row: str(row.id)
        ):
            fleet = sim.logistics.fleet_pool_snapshot(definition.id, source_id)
            for policy in PathPolicy:
                plan = sim.logistics.transport_service_plan_for(
                    definition.id,
                    source_id,
                    destination_id,
                    day=sim.day,
                    path_policy=policy,
                )
                options.append(
                    TransportAllocationOptionRow(
                        vehicle_definition_id=str(definition.id),
                        display_name=definition.display_name,
                        source_id=str(source_id),
                        destination_id=str(destination_id),
                        policy=policy.value,
                        forward_path=tuple(str(value) for value in plan.forward_path),
                        reverse_path=tuple(str(value) for value in plan.reverse_path),
                        cycle_days=plan.cycle_days,
                        forward_latency_days=plan.forward_latency_days,
                        reverse_latency_days=plan.reverse_latency_days,
                        nominal_capacity=self._directional_capacity_row(
                            plan.nominal_per_unit
                        ),
                        fleet_total_units=fleet.total_units,
                        fleet_free_units=fleet.free_units,
                        operational_resource_demand_at_full_unit=tuple(
                            (str(location_id), str(resource_id), amount)
                            for location_id, resource_id, amount
                            in plan.resource_t_per_full_utilization_day
                        ),
                        infrastructure_requirements=infrastructure_requirement_rows(plan),
                        blockers=plan.blockers,
                    )
                )
        return TransportAllocationOptionsView(
            str(source_id), str(destination_id), tuple(options)
        )
