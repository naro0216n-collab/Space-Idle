from __future__ import annotations

from dataclasses import dataclass

from ..shared import RouteId, SpatialNodeId
from .models import PathPolicy


@dataclass(frozen=True)
class TransportPathPlan:
    policy: PathPolicy
    path: tuple[RouteId, ...]
    mode_by_route: tuple[tuple[RouteId, str], ...]
    transit_days: int
    estimated_cost_musd_per_t: float
    estimated_propellant_t_per_cargo_t: float


class TransportQueryMixin:
    """Public read-side planning API for outer application layers.

    Planning implementation details remain private inside the transport domain.
    Application projectors consume this immutable result instead of reaching into
    private path/mode scoring helpers.
    """

    def transport_plan(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        day: int = 0,
        policy: PathPolicy = PathPolicy.FASTEST,
    ) -> TransportPathPlan:
        path = self.find_path(source_id, destination_id, day, policy)
        mode_plan = self._automatic_mode_plan(path, day, policy)
        if mode_plan is None:
            raise ValueError(f"no executable transport plan {source_id} -> {destination_id}")
        ordered_modes = tuple((route_id, mode_plan[route_id]) for route_id in path)
        return TransportPathPlan(
            policy,
            path,
            ordered_modes,
            sum(self.route_mode_transit_days(route_id, mode_id, day) for route_id, mode_id in ordered_modes),
            sum(self._mode_cost_musd_per_t(route_id, mode_id) for route_id, mode_id in ordered_modes),
            sum(self._mode_propellant_t_per_cargo_t(route_id, mode_id) for route_id, mode_id in ordered_modes),
        )
