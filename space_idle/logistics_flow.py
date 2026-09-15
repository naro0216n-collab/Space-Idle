from __future__ import annotations

from dataclasses import dataclass, replace
import heapq

from .external_economy import FundsAllocationPlan, FundsRequest
from .knowledge import DomainActivity
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .supply import SupplyRequirement
from .service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityRequest
from .shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
from .supply_planning import SupplyPlanningOptions
from .logistics_models import (
    CargoArrivalWaiting,
    CargoFlowSegment,
    CargoHandoffStaging,
    CargoServiceLeg,
)
from .transport.models import (
    DirectionalCapacity,
    PathPolicy,
    TransportCapacitySnapshot,
    TransportOperationDependencyProjection,
    TransportServiceSupply,
)


@dataclass(frozen=True)
class _PlannedDispatch:
    source_id: SpatialNodeId
    requirement: SupplyRequirement
    path: tuple[TransportServiceSupply, ...]
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
    requirement_id: EntityId
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

    def _service_edges(self, day: int) -> tuple[TransportServiceSupply, ...]:
        rows: list[TransportServiceSupply] = []
        backpressure = self._arrival_backpressure_by_service()
        for edge in self.transport.transport_service_supplies(day):
            occupied = backpressure.get(self._capacity_owner_key_from_supply(edge), 0.0)
            if occupied <= 1e-12:
                rows.append(edge)
                continue
            rows.append(
                replace(
                    edge,
                    capacity_t_per_day=max(
                        0.0,
                        edge.capacity_t_per_day - occupied / max(1.0, edge.cycle_days),
                    ),
                )
            )
        return tuple(rows)

    @staticmethod
    def _cargo_service_leg(edge: TransportServiceSupply) -> CargoServiceLeg:
        return CargoServiceLeg(
            service_identity=edge.key,
            source_id=edge.source_id,
            destination_id=edge.destination_id,
            latency_days=edge.latency_days,
            cycle_days=edge.cycle_days,
            allocation_id=edge.allocation_id,
            direction=edge.direction,
            external_service_id=edge.external_service_id,
        )

    @staticmethod
    def _capacity_owner_key_from_leg(leg: CargoServiceLeg) -> tuple:
        if leg.allocation_id is not None:
            return ("allocation", leg.allocation_id, leg.direction)
        if leg.external_service_id is not None:
            return ("external", leg.external_service_id, leg.source_id, leg.destination_id)
        return ("service", leg.service_identity)

    @staticmethod
    def _capacity_owner_key_from_supply(edge: TransportServiceSupply) -> tuple:
        if edge.allocation_id is not None:
            return ("allocation", edge.allocation_id, edge.direction)
        if edge.external_service_id is not None:
            return ("external", edge.external_service_id, edge.source_id, edge.destination_id)
        return ("service", edge.key)

    def _arrival_backpressure_by_service(self) -> dict[tuple, float]:
        occupied: dict[tuple, float] = {}
        for waiting in self.arrival_waiting.values():
            key = self._capacity_owner_key_from_leg(waiting.arrival_leg)
            occupied[key] = occupied.get(key, 0.0) + waiting.amount_t
        return occupied

    @staticmethod
    def _edge_score(edge: TransportServiceSupply, policy: PathPolicy) -> float:
        if policy is PathPolicy.FASTEST:
            return float(edge.latency_days)
        if policy is PathPolicy.LOWEST_COST:
            return edge.cost_musd_per_t
        return edge.propellant_t_per_t

    def _automatic_service_path(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        edges: tuple[TransportServiceSupply, ...],
        policy: PathPolicy,
    ) -> tuple[TransportServiceSupply, ...]:
        by_source: dict[SpatialNodeId, list[TransportServiceSupply]] = {}
        for edge in edges:
            by_source.setdefault(edge.source_id, []).append(edge)
        queue: list[tuple[float, tuple[str, ...], SpatialNodeId, tuple[TransportServiceSupply, ...]]] = [
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
        movement_plan_path: tuple[MovementPlanId, ...],
        edges: tuple[TransportServiceSupply, ...],
        policy: PathPolicy,
    ) -> tuple[TransportServiceSupply, ...]:
        candidates = sorted(edges, key=lambda edge: (self._edge_score(edge, policy), edge.key))

        def search(node: SpatialNodeId, index: int) -> tuple[TransportServiceSupply, ...] | None:
            if index == len(movement_plan_path):
                return () if node == destination_id else None
            for edge in candidates:
                if edge.source_id != node:
                    continue
                size = len(edge.movement_plan_path)
                if size == 0 or movement_plan_path[index : index + size] != edge.movement_plan_path:
                    continue
                suffix = search(edge.destination_id, index + size)
                if suffix is not None:
                    return (edge,) + suffix
            return None

        result = search(source_id, 0)
        if result is None:
            raise ValueError("explicit supply path has no matching transport services")
        return result

    def _transport_edges_for_requirement(
        self,
        requirement: SupplyRequirement,
        edges: tuple[TransportServiceSupply, ...],
        *,
        enforce_external_policy: bool = True,
    ) -> tuple[TransportServiceSupply, ...]:
        if not enforce_external_policy:
            return edges
        return tuple(
            edge
            for edge in edges
            if edge.external_service_id is None
            or self.external_economy.service_allowed(
                edge.external_service_id, requirement.owner_kind, requirement.owner_id
            )
        )

    def _supply_path_preferences(
        self, requirement: SupplyRequirement
    ) -> tuple[SpatialNodeId | None, PathPolicy, tuple[MovementPlanId, ...] | None]:
        policy = self.supply_policy_for(requirement)
        source_id = requirement.source_id
        if source_id is None and policy is not None:
            source_id = policy.preferred_source_id
        path_policy = PathPolicy.FASTEST if policy is None else policy.path_policy
        explicit_path = None
        if (
            policy is not None
            and policy.explicit_path is not None
            and source_id == policy.preferred_source_id
        ):
            explicit_path = policy.explicit_path
        return source_id, path_policy, explicit_path

    def supply_service_path(
        self,
        requirement: SupplyRequirement,
        source_id: SpatialNodeId,
        day: int,
        edges: tuple[TransportServiceSupply, ...] | None = None,
        *,
        enforce_external_policy: bool = True,
    ) -> tuple[TransportServiceSupply, ...]:
        available = self._service_edges(day) if edges is None else edges
        available = self._transport_edges_for_requirement(
            requirement, available, enforce_external_policy=enforce_external_policy
        )
        _source, path_policy, explicit_path = self._supply_path_preferences(requirement)
        if explicit_path is None:
            return self._automatic_service_path(
                source_id, requirement.destination_id, available, path_policy
            )
        return self._explicit_service_path(
            source_id, requirement.destination_id, explicit_path, available, path_policy
        )

    @staticmethod
    def _edges_with_remaining(
        edges: tuple[TransportServiceSupply, ...], remaining: dict[str, float]
    ) -> tuple[TransportServiceSupply, ...]:
        return tuple(edge for edge in edges if remaining.get(edge.key, 0.0) > 1e-12)

    def _candidate_supply_paths(
        self,
        requirement: SupplyRequirement,
        day: int,
        edges: tuple[TransportServiceSupply, ...],
    ) -> tuple[tuple[SpatialNodeId, tuple[TransportServiceSupply, ...]], ...]:
        constrained_source, path_policy, _explicit_path = self._supply_path_preferences(requirement)
        if constrained_source is not None:
            source_ids = (constrained_source,)
        else:
            source_ids = tuple(
                node_id
                for node_id in self.facilities.environment.graph.operational_node_ids()
                if node_id != requirement.destination_id
                and self.inventory.available(node_id, requirement.resource_id) > 1e-12
            )

        rows: list[tuple[float, str, SpatialNodeId, tuple[TransportServiceSupply, ...]]] = []
        for source_id in source_ids:
            if source_id == requirement.destination_id:
                continue
            try:
                path = self.supply_service_path(requirement, source_id, day, edges)
            except ValueError:
                continue
            if not path:
                continue
            score = sum(self._edge_score(edge, path_policy) for edge in path)
            rows.append((score, str(source_id), source_id, path))
        rows.sort(key=lambda row: (row[0], row[1], tuple(edge.key for edge in row[3])))
        return tuple((source_id, path) for _score, _key, source_id, path in rows)

    @staticmethod
    def _dispatch_is_due(
        requirement: SupplyRequirement, day: int, path: tuple[TransportServiceSupply, ...]
    ) -> bool:
        if requirement.forecast_requirement_day is None:
            return True
        arrival_day = day + sum(edge.latency_days for edge in path)
        return arrival_day >= requirement.forecast_requirement_day

    def _flow_pipeline_by_requirement(self, requirement_ids: set[EntityId]) -> dict[EntityId, float]:
        pipeline = {requirement_id: 0.0 for requirement_id in requirement_ids}
        for flow in self.cargo_flows.values():
            if flow.requirement_id in pipeline:
                pipeline[flow.requirement_id] += flow.amount_t
        for waiting in self.arrival_waiting.values():
            if waiting.requirement_id in pipeline:
                pipeline[waiting.requirement_id] += waiting.amount_t
        for staging in self.handoff_staging.values():
            if staging.requirement_id in pipeline:
                pipeline[staging.requirement_id] += staging.amount_t
        return pipeline

    def cargo_flow_pipeline_t(self, requirement_id: EntityId) -> float:
        return self._flow_pipeline_by_requirement({requirement_id})[requirement_id]

    def cargo_flow_snapshots(self) -> tuple[CargoFlowSegment, ...]:
        """Return detached in-transit Cargo Flow Segment state."""
        return tuple(
            replace(row)
            for row in sorted(self.cargo_flows.values(), key=lambda row: str(row.id))
        )

    def arrival_waiting_snapshots(self) -> tuple[CargoArrivalWaiting, ...]:
        return tuple(
            replace(row)
            for row in sorted(self.arrival_waiting.values(), key=lambda row: str(row.id))
        )

    def handoff_staging_snapshots(self) -> tuple[CargoHandoffStaging, ...]:
        return tuple(
            replace(row)
            for row in sorted(self.handoff_staging.values(), key=lambda row: str(row.id))
        )

    def _allocation_used_after(
        self,
        used: dict[EntityId, DirectionalCapacity],
        path: tuple[TransportServiceSupply, ...],
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
            for location_id, resource_id, amount in snapshot.operational_supply:
                key = (location_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount
        return totals

    @staticmethod
    def _cargo_claim_id(source_id: SpatialNodeId, requirement_id: EntityId) -> EntityId:
        return EntityId(f"claim.logistics.cargo:{source_id}:{requirement_id}")

    @staticmethod
    def _spending_request_id(
        source_id: SpatialNodeId,
        requirement_id: EntityId,
        service_id: DefinitionId,
        edge_key: str,
        dispatch_index: int,
    ) -> EntityId:
        return EntityId(
            f"funds.logistics:{source_id}:{requirement_id}:{service_id}:{edge_key}:{dispatch_index}"
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
            for location_id, resource_id, amount in snapshot.operational_supply:
                key = (allocation_id, location_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount
        return totals

    def plan_capacity_logistics(
        self, day: int, requirements: tuple[SupplyRequirement, ...]
    ) -> LogisticsResourcePlan:
        """Resolve current shipping requirement from Supply Requirements.

        Supply Planning consumes only already-provisioned Transport Capacity. It
        never changes Fleet Allocation targets. Source stock is represented as
        Resource Claims so Logistics competes with local execution in the shared
        allocation graph instead of pre-consuming Inventory during planning.

        Within one Activity Priority band, Transport Capacity is allocated by
        progressive max-min on normalized requirement fulfillment. A requirement
        whose current best path reaches a saturated edge is frozen only when no
        alternate path remains; independent requirements may continue to use
        unrelated residual capacity.
        """
        edges = self._service_edges(day)
        operation_dependencies = {
            row.allocation_id: row
            for row in self.transport.transport_operation_dependencies(day)
        }
        remaining = {edge.key: edge.capacity_t_per_day for edge in edges}
        requirement_rows = tuple(sorted(requirements, key=lambda row: (-row.priority, str(row.id))))
        pipeline = self._flow_pipeline_by_requirement({row.id for row in requirement_rows})
        used: dict[EntityId, DirectionalCapacity] = {}
        dispatches: list[_PlannedDispatch] = []
        spending_requests: list[FundsRequest] = []

        by_priority: dict[int, list[SupplyRequirement]] = {}
        for requirement in requirement_rows:
            by_priority.setdefault(int(requirement.priority), []).append(requirement)

        for priority in sorted(by_priority, reverse=True):
            band = tuple(sorted(by_priority[priority], key=lambda row: str(row.id)))
            original_need = {
                requirement.id: max(0.0, requirement.amount_t - pipeline[requirement.id])
                for requirement in band
            }
            allocated = {requirement.id: 0.0 for requirement in band}

            while True:
                available_edges = self._edges_with_remaining(edges, remaining)
                if not available_edges:
                    break

                selected: dict[
                    EntityId,
                    tuple[SupplyRequirement, SpatialNodeId, tuple[TransportServiceSupply, ...]],
                ] = {}
                for requirement in band:
                    need = original_need[requirement.id]
                    if need <= 1e-12 or allocated[requirement.id] >= need - 1e-12:
                        continue
                    candidates = self._candidate_supply_paths(
                        requirement, day, available_edges
                    )
                    if not candidates:
                        continue
                    source_id, path = candidates[0]
                    if not self._dispatch_is_due(requirement, day, path):
                        continue
                    selected[requirement.id] = (requirement, source_id, path)

                if not selected:
                    break

                edge_load: dict[str, float] = {}
                completion_delta = 1.0
                for requirement_id, (_requirement, _source_id, path) in selected.items():
                    need = original_need[requirement_id]
                    completion_delta = min(
                        completion_delta,
                        max(0.0, 1.0 - allocated[requirement_id] / need),
                    )
                    for edge in path:
                        edge_load[edge.key] = edge_load.get(edge.key, 0.0) + need

                edge_delta = min(
                    (
                        remaining[edge_key] / coefficient
                        for edge_key, coefficient in edge_load.items()
                        if coefficient > 1e-12
                    ),
                    default=1.0,
                )
                delta = min(completion_delta, edge_delta)
                if delta <= 1e-12:
                    break

                for requirement_id in sorted(selected, key=str):
                    requirement, source_id, path = selected[requirement_id]
                    amount = min(
                        original_need[requirement_id] - allocated[requirement_id],
                        original_need[requirement_id] * delta,
                    )
                    if amount <= 1e-12:
                        continue
                    allocated[requirement_id] += amount
                    pipeline[requirement_id] += amount
                    used = self._allocation_used_after(used, path, amount)
                    for edge in path:
                        remaining[edge.key] = max(
                            0.0, remaining[edge.key] - amount
                        )

                    spending_ids: list[EntityId] = []
                    for edge in path:
                        if (
                            edge.external_service_id is None
                            or edge.cost_musd_per_t <= 1e-12
                        ):
                            continue
                        policy = self.external_economy.resolve_policy(
                            edge.external_service_id, requirement.owner_kind, requirement.owner_id
                        )
                        if policy is None:
                            raise RuntimeError(
                                "external service entered plan without policy authorization"
                            )
                        request_id = self._spending_request_id(
                            source_id,
                            requirement.id,
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
                                requirement.priority,
                                requirement.owner_kind,
                                requirement.owner_id,
                                f"transport:{requirement.id}",
                            )
                        )
                    dispatches.append(
                        _PlannedDispatch(
                            source_id,
                            requirement,
                            path,
                            amount,
                            self._cargo_claim_id(source_id, requirement.id),
                            tuple(spending_ids),
                            amount,
                        )
                    )

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
            requirement = row.requirement
            claims.append(
                ResourceClaim(
                    claim_id,
                    row.source_id,
                    requirement.resource_id,
                    requested,
                    requirement.priority,
                    "logistics_dispatch",
                    requirement.owner_id,
                    f"supply:{requirement.id}",
                    requirement_id=requirement.id,
                )
            )

        operational = self._operational_resource_totals_by_allocation(used, day)
        for (allocation_id, location_id, resource_id), requested in sorted(
            operational.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1]), str(row[0][2])),
        ):
            if requested <= 1e-12:
                continue
            dependency = operation_dependencies[allocation_id]
            claims.append(
                ResourceClaim(
                    self._operation_claim_id(allocation_id, location_id, resource_id),
                    location_id,
                    resource_id,
                    requested,
                    dependency.priority,
                    "transport_operation",
                    allocation_id,
                    "sustained_transport",
                )
            )

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
        operation_dependencies = {
            row.allocation_id: row
            for row in self.transport.transport_operation_dependencies(day)
        }
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
                    row.source_id,
                    row.requirement,
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
            requirement = row.requirement
            claims.append(
                ResourceClaim(
                    claim_id,
                    row.source_id,
                    requirement.resource_id,
                    requested,
                    requirement.priority,
                    "logistics_dispatch",
                    requirement.owner_id,
                    f"supply:{requirement.id}",
                    requirement_id=requirement.id,
                )
            )

        operational = self._operational_resource_totals_by_allocation(used, day)
        for (allocation_id, location_id, resource_id), requested in sorted(
            operational.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1]), str(row[0][2])),
        ):
            if requested <= 1e-12:
                continue
            dependency = operation_dependencies[allocation_id]
            claims.append(
                ResourceClaim(
                    self._operation_claim_id(
                        allocation_id, location_id, resource_id
                    ),
                    location_id,
                    resource_id,
                    requested,
                    dependency.priority,
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
        if any(
            flow.dispatch_start_day <= day < flow.dispatch_end_day
            for flow in self.cargo_flows.values()
        ):
            return day
        return day - 1

    def _derived_allocation_usage(
        self, allocation_id: EntityId, day: int
    ) -> DirectionalCapacity:
        """Rebuild Used capacity from authoritative current-leg Segments."""
        dispatch_day = self._latest_completed_transport_day(day)
        forward = 0.0
        reverse = 0.0
        for flow in self.cargo_flows.values():
            if not (flow.dispatch_start_day <= dispatch_day < flow.dispatch_end_day):
                continue
            if flow.leg.allocation_id != allocation_id:
                continue
            if flow.leg.direction == "forward":
                forward += flow.dispatch_rate_t_per_day
            elif flow.leg.direction == "reverse":
                reverse += flow.dispatch_rate_t_per_day
        return DirectionalCapacity(forward, reverse)

    def _allocation_backpressure(
        self, allocation_id: EntityId
    ) -> tuple[DirectionalCapacity, bool]:
        forward = 0.0
        reverse = 0.0
        any_waiting = False
        for waiting in self.arrival_waiting.values():
            leg = waiting.arrival_leg
            if leg.allocation_id != allocation_id:
                continue
            any_waiting = True
            blocked_rate = waiting.amount_t / max(1.0, leg.cycle_days)
            if leg.direction == "forward":
                forward += blocked_rate
            elif leg.direction == "reverse":
                reverse += blocked_rate
        return DirectionalCapacity(forward, reverse), any_waiting

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
        backpressure, has_backpressure = self._allocation_backpressure(allocation_id)
        available = DirectionalCapacity(
            max(0.0, snapshot.available.forward_t_per_day - backpressure.forward_t_per_day),
            max(0.0, snapshot.available.reverse_t_per_day - backpressure.reverse_t_per_day),
        )
        used = DirectionalCapacity(
            min(snapshot.used.forward_t_per_day, available.forward_t_per_day),
            min(snapshot.used.reverse_t_per_day, available.reverse_t_per_day),
        )
        spare = DirectionalCapacity(
            max(0.0, available.forward_t_per_day - used.forward_t_per_day),
            max(0.0, available.reverse_t_per_day - used.reverse_t_per_day),
        )
        snapshot = replace(
            snapshot,
            available=available,
            used=used,
            spare=spare,
            limiting_factors=tuple(
                dict.fromkeys(
                    snapshot.limiting_factors
                    + (("arrival_backpressure",) if has_backpressure else ())
                )
            ),
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

    @staticmethod
    def _segment_semantics_key(
        resource_id: DefinitionId,
        source_id: SpatialNodeId,
        final_destination_id: SpatialNodeId,
        requirement_id: EntityId | None,
        owner_kind: str,
        owner_id: EntityId,
        priority: int,
        leg: CargoServiceLeg,
        remaining_legs: tuple[CargoServiceLeg, ...],
    ) -> tuple:
        return (
            resource_id, source_id, final_destination_id, requirement_id, owner_kind, owner_id,
            int(priority), leg, remaining_legs,
        )

    def _append_cargo_segment(
        self,
        *,
        resource_id: DefinitionId,
        amount_t: float,
        final_destination_id: SpatialNodeId,
        requirement_id: EntityId | None,
        owner_kind: str,
        owner_id: EntityId,
        priority: int,
        legs: tuple[CargoServiceLeg, ...],
        dispatch_day: int,
    ) -> EntityId:
        if amount_t <= 1e-12:
            raise ValueError("cargo segment append requires positive amount")
        if not legs:
            raise ValueError("cargo segment append requires a transport leg")
        leg = legs[0]
        remaining = legs[1:]
        key = self._segment_semantics_key(
            resource_id, leg.source_id, final_destination_id, requirement_id, owner_kind,
            owner_id, priority, leg, remaining,
        )
        for segment in sorted(self.cargo_flows.values(), key=lambda row: str(row.id)):
            other = self._segment_semantics_key(
                segment.resource_id, segment.source_id, segment.final_destination_id,
                segment.requirement_id, segment.owner_kind, segment.owner_id,
                int(segment.priority), segment.leg, segment.remaining_legs,
            )
            if other != key:
                continue
            if (
                segment.dispatch_end_day == dispatch_day
                and abs(segment.dispatch_rate_t_per_day - amount_t) <= 1e-9
            ):
                segment.dispatch_end_day += 1
                segment.amount_t += amount_t
                return segment.id

        self._cargo_flow_counter += 1
        segment_id = EntityId(f"cargo.segment.{self._cargo_flow_counter}")
        self.cargo_flows[segment_id] = CargoFlowSegment(
            segment_id, resource_id, amount_t, leg.source_id, final_destination_id,
            requirement_id, owner_kind, owner_id, priority, leg, remaining,
            dispatch_day, dispatch_day + 1, amount_t,
        )
        return segment_id

    @staticmethod
    def _waiting_semantics_key(waiting: CargoArrivalWaiting) -> tuple:
        return (
            waiting.resource_id, waiting.node_id, waiting.final_destination_id,
            waiting.requirement_id, waiting.owner_kind, waiting.owner_id, int(waiting.priority),
            waiting.arrival_leg, waiting.remaining_legs,
        )

    def _append_arrival_waiting(
        self, segment: CargoFlowSegment, amount_t: float, day: int
    ) -> EntityId:
        probe = CargoArrivalWaiting(
            EntityId("cargo.waiting.probe"), segment.resource_id, amount_t,
            segment.destination_id, segment.final_destination_id, segment.requirement_id,
            segment.owner_kind, segment.owner_id, segment.priority, segment.leg,
            segment.remaining_legs, day,
        )
        key = self._waiting_semantics_key(probe)
        for waiting in sorted(self.arrival_waiting.values(), key=lambda row: str(row.id)):
            if self._waiting_semantics_key(waiting) == key:
                waiting.amount_t += amount_t
                waiting.arrived_day = min(waiting.arrived_day, day)
                return waiting.id
        self._arrival_waiting_counter += 1
        waiting_id = EntityId(f"cargo.waiting.{self._arrival_waiting_counter}")
        probe.id = waiting_id
        self.arrival_waiting[waiting_id] = probe
        return waiting_id

    def prepare_cargo_arrivals(self, day: int) -> None:
        """Move dispatch slices whose frozen latency elapsed into arrival waiting.

        This is the first part of Boundary settlement. It changes only Logistics
        ownership; Inventory admission and handoff are resolved afterwards.
        """
        for segment_id in sorted(tuple(self.cargo_flows), key=str):
            segment = self.cargo_flows[segment_id]
            arrived_end = min(
                segment.dispatch_end_day,
                day - segment.latency_days + 1,
            )
            arrived_days = max(0, arrived_end - segment.dispatch_start_day)
            if arrived_days <= 0:
                continue
            arrived_amount = min(
                segment.amount_t, segment.dispatch_rate_t_per_day * arrived_days
            )
            self._append_arrival_waiting(segment, arrived_amount, day)
            segment.dispatch_start_day += arrived_days
            segment.amount_t = max(0.0, segment.amount_t - arrived_amount)
            if segment.amount_t <= 1e-9:
                del self.cargo_flows[segment_id]

    @staticmethod
    def _handoff_request_id(owner_id: EntityId, kind: str) -> EntityId:
        return EntityId(f"service.cargo_handoff:{kind}:{owner_id}")

    def external_arrival_handling_supply(
        self,
    ) -> dict[tuple[SpatialNodeId, str], float]:
        """Return exogenous Cargo Handling supplied by active external carriers.

        A commercial Transport service that has already delivered Cargo remains
        responsible for the carrier-side unload/transfer work represented by its
        contracted service capacity.  Local Facility Cargo Handling can augment
        this supply, but bootstrap deliveries are not made impossible merely
        because the destination's own handling infrastructure is the Cargo being
        delivered.  The supply is exposed only for actual external arrivals at
        the boundary and is therefore not a reusable local Service Capacity.
        """
        by_provider: dict[tuple[str, SpatialNodeId], float] = {}
        for waiting in self.arrival_waiting.values():
            service_id = waiting.arrival_leg.external_service_id
            if service_id is None:
                continue
            definition = self.transport.external_transport_service_definition(service_id)
            if definition is None:
                continue
            provider_key = (waiting.arrival_leg.service_identity, waiting.node_id)
            by_provider[provider_key] = max(
                by_provider.get(provider_key, 0.0), definition.capacity_t_per_day
            )
        supply: dict[tuple[SpatialNodeId, str], float] = {}
        for (_provider, node_id), amount in by_provider.items():
            key = (node_id, "cargo_transfer")
            supply[key] = supply.get(key, 0.0) + amount
        return supply

    def cargo_handoff_service_requests(self, day: int) -> tuple[ServiceCapacityRequest, ...]:
        """Expose arrival handling and reload work to shared Service allocation.

        Every arriving Cargo quantity must consume finite Cargo Handling before
        it can either remain Logistics-owned through a direct handoff or cross
        the ownership boundary into Inventory.  Inventory Admission is therefore
        never used as an implicit substitute for Cargo Handling.
        """
        del day
        rows: list[ServiceCapacityRequest] = []
        for waiting in sorted(self.arrival_waiting.values(), key=lambda row: str(row.id)):
            rows.append(
                ServiceCapacityRequest(
                    self._handoff_request_id(waiting.id, "arrival"),
                    waiting.node_id,
                    "cargo_transfer",
                    waiting.amount_t,
                    waiting.priority,
                    "cargo_handoff",
                    waiting.id,
                    "arrival_handling",
                )
            )
        for staging in sorted(self.handoff_staging.values(), key=lambda row: str(row.id)):
            rows.append(
                ServiceCapacityRequest(
                    self._handoff_request_id(staging.id, "reload"),
                    staging.node_id,
                    "cargo_transfer",
                    staging.amount_t,
                    staging.priority,
                    "cargo_handoff",
                    staging.id,
                    "reload_handoff",
                )
            )
        return tuple(rows)

    @staticmethod
    def _allocated_handoff_rate(
        allocations: ServiceCapacityAllocationPlan | None, request_id: EntityId
    ) -> float:
        if allocations is None:
            return 0.0
        try:
            return max(0.0, allocations.allocated(request_id))
        except KeyError:
            return 0.0

    @staticmethod
    def _staging_semantics_key(staging: CargoHandoffStaging) -> tuple:
        return (
            staging.resource_id, staging.node_id, staging.final_destination_id,
            staging.requirement_id, staging.owner_kind, staging.owner_id, int(staging.priority),
            staging.remaining_legs,
        )

    def _stage_unloaded_handoff(
        self, waiting: CargoArrivalWaiting, amount_t: float, day: int
    ) -> float:
        if amount_t <= 1e-12 or not waiting.remaining_legs:
            return 0.0
        probe_key = (
            waiting.resource_id, waiting.node_id, waiting.final_destination_id,
            waiting.requirement_id, waiting.owner_kind, waiting.owner_id, int(waiting.priority),
            waiting.remaining_legs,
        )
        existing = next(
            (
                row for row in sorted(self.handoff_staging.values(), key=lambda row: str(row.id))
                if self._staging_semantics_key(row) == probe_key
            ),
            None,
        )
        if existing is None:
            self._handoff_staging_counter += 1
            staging_id = EntityId(f"cargo.handoff.{self._handoff_staging_counter}")
            reservation_owner = EntityId(f"reservation.cargo_handoff:{staging_id}")
        else:
            staging_id = existing.id
            reservation_owner = existing.reservation_owner_id

        admission = self.inventory.admit(waiting.node_id, waiting.resource_id, amount_t)
        admitted = admission.admitted_t
        if admitted <= 1e-12:
            return 0.0
        reserved = self.inventory.reserve(
            reservation_owner, waiting.node_id, waiting.resource_id, admitted
        )
        if abs(reserved - admitted) > 1e-8:
            raise RuntimeError("cargo handoff admission could not be reserved atomically")
        if existing is None:
            self.handoff_staging[staging_id] = CargoHandoffStaging(
                staging_id, waiting.resource_id, admitted, waiting.node_id,
                waiting.final_destination_id, waiting.requirement_id, waiting.owner_kind,
                waiting.owner_id, waiting.priority, reservation_owner,
                waiting.remaining_legs, day,
            )
        else:
            existing.amount_t += admitted
            existing.staged_day = min(existing.staged_day, day)
        return admitted

    def settle_cargo_arrivals(
        self,
        day: int,
        service_allocations: ServiceCapacityAllocationPlan | None = None,
        direct_handoff_allocations: ServiceCapacityAllocationPlan | None = None,
    ) -> None:
        """Complete Boundary handoff/admission after arrival slices are prepared.

        Arrival handling consumes finite ``cargo_transfer`` Service Capacity
        before either direct handoff or Inventory Admission. Direct handoff
        preserves Logistics ownership. If a handled intermediate quantity is
        unloaded, the admitted Resource is immediately reserved under a
        Logistics continuation commitment and is reloaded through the same
        transfer Service on a later boundary.
        """
        # Existing unloaded handoffs get the first chance to reload according to
        # the shared Service allocation that was resolved for this boundary.
        for staging_id in sorted(tuple(self.handoff_staging), key=str):
            staging = self.handoff_staging[staging_id]
            request_id = self._handoff_request_id(staging.id, "reload")
            direct_plan = direct_handoff_allocations or service_allocations
            amount = min(
                staging.amount_t,
                self._allocated_handoff_rate(direct_plan, request_id),
            )
            if amount <= 1e-12:
                continue
            self.inventory.consume_reserved(
                staging.reservation_owner_id, staging.node_id, staging.resource_id, amount
            )
            self._append_cargo_segment(
                resource_id=staging.resource_id,
                amount_t=amount,
                final_destination_id=staging.final_destination_id,
                requirement_id=staging.requirement_id,
                owner_kind=staging.owner_kind,
                owner_id=staging.owner_id,
                priority=staging.priority,
                legs=staging.remaining_legs,
                dispatch_day=day,
            )
            staging.amount_t = max(0.0, staging.amount_t - amount)
            if staging.amount_t <= 1e-9:
                del self.handoff_staging[staging_id]

        for waiting_id in sorted(tuple(self.arrival_waiting), key=str):
            waiting = self.arrival_waiting[waiting_id]
            arrival_request = self._handoff_request_id(waiting.id, "arrival")
            handled = min(
                waiting.amount_t,
                self._allocated_handoff_rate(service_allocations, arrival_request),
            )
            if handled <= 1e-12:
                continue

            if not waiting.remaining_legs:
                admission = self.inventory.admit(
                    waiting.node_id, waiting.resource_id, handled
                )
                waiting.amount_t = max(0.0, waiting.amount_t - admission.admitted_t)
                if waiting.amount_t <= 1e-9:
                    del self.arrival_waiting[waiting_id]
                continue

            direct_plan = direct_handoff_allocations or service_allocations
            direct = min(
                handled,
                self._allocated_handoff_rate(direct_plan, arrival_request),
            )
            if direct > 1e-12:
                self._append_cargo_segment(
                    resource_id=waiting.resource_id,
                    amount_t=direct,
                    final_destination_id=waiting.final_destination_id,
                    requirement_id=waiting.requirement_id,
                    owner_kind=waiting.owner_kind,
                    owner_id=waiting.owner_id,
                    priority=waiting.priority,
                    legs=waiting.remaining_legs,
                    dispatch_day=day,
                )
                waiting.amount_t = max(0.0, waiting.amount_t - direct)

            unload_budget = max(0.0, handled - direct)
            if unload_budget > 1e-12 and waiting.amount_t > 1e-12:
                staged = self._stage_unloaded_handoff(
                    waiting, min(waiting.amount_t, unload_budget), day
                )
                waiting.amount_t = max(0.0, waiting.amount_t - staged)
            if waiting.amount_t <= 1e-9:
                del self.arrival_waiting[waiting_id]

    def _transport_operation_allocation_factor(
        self,
        dependency: TransportOperationDependencyProjection,
        plan: LogisticsResourcePlan,
        resource_allocations: ResourceAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
    ) -> tuple[float, tuple[str, ...]]:
        """Resolve one Transport Allocation's shared dependency fulfillment.

        Planning exposes operation Resource Claims and turnaround Service requests.
        This method only interprets the shared allocation results; it never reads
        Inventory or runs a Transport-local allocator.
        """
        allocation_id = dependency.allocation_id
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
        if has_planned_usage and dependency.turnaround_service_type is not None:
            request_id = dependency.turnaround_request_id
            if request_id is None:
                raise RuntimeError(
                    f"transport dependency missing turnaround request: {allocation_id}"
                )
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
                    f"servicing_allocation:{dependency.anchor_node_id}:"
                    f"{dependency.turnaround_service_type}"
                )

        for location_id in dependency.surface_service_locations:
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
        # tick. Resource and turnaround ratios below remain requirement-shaped by
        # ``plan``; location-wide upstream services such as surface
        # distribution are authoritative for the allocation regardless of
        # current cargo requirement.
        for dependency in self.transport.transport_operation_dependencies(day):
            allocation_id = dependency.allocation_id
            factor, limiting = self._transport_operation_allocation_factor(
                dependency, plan, allocations, service_allocations
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
                row.requirement.id,
                row.requirement.resource_id,
                row.source_id,
                row.requirement.destination_id,
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
            requirement = row.requirement
            self.inventory.consume_allocated(row.source_id, requirement.resource_id, amount)
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

            activities.append(
                DomainActivity(
                    "transport", amount, "supply_dispatch", requirement.id, row.source_id
                )
            )
            self._append_cargo_segment(
                resource_id=requirement.resource_id,
                amount_t=amount,
                final_destination_id=requirement.destination_id,
                requirement_id=requirement.id,
                owner_kind=requirement.owner_kind,
                owner_id=requirement.owner_id,
                priority=requirement.priority,
                legs=tuple(self._cargo_service_leg(edge) for edge in row.path),
                dispatch_day=day,
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

    def _external_policy_blockers_for_source(
        self,
        requirement: SupplyRequirement,
        source_id: SpatialNodeId,
        day: int,
        edges: tuple[TransportServiceSupply, ...],
    ) -> tuple[str, ...]:
        try:
            physical_path = self.supply_service_path(
                requirement, source_id, day, edges, enforce_external_policy=False
            )
        except ValueError:
            return ()
        denied = {
            edge.external_service_id
            for edge in physical_path
            if edge.external_service_id is not None
            and not self.external_economy.service_allowed(
                edge.external_service_id, requirement.owner_kind, requirement.owner_id
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
    ) -> tuple[TransportServiceSupply, ...]:
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

    def supply_planning_options(
        self,
        requirement: SupplyRequirement,
        day: int = 0,
        *,
        execution_allocation: LogisticsExecutionAllocation | None = None,
    ) -> SupplyPlanningOptions:
        edges = self._service_edges_for_execution_allocation(
            day, execution_allocation
        )
        constrained_source, _path_policy, _explicit_path = (
            self._supply_path_preferences(requirement)
        )
        if constrained_source is not None:
            source_ids = (constrained_source,)
        else:
            source_ids = tuple(
                node_id
                for node_id in self.facilities.environment.graph.operational_node_ids()
                if node_id != requirement.destination_id
            )

        candidates: list[SpatialNodeId] = []
        operational: list[SpatialNodeId] = []
        stocked: list[SpatialNodeId] = []
        blockers: list[str] = []
        for source_id in sorted(source_ids, key=str):
            try:
                physical_path = self.supply_service_path(
                    requirement, source_id, day, edges, enforce_external_policy=False
                )
            except ValueError:
                continue
            if not physical_path:
                continue
            candidates.append(source_id)
            if self.inventory.available(source_id, requirement.resource_id) > 1e-9:
                stocked.append(source_id)
            try:
                path = self.supply_service_path(requirement, source_id, day, edges)
            except ValueError as exc:
                policy_blockers = self._external_policy_blockers_for_source(
                    requirement, source_id, day, edges
                )
                blockers.extend(policy_blockers or (f"transport_capacity:{exc}",))
                continue
            if path and min(edge.capacity_t_per_day for edge in path) > 1e-12:
                operational.append(source_id)

        arrivals = [
            flow.first_arrival_day
            for flow in self.cargo_flows.values()
            if flow.requirement_id == requirement.id
        ]
        return SupplyPlanningOptions(
            tuple(candidates),
            tuple(operational),
            tuple(stocked),
            tuple(dict.fromkeys(blockers)),
            min(arrivals) if arrivals else None,
        )
