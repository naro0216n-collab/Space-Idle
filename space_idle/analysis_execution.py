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
    # Optional facts supplied by the actual settling Domain. Null means the
    # corresponding cause is unknown; Graph edges never fill it in.
    counterparty_id: str | None = None
    activity_id: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in ("inventory_in", "inventory_out", "external_storage_in", "external_storage_out"):
            raise ValueError("unrecognized Inventory settlement direction")
        if not isfinite(self.quantity_t) or self.quantity_t <= 0:
            raise ValueError("Inventory movement must have positive finite quantity")


@dataclass(frozen=True)
class CustodyTransfer:
    """An observed atomic Inventory ↔ owner-staging handoff, not production.

    Only the explicitly paired Owner settlement is attributable. Other gross
    movements keep their unknown source or destination.
    """
    day: int
    node_id: str
    resource_id: str
    quantity_t: float
    source_owner: str
    destination_owner: str
    operation: str


@dataclass(frozen=True)
class ActivityFlow:
    """One settled physical Resource movement with proven activity endpoints."""
    day: int
    resource_id: str
    quantity_t: float
    source_owner: str
    destination_owner: str
    activity_id: str
    operation: str


@dataclass(frozen=True)
class AllocationMetric:
    """Execution allocation is authorized execution, not consumed Resource flow."""
    day: int
    kind: str
    subject_id: str
    context_id: str
    requested: float | None
    allocated: float | None
    unmet: float | None
    unit: str
    provenance: str
    limiting_factors: tuple[str, ...] = ()
    # A finite constraint's unused headroom is not an unmet request. Keeping
    # distinct typed fields prevents false bottleneck readings in consumers.
    capacity: float | None = None
    used: float | None = None
    remaining: float | None = None


