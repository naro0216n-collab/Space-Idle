from __future__ import annotations

from collections.abc import Iterable

from ..resource_demand import ResourceDemand
from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import CargoOrder, LogisticsLane, MissionStatus, PathPolicy


class TransportOrderMixin:
    def create_lane(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
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
            lane_id,
            source_id,
            destination_id,
            requested_capacity_t_per_day,
            priority,
            path,
            selected_modes,
            path_policy,
            False,
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
            if lane.path is None
            else lane.path
        )
        selected_modes = dict(lane.mode_by_route)
        if lane.path is None:
            automatic = self._automatic_mode_plan(selected_path, day, lane.path_policy)
            if automatic is None:
                raise ValueError("lane has no executable automatic transport plan")
            selected_modes = automatic
        self.validate_path(lane.source_id, lane.destination_id, selected_path, day, selected_modes)
        return selected_path, selected_modes

    def lane_blockers(self, lane_id: EntityId, day: int = 0) -> tuple[str, ...]:
        lane = self.lanes[lane_id]
        blockers: list[str] = []
        if lane.paused:
            blockers.append("manual_pause")
        if any(
            order.lane_id == lane.id
            and not self.order_complete(order.id)
            and any(
                mission.order_id == order.id
                and mission.status in {MissionStatus.ARRIVAL_WAITING, MissionStatus.WAYPOINT_WAIT}
                for mission in self.missions.values()
            )
            for order in self.orders.values()
        ):
            blockers.append("arrival_waiting")
        try:
            path, modes = self._lane_path_modes(lane, day)
        except (KeyError, ValueError):
            blockers.append("route_unavailable")
            return tuple(dict.fromkeys(blockers))
        if path:
            first = path[0]
            blockers.extend(
                f"route:{first}:{reason}"
                for reason in self.route_operational_failures(first, day, modes.get(first))
            )
        return tuple(dict.fromkeys(blockers))

    def lane_effective_capacity_t_per_day(self, lane_id: EntityId, day: int = 0) -> float:
        lane = self.lanes[lane_id]
        if self.lane_blockers(lane_id, day):
            return 0.0
        try:
            path, modes = self._lane_path_modes(lane, day)
        except (KeyError, ValueError):
            return 0.0
        if not path:
            return 0.0
        first = path[0]
        dispatchable = self.route_dispatch_capacity_t(first, day, modes.get(first))
        return max(0.0, min(lane.requested_capacity_t_per_day, dispatchable))

    def lane_used_t(self, lane_id: EntityId, day: int) -> float:
        return sum(
            order.amount_t
            for order in self.orders.values()
            if order.lane_id == lane_id and order.created_day == day
        )

    def _demand_pipeline_remaining(self, demand_id: EntityId) -> float:
        return sum(
            max(0.0, order.amount_t - order.delivered_t)
            for order in self.orders.values()
            if order.demand_id == demand_id and not self.order_complete(order.id)
        )

    def demand_remaining_t(self, demand: ResourceDemand) -> float:
        return max(0.0, demand.amount_t - self._demand_pipeline_remaining(demand.id))

    @staticmethod
    def _lane_accepts_demand(lane: LogisticsLane, demand: ResourceDemand) -> bool:
        return (
            lane.destination_id == demand.destination_id
            and (demand.source_id is None or lane.source_id == demand.source_id)
        )

    def lane_queued_t(self, lane_id: EntityId, demands: Iterable[ResourceDemand]) -> float:
        lane = self.lanes[lane_id]
        return sum(
            self.demand_remaining_t(demand)
            for demand in demands
            if self._lane_accepts_demand(lane, demand)
        )

    def advance_automation(self, day: int, demands: Iterable[ResourceDemand] = ()) -> None:
        demand_rows = tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))
        for lane in sorted(self.lanes.values(), key=lambda row: (-row.priority, str(row.id))):
            if lane.paused:
                continue
            effective = self.lane_effective_capacity_t_per_day(lane.id, day)
            remaining_capacity = max(0.0, effective - self.lane_used_t(lane.id, day))
            if remaining_capacity <= 1e-9:
                continue
            try:
                path, modes = self._lane_path_modes(lane, day)
            except (KeyError, ValueError):
                continue
            for demand in demand_rows:
                if remaining_capacity <= 1e-9:
                    break
                if not self._lane_accepts_demand(lane, demand):
                    continue
                gap = self.demand_remaining_t(demand)
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
                    lane.source_id,
                    lane.destination_id,
                    demand.resource_id,
                    amount,
                    day,
                    path,
                    modes,
                    lane.path_policy,
                ):
                    continue
                self.submit_order(
                    lane.source_id,
                    lane.destination_id,
                    demand.resource_id,
                    amount,
                    max(lane.priority, demand.priority),
                    demand.owner_kind,
                    demand.owner_id,
                    day=day,
                    path=path,
                    mode_by_route=modes,
                    path_policy=lane.path_policy,
                    lane_id=lane.id,
                    demand_id=demand.id,
                )
                remaining_capacity -= amount

    def can_submit(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        resource_id: DefinitionId,
        amount_t: float,
        day: int = 0,
        path: tuple[RouteId, ...] | None = None,
        mode_by_route: dict[RouteId, str] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
    ) -> bool:
        if source_id == destination_id or amount_t <= 0:
            return False
        if self.inventory.available(source_id, resource_id) + 1e-9 < amount_t:
            return False
        try:
            selected = self.find_path(source_id, destination_id, day, path_policy) if path is None else path
            selected_modes = {} if mode_by_route is None else dict(mode_by_route)
            if path is None and not selected_modes:
                auto_modes = self._automatic_mode_plan(selected, day, path_policy)
                if auto_modes is None:
                    return False
                selected_modes = auto_modes
            self.validate_path(source_id, destination_id, selected, day, selected_modes)
            if selected and self.route_operational_failures(selected[0], day, selected_modes.get(selected[0])):
                return False
        except (KeyError, ValueError):
            return False
        return True

    def submit_order(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        resource_id: DefinitionId,
        amount_t: float,
        priority: int,
        owner_kind: str,
        owner_id: EntityId,
        *,
        day: int = 0,
        path: tuple[RouteId, ...] | None = None,
        mode_by_route: dict[RouteId, str] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        lane_id: EntityId | None = None,
        demand_id: EntityId | None = None,
    ) -> CargoOrderId:
        if source_id == destination_id:
            raise ValueError("cargo order endpoints must differ")
        if amount_t <= 0:
            raise ValueError("cargo amount must be positive")
        selected_path = self.find_path(source_id, destination_id, day, path_policy) if path is None else path
        selected_modes = {} if mode_by_route is None else dict(mode_by_route)
        if path is None and not selected_modes:
            auto_modes = self._automatic_mode_plan(selected_path, day, path_policy)
            if auto_modes is None:
                raise ValueError("automatic route has no executable transfer or continuous carrier plan")
            selected_modes = auto_modes
        self.validate_path(source_id, destination_id, selected_path, day, selected_modes)
        if selected_path and self.route_operational_failures(selected_path[0], day, selected_modes.get(selected_path[0])):
            raise ValueError("first cargo leg is not currently dispatchable")
        self._counter += 1
        order_id = CargoOrderId(f"cargo.{self._counter}")
        owner = self._waiting_owner(order_id, 0)
        if not self.inventory.stage_unreserved(owner, source_id, resource_id, amount_t):
            self._counter -= 1
            raise ValueError(f"insufficient source stock: {resource_id}")
        self.orders[order_id] = CargoOrder(
            order_id,
            source_id,
            destination_id,
            resource_id,
            amount_t,
            priority,
            owner_kind,
            owner_id,
            selected_path,
            selected_modes,
            path_policy,
            0.0,
            day,
            lane_id,
            demand_id,
        )
        self.waiting[(order_id, 0)] = amount_t
        return order_id

    def order_complete(self, order_id: CargoOrderId) -> bool:
        order = self.orders[order_id]
        return order.delivered_t + 1e-9 >= order.amount_t
