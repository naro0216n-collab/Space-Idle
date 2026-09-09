from __future__ import annotations

from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import CargoOrder, PathPolicy


class TransportOrderMixin:
    """Create and inspect physical resource-specific CargoOrders."""

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
            order_id, source_id, destination_id, resource_id, amount_t, priority,
            owner_kind, owner_id, selected_path, selected_modes, path_policy,
            0.0, day, lane_id, demand_id,
        )
        self.waiting[(order_id, 0)] = amount_t
        return order_id

    def order_complete(self, order_id: CargoOrderId) -> bool:
        order = self.orders[order_id]
        return order.delivered_t + 1e-9 >= order.amount_t
