from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .shared import EntityId, SpatialNodeId


@dataclass(frozen=True)
class ServiceCapacityRequest:
    """Transient request for a finite per-tick service flow.

    Requests are allocation inputs, never persisted state.  ``minimum_rate``
    and ``atomic`` are explicit opt-ins for consumers that are useless below a
    threshold; continuous requests share same-priority scarcity proportionally.
    """

    id: EntityId
    operational_node_id: SpatialNodeId
    service_type: str
    requested_rate: float
    priority: int
    owner_kind: str
    owner_id: EntityId
    purpose: str
    minimum_rate: float = 0.0
    atomic: bool = False

    def __post_init__(self) -> None:
        if not self.service_type:
            raise ValueError("service type must not be empty")
        if self.requested_rate < -1e-9:
            raise ValueError("service capacity requested rate must be non-negative")
        if self.minimum_rate < -1e-9:
            raise ValueError("service capacity minimum rate must be non-negative")
        if self.minimum_rate > self.requested_rate + 1e-9:
            raise ValueError("service capacity minimum cannot exceed requested rate")
        if self.atomic and self.minimum_rate not in (0.0, self.requested_rate):
            raise ValueError("atomic service capacity minimum must be zero or full request")

    @property
    def effective_minimum_rate(self) -> float:
        return self.requested_rate if self.atomic else self.minimum_rate


@dataclass(frozen=True)
class ServiceCapacityAllocation:
    request_id: EntityId
    requested_rate: float
    allocated_rate: float
    unmet_rate: float

    def __post_init__(self) -> None:
        if min(self.requested_rate, self.allocated_rate, self.unmet_rate) < -1e-9:
            raise ValueError("service capacity allocation amounts must be non-negative")
        if abs(self.allocated_rate + self.unmet_rate - self.requested_rate) > 1e-7:
            raise ValueError("service capacity allocation must conserve the request")


@dataclass(frozen=True)
class ServiceCapacitySummary:
    operational_node_id: SpatialNodeId
    service_type: str
    nominal_rate: float
    enabled_rate: float
    requested_rate: float
    allocated_rate: float
    spare_rate: float
    limiting_factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceCapacityAllocationPlan:
    requests: tuple[ServiceCapacityRequest, ...]
    allocations: tuple[ServiceCapacityAllocation, ...]
    supply_nominal: Mapping[tuple[SpatialNodeId, str], float]
    supply_enabled: Mapping[tuple[SpatialNodeId, str], float]
    supply_limiting_factors: Mapping[tuple[SpatialNodeId, str], tuple[str, ...]]

    def __post_init__(self) -> None:
        request_ids = [request.id for request in self.requests]
        allocation_ids = [row.request_id for row in self.allocations]
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("duplicate service capacity request id")
        if set(request_ids) != set(allocation_ids) or len(request_ids) != len(allocation_ids):
            raise ValueError("service capacity allocation plan must contain one allocation per request")
        for key, enabled in self.supply_enabled.items():
            nominal = self.supply_nominal.get(key, 0.0)
            if enabled < -1e-9 or nominal < -1e-9 or enabled > nominal + 1e-7:
                raise ValueError(f"invalid service capacity supply for {key}")

    def request(self, request_id: EntityId) -> ServiceCapacityRequest:
        for request in self.requests:
            if request.id == request_id:
                return request
        raise KeyError(request_id)

    def allocation(self, request_id: EntityId) -> ServiceCapacityAllocation:
        for row in self.allocations:
            if row.request_id == request_id:
                return row
        raise KeyError(request_id)

    def allocated(self, request_id: EntityId) -> float:
        return self.allocation(request_id).allocated_rate

    def allocations_for_owner(self, owner_kind: str, owner_id: EntityId) -> tuple[ServiceCapacityAllocation, ...]:
        ids = {
            request.id
            for request in self.requests
            if request.owner_kind == owner_kind and request.owner_id == owner_id
        }
        return tuple(row for row in self.allocations if row.request_id in ids)

    def summary(self, operational_node_id: SpatialNodeId, service_type: str) -> ServiceCapacitySummary:
        key = (operational_node_id, service_type)
        related = tuple(
            request for request in self.requests
            if request.operational_node_id == operational_node_id and request.service_type == service_type
        )
        ids = {request.id for request in related}
        requested = sum(request.requested_rate for request in related)
        allocated = sum(row.allocated_rate for row in self.allocations if row.request_id in ids)
        nominal = max(0.0, self.supply_nominal.get(key, 0.0))
        enabled = max(0.0, self.supply_enabled.get(key, 0.0))
        return ServiceCapacitySummary(
            operational_node_id,
            service_type,
            nominal,
            enabled,
            requested,
            allocated,
            max(0.0, enabled - allocated),
            self.supply_limiting_factors.get(key, ()),
        )



