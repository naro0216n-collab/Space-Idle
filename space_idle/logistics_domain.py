from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .logistics_models import (
    CargoArrivalWaiting,
    CargoFlowSegment,
    CargoServiceLeg,
)
from .shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
from .supply import (
    LogisticsPolicyAssignmentState, LogisticsPolicyState, PathSelectionMode,
    SourceSelectionMode, TargetStockPolicy,
)
from .transport.models import PathPolicy
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
        "logistics_policies": [
            {
                "id": str(row.id),
                "source_mode": row.source_mode.value,
                "allowed_source_ids": None if row.allowed_source_ids is None else [str(value) for value in row.allowed_source_ids],
                "preferred_source_id": None if row.preferred_source_id is None else str(row.preferred_source_id),
                "path_mode": row.path_mode.value,
                "path_preference": row.path_preference.value,
                "explicit_path": None if row.explicit_path is None else [str(value) for value in row.explicit_path],
                "allowed_handoff_ids": None if row.allowed_handoff_ids is None else [str(value) for value in row.allowed_handoff_ids],
                "allowed_service_ids": None if row.allowed_service_ids is None else list(row.allowed_service_ids),
            }
            for row in lg.logistics_policy_rows()
        ],
        "policy_assignments": [
            {
                "owner_kind": row.owner_kind,
                "owner_id": str(row.owner_id),
                "policy_id": str(row.policy_id),
            }
            for row in lg.logistics_policy_assignments()
        ],
        "global_policy_id": None if lg.global_policy_id is None else str(lg.global_policy_id),
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._cargo_flow_counter = int(data.get("cargo_flow_counter", 0))
    lg._arrival_waiting_counter = int(data.get("arrival_waiting_counter", 0))
    lg.cargo_flows = {
        EntityId(row["id"]): CargoFlowSegment(
            id=EntityId(row["id"]),
            resource_id=DefinitionId(row["resource_id"]),
            amount_t=float(row["amount_t"]),
            source_id=SpatialNodeId(row["source_id"]),
            final_destination_id=SpatialNodeId(row["final_destination_id"]),
            requirement_id=None if row.get("requirement_id") is None else EntityId(row["requirement_id"]),
            owner_kind=row["owner_kind"],
            owner_id=EntityId(row["owner_id"]),
            priority=int(row["priority"]),
            leg=_restore_leg(row["leg"]),
            remaining_legs=tuple(_restore_leg(leg) for leg in row.get("remaining_legs", [])),
            dispatch_start_day=int(row["dispatch_start_day"]),
            dispatch_end_day=int(row["dispatch_end_day"]),
            dispatch_rate_t_per_day=float(row["dispatch_rate_t_per_day"]),
        )
        for row in data.get("cargo_flows", [])
    }
    lg.arrival_waiting = {
        EntityId(row["id"]): CargoArrivalWaiting(
            id=EntityId(row["id"]),
            resource_id=DefinitionId(row["resource_id"]),
            amount_t=float(row["amount_t"]),
            node_id=SpatialNodeId(row["node_id"]),
            final_destination_id=SpatialNodeId(row["final_destination_id"]),
            requirement_id=None if row.get("requirement_id") is None else EntityId(row["requirement_id"]),
            owner_kind=row["owner_kind"],
            owner_id=EntityId(row["owner_id"]),
            priority=int(row["priority"]),
            arrival_leg=_restore_leg(row["arrival_leg"]),
            remaining_legs=tuple(_restore_leg(leg) for leg in row.get("remaining_legs", [])),
            arrived_day=int(row["arrived_day"]),
        )
        for row in data.get("arrival_waiting", [])
    }
    lg.target_stocks = {
        EntityId(row["id"]): TargetStockPolicy(
            EntityId(row["id"]),
            SpatialNodeId(row["destination_id"]),
            DefinitionId(row["resource_id"]),
            float(row["target_quantity_t"]),
            int(row["priority"]),
        )
        for row in data.get("target_stocks", [])
    }
    lg.logistics_policies = {
        EntityId(row["id"]): LogisticsPolicyState(
            id=EntityId(row["id"]),
            source_mode=SourceSelectionMode(row["source_mode"]),
            allowed_source_ids=None if row.get("allowed_source_ids") is None else tuple(SpatialNodeId(value) for value in row["allowed_source_ids"]),
            preferred_source_id=None if row.get("preferred_source_id") is None else SpatialNodeId(row["preferred_source_id"]),
            path_mode=PathSelectionMode(row["path_mode"]),
            explicit_path=None if row.get("explicit_path") is None else tuple(MovementPlanId(value) for value in row["explicit_path"]),
            allowed_handoff_ids=None if row.get("allowed_handoff_ids") is None else tuple(SpatialNodeId(value) for value in row["allowed_handoff_ids"]),
            allowed_service_ids=None if row.get("allowed_service_ids") is None else tuple(str(value) for value in row["allowed_service_ids"]),
            path_preference=PathPolicy(row.get("path_preference", "balanced")),
        )
        for row in data.get("logistics_policies", [])
    }
    lg.policy_assignments = {
        (row["owner_kind"], EntityId(row["owner_id"])): LogisticsPolicyAssignmentState(
            row["owner_kind"], EntityId(row["owner_id"]), EntityId(row["policy_id"])
        )
        for row in data.get("policy_assignments", [])
    }
    lg.global_policy_id = (
        None if data.get("global_policy_id") is None else EntityId(data["global_policy_id"])
    )



def _validate_leg(sim: Any, owner_label: str, leg: CargoServiceLeg) -> None:
    _require(
        sim.graph.has_operational_node(leg.source_id)
        and sim.graph.has_operational_node(leg.destination_id),
        f"{owner_label} references unknown transport endpoint",
    )


def validate_logistics_runtime(sim: Any) -> None:
    lg = sim.logistics
    tr = sim.transport
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

    for policy_id, policy in lg.logistics_policies.items():
        _require(policy_id == policy.id, f"logistics policy key mismatch: {policy_id}")
        for source_id in policy.allowed_source_ids or ():
            _require(sim.graph.has_operational_node(source_id), f"logistics policy references unknown source: {policy_id}")
        if policy.preferred_source_id is not None:
            _require(sim.graph.has_operational_node(policy.preferred_source_id), f"logistics policy references unknown preferred source: {policy_id}")
        for handoff_id in policy.allowed_handoff_ids or ():
            _require(sim.graph.has_operational_node(handoff_id), f"logistics policy references unknown handoff: {policy_id}")
        if policy.path_mode is PathSelectionMode.PINNED and policy.explicit_path:
            first = tr.require_movement_plan(policy.explicit_path[0])
            last = tr.require_movement_plan(policy.explicit_path[-1])
            tr.validate_movement_path_structure(
                first.origin_id, last.destination_id, policy.explicit_path
            )

    if lg.global_policy_id is not None:
        _require(lg.global_policy_id in lg.logistics_policies, "global logistics policy reference is invalid")

    for key, assignment in lg.policy_assignments.items():
        _require(key == (assignment.owner_kind, assignment.owner_id), f"logistics policy assignment key mismatch: {key}")
        _require(assignment.policy_id in lg.logistics_policies, f"logistics policy assignment references unknown policy: {key}")
        _require(lg.policy_owner_exists(assignment.owner_kind, assignment.owner_id), f"orphan logistics policy assignment: {assignment.owner_kind}:{assignment.owner_id}")



LOGISTICS_STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension(
    "logistics",
    state_codec=LOGISTICS_STATE_CODEC,
    runtime_validator=validate_logistics_runtime,
    allocation_pool_provider=lambda sim: sim.logistics,
)
