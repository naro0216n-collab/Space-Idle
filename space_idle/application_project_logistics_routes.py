from __future__ import annotations

from .application_transport_support import vehicle_concept
from .application_views import RouteModeRow, RouteRow, RoutesView, TransportPathOptionRow, TransportPlansView
from .logistics import PathPolicy
from .shared import DefinitionId, SpatialNodeId


class LogisticsRouteProjectorMixin:
    def _route_rows(
        self,
        *,
        origin_id: str | None = None,
        destination_id: str | None = None,
        route_id: str | None = None,
        include_modes: bool = True,
    ) -> tuple[RouteRow, ...]:
        sim = self._simulation
        rows: list[RouteRow] = []
        for route in sorted(sim.logistics.routes.values(), key=lambda row: str(row.id)):
            if origin_id is not None and str(route.origin_id) != origin_id:
                continue
            if destination_id is not None and str(route.destination_id) != destination_id:
                continue
            if route_id is not None and str(route.id) != route_id:
                continue
            route_blockers = sim.logistics.route_failures(route.id, sim.day)
            operational_blockers = sim.logistics.route_operational_failures(route.id, sim.day)
            modes: list[RouteModeRow] = []
            if include_modes:
                for mode_id in sim.logistics.route_mode_ids(route.id, sim.day):
                    service = sim.logistics.external_services.get(DefinitionId(mode_id))
                    if service is not None:
                        vehicle_definition_id = None
                        available_count = 0
                        cost = service.cost_musd_per_t
                        propellant_resource_id = None
                        full_load_propellant = None
                        kind = "external_service"
                        display_name = service.display_name
                    else:
                        definition_id = DefinitionId(mode_id)
                        vehicle = sim.logistics.vehicle_defs[definition_id]
                        vehicle_definition_id = mode_id
                        available_count = len(sim.logistics.available_vehicle_ids(route.id, definition_id, sim.day))
                        cost = vehicle.operating_cost_musd_per_cargo_t
                        propellant_resource_id = None if vehicle.propellant_resource_id is None else str(vehicle.propellant_resource_id)
                        full_load_propellant = vehicle.propellant_t(route, vehicle.max_cargo_for_route(route))
                        kind = vehicle_concept(vehicle)
                        display_name = vehicle.display_name
                    mode_blockers = sim.logistics.route_operational_failures(route.id, sim.day, mode_id)
                    modes.append(RouteModeRow(
                        mode_id,
                        display_name,
                        kind,
                        vehicle_definition_id,
                        available_count,
                        sim.logistics.route_dispatch_capacity_t(route.id, sim.day, mode_id),
                        sim.logistics.route_mode_transit_days(route.id, mode_id, sim.day),
                        cost,
                        propellant_resource_id,
                        full_load_propellant,
                        not mode_blockers,
                        mode_blockers,
                    ))
            rows.append(RouteRow(
                str(route.id),
                route.display_name or str(route.id),
                str(route.origin_id),
                str(route.destination_id),
                not route_blockers,
                not operational_blockers,
                sim.logistics.route_dispatch_capacity_t(route.id, sim.day),
                route.transit_days,
                route.delta_v_km_s,
                tuple((operation.operation_type, operation.delta_v_km_s) for operation in route.operations),
                route_blockers,
                operational_blockers,
                tuple(modes),
            ))
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

    def _transport_plans_view(
        self, source_id: SpatialNodeId, destination_id: SpatialNodeId
    ) -> TransportPlansView:
        sim = self._simulation
        options: list[TransportPathOptionRow] = []
        for policy in PathPolicy:
            try:
                plan = sim.logistics.transport_plan(source_id, destination_id, sim.day, policy)
            except ValueError:
                continue
            options.append(TransportPathOptionRow(
                policy.value,
                tuple(str(route_id) for route_id in plan.path),
                tuple((str(route_id), mode_id) for route_id, mode_id in plan.mode_by_route),
                plan.transit_days,
                plan.estimated_cost_musd_per_t,
                plan.estimated_propellant_t_per_cargo_t,
            ))
        return TransportPlansView(str(source_id), str(destination_id), tuple(options))