@dataclass(frozen=True)
class ServiceCapacityDependency:
    """A same-tick provider edge between finite service types.

    ``service_type`` is the downstream service whose Available supply depends
    on allocation of ``upstream_service_type``. Dependencies are transient
    planning/configuration data, not persisted state.
    """

    service_type: str
    upstream_service_type: str

    def __post_init__(self) -> None:
        if not self.service_type or not self.upstream_service_type:
            raise ValueError("service capacity dependency types must not be empty")


def service_capacity_dependency_order(
    service_types: Iterable[str],
    dependencies: Iterable[ServiceCapacityDependency],
) -> tuple[str, ...]:
    """Return a deterministic upstream-first order and reject cycles."""

    nodes = set(service_types)
    edges = tuple(dependencies)
    for edge in edges:
        nodes.add(edge.service_type)
        nodes.add(edge.upstream_service_type)

    downstream: dict[str, set[str]] = {node: set() for node in nodes}
    indegree: dict[str, int] = {node: 0 for node in nodes}
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        key = (edge.upstream_service_type, edge.service_type)
        if key in seen:
            continue
        seen.add(key)
        downstream[edge.upstream_service_type].add(edge.service_type)
        indegree[edge.service_type] += 1

    ready = sorted(node for node, count in indegree.items() if count == 0)
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for dependent in sorted(downstream[node]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()

    if len(ordered) != len(nodes):
        cyclic = tuple(sorted(node for node, count in indegree.items() if count > 0))
        raise ValueError(
            "service capacity dependency cycle: " + " -> ".join(cyclic)
        )
    return tuple(ordered)


def merge_service_capacity_plans(
    plans: Iterable[ServiceCapacityAllocationPlan],
) -> ServiceCapacityAllocationPlan:
    """Combine disjoint service-type stage results into one tick plan."""

    rows = tuple(plans)
    requests: list[ServiceCapacityRequest] = []
    allocations: list[ServiceCapacityAllocation] = []
    nominal: dict[tuple[SpatialNodeId, str], float] = {}
    enabled: dict[tuple[SpatialNodeId, str], float] = {}
    limiting: dict[tuple[SpatialNodeId, str], tuple[str, ...]] = {}
    for plan in rows:
        requests.extend(plan.requests)
        allocations.extend(plan.allocations)
        for source, target in (
            (plan.supply_nominal, nominal),
            (plan.supply_enabled, enabled),
            (plan.supply_limiting_factors, limiting),
        ):
            for key, value in source.items():
                if key in target:
                    raise ValueError(f"duplicate staged service capacity supply: {key}")
                target[key] = value

    request_ids = [request.id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("duplicate staged service capacity request id")
    allocation_by_id = {row.request_id: row for row in allocations}
    ordered_requests = tuple(
        sorted(requests, key=lambda request: (-request.priority, _request_order_key(request)))
    )
    ordered_allocations = tuple(allocation_by_id[request.id] for request in ordered_requests)
    return ServiceCapacityAllocationPlan(
        ordered_requests, ordered_allocations, nominal, enabled, limiting
    )

def _request_order_key(request: ServiceCapacityRequest) -> tuple:
    return (
        request.owner_kind,
        str(request.owner_id),
        request.purpose,
        str(request.operational_node_id),
        request.service_type,
        str(request.id),
    )


def _allocate_priority_band(
    requests: tuple[ServiceCapacityRequest, ...], available: float
) -> tuple[dict[EntityId, float], float]:
    allocated = {request.id: 0.0 for request in requests}
    available = max(0.0, available)
    if available <= 1e-12:
        return allocated, 0.0

    ordered = tuple(sorted(requests, key=_request_order_key))
    threshold_requests = tuple(
        request for request in ordered if request.effective_minimum_rate > 1e-12
    )
    total_threshold = sum(request.effective_minimum_rate for request in threshold_requests)
    if total_threshold <= available + 1e-12:
        selected = threshold_requests
    else:
        selected_rows: list[ServiceCapacityRequest] = []
        remaining = available
        for request in threshold_requests:
            threshold = request.effective_minimum_rate
            if threshold <= remaining + 1e-12:
                selected_rows.append(request)
                remaining -= threshold
        selected = tuple(selected_rows)

    selected_ids = {request.id for request in selected}
    for request in selected:
        threshold = request.effective_minimum_rate
        allocated[request.id] = threshold
        available -= threshold

    eligible = tuple(
        request for request in ordered
        if request.effective_minimum_rate <= 1e-12 or request.id in selected_ids
    )
    continuous = tuple(request for request in eligible if not request.atomic)
    remaining_need = {
        request.id: max(0.0, request.requested_rate - allocated[request.id])
        for request in continuous
    }
    total_need = sum(remaining_need.values())
    if available > 1e-12 and total_need > 1e-12:
        take_total = min(available, total_need)
        for request in continuous:
            need = remaining_need[request.id]
            if need > 1e-12:
                allocated[request.id] += take_total * need / total_need
        available -= take_total

    return allocated, max(0.0, available)


def allocate_service_capacity(
    requests: Iterable[ServiceCapacityRequest],
    *,
    nominal_supply: Mapping[tuple[SpatialNodeId, str], float],
    enabled_supply: Mapping[tuple[SpatialNodeId, str], float] | None = None,
    limiting_factors: Mapping[tuple[SpatialNodeId, str], tuple[str, ...]] | None = None,
) -> ServiceCapacityAllocationPlan:
    """Allocate finite service flows without using Domain execution order."""

    rows = tuple(requests)
    ids = [request.id for request in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate service capacity request id")
    enabled = dict(nominal_supply if enabled_supply is None else enabled_supply)
    nominal = dict(nominal_supply)
    for key, amount in nominal.items():
        if amount < -1e-9:
            raise ValueError(f"negative nominal service capacity: {key}")
    for key, amount in enabled.items():
        if amount < -1e-9:
            raise ValueError(f"negative enabled service capacity: {key}")
        if amount > nominal.get(key, 0.0) + 1e-7:
            raise ValueError(f"enabled service capacity exceeds nominal: {key}")

    by_key: dict[tuple[SpatialNodeId, str], list[ServiceCapacityRequest]] = {}
    for request in rows:
        by_key.setdefault((request.operational_node_id, request.service_type), []).append(request)

    amounts: dict[EntityId, float] = {request.id: 0.0 for request in rows}
    for key, grouped in sorted(by_key.items(), key=lambda row: (str(row[0][0]), row[0][1])):
        available = max(0.0, enabled.get(key, 0.0))
        by_priority: dict[int, list[ServiceCapacityRequest]] = {}
        for request in grouped:
            by_priority.setdefault(request.priority, []).append(request)
        for priority in sorted(by_priority, reverse=True):
            band = tuple(by_priority[priority])
            band_allocated, available = _allocate_priority_band(band, available)
            amounts.update(band_allocated)

    ordered = tuple(sorted(rows, key=lambda request: (-request.priority, _request_order_key(request))))
    allocations = tuple(
        ServiceCapacityAllocation(
            request.id,
            request.requested_rate,
            min(request.requested_rate, max(0.0, amounts[request.id])),
            max(0.0, request.requested_rate - amounts[request.id]),
        )
        for request in ordered
    )
    return ServiceCapacityAllocationPlan(
        ordered,
        allocations,
        nominal,
        enabled,
        dict(limiting_factors or {}),
    )
