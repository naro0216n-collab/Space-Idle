from __future__ import annotations

from dataclasses import dataclass

from ..resource_demand import ResourceDemand
from ..shared import EntityId, RouteId, SpatialNodeId
from .models import LogisticsLane, PathPolicy


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


@dataclass(frozen=True)
class DemandSupplyOptions:
    """Observable supply alternatives for one Resource Demand."""

    eligible_lane_ids: tuple[EntityId, ...]
    operational_lane_ids: tuple[EntityId, ...]
    stocked_source_ids: tuple[SpatialNodeId, ...]
    blockers: tuple[str, ...]
    earliest_confirmed_arrival_day: int | None


class TransportLaneMixin:
    """Player-owned Logistics Lane configuration only.

    Lane state expresses demand for shared Transport Capacity. Fleet selection,
    service construction, capacity derivation, and Cargo Flow execution belong
    to the Transport/Fleet and steady Logistics responsibilities respectively.
    """

    def create_lane(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        requested_capacity_t_per_day: float,
        priority: int,
        path: tuple[RouteId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
    ) -> EntityId:
        if path is not None:
            self.validate_path_structure(source_id, destination_id, path)
        self._lane_counter += 1
        lane_id = EntityId(f"logistics.lane.{self._lane_counter}")
        self.lanes[lane_id] = LogisticsLane(
            lane_id,
            source_id,
            destination_id,
            requested_capacity_t_per_day,
            priority,
            path,
            path_policy,
            False,
        )
        return lane_id

    def update_lane(
        self,
        lane_id: EntityId,
        requested_capacity_t_per_day: float,
        priority: int,
        path_policy: PathPolicy | None = None,
    ) -> None:
        if requested_capacity_t_per_day <= 0:
            raise ValueError("logistics lane requested capacity must be positive")
        lane = self.lanes[lane_id]
        lane.requested_capacity_t_per_day = requested_capacity_t_per_day
        lane.priority = priority
        if path_policy is not None:
            lane.path_policy = path_policy

    def pause_lane(self, lane_id: EntityId) -> None:
        self.lanes[lane_id].paused = True

    def resume_lane(self, lane_id: EntityId) -> None:
        self.lanes[lane_id].paused = False

    def delete_lane(self, lane_id: EntityId) -> None:
        self.lanes.pop(lane_id)

    @staticmethod
    def _lane_accepts_demand(lane: LogisticsLane, demand: ResourceDemand) -> bool:
        return lane.destination_id == demand.destination_id and (
            demand.source_id is None or lane.source_id == demand.source_id
        )

    def lane_accepts_demand(self, lane: LogisticsLane, demand: ResourceDemand) -> bool:
        return self._lane_accepts_demand(lane, demand)

    def demand_remaining_t(self, demand: ResourceDemand) -> float:
        return max(0.0, demand.amount_t - self.cargo_flow_pipeline_t(demand.id))

    def lane_queued_t(self, lane_id: EntityId, demands) -> float:
        lane = self.lanes[lane_id]
        return sum(
            self.demand_remaining_t(demand)
            for demand in demands
            if self._lane_accepts_demand(lane, demand)
        )
