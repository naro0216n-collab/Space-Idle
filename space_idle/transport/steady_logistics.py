from __future__ import annotations

from dataclasses import dataclass
import heapq

from ..resource_demand import ResourceDemand
from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .lanes import DemandSupplyOptions, LaneRuntimeMetrics, LogisticsLaneSnapshot
from .models import (
    CargoFlowBatch,
    CargoFlowStatus,
    DirectionalCapacity,
    LogisticsLane,
    PathPolicy,
    TransportCapacitySnapshot,
)


@dataclass(frozen=True)
class _ServiceEdge:
    key: str
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    capacity_t_per_day: float
    latency_days: int
    route_path: tuple[RouteId, ...]
    allocation_id: EntityId | None = None
    direction: str | None = None
    external_service_id: DefinitionId | None = None
    cost_musd_per_t: float = 0.0
    propellant_t_per_t: float = 0.0


class SteadyLogisticsMixin:
    """Shared sustained-capacity allocation and Cargo Flow execution.

    The daily capacity budget is derived from Transport Allocations and external
    services. Logistics consumes it; it does not select or resize Fleet assets.
    """

    def _service_edges(self, day: int) -> tuple[_ServiceEdge, ...]:
        edges: list[_ServiceEdge] = []
        for allocation in sorted(
            self.transport_allocations.values(),
            key=lambda row: (str(row.vehicle_definition_id), str(row.anchor_location_id), str(row.destination_id), str(row.id)),
        ):
            plan = self.derive_transport_service_plan(allocation.id, day)
            if not plan.feasible or allocation.paused or allocation.active_units <= 0:
                continue
            snapshot = self.transport_capacity_snapshot(allocation.id, day=day)
            definition = self.vehicle_defs[allocation.vehicle_definition_id]
            propellant_id = definition.propellant_resource_id
            empty_propellant = sum(
                amount for _loc, rid, amount in plan.resource_t_per_empty_cycle_day
                if rid == propellant_id
            )
            forward_increment = sum(
                amount for _loc, rid, amount in plan.resource_t_per_forward_payload_increment_day
                if rid == propellant_id
            )
            reverse_increment = sum(
                amount for _loc, rid, amount in plan.resource_t_per_reverse_payload_increment_day
                if rid == propellant_id
            )
            forward_propellant_per_t = (
                0.0 if plan.nominal_per_unit.forward_t_per_day <= 1e-12
                else (empty_propellant + forward_increment) / plan.nominal_per_unit.forward_t_per_day
            )
            reverse_propellant_per_t = (
                0.0 if plan.nominal_per_unit.reverse_t_per_day <= 1e-12
                else (empty_propellant + reverse_increment) / plan.nominal_per_unit.reverse_t_per_day
            )
            if snapshot.available.forward_t_per_day > 1e-12:
                edges.append(
                    _ServiceEdge(
                        f"allocation:{allocation.id}:forward",
                        allocation.anchor_location_id,
                        allocation.destination_id,
                        snapshot.available.forward_t_per_day,
                        max(1, plan.forward_latency_days),
                        plan.forward_path,
                        allocation.id,
                        "forward",
                        propellant_t_per_t=forward_propellant_per_t,
                    )
                )
            if snapshot.available.reverse_t_per_day > 1e-12 and plan.reverse_path:
                edges.append(
                    _ServiceEdge(
                        f"allocation:{allocation.id}:reverse",
                        allocation.destination_id,
                        allocation.anchor_location_id,
                        snapshot.available.reverse_t_per_day,
                        max(1, plan.reverse_latency_days or 1),
                        plan.reverse_path,
                        allocation.id,
                        "reverse",
                        propellant_t_per_t=reverse_propellant_per_t,
                    )
                )

        for service in sorted(self.external_services.values(), key=lambda row: str(row.id)):
            if service.capacity_t_per_day <= 1e-12:
                continue
            for route in sorted(self.routes.values(), key=lambda row: str(row.id)):
                if self.service_route_failures(route.id, service.id, day):
                    continue
                edges.append(
                    _ServiceEdge(
                        f"external:{service.id}:{route.id}",
                        route.origin_id,
                        route.destination_id,
                        service.capacity_t_per_day,
                        max(1, round(route.transit_days * service.transit_time_multiplier)),
                        (route.id,),
                        external_service_id=service.id,
                        cost_musd_per_t=service.cost_musd_per_t,
                    )
                )
        return tuple(edges)

    @staticmethod
    def _edge_score(edge: _ServiceEdge, policy: PathPolicy) -> float:
        if policy is PathPolicy.FASTEST:
            return float(edge.latency_days)
        if policy is PathPolicy.LOWEST_COST:
            return edge.cost_musd_per_t
        return edge.propellant_t_per_t

    def _automatic_service_path(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        edges: tuple[_ServiceEdge, ...],
        policy: PathPolicy,
    ) -> tuple[_ServiceEdge, ...]:
        by_source: dict[SpatialNodeId, list[_ServiceEdge]] = {}
        for edge in edges:
            by_source.setdefault(edge.source_id, []).append(edge)
        queue: list[tuple[float, tuple[str, ...], SpatialNodeId, tuple[_ServiceEdge, ...]]] = [
            (0.0, (), source_id, ())
        ]
        best: dict[SpatialNodeId, tuple[float, tuple[str, ...]]] = {}
        while queue:
            score, keys, node, path = heapq.heappop(queue)
            prior = best.get(node)
            if prior is not None and prior <= (score, keys):
                continue
            best[node] = (score, keys)
            if node == destination_id:
                return path
            for edge in sorted(by_source.get(node, ()), key=lambda row: row.key):
                new_path = path + (edge,)
                heapq.heappush(
                    queue,
                    (
                        score + self._edge_score(edge, policy),
                        keys + (edge.key,),
                        edge.destination_id,
                        new_path,
                    ),
                )
        raise ValueError(f"no available transport service path {source_id} -> {destination_id}")

    def _explicit_service_path(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        route_path: tuple[RouteId, ...],
        edges: tuple[_ServiceEdge, ...],
        policy: PathPolicy,
    ) -> tuple[_ServiceEdge, ...]:
        candidates = sorted(edges, key=lambda edge: (self._edge_score(edge, policy), edge.key))

        def search(node: SpatialNodeId, index: int) -> tuple[_ServiceEdge, ...] | None:
            if index == len(route_path):
                return () if node == destination_id else None
            for edge in candidates:
                if edge.source_id != node:
                    continue
                size = len(edge.route_path)
                if size == 0 or route_path[index : index + size] != edge.route_path:
                    continue
                suffix = search(edge.destination_id, index + size)
                if suffix is not None:
                    return (edge,) + suffix
            return None

        result = search(source_id, 0)
        if result is None:
            raise ValueError("explicit lane path has no matching transport services")
        return result

    def lane_service_path(
        self, lane: LogisticsLane, day: int, edges: tuple[_ServiceEdge, ...] | None = None
    ) -> tuple[_ServiceEdge, ...]:
        available = self._service_edges(day) if edges is None else edges
        if lane.path is None:
            return self._automatic_service_path(
                lane.source_id, lane.destination_id, available, lane.path_policy
            )
        return self._explicit_service_path(
            lane.source_id,
            lane.destination_id,
            lane.path,
            available,
            lane.path_policy,
        )

    @staticmethod
    def _edges_with_remaining(
        edges: tuple[_ServiceEdge, ...], remaining: dict[str, float]
    ) -> tuple[_ServiceEdge, ...]:
        return tuple(edge for edge in edges if remaining.get(edge.key, 0.0) > 1e-12)

    def _lane_transport_capacity(
        self,
        lane: LogisticsLane,
        day: int,
        edges: tuple[_ServiceEdge, ...],
        remaining: dict[str, float],
    ) -> float:
        """Return capacity available to one Lane across parallel Service paths.

        Successive policy-ordered augmenting paths let a Lane consume a second
        Fleet Allocation or External Service after the preferred path is full,
        while every underlying Service edge remains a shared capacity budget.
        """
        scratch = dict(remaining)
        total = 0.0
        limit = lane.requested_capacity_t_per_day
        while total + 1e-12 < limit:
            available_edges = self._edges_with_remaining(edges, scratch)
            if not available_edges:
                break
            try:
                path = self.lane_service_path(lane, day, available_edges)
            except ValueError:
                break
            if not path:
                break
            bottleneck = min(scratch[edge.key] for edge in path)
            amount = min(limit - total, bottleneck)
            if amount <= 1e-12:
                break
            total += amount
            for edge in path:
                scratch[edge.key] -= amount
        return total

    @staticmethod
    def _lane_execution_key(lane: LogisticsLane) -> tuple:
        """Order equal-priority Lane work by configuration, not creation order."""
        return (
            -lane.priority,
            str(lane.source_id),
            str(lane.destination_id),
            lane.path_policy.value,
            tuple(str(route_id) for route_id in (lane.path or ())),
            lane.requested_capacity_t_per_day,
            str(lane.id),
        )

    def _flow_pipeline_by_demand(self, demand_ids: set[EntityId]) -> dict[EntityId, float]:
        pipeline = {demand_id: 0.0 for demand_id in demand_ids}
        for flow in self.cargo_flows.values():
            if flow.demand_id in pipeline:
                pipeline[flow.demand_id] += flow.amount_t
        return pipeline

    def cargo_flow_pipeline_t(self, demand_id: EntityId) -> float:
        return self._flow_pipeline_by_demand({demand_id})[demand_id]

    def _allocation_used_after(
        self,
        used: dict[EntityId, DirectionalCapacity],
        path: tuple[_ServiceEdge, ...],
        amount: float,
    ) -> dict[EntityId, DirectionalCapacity]:
        result = dict(used)
        for edge in path:
            if edge.allocation_id is None or edge.direction is None:
                continue
            current = result.get(edge.allocation_id, DirectionalCapacity())
            if edge.direction == "forward":
                result[edge.allocation_id] = DirectionalCapacity(
                    current.forward_t_per_day + amount,
                    current.reverse_t_per_day,
                )
            else:
                result[edge.allocation_id] = DirectionalCapacity(
                    current.forward_t_per_day,
                    current.reverse_t_per_day + amount,
                )
        return result

    def _operational_resource_totals(
        self,
        used: dict[EntityId, DirectionalCapacity],
        day: int,
    ) -> dict[tuple[SpatialNodeId, DefinitionId], float]:
        totals: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for allocation_id, directional in sorted(used.items(), key=lambda row: str(row[0])):
            snapshot = self.transport_capacity_snapshot(
                allocation_id, day=day, used=directional
            )
            for location_id, resource_id, amount in snapshot.operational_resource_demand:
                key = (location_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount
        return totals

    def _candidate_amount_is_fundable(
        self,
        lane: LogisticsLane,
        demand: ResourceDemand,
        path: tuple[_ServiceEdge, ...],
        amount: float,
        used: dict[EntityId, DirectionalCapacity],
        stock_budget: dict[tuple[SpatialNodeId, DefinitionId], float],
        current_operational: dict[tuple[SpatialNodeId, DefinitionId], float],
        funds_budget: float,
        day: int,
    ) -> bool:
        if amount <= 1e-12:
            return True
        proposed_used = self._allocation_used_after(used, path, amount)
        proposed_operational = self._operational_resource_totals(proposed_used, day)
        required: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        required[(lane.source_id, demand.resource_id)] = amount
        for key, total in proposed_operational.items():
            increment = max(0.0, total - current_operational.get(key, 0.0))
            required[key] = required.get(key, 0.0) + increment
        if any(stock_budget.get(key, 0.0) + 1e-9 < needed for key, needed in required.items()):
            return False
        cost = amount * sum(edge.cost_musd_per_t for edge in path)
        return funds_budget + 1e-9 >= cost

    def _feasible_dispatch_amount(
        self,
        lane: LogisticsLane,
        demand: ResourceDemand,
        path: tuple[_ServiceEdge, ...],
        upper: float,
        used: dict[EntityId, DirectionalCapacity],
        stock_budget: dict[tuple[SpatialNodeId, DefinitionId], float],
        current_operational: dict[tuple[SpatialNodeId, DefinitionId], float],
        funds_budget: float,
        day: int,
    ) -> float:
        if self._candidate_amount_is_fundable(
            lane, demand, path, upper, used, stock_budget, current_operational, funds_budget, day
        ):
            return upper
        lo, hi = 0.0, upper
        for _ in range(36):
            mid = (lo + hi) / 2.0
            if self._candidate_amount_is_fundable(
                lane, demand, path, mid, used, stock_budget, current_operational, funds_budget, day
            ):
                lo = mid
            else:
                hi = mid
        return lo

    def _latest_completed_transport_day(self, day: int) -> int:
        """Resolve the dispatch day represented by current decision projections.

        Normal Simulation queries occur after the day counter advances, so the
        last completed transport tick is ``day - 1``. Domain-level tests and
        tools may execute Logistics directly without advancing the Simulation
        clock; a Cargo Flow dispatched on ``day`` is then authoritative evidence
        that this transport tick has already executed.
        """
        if any(flow.departure_day == day for flow in self.cargo_flows.values()):
            return day
        return day - 1

    def _derived_allocation_usage(
        self, allocation_id: EntityId, day: int
    ) -> DirectionalCapacity:
        """Rebuild Used capacity from authoritative Cargo Flow state."""
        departure_day = self._latest_completed_transport_day(day)
        forward_key = f"allocation:{allocation_id}:forward"
        reverse_key = f"allocation:{allocation_id}:reverse"
        forward = 0.0
        reverse = 0.0
        for flow in self.cargo_flows.values():
            if flow.departure_day != departure_day:
                continue
            if forward_key in flow.service_ids:
                forward += flow.amount_t
            if reverse_key in flow.service_ids:
                reverse += flow.amount_t
        return DirectionalCapacity(forward, reverse)

    def current_transport_capacity_snapshot(
        self, allocation_id: EntityId, *, day: int = 0
    ) -> TransportCapacitySnapshot:
        """Project current capacity with Used re-derived from Cargo Flows."""
        return self.transport_capacity_snapshot(
            allocation_id,
            day=day,
            used=self._derived_allocation_usage(allocation_id, day),
        )

    def _derived_lane_usage(self, lane_id: EntityId, day: int) -> float:
        departure_day = self._latest_completed_transport_day(day)
        return sum(
            flow.amount_t
            for flow in self.cargo_flows.values()
            if flow.departure_day == departure_day and flow.lane_id == lane_id
        )

    def _progress_cargo_arrivals(self, day: int) -> None:
        for flow_id in sorted(tuple(self.cargo_flows), key=str):
            flow = self.cargo_flows[flow_id]
            if flow.status is CargoFlowStatus.IN_TRANSIT and flow.ready_day <= day:
                flow.status = CargoFlowStatus.ARRIVAL_WAITING
            if flow.status is not CargoFlowStatus.ARRIVAL_WAITING:
                continue
            accepted = self.inventory.add_up_to(
                flow.destination_id, flow.resource_id, flow.amount_t
            )
            flow.amount_t = max(0.0, flow.amount_t - accepted)
            if flow.amount_t <= 1e-9:
                del self.cargo_flows[flow_id]

    def advance_capacity_logistics(
        self, day: int, demands: tuple[ResourceDemand, ...]
    ) -> None:
        # Derive transport availability before any arrivals in this tick. This
        # snapshot is never retroactively increased by cargo received below.
        self.advance_fleet_state(day)
        edges = self._service_edges(day)
        remaining = {edge.key: edge.capacity_t_per_day for edge in edges}
        demand_rows = tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))
        pipeline = self._flow_pipeline_by_demand({row.id for row in demand_rows})
        stock_budget = {
            (location_id, resource_id): self.inventory.available(location_id, resource_id)
            for location_id in self.facilities.environment.graph.operational_node_ids()
            for resource_id in {row.resource_id for row in demand_rows}
        }
        # Operational resources may not appear in the demand set.
        for allocation in self.transport_allocations.values():
            plan = self.derive_transport_service_plan(allocation.id, day)
            for location_id, resource_id, _amount in plan.resource_t_per_full_utilization_day:
                stock_budget.setdefault(
                    (location_id, resource_id), self.inventory.available(location_id, resource_id)
                )

        used: dict[EntityId, DirectionalCapacity] = {}
        operational_reserved: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        funds_budget = self.account.funds_musd
        for lane in sorted(self.lanes.values(), key=self._lane_execution_key):
            if lane.paused:
                continue
            lane_capacity = self._lane_transport_capacity(lane, day, edges, remaining)
            if lane_capacity <= 1e-12:
                continue

            used_lane = 0.0
            for demand in demand_rows:
                if used_lane + 1e-9 >= lane_capacity:
                    break
                if not self._lane_accepts_demand(lane, demand):
                    continue
                while used_lane + 1e-9 < lane_capacity:
                    gap = max(0.0, demand.amount_t - pipeline[demand.id])
                    if gap <= 1e-9:
                        break
                    available_edges = self._edges_with_remaining(edges, remaining)
                    if not available_edges:
                        break
                    try:
                        path = self.lane_service_path(lane, day, available_edges)
                    except ValueError:
                        break
                    if not path:
                        break
                    path_capacity = min(remaining[edge.key] for edge in path)
                    upper = min(gap, lane_capacity - used_lane, path_capacity)
                    amount = self._feasible_dispatch_amount(
                        lane,
                        demand,
                        path,
                        upper,
                        used,
                        stock_budget,
                        operational_reserved,
                        funds_budget,
                        day,
                    )
                    if amount <= 1e-9:
                        # The policy-selected path is currently unfundable by
                        # resource/funds budgets. Do not burn its shared capacity;
                        # stop this Lane rather than looping or silently changing
                        # the player's policy.
                        break

                    proposed_used = self._allocation_used_after(used, path, amount)
                    proposed_operational = self._operational_resource_totals(proposed_used, day)
                    for key, total in proposed_operational.items():
                        increment = max(0.0, total - operational_reserved.get(key, 0.0))
                        stock_budget[key] = stock_budget.get(key, 0.0) - increment
                    operational_reserved = proposed_operational
                    cargo_key = (lane.source_id, demand.resource_id)
                    stock_budget[cargo_key] = stock_budget.get(cargo_key, 0.0) - amount
                    used = proposed_used
                    cost = amount * sum(edge.cost_musd_per_t for edge in path)
                    funds_budget -= cost
                    for edge in path:
                        remaining[edge.key] -= amount
                    used_lane += amount
                    pipeline[demand.id] += amount

                    if not self.inventory.take_unreserved(lane.source_id, demand.resource_id, amount):
                        raise RuntimeError("cargo stock changed after tick-start allocation")
                    if cost > 1e-12 and not self.account.spend(cost):
                        raise RuntimeError("external transport funds changed after tick-start allocation")
                    self._cargo_flow_counter += 1
                    flow_id = EntityId(f"cargo.flow.{self._cargo_flow_counter}")
                    self.cargo_flows[flow_id] = CargoFlowBatch(
                        flow_id,
                        demand.resource_id,
                        amount,
                        lane.source_id,
                        lane.destination_id,
                        lane.id,
                        demand.id,
                        demand.owner_kind,
                        demand.owner_id,
                        demand.priority,
                        tuple(edge.key for edge in path),
                        tuple(edge.destination_id for edge in path),
                        day,
                        day + sum(edge.latency_days for edge in path),
                    )

        # Consume operational resources only after Lane usage is known. These
        # amounts came from tick-start budgets, so same-tick arrivals cannot fund
        # this tick's Transport Capacity.
        for (location_id, resource_id), amount in sorted(
            operational_reserved.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            if amount <= 1e-12:
                continue
            if not self.inventory.take_unreserved(location_id, resource_id, amount):
                raise RuntimeError("transport operational resource budget was overcommitted")

        for allocation_id, directional in used.items():
            if directional.forward_t_per_day > 1e-12 or directional.reverse_t_per_day > 1e-12:
                self.transport_allocations[allocation_id].last_operated_day = day
        self._progress_cargo_arrivals(day)

    def lane_snapshot(
        self, demands: tuple[ResourceDemand, ...], day: int = 0
    ) -> LogisticsLaneSnapshot:
        pipeline = self._flow_pipeline_by_demand({demand.id for demand in demands})
        rows: list[LaneRuntimeMetrics] = []
        edges = self._service_edges(day)
        for lane in sorted(self.lanes.values(), key=lambda row: str(row.id)):
            blockers: list[str] = []
            try:
                remaining = {edge.key: edge.capacity_t_per_day for edge in edges}
                effective = (
                    self._lane_transport_capacity(lane, day, edges, remaining)
                    if not lane.paused else 0.0
                )
            except ValueError as exc:
                effective = 0.0
                blockers.append(f"transport_capacity:{exc}")
            if lane.paused:
                blockers.append("manual_pause")
            queued = sum(
                max(0.0, demand.amount_t - pipeline[demand.id])
                for demand in demands
                if self._lane_accepts_demand(lane, demand)
            )
            rows.append(
                LaneRuntimeMetrics(
                    lane.id,
                    effective,
                    self._derived_lane_usage(lane.id, day),
                    queued,
                    tuple(blockers),
                )
            )
        return LogisticsLaneSnapshot(
            tuple(sorted(pipeline.items(), key=lambda row: str(row[0]))),
            tuple(rows),
        )

    def demand_supply_options(
        self, demand: ResourceDemand, day: int = 0
    ) -> DemandSupplyOptions:
        edges = self._service_edges(day)
        eligible = tuple(
            lane for lane in sorted(self.lanes.values(), key=lambda row: str(row.id))
            if self._lane_accepts_demand(lane, demand)
        )
        operational: list[EntityId] = []
        blockers: list[str] = []
        stocked_sources: set[SpatialNodeId] = set()
        for lane in eligible:
            if self.inventory.available(lane.source_id, demand.resource_id) > 1e-9:
                stocked_sources.add(lane.source_id)
            try:
                path = self.lane_service_path(lane, day, edges)
                if path and not lane.paused:
                    operational.append(lane.id)
            except ValueError as exc:
                blockers.append(f"transport_capacity:{exc}")
        arrivals = [
            flow.ready_day
            for flow in self.cargo_flows.values()
            if flow.demand_id == demand.id and flow.status is CargoFlowStatus.IN_TRANSIT
        ]
        return DemandSupplyOptions(
            tuple(lane.id for lane in eligible),
            tuple(operational),
            tuple(sorted(stocked_sources, key=str)),
            tuple(dict.fromkeys(blockers)),
            min(arrivals) if arrivals else None,
        )
