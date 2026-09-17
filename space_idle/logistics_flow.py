from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
from typing import Mapping

from .execution_requirements import (
    AllocationConstraintKey,
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    PoolRequirement,
    ResourceRequirement,
    ServiceCapacityRequirement,
    pool_constraint,
)
from .knowledge import DomainActivity
from .allocation_projection import ResourceAllocationProjectionRow
from .supply import SupplyRequirement
from .service_capacity import ServiceCapacityAllocationPlan
from .shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
from .supply_planning import SupplyPlanningOptions
from .logistics_models import (
    CargoArrivalWaiting,
    CargoFlowSegment,
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
    cargo_execution_id: EntityId


@dataclass(frozen=True)
class LogisticsResourcePlan:
    dispatches: tuple[_PlannedDispatch, ...]
    planned_usage: tuple[tuple[EntityId, DirectionalCapacity], ...]


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

    Cargo quantity is already fixed by the common Execution Requirement
    allocation graph, including source Resource, Transport Capacity, Fleet
    operation Resource and turnaround Service requirements.  This object only
    freezes that result for execution and Application projection.
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

    The daily capacity budget is derived from player-owned Transport Allocations.
    Logistics consumes it; it does not select or resize Fleet assets.
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
    def _transport_capacity_pool_id(edge: TransportServiceSupply) -> str:
        return edge.key

    def allocation_pool_capacities(
        self,
        day: int,
        availability_factors: Mapping[EntityId, float] | None = None,
    ) -> dict[AllocationConstraintKey, float]:
        """Expose directional Transport Capacity as shared allocation pools.

        ``availability_factors`` represents upstream operation-support
        availability already resolved by the Simulation allocation graph for
        each player-owned Transport Allocation.
        """
        factors = availability_factors or {}
        capacities: dict[AllocationConstraintKey, float] = {}
        for edge in self._service_edges(day):
            factor = max(0.0, min(1.0, factors.get(edge.allocation_id, 1.0)))
            key = pool_constraint(
                self._transport_capacity_pool_id(edge),
                scope_id="transport_capacity",
            )
            capacity = edge.capacity_t_per_day * factor
            existing = capacities.get(key)
            if existing is not None and abs(existing - capacity) > 1e-9:
                raise RuntimeError(
                    f"transport capacity pool has inconsistent edge capacity: {key}"
                )
            capacities[key] = capacity
        return capacities

    def _operation_reference_usage(
        self,
        plan: LogisticsResourcePlan,
        reference_usage: Mapping[EntityId, DirectionalCapacity] | None,
    ) -> dict[EntityId, DirectionalCapacity]:
        planned = dict(plan.planned_usage)
        if reference_usage is None:
            return planned
        rows = dict(reference_usage)
        # A zero allocation still needs operation coefficients in order to test
        # whether Cargo can start on the next solve.  The planned mix supplies a
        # deterministic reference without reserving anything when execution is 0.
        for allocation_id, usage in planned.items():
            current = rows.get(allocation_id, DirectionalCapacity())
            if (
                current.forward_t_per_day <= 1e-12
                and current.reverse_t_per_day <= 1e-12
            ):
                rows[allocation_id] = usage
        return rows

    def dispatch_execution_requirements(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        reference_usage: Mapping[EntityId, DirectionalCapacity] | None = None,
    ) -> tuple[ExecutionRequirementBundle, ...]:
        """Convert each planned Cargo dispatch into one complete root Bundle.

        Source Resource, end-to-end Transport Capacity, Fleet operational
        Resources and turnaround Service Capacity are all requirements of the
        same dispatched tonne.  Shared empty-cycle/turnaround load is attributed
        between directions from ``reference_usage`` by Transport; Simulation
        iterates that reference until it matches the allocated Cargo mix.
        """
        usage_reference = self._operation_reference_usage(plan, reference_usage)
        operation_by_allocation = {
            allocation_id: self.transport.transport_operation_usage_requirements(
                allocation_id, day, usage
            )
            for allocation_id, usage in usage_reference.items()
        }

        rows: list[ExecutionRequirementBundle] = []
        seen: set[EntityId] = set()
        for dispatch in plan.dispatches:
            if dispatch.cargo_execution_id in seen:
                raise RuntimeError(
                    "planned dispatches must have one root execution bundle per cargo dispatch"
                )
            seen.add(dispatch.cargo_execution_id)

            resources: dict[tuple[SpatialNodeId, DefinitionId], float] = {
                (dispatch.source_id, dispatch.requirement.resource_id): 1.0
            }
            services: dict[tuple[SpatialNodeId, str], float] = {}
            edge_counts: dict[str, int] = {}
            for edge in dispatch.path:
                key = self._transport_capacity_pool_id(edge)
                edge_counts[key] = edge_counts.get(key, 0) + 1
                operation = operation_by_allocation.get(edge.allocation_id)
                if operation is None:
                    raise RuntimeError(
                        f"owned transport edge lacks operation requirements: {edge.allocation_id}"
                    )
                if edge.direction == "forward":
                    resource_rows = operation.forward_resource_per_t
                    turnaround = operation.forward_turnaround_per_t
                else:
                    resource_rows = operation.reverse_resource_per_t
                    turnaround = operation.reverse_turnaround_per_t
                for node_id, resource_id, amount in resource_rows:
                    resource_key = (node_id, resource_id)
                    resources[resource_key] = resources.get(resource_key, 0.0) + amount
                if (
                    operation.turnaround_service_type is not None
                    and turnaround > 1e-12
                ):
                    service_key = (
                        operation.turnaround_node_id,
                        operation.turnaround_service_type,
                    )
                    services[service_key] = services.get(service_key, 0.0) + turnaround

            requirements = [
                *(
                    ResourceRequirement(
                        resource_id, amount, constraint_node_id=node_id
                    )
                    for (node_id, resource_id), amount in sorted(
                        resources.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
                    )
                    if amount > 1e-12
                ),
                *(
                    ServiceCapacityRequirement(
                        service_type, amount, constraint_node_id=node_id
                    )
                    for (node_id, service_type), amount in sorted(
                        services.items(), key=lambda row: (str(row[0][0]), row[0][1])
                    )
                    if amount > 1e-12
                ),
                *(
                    PoolRequirement(
                        pool_id,
                        float(count),
                        scope_id="transport_capacity",
                    )
                    for pool_id, count in sorted(edge_counts.items())
                ),
            ]
            rows.append(
                ExecutionRequirementBundle(
                    id=dispatch.cargo_execution_id,
                    owner_kind="logistics_dispatch",
                    owner_id=dispatch.requirement.owner_id,
                    purpose=f"supply:{dispatch.requirement.id}",
                    operational_node_id=dispatch.source_id,
                    requested_execution=dispatch.amount_t,
                    priority=dispatch.requirement.priority,
                    requirements=tuple(requirements),
                )
            )
        return tuple(rows)

    def dispatch_usage_from_execution(
        self, plan: LogisticsResourcePlan, execution: ExecutionAllocationPlan
    ) -> dict[EntityId, DirectionalCapacity]:
        """Derive owned-Fleet directional use from allocated Cargo root Bundles."""
        used: dict[EntityId, DirectionalCapacity] = {}
        for dispatch in plan.dispatches:
            try:
                amount = execution.allocated(dispatch.cargo_execution_id)
            except KeyError:
                amount = 0.0
            amount = min(dispatch.amount_t, max(0.0, amount))
            if amount <= 1e-12:
                continue
            used = self._allocation_used_after(used, dispatch.path, amount)
        return used

    def transport_surface_availability(
        self,
        day: int,
        service_allocations: ServiceCapacityAllocationPlan,
    ) -> tuple[dict[EntityId, float], dict[EntityId, tuple[str, ...]]]:
        """Project location-wide surface distribution fulfillment to Fleet service."""
        factors: dict[EntityId, float] = {}
        limits: dict[EntityId, tuple[str, ...]] = {}
        for dependency in self.transport.transport_operation_dependencies(day):
            ratios: list[float] = []
            row_limits: list[str] = []
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
                    row_limits.append(f"surface_infrastructure:{location_id}")
            factors[dependency.allocation_id] = min(ratios) if ratios else 1.0
            limits[dependency.allocation_id] = tuple(dict.fromkeys(row_limits))
        return factors, limits

    def transport_operation_constraint_keys(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        reference_usage: Mapping[EntityId, DirectionalCapacity],
    ) -> dict[EntityId, frozenset[AllocationConstraintKey]]:
        """Return Resource/Service constraints that physically operate each Fleet."""
        usage_reference = self._operation_reference_usage(plan, reference_usage)
        result: dict[EntityId, frozenset[AllocationConstraintKey]] = {}
        for allocation_id, usage in usage_reference.items():
            operation = self.transport.transport_operation_usage_requirements(
                allocation_id, day, usage
            )
            keys: set[AllocationConstraintKey] = set()
            for rows in (
                operation.forward_resource_per_t,
                operation.reverse_resource_per_t,
            ):
                for node_id, resource_id, amount in rows:
                    if amount > 1e-12:
                        keys.add(
                            ResourceRequirement(
                                resource_id, amount, constraint_node_id=node_id
                            ).constraint_key(node_id)
                        )
            if operation.turnaround_service_type is not None:
                if (
                    operation.forward_turnaround_per_t > 1e-12
                    or operation.reverse_turnaround_per_t > 1e-12
                ):
                    keys.add(
                        ServiceCapacityRequirement(
                            operation.turnaround_service_type,
                            1.0,
                            constraint_node_id=operation.turnaround_node_id,
                        ).constraint_key(operation.turnaround_node_id)
                    )
            result[allocation_id] = frozenset(keys)
        return result

    @staticmethod
    def _operation_constraint_limit_label(key: AllocationConstraintKey) -> str:
        if key.kind == "resource":
            node_id = key.scope_id.removeprefix("node:")
            return f"resource_allocation:{node_id}:{key.name}"
        if key.kind == "service":
            node_id = key.scope_id.removeprefix("node:")
            return f"servicing_allocation:{node_id}:{key.name}"
        return f"allocation:{key.kind}:{key.scope_id}:{key.name}"

    def transport_operation_execution_projection(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        execution: ExecutionAllocationPlan,
        used_by_allocation: Mapping[EntityId, DirectionalCapacity],
        reference_usage: Mapping[EntityId, DirectionalCapacity],
        surface_factors: Mapping[EntityId, float],
        surface_limits: Mapping[EntityId, tuple[str, ...]],
    ) -> tuple[tuple[EntityId, float, tuple[str, ...]], ...]:
        """Expose operation-induced Available-capacity factors for queries.

        Cargo root Bundles already consumed the operation Requirements.  This
        projection never changes execution; it only explains when those specific
        constraints reduced the executable service.
        """
        operation_keys = self.transport_operation_constraint_keys(
            day, plan, reference_usage
        )
        dispatch_by_id = {row.cargo_execution_id: row for row in plan.dispatches}
        factors = {
            dependency.allocation_id: max(
                0.0, min(1.0, surface_factors.get(dependency.allocation_id, 1.0))
            )
            for dependency in self.transport.transport_operation_dependencies(day)
        }
        limits = {
            allocation_id: list(surface_limits.get(allocation_id, ()))
            for allocation_id in factors
        }
        support_limited: set[EntityId] = set()
        for allocation in execution.allocations:
            if allocation.allocated_execution >= allocation.requested_execution - 1e-10:
                continue
            dispatch = dispatch_by_id.get(allocation.bundle_id)
            if dispatch is None:
                continue
            for edge in dispatch.path:
                hits = set(allocation.limiting_constraints) & set(
                    operation_keys.get(edge.allocation_id, frozenset())
                )
                if not hits:
                    continue
                support_limited.add(edge.allocation_id)
                limits.setdefault(edge.allocation_id, []).extend(
                    self._operation_constraint_limit_label(key)
                    for key in sorted(hits)
                )

        for allocation_id in support_limited:
            usage = used_by_allocation.get(allocation_id, DirectionalCapacity())
            snapshot = self.transport.transport_capacity_snapshot(
                allocation_id, day=day, used=usage
            )
            ratios: list[float] = []
            if snapshot.available.forward_t_per_day > 1e-12:
                ratios.append(
                    usage.forward_t_per_day / snapshot.available.forward_t_per_day
                )
            if snapshot.available.reverse_t_per_day > 1e-12:
                ratios.append(
                    usage.reverse_t_per_day / snapshot.available.reverse_t_per_day
                )
            factors[allocation_id] = min(
                factors.get(allocation_id, 1.0),
                max(0.0, min(1.0, max(ratios, default=0.0))),
            )

        return tuple(
            (
                allocation_id,
                factors[allocation_id],
                tuple(dict.fromkeys(limits.get(allocation_id, ()))),
            )
            for allocation_id in sorted(factors, key=str)
        )

    def transport_service_allocation_overrides(
        self,
        day: int,
        used_by_allocation: Mapping[EntityId, DirectionalCapacity],
    ) -> dict[EntityId, float]:
        """Project allocated Fleet turnaround use into the Service query view."""
        usage = dict(used_by_allocation)
        dynamic_turnaround = {
            request.owner_id: request
            for request in self.transport.transport_service_capacity_requests(
                day, tuple(sorted(usage.items(), key=lambda row: str(row[0])))
            )
            if request.owner_kind == "transport"
            and request.purpose == "turnaround_servicing"
        }
        return {
            request.id: request.requested_rate
            for request in dynamic_turnaround.values()
        }

    def resource_allocation_projection(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        execution: ExecutionAllocationPlan,
        used_by_allocation: Mapping[EntityId, DirectionalCapacity],
        reference_usage: Mapping[EntityId, DirectionalCapacity] | None = None,
    ) -> tuple[ResourceAllocationProjectionRow, ...]:
        """Project Cargo and Fleet Resource use from the common execution result."""
        cargo_totals: dict[EntityId, float] = {}
        cargo_meta: dict[EntityId, _PlannedDispatch] = {}
        for dispatch in plan.dispatches:
            cargo_totals[dispatch.cargo_execution_id] = (
                cargo_totals.get(dispatch.cargo_execution_id, 0.0) + dispatch.amount_t
            )
            cargo_meta.setdefault(dispatch.cargo_execution_id, dispatch)

        rows: list[ResourceAllocationProjectionRow] = []
        for execution_id, requested in sorted(cargo_totals.items(), key=lambda row: str(row[0])):
            dispatch = cargo_meta[execution_id]
            requirement = dispatch.requirement
            try:
                allocated = execution.allocated(execution_id)
            except KeyError:
                allocated = 0.0
            rows.append(
                ResourceAllocationProjectionRow(
                    execution_id,
                    dispatch.source_id,
                    requirement.resource_id,
                    "logistics_dispatch",
                    requirement.owner_id,
                    f"supply:{requirement.id}",
                    requirement.priority,
                    requested,
                    min(requested, max(0.0, allocated)),
                    requirement_id=requirement.id,
                )
            )

        requested_usage = dict(plan.planned_usage) if reference_usage is None else dict(reference_usage)
        requested_operational = self._operational_resource_totals_by_allocation(
            requested_usage, day
        )
        allocated_operational = self._operational_resource_totals_by_allocation(
            dict(used_by_allocation), day
        )
        dependencies = {
            row.allocation_id: row
            for row in self.transport.transport_operation_dependencies(day)
        }
        for (allocation_id, location_id, resource_id), requested in sorted(
            requested_operational.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1]), str(row[0][2])),
        ):
            if requested <= 1e-12:
                continue
            allocated = allocated_operational.get(
                (allocation_id, location_id, resource_id), 0.0
            )
            dependency = dependencies.get(allocation_id)
            if dependency is None:
                continue
            rows.append(
                ResourceAllocationProjectionRow(
                    self._operation_projection_id(
                        allocation_id, location_id, resource_id
                    ),
                    location_id,
                    resource_id,
                    "transport_operation",
                    allocation_id,
                    "sustained_transport",
                    dependency.priority,
                    requested,
                    min(requested, max(0.0, allocated)),
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
        )

    @staticmethod
    def _capacity_owner_key_from_leg(leg: CargoServiceLeg) -> tuple:
        return ("allocation", leg.allocation_id, leg.direction)

    @staticmethod
    def _capacity_owner_key_from_supply(edge: TransportServiceSupply) -> tuple:
        return ("allocation", edge.allocation_id, edge.direction)

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
    ) -> tuple[TransportServiceSupply, ...]:
        available = self._service_edges(day) if edges is None else edges
        _source, path_policy, explicit_path = self._supply_path_preferences(requirement)
        if explicit_path is None:
            return self._automatic_service_path(
                source_id, requirement.destination_id, available, path_policy
            )
        return self._explicit_service_path(
            source_id, requirement.destination_id, explicit_path, available, path_policy
        )

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

    def _allocation_used_after(
        self,
        used: dict[EntityId, DirectionalCapacity],
        path: tuple[TransportServiceSupply, ...],
        amount: float,
    ) -> dict[EntityId, DirectionalCapacity]:
        result = dict(used)
        for edge in path:
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
    def _cargo_execution_id(source_id: SpatialNodeId, requirement_id: EntityId) -> EntityId:
        return EntityId(f"execution.logistics.cargo:{source_id}:{requirement_id}")

    @staticmethod
    def _operation_projection_id(
        allocation_id: EntityId, location_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(
            f"allocation.transport.operation:{allocation_id}:{location_id}:{resource_id}"
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

    def active_shipping_requirements(
        self, day: int, requirements: tuple[SupplyRequirement, ...]
    ) -> tuple[SupplyRequirement, ...]:
        """Resolve gross future need into latency-aware off-site shipping targets.

        Stable Supply Requirements describe desired quantity and, optionally, a
        recurring consumption/throughput rate.  Existing inbound Cargo belongs
        to its requirement and is credited first.  Destination Inventory is then
        shared by Activity Priority (with proportional fairness inside a band).
        For recurring demand, the target includes enough coverage for the
        selected end-to-end latency plus the current execution day.

        The returned rows still include requirement-owned inbound in ``amount_t``;
        ``plan_capacity_logistics`` subtracts that pipeline exactly once when it
        derives today's dispatch.
        """
        edges = self._service_edges(day)
        ordered = tuple(sorted(requirements, key=lambda row: (-row.priority, str(row.id))))
        pipeline = self._flow_pipeline_by_requirement({row.id for row in ordered})
        target_by_id: dict[EntityId, float] = {}
        uncovered_by_id: dict[EntityId, float] = {}

        for requirement in ordered:
            target = requirement.amount_t
            if requirement.recurring_rate_t_per_day is not None:
                candidates = self._candidate_supply_paths(requirement, day, edges)
                if candidates:
                    _source_id, path = candidates[0]
                    lead_days = sum(edge.latency_days for edge in path)
                    target = max(
                        target,
                        requirement.recurring_rate_t_per_day * (lead_days + 1),
                    )
            target_by_id[requirement.id] = target
            uncovered_by_id[requirement.id] = max(0.0, target - pipeline[requirement.id])

        local_credit: dict[EntityId, float] = {}
        by_key: dict[tuple[SpatialNodeId, DefinitionId], list[SupplyRequirement]] = {}
        for requirement in ordered:
            by_key.setdefault((requirement.destination_id, requirement.resource_id), []).append(requirement)

        for key in sorted(by_key, key=lambda row: (str(row[0]), str(row[1]))):
            available = max(0.0, self.inventory.available(key[0], key[1]))
            priority_bands: dict[int, list[SupplyRequirement]] = {}
            for requirement in by_key[key]:
                priority_bands.setdefault(int(requirement.priority), []).append(requirement)
            for priority in sorted(priority_bands, reverse=True):
                band = priority_bands[priority]
                total_need = sum(uncovered_by_id[row.id] for row in band)
                if available <= 1e-12 or total_need <= 1e-12:
                    continue
                credit_total = min(available, total_need)
                for requirement in band:
                    need = uncovered_by_id[requirement.id]
                    local_credit[requirement.id] = credit_total * need / total_need
                available -= credit_total

        rows: list[SupplyRequirement] = []
        for requirement in ordered:
            amount = max(0.0, target_by_id[requirement.id] - local_credit.get(requirement.id, 0.0))
            if amount <= 1e-12:
                continue
            rows.append(replace(requirement, amount_t=amount))
        return tuple(rows)

    def plan_capacity_logistics(
        self, day: int, requirements: tuple[SupplyRequirement, ...]
    ) -> LogisticsResourcePlan:
        """Plan due end-to-end dispatch intents without settling scarce capacity.

        ``requirements`` are off-site shipping targets after destination Inventory
        credit.  Planning selects a source/path candidate and requested dispatch
        amount, then credits requirement-owned inbound Cargo exactly once. Source
        Inventory and every Transport Service edge remain finite requirements of
        the resulting root execution Bundle, so Activity Priority and progressive
        max-min are resolved once in the common allocation graph.
        """
        edges = self._service_edges(day)
        requirement_rows = tuple(
            sorted(requirements, key=lambda row: (-row.priority, str(row.id)))
        )
        pipeline = self._flow_pipeline_by_requirement({row.id for row in requirement_rows})
        used: dict[EntityId, DirectionalCapacity] = {}
        dispatches: list[_PlannedDispatch] = []

        for requirement in requirement_rows:
            amount = max(0.0, requirement.amount_t - pipeline[requirement.id])
            if amount <= 1e-12:
                continue
            candidates = self._candidate_supply_paths(requirement, day, edges)
            selected = next(
                (
                    (source_id, path)
                    for source_id, path in candidates
                    if self._dispatch_is_due(requirement, day, path)
                ),
                None,
            )
            if selected is None:
                continue
            source_id, path = selected

            dispatches.append(
                _PlannedDispatch(
                    source_id,
                    requirement,
                    path,
                    amount,
                    self._cargo_execution_id(source_id, requirement.id),
                )
            )
            used = self._allocation_used_after(used, path, amount)

        return LogisticsResourcePlan(
            tuple(dispatches),
            tuple(sorted(used.items(), key=lambda row: str(row[0]))),
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

    def boundary_execution_bundles(self, day: int) -> tuple[ExecutionRequirementBundle, ...]:
        """Expose already-arrived Cargo as finite Boundary obligations.

        Final arrivals require both Cargo Handling and Inventory Admission in one
        root bundle. Intermediate direct handoffs require Cargo Handling only.
        The common boundary allocator therefore applies the same Activity
        Priority/fairness semantics across all obligations.
        """
        del day
        from .execution_requirements import StockOrPoolAdmissionRequirement
        rows: list[ExecutionRequirementBundle] = []
        for waiting in sorted(self.arrival_waiting.values(), key=lambda row: str(row.id)):
            requirements: list = [ServiceCapacityRequirement("cargo_transfer", 1.0)]
            if not waiting.remaining_legs:
                storage_class = self.inventory.resource_storage_class.get(waiting.resource_id)
                if storage_class is not None:
                    requirements.append(StockOrPoolAdmissionRequirement(storage_class, 1.0))
            rows.append(ExecutionRequirementBundle(
                id=self._handoff_request_id(waiting.id, "arrival"),
                owner_kind="cargo_handoff", owner_id=waiting.id, purpose="arrival_handling",
                operational_node_id=waiting.node_id, requested_execution=waiting.amount_t,
                priority=waiting.priority, requirements=tuple(requirements),
            ))
        return tuple(rows)

    def settle_cargo_boundary_execution(
        self, day: int, execution: ExecutionAllocationPlan
    ) -> None:
        """Settle only quantities authorized by the common Boundary allocation."""
        for waiting_id in sorted(tuple(self.arrival_waiting), key=str):
            waiting = self.arrival_waiting[waiting_id]
            request_id = self._handoff_request_id(waiting.id, "arrival")
            try:
                amount = min(waiting.amount_t, max(0.0, execution.allocated(request_id)))
            except KeyError:
                amount = 0.0
            if amount <= 1e-12:
                continue
            if waiting.remaining_legs:
                self._append_cargo_segment(
                    resource_id=waiting.resource_id, amount_t=amount,
                    final_destination_id=waiting.final_destination_id,
                    requirement_id=waiting.requirement_id, owner_kind=waiting.owner_kind,
                    owner_id=waiting.owner_id, priority=waiting.priority,
                    legs=waiting.remaining_legs, dispatch_day=day,
                )
            else:
                admission = self.inventory.admit(waiting.node_id, waiting.resource_id, amount)
                if abs(admission.admitted_t - amount) > 1e-7:
                    raise RuntimeError("boundary Cargo allocation exceeded Inventory Admission")
            waiting.amount_t = max(0.0, waiting.amount_t - amount)
            if waiting.amount_t <= 1e-9:
                del self.arrival_waiting[waiting_id]

    def build_capacity_logistics_execution(
        self,
        day: int,
        plan: LogisticsResourcePlan,
        execution: ExecutionAllocationPlan,
        operation_factors: tuple[tuple[EntityId, float, tuple[str, ...]], ...],
    ) -> LogisticsExecutionAllocation:
        """Build the immutable Logistics execution result from common allocation.

        Every executable Cargo quantity is already the root Bundle allocation.
        This method performs no secondary scarcity calculation and no ``min``
        across independently settled Resource/Service plans.
        """
        used: dict[EntityId, DirectionalCapacity] = {}
        executable: list[tuple[_PlannedDispatch, float]] = []
        for row in plan.dispatches:
            try:
                amount = execution.allocated(row.cargo_execution_id)
            except KeyError:
                amount = 0.0
            amount = min(row.amount_t, max(0.0, amount))
            if amount <= 1e-9:
                continue
            executable.append((row, amount))
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
            operation_factors,
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
        execution: LogisticsExecutionAllocation,
    ) -> tuple[DomainActivity, ...]:
        """Execute exactly the already-resolved Transport allocation."""
        activities: list[DomainActivity] = []
        for row, amount in execution.executable_dispatches:
            requirement = row.requirement
            self.inventory.consume_allocated(row.source_id, requirement.resource_id, amount)

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

    def _service_edges_for_execution_allocation(
        self,
        day: int,
        execution_allocation: LogisticsExecutionAllocation | None,
    ) -> tuple[TransportServiceSupply, ...]:
        edges = self._service_edges(day)
        if execution_allocation is None:
            return edges
        return tuple(
            replace(
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
            # Source candidacy is independent of today's Transport Capacity.
            # A valid source remains visible while the player has not yet
            # provisioned a Fleet allocation; transport feasibility/availability
            # is projected separately through ``operational_source_ids``.
            candidates.append(source_id)
            if self.inventory.available(source_id, requirement.resource_id) > 1e-9:
                stocked.append(source_id)
            try:
                physical_path = self.supply_service_path(
                    requirement, source_id, day, edges
                )
            except ValueError:
                continue
            if not physical_path:
                continue
            if min(edge.capacity_t_per_day for edge in physical_path) > 1e-12:
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
