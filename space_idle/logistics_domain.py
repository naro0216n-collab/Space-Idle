from __future__ import annotations

from typing import Any

from .domain import (
    DomainExtension, StateCodec, decode_float, decode_int, decode_list, decode_str,
    require_fields,
)
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


def _restore_leg(value: Any, field: str = "cargo leg") -> CargoServiceLeg:
    row = require_fields(
        value,
        {
            "service_identity", "source_id", "destination_id", "latency_days",
            "cycle_days", "allocation_id", "direction",
        },
        field,
    )
    return CargoServiceLeg(
        service_identity=decode_str(row["service_identity"], f"{field} service_identity"),
        source_id=SpatialNodeId(decode_str(row["source_id"], f"{field} source_id")),
        destination_id=SpatialNodeId(
            decode_str(row["destination_id"], f"{field} destination_id")
        ),
        latency_days=decode_int(row["latency_days"], f"{field} latency_days"),
        cycle_days=decode_float(row["cycle_days"], f"{field} cycle_days"),
        allocation_id=EntityId(decode_str(row["allocation_id"], f"{field} allocation_id")),
        direction=decode_str(row["direction"], f"{field} direction"),
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
    lg._cargo_flow_counter = decode_int(data["cargo_flow_counter"], "cargo_flow_counter")
    lg._arrival_waiting_counter = decode_int(data["arrival_waiting_counter"], "arrival_waiting_counter")

    flow_fields = {
        "id", "resource_id", "amount_t", "source_id", "final_destination_id",
        "requirement_id", "owner_kind", "owner_id", "priority", "leg",
        "remaining_legs", "dispatch_start_day", "dispatch_end_day",
        "dispatch_rate_t_per_day",
    }
    lg.cargo_flows = {}
    for index, raw in enumerate(decode_list(data["cargo_flows"], "cargo_flows")):
        row = require_fields(raw, flow_fields, f"cargo flow[{index}]")
        flow_id = EntityId(decode_str(row["id"], "cargo flow id"))
        if flow_id in lg.cargo_flows:
            raise ValueError(f"duplicate cargo flow: {flow_id}")
        lg.cargo_flows[flow_id] = CargoFlowSegment(
            id=flow_id,
            resource_id=DefinitionId(decode_str(row["resource_id"], "cargo resource_id")),
            amount_t=decode_float(row["amount_t"], "cargo amount_t"),
            source_id=SpatialNodeId(decode_str(row["source_id"], "cargo source_id")),
            final_destination_id=SpatialNodeId(
                decode_str(row["final_destination_id"], "cargo final_destination_id")
            ),
            requirement_id=(
                None if row["requirement_id"] is None
                else EntityId(decode_str(row["requirement_id"], "cargo requirement_id"))
            ),
            owner_kind=decode_str(row["owner_kind"], "cargo owner_kind"),
            owner_id=EntityId(decode_str(row["owner_id"], "cargo owner_id")),
            priority=decode_int(row["priority"], "logistics priority"),
            leg=_restore_leg(row["leg"], f"cargo flow[{index}] leg"),
            remaining_legs=tuple(
                _restore_leg(leg, f"cargo flow[{index}] remaining_leg[{leg_index}]")
                for leg_index, leg in enumerate(
                    decode_list(row["remaining_legs"], "cargo remaining_legs")
                )
            ),
            dispatch_start_day=decode_int(row["dispatch_start_day"], "cargo dispatch_start_day"),
            dispatch_end_day=decode_int(row["dispatch_end_day"], "cargo dispatch_end_day"),
            dispatch_rate_t_per_day=decode_float(
                row["dispatch_rate_t_per_day"], "cargo dispatch_rate_t_per_day"
            ),
        )

    waiting_fields = {
        "id", "resource_id", "amount_t", "node_id", "final_destination_id",
        "requirement_id", "owner_kind", "owner_id", "priority", "arrival_leg",
        "remaining_legs", "arrived_day",
    }
    lg.arrival_waiting = {}
    for index, raw in enumerate(decode_list(data["arrival_waiting"], "arrival_waiting")):
        row = require_fields(raw, waiting_fields, f"arrival waiting[{index}]")
        waiting_id = EntityId(decode_str(row["id"], "arrival waiting id"))
        if waiting_id in lg.arrival_waiting:
            raise ValueError(f"duplicate arrival waiting: {waiting_id}")
        lg.arrival_waiting[waiting_id] = CargoArrivalWaiting(
            id=waiting_id,
            resource_id=DefinitionId(decode_str(row["resource_id"], "cargo resource_id")),
            amount_t=decode_float(row["amount_t"], "cargo amount_t"),
            node_id=SpatialNodeId(decode_str(row["node_id"], "cargo node_id")),
            final_destination_id=SpatialNodeId(
                decode_str(row["final_destination_id"], "cargo final_destination_id")
            ),
            requirement_id=(
                None if row["requirement_id"] is None
                else EntityId(decode_str(row["requirement_id"], "cargo requirement_id"))
            ),
            owner_kind=decode_str(row["owner_kind"], "cargo owner_kind"),
            owner_id=EntityId(decode_str(row["owner_id"], "cargo owner_id")),
            priority=decode_int(row["priority"], "logistics priority"),
            arrival_leg=_restore_leg(row["arrival_leg"], f"arrival waiting[{index}] leg"),
            remaining_legs=tuple(
                _restore_leg(leg, f"arrival waiting[{index}] remaining_leg[{leg_index}]")
                for leg_index, leg in enumerate(
                    decode_list(row["remaining_legs"], "arrival waiting remaining_legs")
                )
            ),
            arrived_day=decode_int(row["arrived_day"], "cargo arrived_day"),
        )

    target_fields = {"id", "destination_id", "resource_id", "target_quantity_t", "priority"}
    lg.target_stocks = {}
    for index, raw in enumerate(decode_list(data["target_stocks"], "target_stocks")):
        row = require_fields(raw, target_fields, f"target stock[{index}]")
        policy_id = EntityId(decode_str(row["id"], "target stock id"))
        if policy_id in lg.target_stocks:
            raise ValueError(f"duplicate target stock: {policy_id}")
        lg.target_stocks[policy_id] = TargetStockPolicy(
            policy_id,
            SpatialNodeId(decode_str(row["destination_id"], "target stock destination_id")),
            DefinitionId(decode_str(row["resource_id"], "target stock resource_id")),
            decode_float(row["target_quantity_t"], "target stock quantity"),
            decode_int(row["priority"], "logistics priority"),
        )

    lg.routing_constraints = {}
    routing_fields = {
        "destination_id", "owner_kind", "owner_id", "resource_id",
        "source_node_id", "required_via_node_ids",
        "required_transport_allocation_ids",
    }
    for index, raw in enumerate(
        decode_list(data["routing_constraints"], "routing_constraints")
    ):
        row = require_fields(raw, routing_fields, f"routing constraint[{index}]")
        scope = SupplyRoutingConstraintScope(
            destination_id=SpatialNodeId(
                decode_str(row["destination_id"], "routing destination_id")
            ),
            owner_kind=decode_str(row["owner_kind"], "routing owner_kind"),
            owner_id=(
                None if row["owner_id"] is None
                else EntityId(decode_str(row["owner_id"], "routing owner_id"))
            ),
            resource_id=(
                None if row["resource_id"] is None
                else DefinitionId(decode_str(row["resource_id"], "routing resource_id"))
            ),
        )
        if scope in lg.routing_constraints:
            raise ValueError(f"duplicate routing constraint: {scope}")
        lg.routing_constraints[scope] = SupplyRoutingConstraintState(
            scope=scope,
            source_node_id=(
                None if row["source_node_id"] is None
                else SpatialNodeId(decode_str(row["source_node_id"], "routing source_node_id"))
            ),
            required_via_node_ids=tuple(
                SpatialNodeId(decode_str(value, "routing required_via_node_id"))
                for value in decode_list(row["required_via_node_ids"], "routing required_via_node_ids")
            ),
            required_transport_allocation_ids=tuple(
                EntityId(decode_str(value, "routing required_transport_allocation_id"))
                for value in decode_list(
                    row["required_transport_allocation_ids"],
                    "routing required_transport_allocation_ids",
                )
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
