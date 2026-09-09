from __future__ import annotations

from .application_project_logistics_lanes import LogisticsLaneProjectorMixin
from .application_project_logistics_routes import LogisticsRouteProjectorMixin
from .application_project_logistics_state import LogisticsStateProjectorMixin
from .application_views import LogisticsSummaryView, LogisticsView


class LogisticsProjectorMixin(
    LogisticsRouteProjectorMixin,
    LogisticsStateProjectorMixin,
    LogisticsLaneProjectorMixin,
):
    def _logistics_view(self) -> LogisticsView:
        sim = self._simulation
        demands = sim.resource_demands()
        snapshot = sim.logistics.lane_snapshot(demands, sim.day)
        return LogisticsView(
            self._route_rows(),
            self._vehicle_rows(),
            self._mission_rows(),
            self._order_rows(),
            self._lane_rows(demands, snapshot),
            self._demand_rows(demands, snapshot),
        )

    def _logistics_summary_view(self) -> LogisticsSummaryView:
        sim = self._simulation
        routes = self._route_rows(include_modes=False)
        vehicles = self._vehicle_rows()
        missions = self._mission_rows()
        orders = self._order_rows()
        demands = sim.resource_demands()
        snapshot = sim.logistics.lane_snapshot(demands, sim.day)
        lanes = self._lane_rows(demands, snapshot)
        demand_rows = self._demand_rows(demands, snapshot)
        return LogisticsSummaryView(
            route_count=len(routes),
            usable_route_count=sum(1 for row in routes if row.usable_now),
            vehicle_count=len(vehicles),
            available_vehicle_count=sum(
                1 for row in vehicles
                if getattr(row.status, "value", row.status) == "available"
            ),
            mission_count=len(missions),
            order_count=len(orders),
            blocked_order_count=sum(1 for row in orders if row.blockers),
            lane_count=len(lanes),
            paused_lane_count=sum(1 for row in lanes if row.paused),
            demand_count=len(demands),
            queued_demand_t=sum(row.remaining_t for row in demand_rows),
            waiting_t=sum(row.waiting_t for row in orders),
            in_transit_t=sum(row.in_transit_t for row in orders),
            arrival_waiting_t=sum(row.arrival_waiting_t for row in orders),
        )
