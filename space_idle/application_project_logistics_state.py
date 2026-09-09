from __future__ import annotations

from .application_transport_support import vehicle_concept
from .application_views import CargoOrderRow, CargoOrdersView, TransportMissionRow, TransportMissionsView, VehicleRow, VehiclesView


class LogisticsStateProjectorMixin:
    def _vehicle_rows(
        self,
        *,
        location_id: str | None = None,
        status: str | None = None,
    ) -> tuple[VehicleRow, ...]:
        sim = self._simulation
        rows: list[VehicleRow] = []
        for state in sorted(sim.logistics.vehicles.values(), key=lambda row: str(row.id)):
            if location_id is not None and (
                state.location_id is None or str(state.location_id) != location_id
            ):
                continue
            if status is not None and str(state.status) != status and getattr(state.status, "value", None) != status:
                continue
            definition = sim.logistics.vehicle_defs[state.definition_id]
            rows.append(VehicleRow(
                str(state.id),
                str(definition.id),
                definition.display_name,
                vehicle_concept(definition),
                None if state.location_id is None else str(state.location_id),
                state.status,
                state.available_day,
                definition.payload_t,
                definition.dry_mass_t,
                state.propellant_t,
                definition.propellant_capacity_t,
                None if definition.propellant_resource_id is None else str(definition.propellant_resource_id),
                tuple(sorted(capability.operation_type for capability in definition.performance.operation_capabilities)),
                None if state.transit_destination_id is None else str(state.transit_destination_id),
                definition.turnaround_capability_id,
                definition.turnaround_cost_musd,
                tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.turnaround_resources),
                sim.logistics.vehicle_blockers(state.id, sim.day),
            ))
        return tuple(rows)

    def _mission_rows(self) -> tuple[TransportMissionRow, ...]:
        sim = self._simulation
        return tuple(
            TransportMissionRow(
                str(mission.id),
                str(mission.order_id),
                mission.leg_index,
                str(sim.logistics.orders[mission.order_id].path[mission.leg_index]),
                mission.amount_t,
                mission.mode_id,
                None if mission.vehicle_id is None else str(mission.vehicle_id),
                mission.vehicle_disposition.value,
                mission.status,
                mission.departure_day,
                mission.arrival_day,
                mission.onboard,
                None if mission.handoff_vehicle_id is None else str(mission.handoff_vehicle_id),
            )
            for mission in sorted(sim.logistics.missions.values(), key=lambda row: str(row.id))
        )

    def _order_rows(self) -> tuple[CargoOrderRow, ...]:
        sim = self._simulation
        waiting_by_order: dict[object, float] = {}
        for (order_id, _leg), mass in sim.logistics.waiting.items():
            waiting_by_order[order_id] = waiting_by_order.get(order_id, 0.0) + mass
        transit_by_order: dict[object, float] = {}
        arrival_by_order: dict[object, float] = {}
        for mission in sim.logistics.missions.values():
            mission_status = getattr(mission.status, "value", mission.status)
            if mission_status == "in_transit":
                transit_by_order[mission.order_id] = transit_by_order.get(mission.order_id, 0.0) + mission.amount_t
            elif mission_status in {"arrival_waiting", "waypoint_wait"}:
                arrival_by_order[mission.order_id] = arrival_by_order.get(mission.order_id, 0.0) + mission.amount_t

        rows: list[CargoOrderRow] = []
        for order in sorted(sim.logistics.orders.values(), key=lambda row: str(row.id)):
            waiting = waiting_by_order.get(order.id, 0.0)
            transit = transit_by_order.get(order.id, 0.0)
            arrival_waiting = arrival_by_order.get(order.id, 0.0)
            if sim.logistics.order_complete(order.id):
                status = "complete"
            elif arrival_waiting > 1e-12:
                status = "arrival_waiting"
            elif transit > 1e-12:
                status = "in_transit"
            else:
                status = "waiting"
            rows.append(CargoOrderRow(
                str(order.id),
                order.owner_kind,
                str(order.owner_id),
                str(order.source_id),
                str(order.destination_id),
                str(order.resource_id),
                order.amount_t,
                order.delivered_t,
                order.priority,
                tuple(str(route_id) for route_id in order.path),
                tuple(
                    (str(route_id), mode_id)
                    for route_id, mode_id in sorted(order.mode_by_route.items(), key=lambda row: str(row[0]))
                ),
                order.path_policy.value,
                status,
                waiting,
                transit,
                arrival_waiting,
                sim.logistics.order_blockers(order.id, sim.day),
                None if order.lane_id is None else str(order.lane_id),
                None if order.demand_id is None else str(order.demand_id),
            ))
        return tuple(rows)

    def _vehicles_view(self, query) -> VehiclesView:
        return VehiclesView(self._vehicle_rows(location_id=query.location_id, status=query.status))

    def _cargo_orders_view(self) -> CargoOrdersView:
        return CargoOrdersView(self._order_rows())

    def _transport_missions_view(self) -> TransportMissionsView:
        return TransportMissionsView(self._mission_rows())
