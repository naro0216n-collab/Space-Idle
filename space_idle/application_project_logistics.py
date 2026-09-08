from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Mapping

from .application_views import (
    CargoOrderRow, CargoOrdersView, LogisticsRuleRow, LogisticsRulesView,
    LogisticsSummaryView, LogisticsView, RouteModeRow, RouteRow, RoutesView,
    TransportMissionRow, TransportMissionsView, TransportPathOptionRow,
    TransportPlansView, VehicleRow, VehiclesView,
)
from .shared import DefinitionId, SpatialNodeId


class LogisticsProjectorMixin:
    def _transport_value(self, value: object) -> object:
        if isinstance(value, Mapping):
            return tuple(
                (str(k), self._transport_value(v))
                for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            )
        if isinstance(value, (tuple, list)):
            return tuple(self._transport_value(v) for v in value)
        return value

    def _route_rows(
        self,
        *,
        origin_id: str | None = None,
        destination_id: str | None = None,
        route_id: str | None = None,
        include_modes: bool = True,
    ) -> tuple[RouteRow, ...]:
        sim = self._simulation
        routes: list[RouteRow] = []
        for route in sorted(sim.logistics.routes.values(), key=lambda row: str(row.id)):
            if origin_id is not None and str(route.origin_id) != origin_id:
                continue
            if destination_id is not None and str(route.destination_id) != destination_id:
                continue
            if route_id is not None and str(route.id) != route_id:
                continue
            route_blockers = sim.logistics.route_failures(route.id, sim.day)
            operational_blockers = sim.logistics.route_operational_failures(route.id, sim.day)
            mode_rows: list[RouteModeRow] = []
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
                        available_ids = sim.logistics.available_vehicle_ids(route.id, definition_id, sim.day)
                        available_count = len(available_ids)
                        cost = vehicle.operating_cost_musd_per_cargo_t
                        propellant_resource_id = None if vehicle.propellant_resource_id is None else str(vehicle.propellant_resource_id)
                        full_load_propellant = vehicle.propellant_t(route, vehicle.max_cargo_for_route(route))
                        kind = self._vehicle_concept(vehicle)
                        display_name = vehicle.display_name
                    mode_blockers = sim.logistics.route_operational_failures(route.id, sim.day, mode_id)
                    mode_rows.append(RouteModeRow(
                        mode_id, display_name, kind, vehicle_definition_id, available_count,
                        sim.logistics.route_dispatch_capacity_t(route.id, sim.day, mode_id),
                        sim.logistics.route_mode_transit_days(route.id, mode_id, sim.day), cost,
                        propellant_resource_id, full_load_propellant, not mode_blockers, mode_blockers,
                    ))
            routes.append(RouteRow(
                str(route.id), route.display_name or str(route.id), str(route.origin_id), str(route.destination_id),
                not route_blockers, not operational_blockers,
                sim.logistics.route_dispatch_capacity_t(route.id, sim.day), route.transit_days, route.delta_v_km_s,
                tuple((operation.operation_type, operation.delta_v_km_s) for operation in route.operations),
                route_blockers, operational_blockers, tuple(mode_rows),
            ))
        return tuple(routes)

    def _vehicle_rows(
        self,
        *,
        location_id: str | None = None,
        status: str | None = None,
    ) -> tuple[VehicleRow, ...]:
        sim = self._simulation
        vehicles: list[VehicleRow] = []
        for state in sorted(sim.logistics.vehicles.values(), key=lambda row: str(row.id)):
            if location_id is not None and (state.location_id is None or str(state.location_id) != location_id):
                continue
            if status is not None and str(state.status) != status and getattr(state.status, "value", None) != status:
                continue
            definition = sim.logistics.vehicle_defs[state.definition_id]
            capability_names = tuple(sorted(capability.operation_type for capability in definition.performance.operation_capabilities))
            vehicles.append(VehicleRow(
                str(state.id), str(definition.id), definition.display_name, self._vehicle_concept(definition),
                None if state.location_id is None else str(state.location_id), state.status, state.available_day,
                definition.payload_t, definition.dry_mass_t, state.propellant_t, definition.propellant_capacity_t,
                None if definition.propellant_resource_id is None else str(definition.propellant_resource_id),
                capability_names,
                None if state.transit_destination_id is None else str(state.transit_destination_id),
                definition.turnaround_capability_id, definition.turnaround_cost_musd,
                tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.turnaround_resources),
                sim.logistics.vehicle_blockers(state.id, sim.day),
            ))
        return tuple(vehicles)

    def _mission_rows(self) -> tuple[TransportMissionRow, ...]:
        sim = self._simulation
        return tuple(
            TransportMissionRow(
                str(mission.id), str(mission.order_id), mission.leg_index,
                str(sim.logistics.orders[mission.order_id].path[mission.leg_index]),
                mission.amount_t, mission.mode_id,
                None if mission.vehicle_id is None else str(mission.vehicle_id),
                mission.vehicle_disposition.value, mission.status,
                mission.departure_day, mission.arrival_day, mission.onboard,
                None if mission.handoff_vehicle_id is None else str(mission.handoff_vehicle_id),
            )
            for mission in sorted(sim.logistics.missions.values(), key=lambda row: str(row.id))
        )

    def _order_rows(self) -> tuple[CargoOrderRow, ...]:
        sim = self._simulation
        orders: list[CargoOrderRow] = []
        for order in sorted(sim.logistics.orders.values(), key=lambda row: str(row.id)):
            waiting = sum(mass for (oid, _), mass in sim.logistics.waiting.items() if oid == order.id)
            order_missions = [mission for mission in sim.logistics.missions.values() if mission.order_id == order.id]
            transit = sum(
                mission.amount_t for mission in order_missions
                if getattr(mission.status, "value", mission.status) == "in_transit"
            )
            arrival_waiting = sum(
                mission.amount_t for mission in order_missions
                if getattr(mission.status, "value", mission.status) in {"arrival_waiting", "waypoint_wait"}
            )
            if sim.logistics.order_complete(order.id):
                status = "complete"
            elif arrival_waiting > 1e-12:
                status = "arrival_waiting"
            elif transit > 1e-12:
                status = "in_transit"
            else:
                status = "waiting"
            orders.append(CargoOrderRow(
                str(order.id), order.owner_kind, str(order.owner_id),
                str(order.source_id), str(order.destination_id), str(order.resource_id),
                order.amount_t, order.delivered_t, order.priority, tuple(str(x) for x in order.path),
                tuple((str(route_id), mode_id) for route_id, mode_id in sorted(order.mode_by_route.items(), key=lambda row: str(row[0]))),
                order.path_policy.value, status, waiting, transit, arrival_waiting,
                sim.logistics.order_blockers(order.id, sim.day),
            ))
        return tuple(orders)

    def _rule_rows(self) -> tuple[LogisticsRuleRow, ...]:
        sim = self._simulation
        return tuple(
            LogisticsRuleRow(
                str(rule.id), str(rule.source_id), str(rule.destination_id), str(rule.resource_id),
                rule.target_stock_t, rule.batch_t, rule.priority,
                None if rule.path is None else tuple(str(x) for x in rule.path),
                tuple((str(route_id), mode_id) for route_id, mode_id in sorted(rule.mode_by_route.items(), key=lambda row: str(row[0]))),
                rule.path_policy.value, rule.paused, sim.logistics.recurring_rule_blockers(rule.id, sim.day),
            )
            for rule in sorted(sim.logistics.recurring_rules.values(), key=lambda row: str(row.id))
        )

    def _logistics_view(self) -> LogisticsView:
        return LogisticsView(
            self._route_rows(), self._vehicle_rows(), self._mission_rows(),
            self._order_rows(), self._rule_rows(),
        )

    def _logistics_summary_view(self) -> LogisticsSummaryView:
        routes = self._route_rows(include_modes=False)
        vehicles = self._vehicle_rows()
        missions = self._mission_rows()
        orders = self._order_rows()
        rules = self._rule_rows()
        return LogisticsSummaryView(
            route_count=len(routes),
            usable_route_count=sum(1 for row in routes if row.usable_now),
            vehicle_count=len(vehicles),
            available_vehicle_count=sum(1 for row in vehicles if getattr(row.status, "value", row.status) == "available"),
            mission_count=len(missions),
            order_count=len(orders),
            blocked_order_count=sum(1 for row in orders if row.blockers),
            rule_count=len(rules),
            paused_rule_count=sum(1 for row in rules if row.paused),
            waiting_t=sum(row.waiting_t for row in orders),
            in_transit_t=sum(row.in_transit_t for row in orders),
            arrival_waiting_t=sum(row.arrival_waiting_t for row in orders),
        )

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

    def _vehicles_view(self, query) -> VehiclesView:
        return VehiclesView(self._vehicle_rows(location_id=query.location_id, status=query.status))

    def _cargo_orders_view(self) -> CargoOrdersView:
        return CargoOrdersView(self._order_rows())

    def _logistics_rules_view(self) -> LogisticsRulesView:
        return LogisticsRulesView(self._rule_rows())

    def _transport_missions_view(self) -> TransportMissionsView:
        return TransportMissionsView(self._mission_rows())

    def _transport_plans_view(self, source_id: SpatialNodeId, destination_id: SpatialNodeId) -> TransportPlansView:
        from .logistics import PathPolicy

        sim = self._simulation
        options: list[TransportPathOptionRow] = []
        for policy in PathPolicy:
            try:
                path = sim.logistics.find_path(source_id, destination_id, sim.day, policy)
            except ValueError:
                continue
            mode_plan = sim.logistics._automatic_mode_plan(path, sim.day, policy)
            if mode_plan is None:
                continue
            options.append(TransportPathOptionRow(
                policy.value,
                tuple(str(route_id) for route_id in path),
                tuple((str(route_id), mode_plan[route_id]) for route_id in path),
                sum(sim.logistics.route_mode_transit_days(route_id, mode_plan[route_id], sim.day) for route_id in path),
                sum(sim.logistics._mode_cost_musd_per_t(route_id, mode_plan[route_id]) for route_id in path),
                sum(sim.logistics._mode_propellant_t_per_cargo_t(route_id, mode_plan[route_id]) for route_id in path),
            ))
        return TransportPlansView(str(source_id), str(destination_id), tuple(options))
