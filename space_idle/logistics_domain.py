from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .transport.models import CargoFlowBatch, CargoFlowStatus, LogisticsLane, PathPolicy
from .validation_support import require as _require

def capture_logistics(sim: Any) -> dict[str, Any]:
    lg = sim.logistics
    return {
        "lane_counter": lg._lane_counter,
        "cargo_flow_counter": lg._cargo_flow_counter,
        "cargo_flows": [
            {
                "id": str(row.id), "resource_id": str(row.resource_id), "amount_t": row.amount_t,
                "source_id": str(row.source_id), "destination_id": str(row.destination_id),
                "lane_id": None if row.lane_id is None else str(row.lane_id),
                "demand_id": None if row.demand_id is None else str(row.demand_id),
                "owner_kind": row.owner_kind, "owner_id": str(row.owner_id), "priority": row.priority,
                "service_ids": list(row.service_ids),
                "service_destinations": [str(value) for value in row.service_destinations],
                "departure_day": row.departure_day, "ready_day": row.ready_day, "status": row.status.value,
            }
            for row in sorted(lg.cargo_flows.values(), key=lambda row: str(row.id))
        ],
        "lanes": [
            {
                "id": str(lane.id), "source_id": str(lane.source_id), "destination_id": str(lane.destination_id),
                "requested_capacity_t_per_day": lane.requested_capacity_t_per_day, "priority": lane.priority,
                "path": None if lane.path is None else [str(route_id) for route_id in lane.path],
                "path_policy": lane.path_policy.value, "paused": lane.paused,
            }
            for lane in sorted(lg.lanes.values(), key=lambda row: str(row.id))
        ],
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._lane_counter = int(data.get("lane_counter", 0))
    lg._cargo_flow_counter = int(data.get("cargo_flow_counter", 0))
    lg.cargo_flows = {
        EntityId(row["id"]): CargoFlowBatch(
            EntityId(row["id"]), DefinitionId(row["resource_id"]), float(row["amount_t"]),
            SpatialNodeId(row["source_id"]), SpatialNodeId(row["destination_id"]),
            None if row.get("lane_id") is None else EntityId(row["lane_id"]),
            None if row.get("demand_id") is None else EntityId(row["demand_id"]),
            row["owner_kind"], EntityId(row["owner_id"]), int(row["priority"]), tuple(row["service_ids"]),
            tuple(SpatialNodeId(value) for value in row["service_destinations"]), int(row["departure_day"]), int(row["ready_day"]),
            CargoFlowStatus(row.get("status", "in_transit")),
        )
        for row in data.get("cargo_flows", [])
    }
    lg.lanes = {
        EntityId(row["id"]): LogisticsLane(
            EntityId(row["id"]), SpatialNodeId(row["source_id"]), SpatialNodeId(row["destination_id"]),
            float(row["requested_capacity_t_per_day"]), int(row["priority"]),
            None if row.get("path") is None else tuple(RouteId(value) for value in row["path"]),
            PathPolicy(row.get("path_policy", "fastest")), bool(row.get("paused", False)),
        )
        for row in data.get("lanes", [])
    }

def validate_logistics_runtime(sim: Any) -> None:
    lg = sim.logistics
    tr = sim.transport
    for flow_id, flow in lg.cargo_flows.items():
        _require(flow_id == flow.id, f"cargo flow key mismatch: {flow_id}")
        _require(sim.graph.has_operational_node(flow.source_id) and sim.graph.has_operational_node(flow.destination_id), f"cargo flow references unknown endpoint: {flow_id}")
        _require(flow.amount_t > 0, f"cargo flow has non-positive amount: {flow_id}")
        _require(flow.ready_day >= flow.departure_day, f"cargo flow arrives before departure: {flow_id}")
        if flow.lane_id is not None:
            _require(flow.lane_id in lg.lanes, f"cargo flow references unknown lane: {flow_id}/{flow.lane_id}")
    for lane_id, lane in lg.lanes.items():
        _require(lane_id == lane.id, f"lane key mismatch: {lane_id}")
        _require(sim.graph.has_operational_node(lane.source_id) and sim.graph.has_operational_node(lane.destination_id), f"lane references unknown endpoint: {lane_id}")
        _require(lane.source_id != lane.destination_id, f"lane loops to same location: {lane_id}")
        _require(lane.requested_capacity_t_per_day > 0, f"lane has non-positive requested capacity: {lane_id}")
        if lane.path is not None:
            tr.validate_path_structure(lane.source_id, lane.destination_id, lane.path)

LOGISTICS_STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension(
    "logistics",
    state_codec=LOGISTICS_STATE_CODEC,
    runtime_validator=validate_logistics_runtime,
)
