from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .logistics_models import (
    CargoArrivalWaiting,
    CargoFlowSegment,
    CargoServiceLeg,
)
from .shared import DefinitionId, EntityId, SpatialNodeId
from .supply import (
    SupplyRoutingConstraintScope, SupplyRoutingConstraintState, TargetStockPolicy,
)
from .validation_support import require as _require


def _capture_leg(leg: CargoServiceLeg) -> dict[str, Any]:
    return {
        "service_identity": leg.service_identity,
        "source_id": str(leg.source_id),
        "destination_id": str(leg.destination_id),
        "latency_days": leg.latency_days,
        "cycle_days": leg.cycle_days,
        "allocation_id": str(leg.allocation_id),
        "direction": leg.direction,
    }


def _restore_leg(row: dict[str, Any]) -> CargoServiceLeg:
    return CargoServiceLeg(
        service_identity=row["service_identity"],
        source_id=SpatialNodeId(row["source_id"]),
        destination_id=SpatialNodeId(row["destination_id"]),
        latency_days=int(row["latency_days"]),
        cycle_days=float(row["cycle_days"]),
        allocation_id=EntityId(row["allocation_id"]),
        direction=row["direction"],
    )


def capture_logistics(sim: Any) -> dict[str, Any]:
    lg = sim.logistics
    return {
        "cargo_flow_counter": lg._cargo_flow_counter,
        "arrival_waiting_counter": lg._arrival_waiting_counter,
        "cargo_flows": [
            {
                "id": str(row.id),
                "resource_id": str(row.resource_id),
                "amount_t": row.amount_t,
                "source_id": str(row.source_id),
                "final_destination_id": str(row.final_destination_id),
                "requirement_id": None if row.requirement_id is None else str(row.requirement_id),
                "owner_kind": row.owner_kind,
                "owner_id": str(row.owner_id),
                "priority": int(row.priority),
                "leg": _capture_leg(row.leg),
                "remaining_legs": [_capture_leg(leg) for leg in row.remaining_legs],
                "dispatch_start_day": row.dispatch_start_day,
                "dispatch_end_day": row.dispatch_end_day,
                "dispatch_rate_t_per_day": row.dispatch_rate_t_per_day,
            }
            for row in sorted(lg.cargo_flows.values(), key=lambda row: str(row.id))
        ],
        "arrival_waiting": [
            {
                "id": str(row.id),
                "resource_id": str(row.resource_id),
                "amount_t": row.amount_t,
                "node_id": str(row.node_id),
                "final_destination_id": str(row.final_destination_id),
                "requirement_id": None if row.requirement_id is None else str(row.requirement_id),
                "owner_kind": row.owner_kind,
                "owner_id": str(row.owner_id),
                "priority": int(row.priority),
                "arrival_leg": _capture_leg(row.arrival_leg),
                "remaining_legs": [_capture_leg(leg) for leg in row.remaining_legs],
                "arrived_day": row.arrived_day,
            }
            for row in sorted(lg.arrival_waiting.values(), key=lambda row: str(row.id))
        ],
        "target_stocks": [
            {
                "id": str(row.id),
                "destination_id": str(row.destination_id),
                "resource_id": str(row.resource_id),
                "target_quantity_t": row.target_quantity_t,
                "priority": int(row.priority),
            }
            for row in lg.target_stock_policies()
        ],
        "routing_constraints": [
            {
                "destination_id": str(row.scope.destination_id),
                "owner_kind": row.scope.owner_kind,
                "owner_id": None if row.scope.owner_id is None else str(row.scope.owner_id),
                "resource_id": None if row.scope.resource_id is None else str(row.scope.resource_id),
                "source_node_id": None if row.source_node_id is None else str(row.source_node_id),
                "required_via_node_ids": [str(value) for value in row.required_via_node_ids],
                "required_transport_allocation_ids": [
                    str(value) for value in row.required_transport_allocation_ids
                ],
            }
            for row in lg.routing_constraint_rows()
        ],
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._cargo_flow_counter = int(data["cargo_flow_counter"])
    lg._arrival_waiting_counter = int(data["arrival_waiting_counter"])
    lg.cargo_flows = {
        EntityId(row["id"]): CargoFlowSegment(
            id=EntityId(row["id"]),
            resource_id=DefinitionId(row["resource_id"]),
            amount_t=float(row["amount_t"]),
            source_id=SpatialNodeId(row["source_id"]),
            final_destination_id=SpatialNodeId(row["final_destination_id"]),
            requirement_id=None if row["requirement_id"] is None else EntityId(row["requirement_id"]),
            owner_kind=row["owner_kind"],
            owner_id=EntityId(row["owner_id"]),
            priority=int(row["priority"]),
            leg=_restore_leg(row["leg"]),
            remaining_legs=tuple(_restore_leg(leg) for leg in row["remaining_legs"]),
            dispatch_start_day=int(row["dispatch_start_day"]),
            dispatch_end_day=int(row["dispatch_end_day"]),
            dispatch_rate_t_per_day=float(row["dispatch_rate_t_per_day"]),
        )
        for row in data["cargo_flows"]
    }
    lg.arrival_waiting = {
        EntityId(row["id"]): CargoArrivalWaiting(
            id=EntityId(row["id"]),
            resource_id=DefinitionId(row["resource_id"]),
            amount_t=float(row["amount_t"]),
            node_id=SpatialNodeId(row["node_id"]),
            final_destination_id=SpatialNodeId(row["final_destination_id"]),
            requirement_id=None if row["requirement_id"] is None else EntityId(row["requirement_id"]),
            owner_kind=row["owner_kind"],
            owner_id=EntityId(row["owner_id"]),
            priority=int(row["priority"]),
            arrival_leg=_restore_leg(row["arrival_leg"]),
            remaining_legs=tuple(_restore_leg(leg) for leg in row["remaining_legs"]),
            arrived_day=int(row["arrived_day"]),
        )
        for row in data["arrival_waiting"]
    }
    lg.target_stocks = {
        EntityId(row["id"]): TargetStockPolicy(
            EntityId(row["id"]),
            SpatialNodeId(row["destination_id"]),
            DefinitionId(row["resource_id"]),
            float(row["target_quantity_t"]),
            int(row["priority"]),
        )
        for row in data["target_stocks"]
    }
    lg.routing_constraints = {}
    routing_fields = {
        "destination_id", "owner_kind", "owner_id", "resource_id",
        "source_node_id", "required_via_node_ids",
        "required_transport_allocation_ids",
    }
    for row in data["routing_constraints"]:
        if set(row) != routing_fields:
            raise ValueError("routing constraint has invalid fields")
        scope = SupplyRoutingConstraintScope(
            destination_id=SpatialNodeId(row["destination_id"]),
            owner_kind=row["owner_kind"],
            owner_id=None if row["owner_id"] is None else EntityId(row["owner_id"]),
            resource_id=(
                None if row["resource_id"] is None else DefinitionId(row["resource_id"])
            ),
        )
        lg.routing_constraints[scope] = SupplyRoutingConstraintState(
            scope=scope,
            source_node_id=(
                None
                if row["source_node_id"] is None
                else SpatialNodeId(row["source_node_id"])
            ),
            required_via_node_ids=tuple(
                SpatialNodeId(value) for value in row["required_via_node_ids"]
            ),
            required_transport_allocation_ids=tuple(
                EntityId(value)
                for value in row["required_transport_allocation_ids"]
            ),
        )



def _validate_leg(sim: Any, owner_label: str, leg: CargoServiceLeg) -> None:
    _require(
        sim.graph.has_operational_node(leg.source_id)
        and sim.graph.has_operational_node(leg.destination_id),
        f"{owner_label} references unknown transport endpoint",
    )


def validate_logistics_runtime(sim: Any) -> None:
    lg = sim.logistics
    for flow_id, flow in lg.cargo_flows.items():
        _require(flow_id == flow.id, f"cargo flow key mismatch: {flow_id}")
        _require(flow.amount_t > 0, f"cargo flow has non-positive amount: {flow_id}")
        _require(1 <= int(flow.priority) <= 5, f"cargo flow priority must be 1..5: {flow_id}")
        _require(
            flow.dispatch_end_day > flow.dispatch_start_day,
            f"cargo flow has non-positive dispatch interval: {flow_id}",
        )
        expected = flow.dispatch_rate_t_per_day * (
            flow.dispatch_end_day - flow.dispatch_start_day
        )
        _require(
            abs(flow.amount_t - expected) <= max(1e-9, expected * 1e-8),
            f"cargo flow amount/rate mismatch: {flow_id}",
        )
        for leg in (flow.leg,) + flow.remaining_legs:
            _validate_leg(sim, f"cargo flow {flow_id}", leg)

    for waiting_id, waiting in lg.arrival_waiting.items():
        _require(waiting_id == waiting.id, f"arrival waiting key mismatch: {waiting_id}")
        _require(waiting.amount_t > 0, f"arrival waiting has non-positive amount: {waiting_id}")
        _require(1 <= int(waiting.priority) <= 5, f"arrival waiting priority must be 1..5: {waiting_id}")
        _require(
            sim.graph.has_operational_node(waiting.node_id)
            and sim.graph.has_operational_node(waiting.final_destination_id),
            f"arrival waiting references unknown node: {waiting_id}",
        )
        _validate_leg(sim, f"arrival waiting {waiting_id}", waiting.arrival_leg)
        for leg in waiting.remaining_legs:
            _validate_leg(sim, f"arrival waiting {waiting_id}", leg)


    for policy_id, policy in lg.target_stocks.items():
        _require(policy_id == policy.id, f"target stock key mismatch: {policy_id}")
        _require(sim.graph.has_operational_node(policy.destination_id), f"target stock references unknown destination: {policy_id}")
        _require(policy.target_quantity_t >= 0, f"target stock has negative quantity: {policy_id}")
        _require(1 <= int(policy.priority) <= 5, f"target stock priority must be 1..5: {policy_id}")

    seen_constraints: list[SupplyRoutingConstraintState] = []
    for scope, constraint in lg.routing_constraints.items():
        _require(scope == constraint.scope, f"routing constraint key mismatch: {scope}")
        _require(
            sim.graph.has_operational_node(scope.destination_id),
            f"routing constraint references unknown destination: {scope}",
        )
        if scope.resource_id is not None:
            _require(
                scope.resource_id in sim.inventory.resource_definitions,
                f"routing constraint references unknown resource: {scope}",
            )
        if scope.owner_kind is not None:
            _require(
                lg.supply_owner_exists(scope.owner_kind, scope.owner_id),
                f"orphan routing constraint: {scope.owner_kind}:{scope.owner_id}",
            )
        if constraint.source_node_id is not None:
            _require(
                sim.graph.has_operational_node(constraint.source_node_id),
                f"routing constraint references unknown source: {scope}",
            )
        for node_id in constraint.required_via_node_ids:
            _require(
                sim.graph.has_operational_node(node_id),
                f"routing constraint references unknown via node: {scope}",
            )
            _require(
                node_id != scope.destination_id,
                f"routing constraint destination cannot also be a via node: {scope}",
            )
        for allocation_id in constraint.required_transport_allocation_ids:
            _require(
                sim.transport.transport_allocation_snapshot(allocation_id) is not None,
                f"routing constraint references unknown transport allocation: {scope}",
            )
        for prior in seen_constraints:
            if not lg._scopes_overlap(prior.scope, scope):
                continue
            if (
                prior.source_node_id is not None
                and constraint.source_node_id is not None
                and prior.source_node_id != constraint.source_node_id
            ):
                _require(False, "overlapping routing constraints require conflicting source nodes")
        seen_constraints.append(constraint)



LOGISTICS_STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension(
    "logistics",
    state_codec=LOGISTICS_STATE_CODEC,
    runtime_validator=validate_logistics_runtime,
    allocation_pool_provider=lambda sim: sim.logistics,
)
