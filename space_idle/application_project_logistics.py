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
            routes=self._route_rows(),
            fleet_pools=self._fleet_pool_rows(),
            relocations=self._fleet_relocation_rows(),
            releases=self._fleet_release_rows(),
            allocations=self._transport_allocation_rows(),
            vehicle_production_options=self._vehicle_production_option_rows(),
            vehicle_production=self._vehicle_production_rows(),
            cargo_flows=self._cargo_flow_rows(),
            lanes=self._lane_rows(demands, snapshot),
            demands=self._demand_rows(demands, snapshot),
        )

    def _logistics_summary_view(self) -> LogisticsSummaryView:
        sim = self._simulation
        routes = self._route_rows(include_modes=False)
        pools = self._fleet_pool_rows()
        allocations = self._transport_allocation_rows()
        flows = self._cargo_flow_rows()
        demands = sim.resource_demands()
        snapshot = sim.logistics.lane_snapshot(demands, sim.day)
        lanes = self._lane_rows(demands, snapshot)
        demand_rows = self._demand_rows(demands, snapshot)
        return LogisticsSummaryView(
            route_count=len(routes),
            usable_route_count=sum(1 for row in routes if row.service_feasible_now),
            fleet_units=sum(row.total_units for row in pools),
            free_fleet_units=sum(row.free_units for row in pools),
            allocation_count=len(allocations),
            unfilled_allocation_units=sum(row.unfilled_units for row in allocations),
            cargo_flow_count=len(flows),
            lane_count=len(lanes),
            paused_lane_count=sum(1 for row in lanes if row.paused),
            demand_count=len(demand_rows),
            queued_demand_t=sum(row.remaining_t for row in demand_rows),
            in_transit_t=sum(row.amount_t for row in flows if row.status == "in_transit"),
            arrival_waiting_t=sum(row.amount_t for row in flows if row.status == "arrival_waiting"),
        )
