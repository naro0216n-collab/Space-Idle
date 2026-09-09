from __future__ import annotations

from .application_views import LogisticsLaneRow, LogisticsLanesView, ResourceDemandRow


class LogisticsLaneProjectorMixin:
    def _demand_rows(self, demands=None, snapshot=None) -> tuple[ResourceDemandRow, ...]:
        sim = self._simulation
        demand_rows = sim.resource_demands() if demands is None else tuple(demands)
        lane_snapshot = sim.logistics.lane_snapshot(demand_rows, sim.day) if snapshot is None else snapshot
        pipeline = dict(lane_snapshot.demand_pipeline_t)
        return tuple(
            ResourceDemandRow(
                str(demand.id),
                demand.owner_kind,
                str(demand.owner_id),
                None if demand.source_id is None else str(demand.source_id),
                str(demand.destination_id),
                str(demand.resource_id),
                demand.amount_t,
                pipeline.get(demand.id, 0.0),
                max(0.0, demand.amount_t - pipeline.get(demand.id, 0.0)),
                demand.priority,
            )
            for demand in demand_rows
        )

    def _lane_rows(self, demands=None, snapshot=None) -> tuple[LogisticsLaneRow, ...]:
        sim = self._simulation
        demand_rows = sim.resource_demands() if demands is None else tuple(demands)
        lane_snapshot = sim.logistics.lane_snapshot(demand_rows, sim.day) if snapshot is None else snapshot
        metrics = {row.lane_id: row for row in lane_snapshot.lanes}
        return tuple(
            LogisticsLaneRow(
                str(lane.id),
                str(lane.source_id),
                str(lane.destination_id),
                lane.requested_capacity_t_per_day,
                metrics[lane.id].effective_capacity_t_per_day,
                metrics[lane.id].used_t,
                metrics[lane.id].queued_t,
                lane.priority,
                None if lane.path is None else tuple(str(route_id) for route_id in lane.path),
                tuple(
                    (str(route_id), mode_id)
                    for route_id, mode_id in sorted(lane.mode_by_route.items(), key=lambda row: str(row[0]))
                ),
                lane.path_policy.value,
                lane.paused,
                metrics[lane.id].blockers,
            )
            for lane in sorted(sim.logistics.lanes.values(), key=lambda row: str(row.id))
        )

    def _logistics_lanes_view(self) -> LogisticsLanesView:
        sim = self._simulation
        demands = sim.resource_demands()
        snapshot = sim.logistics.lane_snapshot(demands, sim.day)
        return LogisticsLanesView(
            self._lane_rows(demands, snapshot),
            self._demand_rows(demands, snapshot),
        )
