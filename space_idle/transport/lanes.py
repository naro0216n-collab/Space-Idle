from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..resource_demand import ResourceDemand
from ..shared import EntityId, RouteId
from .models import LogisticsLane, MissionStatus, PathPolicy


@dataclass(frozen=True)
class LaneRuntimeMetrics:
    lane_id: EntityId
    effective_capacity_t_per_day: float
    used_t: float
    queued_t: float
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class LogisticsLaneSnapshot:
    demand_pipeline_t: tuple[tuple[EntityId, float], ...]
    lanes: tuple[LaneRuntimeMetrics, ...]


class TransportLaneMixin:
    """Player lane configuration and allocation of domain ResourceDemand."""

    def create_lane(
        self,
        source_id,
        destination_id,
        requested_capacity_t_per_day: float,
        priority: int,
        path: tuple[RouteId, ...] | None = None,
        mode_by_route: dict[RouteId, str] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
    ) -> EntityId:
        selected_modes = {} if mode_by_route is None else dict(mode_by_route)
        if path is None and selected_modes:
            raise ValueError("explicit transport modes require an explicit route path for lanes")
        if path is not None:
            self.validate_path_structure(source_id, destination_id, path)
            self.validate_mode_selection(path, selected_modes)
        self._lane_counter += 1
        lane_id = EntityId(f"logistics.lane.{self._lane_counter}")
        self.lanes[lane_id] = LogisticsLane(
            lane_id, source_id, destination_id, requested_capacity_t_per_day,
            priority, path, selected_modes, path_policy, False,
        )
        return lane_id

    def pause_lane(self, lane_id: EntityId) -> None:
        self.lanes[lane_id].paused = True

    def resume_lane(self, lane_id: EntityId) -> None:
        self.lanes[lane_id].paused = False

    def delete_lane(self, lane_id: EntityId) -> None:
        self.lanes.pop(lane_id)

    def _lane_path_modes(
        self, lane: LogisticsLane, day: int
    ) -> tuple[tuple[RouteId, ...], dict[RouteId, str]]:
        selected_path = (
            self.find_path(lane.source_id, lane.destination_id, day, lane.path_policy)
            if lane.path is None else lane.path
        )
        selected_modes = dict(lane.mode_by_route)
        if lane.path is None:
            automatic = self._automatic_mode_plan(selected_path, day, lane.path_policy)
            if automatic is None:
                raise ValueError("lane has no executable automatic transport plan")
            selected_modes = automatic
        self.validate_path(lane.source_id, lane.destination_id, selected_path, day, selected_modes)
        return selected_path, selected_modes

    def _lanes_with_waiting_missions(self) -> set[EntityId]:
        blocked: set[EntityId] = set()
        for mission in self.missions.values():
            if mission.status not in {MissionStatus.ARRIVAL_WAITING, MissionStatus.WAYPOINT_WAIT}:
                continue
            order = self.orders.get(mission.order_id)
            if order is not None and order.lane_id is not None and not self.order_complete(order.id):
                blocked.add(order.lane_id)
        return blocked

    def _lane_runtime(
        self,
        lane: LogisticsLane,
        day: int,
        waiting_lanes: set[EntityId] | None = None,
    ) -> tuple[tuple[RouteId, ...], dict[RouteId, str], tuple[str, ...], float]:
        blockers: list[str] = []
        if lane.paused:
            blockers.append("manual_pause")
        if lane.id in (self._lanes_with_waiting_missions() if waiting_lanes is None else waiting_lanes):
            blockers.append("arrival_waiting")
        try:
            path, modes = self._lane_path_modes(lane, day)
        except (KeyError, ValueError):
            blockers.append("route_unavailable")
            return (), {}, tuple(dict.fromkeys(blockers)), 0.0
        if path:
            first = path[0]
            blockers.extend(
                f"route:{first}:{reason}"
                for reason in self.route_operational_failures(first, day, modes.get(first))
            )
        blockers_tuple = tuple(dict.fromkeys(blockers))
        if blockers_tuple or not path:
            return path, modes, blockers_tuple, 0.0
        first = path[0]
        effective = max(
            0.0,
            min(
                lane.requested_capacity_t_per_day,
                self.route_dispatch_capacity_t(first, day, modes.get(first)),
            ),
        )
        return path, modes, blockers_tuple, effective

    def lane_blockers(self, lane_id: EntityId, day: int = 0) -> tuple[str, ...]:
        lane = self.lanes[lane_id]
        return self._lane_runtime(lane, day)[2]

    def lane_effective_capacity_t_per_day(self, lane_id: EntityId, day: int = 0) -> float:
        lane = self.lanes[lane_id]
        return self._lane_runtime(lane, day)[3]

    def lane_used_t(self, lane_id: EntityId, day: int) -> float:
        return sum(
            order.amount_t for order in self.orders.values()
            if order.lane_id == lane_id and order.created_day == day
        )

    def _demand_pipeline_by_id(self, demand_ids: set[EntityId]) -> dict[EntityId, float]:
        pipeline = {demand_id: 0.0 for demand_id in demand_ids}
        if not pipeline:
            return pipeline
        for order in self.orders.values():
            if order.demand_id in pipeline and not self.order_complete(order.id):
                pipeline[order.demand_id] += max(0.0, order.amount_t - order.delivered_t)
        return pipeline

    def demand_pipeline_t(self, demand_id: EntityId) -> float:
        return self._demand_pipeline_by_id({demand_id})[demand_id]

    def demand_remaining_t(self, demand: ResourceDemand) -> float:
        return max(0.0, demand.amount_t - self.demand_pipeline_t(demand.id))

    @staticmethod
    def _lane_accepts_demand(lane: LogisticsLane, demand: ResourceDemand) -> bool:
        return lane.destination_id == demand.destination_id and (
            demand.source_id is None or lane.source_id == demand.source_id
        )

    def lane_queued_t(self, lane_id: EntityId, demands: Iterable[ResourceDemand]) -> float:
        lane = self.lanes[lane_id]
        accepted = tuple(demand for demand in demands if self._lane_accepts_demand(lane, demand))
        pipeline = self._demand_pipeline_by_id({demand.id for demand in accepted})
        return sum(max(0.0, demand.amount_t - pipeline[demand.id]) for demand in accepted)

    def lane_snapshot(
        self, demands: Iterable[ResourceDemand], day: int = 0
    ) -> LogisticsLaneSnapshot:
        demand_rows = tuple(demands)
        pipeline = self._demand_pipeline_by_id({demand.id for demand in demand_rows})
        used_by_lane: dict[EntityId, float] = {}
        for order in self.orders.values():
            if order.lane_id is not None and order.created_day == day:
                used_by_lane[order.lane_id] = used_by_lane.get(order.lane_id, 0.0) + order.amount_t
        waiting_lanes = self._lanes_with_waiting_missions()
        lane_rows: list[LaneRuntimeMetrics] = []
        for lane in sorted(self.lanes.values(), key=lambda row: str(row.id)):
            _path, _modes, blockers, effective = self._lane_runtime(lane, day, waiting_lanes)
            queued = sum(
                max(0.0, demand.amount_t - pipeline[demand.id])
                for demand in demand_rows
                if self._lane_accepts_demand(lane, demand)
            )
            lane_rows.append(LaneRuntimeMetrics(
                lane.id,
                effective,
                used_by_lane.get(lane.id, 0.0),
                queued,
                blockers,
            ))
        return LogisticsLaneSnapshot(
            tuple(sorted(pipeline.items(), key=lambda row: str(row[0]))),
            tuple(lane_rows),
        )

    def advance_automation(self, day: int, demands: Iterable[ResourceDemand] = ()) -> None:
        demand_rows = tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))
        if not demand_rows or not self.lanes:
            return
        pipeline_by_demand = self._demand_pipeline_by_id({demand.id for demand in demand_rows})
        used_by_lane: dict[EntityId, float] = {}
        for order in self.orders.values():
            if order.lane_id is not None and order.created_day == day:
                used_by_lane[order.lane_id] = used_by_lane.get(order.lane_id, 0.0) + order.amount_t
        waiting_lanes = self._lanes_with_waiting_missions()

        for lane in sorted(self.lanes.values(), key=lambda row: (-row.priority, str(row.id))):
            if lane.paused or lane.id in waiting_lanes:
                continue
            path, modes, blockers, effective = self._lane_runtime(lane, day, waiting_lanes)
            if blockers or not path:
                continue
            remaining_capacity = max(0.0, effective - used_by_lane.get(lane.id, 0.0))
            if remaining_capacity <= 1e-9:
                continue
            for demand in demand_rows:
                if remaining_capacity <= 1e-9:
                    break
                if not self._lane_accepts_demand(lane, demand):
                    continue
                gap = max(0.0, demand.amount_t - pipeline_by_demand[demand.id])
                if gap <= 1e-9:
                    continue
                amount = min(
                    gap,
                    remaining_capacity,
                    self.inventory.available(lane.source_id, demand.resource_id),
                )
                if amount <= 1e-9:
                    continue
                if not self.can_submit(
                    lane.source_id, lane.destination_id, demand.resource_id, amount,
                    day, path, modes, lane.path_policy,
                ):
                    continue
                self.submit_order(
                    lane.source_id, lane.destination_id, demand.resource_id, amount,
                    max(lane.priority, demand.priority), demand.owner_kind, demand.owner_id,
                    day=day, path=path, mode_by_route=modes, path_policy=lane.path_policy,
                    lane_id=lane.id, demand_id=demand.id,
                )
                pipeline_by_demand[demand.id] += amount
                used_by_lane[lane.id] = used_by_lane.get(lane.id, 0.0) + amount
                remaining_capacity -= amount
