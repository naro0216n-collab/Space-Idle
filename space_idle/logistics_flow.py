from __future__ import annotations

from dataclasses import dataclass, replace
import heapq

from .external_economy import FundsAllocationPlan, FundsRequest
from .knowledge import DomainActivity
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .resource_demand import ResourceDemand
from .service_capacity import ServiceCapacityAllocationPlan
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .logistics_lanes import DemandSupplyOptions, LaneRuntimeMetrics, LogisticsLaneSnapshot
from .logistics_models import CargoFlowBatch, CargoFlowStatus, LogisticsLane
from .transport.models import DirectionalCapacity, PathPolicy, TransportCapacitySnapshot


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


@dataclass(frozen=True)
class _PlannedDispatch:
    lane_id: EntityId
    demand: ResourceDemand
    path: tuple[_ServiceEdge, ...]
    amount_t: float
    cargo_claim_id: EntityId
    spending_request_ids: tuple[EntityId, ...] = ()
    raw_amount_t: float | None = None

    @property
    def planned_amount_t(self) -> float:
        return self.amount_t if self.raw_amount_t is None else self.raw_amount_t


@dataclass(frozen=True)
class LogisticsResourcePlan:
    dispatches: tuple[_PlannedDispatch, ...]
    claims: tuple[ResourceClaim, ...]
    planned_usage: tuple[tuple[EntityId, DirectionalCapacity], ...]
    spending_requests: tuple[FundsRequest, ...] = ()


@dataclass(frozen=True)
class LogisticsDispatchProjection:
    lane_id: EntityId
    demand_id: EntityId
    resource_id: DefinitionId
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    amount_t: float


@dataclass(frozen=True)
class LogisticsExecutionProjection:
    dispatches: tuple[LogisticsDispatchProjection, ...]
    operational_resource_use: tuple[tuple[SpatialNodeId, DefinitionId, float], ...]


@dataclass(frozen=True)
class LogisticsExecutionAllocation:
    """Final same-tick Transport/Logistics allocation result.

    This transient object is resolved after Funds, Resource and Service
    allocations. Execution and Application queries consume this same result;
    neither may reinterpret upstream scarcity independently.
    """

    executable_dispatches: tuple[tuple[_PlannedDispatch, float], ...]
    used_by_allocation: tuple[tuple[EntityId, DirectionalCapacity], ...]
    operational_resource_use_by_allocation: tuple[
        tuple[EntityId, SpatialNodeId, DefinitionId, float], ...
    ]
    operation_factors: tuple[tuple[EntityId, float, tuple[str, ...]], ...]

    def factor(self, allocation_id: EntityId) -> tuple[float, tuple[str, ...]]:
        for row_id, factor, limiting in self.operation_factors:
            if row_id == allocation_id:
                return factor, limiting
        return 1.0, ()


