from __future__ import annotations

from .application_views import LogisticsLaneRow, LogisticsLanesView, ResourceDemandRow


class LogisticsLaneProjectorMixin:
    def _demand_rows(self, demands=None) -> tuple[ResourceDemandRow, ...]:
        sim = self._simulation
        demand_rows = sim.resource_demands() if demands is None else tuple(demands)
        return tuple(
            ResourceDemandRow(
                str(demand.id),
                demand.owner_kind,
                str(demand.owner_id),
                None if demand.source_id is None else str(demand.source_id),
                str(demand.destination_id),
                str(demand.resource_id),
                demand.amount_t,
                sim.logistics.demand_pipeline_t(demand.id),
                sim.logistics.demand_remaining_t(demand),
                demand.priority,
            )
            for demand in demand_rows
        )

    def _lane_rows(self, demands=None) -> tuple[LogisticsLaneRow, ...]:
        sim = self._simulation
        demand_rows = sim.resource_demands() if demands is None else tuple(demands)
        return tuple(
            LogisticsLaneRow(
                str(lane.id),
                str(lane.source_id),
                str(lane.destination_id),
                lane.requested_capacity_t_per_day,
                sim.logistics.lane_effective_capacity_t_per_day(lane.id, sim.day),
                sim.logistics.lane_used_t(lane.id, sim.day),
                sim.logistics.lane_queued_t(lane.id, demand_rows),
                lane.priority,
                None if lane.path is None else tuple(str(route_id) for route_id in lane.path),
                tuple(
                    (str(route_id), mode_id)
                    for route_id, mode_id in sorted(lane.mode_by_route.items(), key=lambda row: str(row[0]))
                ),
                lane.path_policy.value,
                lane.paused,
                sim.logistics.lane_blockers(lane.id, sim.day),
            )
            for lane in sorted(sim.logistics.lanes.values(), key=lambda row: str(row.id))
        )

    def _logistics_lanes_view(self) -> LogisticsLanesView:
        demands = self._simulation.resource_demands()
        return LogisticsLanesView(self._lane_rows(demands), self._demand_rows(demands))