@dataclass
class CanonicalDayTrace:
    day: int
    movements: list[InventoryMovement] = field(default_factory=list)
    allocations: list[AllocationMetric] = field(default_factory=list)

    def to_json_data(self) -> dict:
        return {"day": self.day,
                "inventory_movements": [asdict(row) for row in self.movements],
                "custody_transfers": [asdict(row) for row in self.custody_transfers()],
                "activity_flows": [asdict(row) for row in self.activity_flows()],
                "unattributed_movements": [asdict(row) for row in self.unattributed_movements()],
                "allocations": [asdict(row) for row in self.allocations]}

    def activity_flows(self) -> tuple[ActivityFlow, ...]:
        """Project proven Owner handoffs, without inventing or double-counting Flow.

        Inventory↔staging reclassifications have two paired ledger movements
        and belong only to custody_transfers(). A later release of staged
        material to a known Activity is a separate physical settlement from
        the staging Owner, never a second consumption of Inventory stock.
        """
        rows = []
        for movement in self.movements:
            if movement.counterparty_id is None or movement.activity_id is None:
                continue
            inventory_owner = f"inventory:{movement.node_id}"
            if movement.direction == "inventory_in":
                source, target = movement.counterparty_id, inventory_owner
            elif movement.direction == "inventory_out":
                source, target = inventory_owner, movement.counterparty_id
            elif movement.direction == "external_storage_out" and movement.staging_owner_id is not None:
                source, target = f"staging:{movement.staging_owner_id}", movement.counterparty_id
            else:
                continue
            rows.append(ActivityFlow(movement.day, movement.resource_id, movement.quantity_t,
                                     source, target, movement.activity_id, movement.operation))
        return tuple(rows)

    def _paired_custody(self) -> tuple[tuple[int, int, CustodyTransfer], ...]:
        """Recover actual atomic handoffs and the two ledger rows they own.

        No other Inventory movement is paired on mere equal quantity or time.
        The observer sees owner-staging mutations synchronously and in order.
        """
        pairs = []
        for index, (first, second) in enumerate(zip(self.movements, self.movements[1:])):
            same = (first.day == second.day and first.node_id == second.node_id
                    and first.resource_id == second.resource_id
                    and abs(first.quantity_t - second.quantity_t) <= 1e-9
                    and first.staging_owner_id is not None
                    and first.staging_owner_id == second.staging_owner_id)
            if not same:
                continue
            if (first.direction == "inventory_out" and second.direction == "external_storage_in"
                    and first.operation == second.operation
                    and first.operation in ("inventory.stage_allocated", "inventory.stage_reserved")):
                source = f"inventory:{first.node_id}"
                destination = f"staging:{first.staging_owner_id}"
                operation = first.operation
            elif (first.direction == "external_storage_out" and second.direction == "inventory_in"
                  and first.operation == "inventory.release_storage_occupancy"
                  and second.operation == "inventory.unstage_to_stock"):
                source = f"staging:{first.staging_owner_id}"
                destination = f"inventory:{first.node_id}"
                operation = second.operation
            else:
                continue
            pairs.append((index, index + 1, CustodyTransfer(
                first.day, first.node_id, first.resource_id,
                first.quantity_t, source, destination, operation,
            )))
        return tuple(pairs)

    def custody_transfers(self) -> tuple[CustodyTransfer, ...]:
        """Paired Inventory/staging custody handoffs, never production."""
        return tuple(row for _, _, row in self._paired_custody())

    def unattributed_movements(self) -> tuple[InventoryMovement, ...]:
        """Owner stock movements without known causal endpoints, excluding custody.

        An unmatched staging release is not a change in Inventory Stock, but it
        still moves physical Resource out of an Owner's custody. Keep it
        visible as unknown rather than silently treating it as consumption.
        Paired Inventory↔staging reclassifications are reported separately.
        """
        custody_rows = {index for left, right, _ in self._paired_custody()
                        for index in (left, right)}
        return tuple(row for index, row in enumerate(self.movements)
                     if index not in custody_rows
                     and (row.counterparty_id is None or row.activity_id is None))

    def reconcile(self, before: dict, after: dict) -> list[dict]:
        """Reconcile actual Inventory Stock against one classified settlement ledger.

        This makes physical custody, observed Activity and truly unknown causes
        separately inspectable. Each ordinary Inventory row has exactly one
        class; staging's second ledger entry is never double-counted as Stock.
        """
        from collections import defaultdict

        net = defaultdict(float)
        activity = defaultdict(float)
        custody = defaultdict(float)
        unknown = defaultdict(float)
        custody_rows = {index for left, right, _ in self._paired_custody()
                        for index in (left, right)}
        for index, row in enumerate(self.movements):
            if row.direction not in ("inventory_in", "inventory_out"):
                continue
            key = row.node_id, row.resource_id
            signed = row.quantity_t if row.direction == "inventory_in" else -row.quantity_t
            net[key] += signed
            if index in custody_rows:
                custody[key] += signed
            elif row.counterparty_id is not None and row.activity_id is not None:
                activity[key] += signed
            else:
                unknown[key] += signed
        keys = set(before) | set(after) | set(net)
        rows = []
        for node, resource in sorted(keys):
            key = node, resource
            delta = after.get(key, 0.0) - before.get(key, 0.0)
            settled = net[key]
            if abs(delta) <= 1e-9 and abs(settled) <= 1e-9:
                continue
            rows.append({
                "node_id": node, "resource_id": resource,
                "stock_delta_t": delta, "settled_net_t": settled,
                "attributed_activity_delta_t": activity[key],
                "custody_delta_t": custody[key],
                "unknown_cause_delta_t": unknown[key],
                "unattributed_delta_t": delta - settled,
            })
        return rows

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
        # Resource and stock-admission constraints are measured in physical
        # tonnes; other pool capacities retain their native constraint units.
        # In particular, housing stock capacity is not a daily flow rate.
        unit = "t" if key.kind in ("resource", "admission") else "constraint_units"
        trace.allocations.append(AllocationMetric(
            trace.day, "finite_constraint", key.name, key.scope_id,
            None, None, None, unit, f"allocation:{key.kind}",
            capacity=capacity, used=used, remaining=max(0.0, capacity - used),
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

    def inventory_sink(direction, node_id, resource_id, amount, operation, owner, counterparty, activity):
        if ((operational_node_ids is None or node_id in operational_node_ids)
                and (resource_ids is None or resource_id in resource_ids)):
            trace.movements.append(InventoryMovement(
                sim.day, direction, str(node_id), str(resource_id), amount, operation, owner,
                counterparty, activity,
            ))

    # The canonical allocator names physical scopes as ``node:<id>`` while
    # Activity and request projections carry bare Operational Node IDs.
    # Both must participate in the same selective observation contract.
    node_ids = None if operational_node_ids is None else {str(node) for node in operational_node_ids}
    resource_keys = None if resource_ids is None else {str(resource) for resource in resource_ids}

    def in_scope(row: AllocationMetric) -> bool:
        if node_ids is not None:
            context = row.context_id
            if context != "organization" and context not in node_ids and not (
                context.startswith("node:") and context[5:] in node_ids
            ):
                # Owner-local pools are not Operational Node capacity and must
                # not be attributed to a selected Node just by asset location.
                return False
        if resource_keys is not None:
            if row.kind == "resource_request" and row.subject_id not in resource_keys:
                return False
            if (row.kind == "finite_constraint" and row.provenance == "allocation:resource"
                    and row.subject_id not in resource_keys):
                return False
        return True

    def decision_sink(decision):
        _read_allocation(trace, decision)
        if node_ids is not None or resource_keys is not None:
            trace.allocations[:] = [row for row in trace.allocations if in_scope(row)]

    sim._analysis_decision_observer = decision_sink
    sim.inventory._settlement_observer = inventory_sink
    try:
        yield trace
    finally:
        sim._analysis_decision_observer = None
        sim.inventory._settlement_observer = None