class LogisticsFlowMixin:
    """Shared sustained-capacity allocation and Cargo Flow execution.

    The daily capacity budget is derived from Transport Allocations and external
    services. Logistics consumes it; it does not select or resize Fleet assets.
    """

    def _service_edges(self, day: int) -> tuple[_ServiceEdge, ...]:
        edges: list[_ServiceEdge] = []
        for allocation in sorted(
            self.transport.transport_allocations.values(),
            key=lambda row: (str(row.vehicle_definition_id), str(row.anchor_node_id), str(row.destination_id), str(row.id)),
        ):
            plan = self.transport.derive_transport_service_plan(allocation.id, day)
            if not plan.feasible or allocation.paused or self.transport.transport_active_units(allocation.id) <= 0:
                continue
            snapshot = self.transport.transport_capacity_snapshot(allocation.id, day=day)
            definition = self.transport.vehicle_defs[allocation.vehicle_definition_id]
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
                        allocation.anchor_node_id,
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
                        allocation.anchor_node_id,
                        snapshot.available.reverse_t_per_day,
                        max(1, plan.reverse_latency_days or 1),
                        plan.reverse_path,
                        allocation.id,
                        "reverse",
                        propellant_t_per_t=reverse_propellant_per_t,
                    )
                )

        for service in sorted(self.transport.external_services.values(), key=lambda row: str(row.id)):
            if service.capacity_t_per_day <= 1e-12:
                continue
            for route in sorted(self.transport.routes.values(), key=lambda row: str(row.id)):
                if self.transport.service_route_failures(route.id, service.id, day):
                    continue
                edges.append(
                    _ServiceEdge(
                        f"external:{service.id}:{route.id}",
                        route.origin_id,
                        route.destination_id,
                        service.capacity_t_per_day,
                        self.transport.performance_route_transit_days(
                            route,
                            service.performance,
                            transit_multiplier=service.transit_time_multiplier,
                        ),
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
        self,
        lane: LogisticsLane,
        day: int,
        edges: tuple[_ServiceEdge, ...] | None = None,
        *,
        enforce_external_policy: bool = True,
    ) -> tuple[_ServiceEdge, ...]:
        available = self._service_edges(day) if edges is None else edges
        if enforce_external_policy:
            available = tuple(
                edge
                for edge in available
                if edge.external_service_id is None
                or self.external_economy.service_allowed(
                    edge.external_service_id, "lane", lane.id
                )
            )
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
            snapshot = self.transport.transport_capacity_snapshot(
                allocation_id, day=day, used=directional
            )
            for location_id, resource_id, amount in snapshot.operational_resource_demand:
                key = (location_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount
        return totals

    @staticmethod
    def _cargo_claim_id(lane_id: EntityId, demand_id: EntityId) -> EntityId:
        return EntityId(f"claim.logistics.cargo:{lane_id}:{demand_id}")

    @staticmethod
    def _spending_request_id(
        lane_id: EntityId,
        demand_id: EntityId,
        service_id: DefinitionId,
        edge_key: str,
        dispatch_index: int,
    ) -> EntityId:
        return EntityId(
            f"funds.logistics:{lane_id}:{demand_id}:{service_id}:{edge_key}:{dispatch_index}"
        )

    @staticmethod
    def _operation_claim_id(
        allocation_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(
            f"claim.transport.operation:{allocation_id}:{location_id}:{resource_id}"
        )

    def _operational_resource_totals_by_allocation(
        self,
        used: dict[EntityId, DirectionalCapacity],
        day: int,
    ) -> dict[tuple[EntityId, SpatialNodeId, DefinitionId], float]:
        totals: dict[tuple[EntityId, SpatialNodeId, DefinitionId], float] = {}
        for allocation_id, directional in sorted(used.items(), key=lambda row: str(row[0])):
            snapshot = self.transport.transport_capacity_snapshot(
                allocation_id, day=day, used=directional
            )
            for location_id, resource_id, amount in snapshot.operational_resource_demand:
                key = (allocation_id, location_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount
        return totals

    def plan_capacity_logistics(
        self, day: int, demands: tuple[ResourceDemand, ...]
    ) -> LogisticsResourcePlan:
        """Plan transport and expose all current inventory use as ResourceClaims.

        Transport capacity and routing are resolved without spending source stock.
        Cargo and owned-fleet operational resources then compete in the shared
        Resource allocator with every local Domain consumer.
        """
        edges = self._service_edges(day)
        remaining = {edge.key: edge.capacity_t_per_day for edge in edges}
        demand_rows = tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))
        pipeline = self._flow_pipeline_by_demand({row.id for row in demand_rows})
        used: dict[EntityId, DirectionalCapacity] = {}
        dispatches: list[_PlannedDispatch] = []
        spending_requests: list[FundsRequest] = []

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
                    amount = upper
                    if amount <= 1e-9:
                        break

                    used = self._allocation_used_after(used, path, amount)
                    for edge in path:
                        remaining[edge.key] -= amount
                    used_lane += amount
                    pipeline[demand.id] += amount
                    spending_ids: list[EntityId] = []
                    for edge in path:
                        if (
                            edge.external_service_id is None
                            or edge.cost_musd_per_t <= 1e-12
                        ):
                            continue
                        policy = self.external_economy.resolve_policy(
                            edge.external_service_id, "lane", lane.id
                        )
                        if policy is None:
                            raise RuntimeError(
                                "external service entered plan without policy authorization"
                            )
                        request_id = self._spending_request_id(
                            lane.id,
                            demand.id,
                            edge.external_service_id,
                            edge.key,
                            len(dispatches),
                        )
                        spending_ids.append(request_id)
                        spending_requests.append(
                            FundsRequest(
                                request_id,
                                policy.id,
                                edge.external_service_id,
                                amount * edge.cost_musd_per_t,
                                lane.priority,
                                "lane",
                                lane.id,
                                f"transport:{demand.id}",
                            )
                        )
                    dispatches.append(_PlannedDispatch(
                        lane.id,
                        demand,
                        path,
                        amount,
                        self._cargo_claim_id(lane.id, demand.id),
                        tuple(spending_ids),
                        amount,
                    ))

        cargo_totals: dict[EntityId, float] = {}
        cargo_meta: dict[EntityId, _PlannedDispatch] = {}
        for row in dispatches:
            cargo_totals[row.cargo_claim_id] = cargo_totals.get(row.cargo_claim_id, 0.0) + row.amount_t
            cargo_meta.setdefault(row.cargo_claim_id, row)

        claims: list[ResourceClaim] = []
        for claim_id, requested in sorted(cargo_totals.items(), key=lambda row: str(row[0])):
            row = cargo_meta[claim_id]
            demand = row.demand
            lane = self.lanes[row.lane_id]
            claims.append(ResourceClaim(
                claim_id,
                lane.source_id,
                demand.resource_id,
                requested,
                demand.priority,
                "logistics_dispatch",
                demand.owner_id,
                f"lane:{lane.id}",
                demand_id=demand.id,
            ))

        operational = self._operational_resource_totals_by_allocation(used, day)
        for (allocation_id, location_id, resource_id), requested in sorted(
            operational.items(), key=lambda row: (str(row[0][0]), str(row[0][1]), str(row[0][2]))
        ):
            if requested <= 1e-12:
                continue
            allocation = self.transport.transport_allocations[allocation_id]
            claims.append(ResourceClaim(
                self._operation_claim_id(allocation_id, location_id, resource_id),
                location_id,
                resource_id,
                requested,
                allocation.priority,
                "transport_operation",
                allocation_id,
                "sustained_transport",
            ))

        return LogisticsResourcePlan(
            tuple(dispatches),
            tuple(claims),
            tuple(sorted(used.items(), key=lambda row: str(row[0]))),
            tuple(sorted(spending_requests, key=lambda row: str(row.id))),
        )

    def authorize_capacity_logistics(
        self,
        plan: LogisticsResourcePlan,
        funds: FundsAllocationPlan,
        day: int,
    ) -> LogisticsResourcePlan:
        """Apply Funds authorization before Resource allocation.

        External spending is an upstream dependency of dispatch. Reducing a paid
        dispatch here prevents denied external work from reserving source stock or
        owned-fleet operating resources later in the same allocation phase.
        """
        dispatches: list[_PlannedDispatch] = []
        used: dict[EntityId, DirectionalCapacity] = {}
        requests_by_id = {request.id: request for request in plan.spending_requests}
        for row in plan.dispatches:
            amount = row.amount_t
            for request_id in row.spending_request_ids:
                request = requests_by_id[request_id]
                if request.requested_musd <= 1e-12:
                    continue
                authorized = funds.authorized(request_id)
                amount = min(
                    amount,
                    row.amount_t * max(0.0, authorized) / request.requested_musd,
                )
            if amount <= 1e-12:
                continue
            dispatches.append(
                _PlannedDispatch(
                    row.lane_id,
                    row.demand,
                    row.path,
                    amount,
                    row.cargo_claim_id,
                    row.spending_request_ids,
                    row.planned_amount_t,
                )
            )
            used = self._allocation_used_after(used, row.path, amount)

        cargo_totals: dict[EntityId, float] = {}
        cargo_meta: dict[EntityId, _PlannedDispatch] = {}
        for row in dispatches:
            cargo_totals[row.cargo_claim_id] = (
                cargo_totals.get(row.cargo_claim_id, 0.0) + row.amount_t
            )
            cargo_meta.setdefault(row.cargo_claim_id, row)

        claims: list[ResourceClaim] = []
        for claim_id, requested in sorted(cargo_totals.items(), key=lambda row: str(row[0])):
            row = cargo_meta[claim_id]
            demand = row.demand
            lane = self.lanes[row.lane_id]
            claims.append(
                ResourceClaim(
                    claim_id,
                    lane.source_id,
                    demand.resource_id,
                    requested,
                    demand.priority,
                    "logistics_dispatch",
                    demand.owner_id,
                    f"lane:{lane.id}",
                    demand_id=demand.id,
                )
            )

        operational = self._operational_resource_totals_by_allocation(used, day)
        for (allocation_id, location_id, resource_id), requested in sorted(
            operational.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1]), str(row[0][2])),
        ):
            if requested <= 1e-12:
                continue
            allocation = self.transport.transport_allocations[allocation_id]
            claims.append(
                ResourceClaim(
                    self._operation_claim_id(
                        allocation_id, location_id, resource_id
                    ),
                    location_id,
                    resource_id,
                    requested,
                    allocation.priority,
                    "transport_operation",
                    allocation_id,
                    "sustained_transport",
                )
            )
        return LogisticsResourcePlan(
            tuple(dispatches),
            tuple(claims),
            tuple(sorted(used.items(), key=lambda row: str(row[0]))),
            plan.spending_requests,
        )

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
        self,
        allocation_id: EntityId,
        *,
        day: int = 0,
        execution_allocation: LogisticsExecutionAllocation | None = None,
    ) -> TransportCapacitySnapshot:
        """Project capacity from physical state and the resolved Transport node."""
        snapshot = self.transport.transport_capacity_snapshot(
            allocation_id,
            day=day,
            used=self._derived_allocation_usage(allocation_id, day),
        )
        if execution_allocation is None:
            return snapshot
        factor, allocation_limits = execution_allocation.factor(allocation_id)
        available = DirectionalCapacity(
            snapshot.available.forward_t_per_day * factor,
            snapshot.available.reverse_t_per_day * factor,
        )
        used = DirectionalCapacity(
            min(snapshot.used.forward_t_per_day, available.forward_t_per_day),
            min(snapshot.used.reverse_t_per_day, available.reverse_t_per_day),
        )
        spare = DirectionalCapacity(
            max(0.0, available.forward_t_per_day - used.forward_t_per_day),
            max(0.0, available.reverse_t_per_day - used.reverse_t_per_day),
        )
        return replace(
            snapshot,
            available=available,
            used=used,
            spare=spare,
            limiting_factors=tuple(
                dict.fromkeys(snapshot.limiting_factors + allocation_limits)
            ),
        )

    def _derived_lane_usage(self, lane_id: EntityId, day: int) -> float:
        departure_day = self._latest_completed_transport_day(day)
        return sum(
            flow.amount_t
            for flow in self.cargo_flows.values()
            if flow.departure_day == departure_day and flow.lane_id == lane_id
        )

    def settle_cargo_arrivals(self, day: int) -> None:
        """Settle Cargo Flow batches that reached their boundary arrival time.

        Arrival admission is a Simulation boundary operation.  Dispatch during
        the current tick must never feed inventory back into the same tick's
        allocation graph, even if a route's modeled latency is minimal.
        """
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

    def _transport_operation_allocation_factor(
        self,
        allocation_id: EntityId,
        plan: LogisticsResourcePlan,
        resource_allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int,
    ) -> tuple[float, tuple[str, ...]]:
        """Resolve one Transport Allocation's shared dependency fulfillment.

        Planning exposes operation Resource Claims and turnaround Service requests.
        This method only interprets the shared allocation results; it never reads
        Inventory or runs a Transport-local allocator.
        """
        ratios: list[float] = []
        limiting: list[str] = []
        for claim in plan.claims:
            if claim.owner_kind != "transport_operation" or claim.owner_id != allocation_id:
                continue
            if claim.requested_amount <= 1e-12:
                continue
            try:
                allocated = resource_allocations.allocated(claim.id)
            except KeyError:
                allocated = 0.0
            ratio = max(0.0, min(1.0, allocated / claim.requested_amount))
            ratios.append(ratio)
            if ratio < 1.0 - 1e-12:
                limiting.append(
                    f"resource_allocation:{claim.operational_node_id}:{claim.resource_id}"
                )

        directional = dict(plan.planned_usage).get(allocation_id, DirectionalCapacity())
        has_planned_usage = (
            directional.forward_t_per_day > 1e-12
            or directional.reverse_t_per_day > 1e-12
        )
        allocation = self.transport.transport_allocations[allocation_id]
        definition = self.transport.vehicle_defs[allocation.vehicle_definition_id]
        if has_planned_usage and definition.turnaround_service_type is not None:
            request_id = self.transport.transport_service_request_id(allocation_id)
            try:
                request = service_allocations.request(request_id)
                allocated = service_allocations.allocated(request_id)
            except KeyError:
                request = None
                allocated = 0.0
            if request is None or request.requested_rate <= 1e-12:
                ratio = 0.0
            else:
                ratio = max(
                    0.0, min(1.0, allocated / request.requested_rate)
                )
            ratios.append(ratio)
            if ratio < 1.0 - 1e-12:
                limiting.append(
                    f"servicing_allocation:{allocation.anchor_node_id}:"
                    f"{definition.turnaround_service_type}"
                )

        service_plan = self.transport.derive_transport_service_plan(allocation_id, day)
        surface_locations: set[SpatialNodeId] = set()
        for route_id in service_plan.forward_path + service_plan.reverse_path:
            geometry = self.transport.route_geometry(route_id)
            for endpoint in (geometry.origin, geometry.destination):
                if endpoint.surface_cell_id is not None:
                    surface_locations.add(endpoint.node_id)
        for location_id in sorted(surface_locations, key=str):
            request_id = EntityId(f"service.surface_distribution:{location_id}")
            try:
                request = service_allocations.request(request_id)
                allocated = service_allocations.allocated(request_id)
            except KeyError:
                request = None
                allocated = 0.0
            if request is None:
                ratio = 0.0
            elif request.requested_rate <= 1e-12:
                ratio = 1.0
            else:
                ratio = max(0.0, min(1.0, allocated / request.requested_rate))
            ratios.append(ratio)
            if ratio < 1.0 - 1e-12:
                limiting.append(f"surface_infrastructure:{location_id}")

        factor = min(ratios) if ratios else 1.0
        return max(0.0, min(1.0, factor)), tuple(dict.fromkeys(limiting))

    def allocate_capacity_logistics_execution(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
    ) -> LogisticsExecutionAllocation:
        """Resolve the final Transport/Logistics allocation without mutation.

        Upstream Funds authorization has already shaped ``plan``. Resource and
        Service allocation results are interpreted exactly once here. The
        returned object is then shared by queries and movement execution.
        """
        operation_factor: dict[EntityId, float] = {}
        operation_limits: dict[EntityId, tuple[str, ...]] = {}
        # Capacity queries must observe upstream Service scarcity even when no
        # cargo happens to be scheduled for this allocation in the current
        # tick. Resource and turnaround ratios below remain demand-shaped by
        # ``plan``; location-wide upstream services such as surface
        # distribution are authoritative for the allocation regardless of
        # current cargo demand.
        for allocation_id in sorted(self.transport.transport_allocations, key=str):
            factor, limiting = self._transport_operation_allocation_factor(
                allocation_id, plan, allocations, service_allocations, day
            )
            operation_factor[allocation_id] = factor
            operation_limits[allocation_id] = limiting

        cargo_budget: dict[EntityId, float] = {}
        for claim in plan.claims:
            if claim.owner_kind != "logistics_dispatch":
                continue
            try:
                cargo_budget[claim.id] = allocations.allocated(claim.id)
            except KeyError:
                cargo_budget[claim.id] = 0.0

        used: dict[EntityId, DirectionalCapacity] = {}
        executable: list[tuple[_PlannedDispatch, float]] = []
        for row in plan.dispatches:
            path_factor = min(
                (
                    operation_factor.get(edge.allocation_id, 1.0)
                    for edge in row.path
                    if edge.allocation_id is not None
                ),
                default=1.0,
            )
            allowed_by_operation = row.amount_t * max(0.0, min(1.0, path_factor))
            allowed_by_cargo = cargo_budget.get(row.cargo_claim_id, 0.0)
            amount = min(allowed_by_operation, allowed_by_cargo)
            if amount <= 1e-9:
                continue
            executable.append((row, amount))
            cargo_budget[row.cargo_claim_id] = max(0.0, allowed_by_cargo - amount)
            used = self._allocation_used_after(used, row.path, amount)

        operational = self._operational_resource_totals_by_allocation(used, day)
        return LogisticsExecutionAllocation(
            tuple(executable),
            tuple(sorted(used.items(), key=lambda row: str(row[0]))),
            tuple(
                (allocation_id, location_id, resource_id, amount)
                for (allocation_id, location_id, resource_id), amount in sorted(
                    operational.items(),
                    key=lambda row: (
                        str(row[0][0]), str(row[0][1]), str(row[0][2])
                    ),
                )
                if amount > 1e-12
            ),
            tuple(
                (allocation_id, operation_factor[allocation_id], operation_limits[allocation_id])
                for allocation_id in sorted(operation_factor, key=str)
            ),
        )

    def capacity_logistics_execution_projection(
        self, allocation: LogisticsExecutionAllocation
    ) -> LogisticsExecutionProjection:
        dispatches = tuple(
            LogisticsDispatchProjection(
                row.lane_id,
                row.demand.id,
                row.demand.resource_id,
                self.lanes[row.lane_id].source_id,
                self.lanes[row.lane_id].destination_id,
                amount,
            )
            for row, amount in allocation.executable_dispatches
        )
        resource_use = tuple(
            (location_id, resource_id, amount)
            for _allocation_id, location_id, resource_id, amount
            in allocation.operational_resource_use_by_allocation
        )
        return LogisticsExecutionProjection(dispatches, resource_use)

    def advance_capacity_logistics(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        funds: FundsAllocationPlan,
        execution: LogisticsExecutionAllocation,
    ) -> tuple[DomainActivity, ...]:
        """Execute exactly the already-resolved Transport allocation."""
        activities: list[DomainActivity] = []
        requests_by_id = {request.id: request for request in plan.spending_requests}
        for row, amount in execution.executable_dispatches:
            lane = self.lanes[row.lane_id]
            demand = row.demand
            self.inventory.consume_allocated(lane.source_id, demand.resource_id, amount)
            if row.spending_request_ids:
                raw_amount = row.planned_amount_t
                execution_factor = 0.0 if raw_amount <= 1e-12 else amount / raw_amount
                for request_id in row.spending_request_ids:
                    authorization = funds.authorization(request_id)
                    request = requests_by_id[request_id]
                    actual_cost = request.requested_musd * execution_factor
                    if actual_cost > authorization.authorized_musd + 1e-8:
                        raise RuntimeError(
                            "external transport spend exceeded funds authorization"
                        )
                    self.external_economy.spend_authorized(
                        authorization, actual_cost, day
                    )

            self._cargo_flow_counter += 1
            flow_id = EntityId(f"cargo.flow.{self._cargo_flow_counter}")
            activities.append(
                DomainActivity(
                    "transport", amount, "logistics_lane", row.lane_id, lane.source_id
                )
            )
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
                tuple(edge.key for edge in row.path),
                tuple(edge.destination_id for edge in row.path),
                day,
                day + sum(edge.latency_days for edge in row.path),
            )

        for allocation_id, location_id, resource_id, amount in (
            execution.operational_resource_use_by_allocation
        ):
            self.inventory.consume_allocated(location_id, resource_id, amount)

        for allocation_id, directional in execution.used_by_allocation:
            if (
                directional.forward_t_per_day > 1e-12
                or directional.reverse_t_per_day > 1e-12
            ):
                self.transport.record_transport_operation(allocation_id, day)
        return tuple(activities)

    def _external_policy_blockers_for_lane(
        self, lane: LogisticsLane, day: int, edges: tuple[_ServiceEdge, ...]
    ) -> tuple[str, ...]:
        try:
            physical_path = self.lane_service_path(
                lane, day, edges, enforce_external_policy=False
            )
        except ValueError:
            return ()
        denied = {
            edge.external_service_id
            for edge in physical_path
            if edge.external_service_id is not None
            and not self.external_economy.service_allowed(
                edge.external_service_id, "lane", lane.id
            )
        }
        return tuple(
            f"external_policy_denied:{service_id}"
            for service_id in sorted(denied, key=str)
        )

    def _service_edges_for_execution_allocation(
        self,
        day: int,
        execution_allocation: LogisticsExecutionAllocation | None,
    ) -> tuple[_ServiceEdge, ...]:
        edges = self._service_edges(day)
        if execution_allocation is None:
            return edges
        return tuple(
            edge
            if edge.allocation_id is None
            else replace(
                edge,
                capacity_t_per_day=(
                    edge.capacity_t_per_day
                    * execution_allocation.factor(edge.allocation_id)[0]
                ),
            )
            for edge in edges
        )

    def lane_snapshot(
        self,
        demands: tuple[ResourceDemand, ...],
        day: int = 0,
        *,
        execution_allocation: LogisticsExecutionAllocation | None = None,
    ) -> LogisticsLaneSnapshot:
        pipeline = self._flow_pipeline_by_demand({demand.id for demand in demands})
        rows: list[LaneRuntimeMetrics] = []
        edges = self._service_edges_for_execution_allocation(
            day, execution_allocation
        )
        for lane in sorted(self.lanes.values(), key=lambda row: str(row.id)):
            blockers: list[str] = []
            try:
                remaining = {edge.key: edge.capacity_t_per_day for edge in edges}
                effective = (
                    self._lane_transport_capacity(lane, day, edges, remaining)
                    if not lane.paused else 0.0
                )
                if effective <= 1e-12 and not lane.paused:
                    blockers.extend(
                        self._external_policy_blockers_for_lane(lane, day, edges)
                    )
            except ValueError as exc:
                effective = 0.0
                policy_blockers = self._external_policy_blockers_for_lane(
                    lane, day, edges
                )
                blockers.extend(policy_blockers)
                if not policy_blockers:
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
        self,
        demand: ResourceDemand,
        day: int = 0,
        *,
        execution_allocation: LogisticsExecutionAllocation | None = None,
    ) -> DemandSupplyOptions:
        edges = self._service_edges_for_execution_allocation(
            day, execution_allocation
        )
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
                policy_blockers = self._external_policy_blockers_for_lane(
                    lane, day, edges
                )
                blockers.extend(policy_blockers or (f"transport_capacity:{exc}",))
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
