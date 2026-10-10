"""Explicit, non-authoritative observations of canonical Allocation and Inventory settlement.

No alternative allocator, stock-difference approximation of gross flow, or
permanent domain history. Observers are installed only by an experiment scope.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Iterator

from .shared import DefinitionId, SpatialNodeId
from .simulation import Simulation, TickDecisionProjection


@dataclass(frozen=True)
class InventoryMovement:
    day: int
    direction: str
    node_id: str
    resource_id: str
    quantity_t: float
    operation: str
    staging_owner_id: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in ("inventory_in", "inventory_out", "external_storage_in", "external_storage_out"):
            raise ValueError("unrecognized Inventory settlement direction")
        if not isfinite(self.quantity_t) or self.quantity_t <= 0:
            raise ValueError("Inventory movement must have positive finite quantity")


@dataclass(frozen=True)
class AllocationMetric:
    """Execution allocation is authorized execution, not consumed Resource flow."""
    day: int
    kind: str
    subject_id: str
    context_id: str
    requested: float
    allocated: float
    unmet: float
    unit: str
    provenance: str
    limiting_factors: tuple[str, ...] = ()


@dataclass
class CanonicalDayTrace:
    day: int
    movements: list[InventoryMovement] = field(default_factory=list)
    allocations: list[AllocationMetric] = field(default_factory=list)

    def to_json_data(self) -> dict:
        return {"day": self.day,
                "inventory_movements": [asdict(row) for row in self.movements],
                "allocations": [asdict(row) for row in self.allocations]}

    def reconcile(self, before: dict, after: dict) -> list[dict]:
        """Match measured gross movements to actual ordinary Inventory stock change.

        Staging is an independent owned store and is never counted as ordinary
        Inventory. Nonzero residuals remain explicit rather than being assigned
        to imaginary production or loss.
        """
        keys = set(before) | set(after) | {
            (row.node_id, row.resource_id) for row in self.movements
            if row.direction in ("inventory_in", "inventory_out")
        }
        return [
            {"node_id": node, "resource_id": resource,
             "stock_delta_t": after.get((node, resource), 0.0) - before.get((node, resource), 0.0),
             "settled_net_t": self.inventory_balance(node_id=node, resource_id=resource),
             "unattributed_delta_t": (after.get((node, resource), 0.0) - before.get((node, resource), 0.0)
                                        - self.inventory_balance(node_id=node, resource_id=resource))}
            for node, resource in sorted(keys)
            if abs(after.get((node, resource), 0.0) - before.get((node, resource), 0.0)) > 1e-9
            or abs(self.inventory_balance(node_id=node, resource_id=resource)) > 1e-9
        ]

    def inventory_balance(self, *, node_id: str, resource_id: str) -> float:
        """Change in ordinary Inventory stock, excluding external storage custody."""
        return sum((1 if row.direction == "inventory_in" else -1)
                   * row.quantity_t for row in self.movements
                   if row.node_id == node_id and row.resource_id == resource_id
                   and row.direction in ("inventory_in", "inventory_out"))


def _read_allocation(trace: CanonicalDayTrace, decision: TickDecisionProjection) -> None:
    execution = decision.allocations.execution
    allocated = {row.bundle_id: row for row in execution.allocations}
    for bundle in execution.bundles:
        row = allocated[bundle.id]
        trace.allocations.append(AllocationMetric(
            trace.day, "activity_execution", str(bundle.id),
            str(bundle.operational_node_id) if bundle.operational_node_id is not None else "organization",
            row.requested_execution, row.allocated_execution, row.unmet_execution,
            "executions/day", f"{bundle.owner_kind}:{bundle.owner_id}:{bundle.purpose}",
            tuple(f"{key.kind}:{key.scope_id}:{key.name}" for key in row.limiting_constraints),
        ))
    for row in decision.allocations.resources.rows:
        trace.allocations.append(AllocationMetric(
            trace.day, "resource_request", str(row.resource_id), str(row.operational_node_id),
            row.requested_amount, row.allocated_amount, row.unmet_amount, "t/day",
            f"{row.owner_kind}:{row.owner_id}:{row.purpose}:{row.id}",
        ))
    services = decision.allocations.services
    grants = {row.request_id: row for row in services.allocations}
    for request in services.requests:
        grant = grants[request.id]
        trace.allocations.append(AllocationMetric(
            trace.day, "service_request", request.service_type, str(request.operational_node_id),
            grant.requested_rate, grant.allocated_rate, grant.unmet_rate, "service_units/day",
            f"{request.owner_kind}:{request.owner_id}:{request.purpose}:{request.id}",
        ))
    for key, capacity in sorted(execution.capacity_by_constraint.items()):
        used = execution.used_by_constraint.get(key, 0.0)
        trace.allocations.append(AllocationMetric(
            trace.day, "finite_constraint", key.name, key.scope_id, capacity, used,
            max(0.0, capacity - used), ( "t/day" if key.kind == "resource" else "capacity_units/day" ),
            f"allocation:{key.kind}",
        ))


@contextmanager
def observe_canonical_day(
    sim: Simulation, *,
    operational_node_ids: frozenset[SpatialNodeId] | None = None,
    resource_ids: frozenset[DefinitionId] | None = None,
) -> Iterator[CanonicalDayTrace]:
    """Observe Command settlement plus exactly one canonical day through owner hooks.

    Caller must execute one day through the Application within this scope. A
    command that fails still leaves observers detached; no State is saved.
    """
    if sim._analysis_decision_observer is not None or sim.inventory._settlement_observer is not None:
        raise RuntimeError("nested canonical observation is not supported")
    trace = CanonicalDayTrace(sim.day)

    def inventory_sink(direction, node_id, resource_id, amount, operation, owner):
        if ((operational_node_ids is None or node_id in operational_node_ids)
                and (resource_ids is None or resource_id in resource_ids)):
            trace.movements.append(InventoryMovement(
                sim.day, direction, str(node_id), str(resource_id), amount, operation, owner,
            ))

    def decision_sink(decision):
        _read_allocation(trace, decision)
        if operational_node_ids is not None or resource_ids is not None:
            trace.allocations[:] = [row for row in trace.allocations
                if (operational_node_ids is None or row.context_id == "organization"
                    or row.context_id in {str(node) for node in operational_node_ids})
                and (resource_ids is None or row.kind != "resource_request"
                    or row.subject_id in {str(resource) for resource in resource_ids})]

    sim._analysis_decision_observer = decision_sink
    sim.inventory._settlement_observer = inventory_sink
    try:
        yield trace
    finally:
        sim._analysis_decision_observer = None
        sim.inventory._settlement_observer = None
