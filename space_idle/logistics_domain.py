from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .external_procurement import ProcurementDeliveryBatch, ProcurementDeliveryStatus
from .logistics_models import CargoFlowBatch, CargoFlowStatus
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .supply import SupplyPolicy, TargetStockPolicy
from .transport.models import PathPolicy
from .validation_support import require as _require


def capture_logistics(sim: Any) -> dict[str, Any]:
    lg = sim.logistics
    return {
        "cargo_flow_counter": lg._cargo_flow_counter,
        "procurement_delivery_counter": lg._procurement_delivery_counter,
        "cargo_flows": [
            {
                "id": str(row.id),
                "resource_id": str(row.resource_id),
                "amount_t": row.amount_t,
                "source_id": str(row.source_id),
                "destination_id": str(row.destination_id),
                "demand_id": None if row.demand_id is None else str(row.demand_id),
                "owner_kind": row.owner_kind,
                "owner_id": str(row.owner_id),
                "priority": row.priority,
                "service_ids": list(row.service_ids),
                "service_destinations": [str(value) for value in row.service_destinations],
                "departure_day": row.departure_day,
                "ready_day": row.ready_day,
                "status": row.status.value,
            }
            for row in sorted(lg.cargo_flows.values(), key=lambda row: str(row.id))
        ],
        "procurement_deliveries": [
            {
                "id": str(row.id),
                "service_id": str(row.service_id),
                "demand_id": str(row.demand_id),
                "owner_kind": row.owner_kind,
                "owner_id": str(row.owner_id),
                "delivery_node_id": str(row.delivery_node_id),
                "resource_id": str(row.resource_id),
                "amount_t": row.amount_t,
                "order_day": row.order_day,
                "ready_day": row.ready_day,
                "status": row.status.value,
            }
            for row in sorted(lg.procurement_deliveries.values(), key=lambda row: str(row.id))
        ],
        "target_stocks": [
            {
                "id": str(row.id),
                "destination_id": str(row.destination_id),
                "resource_id": str(row.resource_id),
                "target_quantity_t": row.target_quantity_t,
                "priority": row.priority,
            }
            for row in lg.target_stock_policies()
        ],
        "supply_policies": [
            {
                "id": str(row.id),
                "destination_id": str(row.destination_id),
                "resource_id": str(row.resource_id),
                "preferred_source_id": (
                    None if row.preferred_source_id is None else str(row.preferred_source_id)
                ),
                "path_policy": row.path_policy.value,
                "explicit_path": (
                    None
                    if row.explicit_path is None
                    else [str(route_id) for route_id in row.explicit_path]
                ),
            }
            for row in lg.supply_policy_rows()
        ],
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._cargo_flow_counter = int(data.get("cargo_flow_counter", 0))
    lg._procurement_delivery_counter = int(data.get("procurement_delivery_counter", 0))
    lg.cargo_flows = {
        EntityId(row["id"]): CargoFlowBatch(
            EntityId(row["id"]),
            DefinitionId(row["resource_id"]),
            float(row["amount_t"]),
            SpatialNodeId(row["source_id"]),
            SpatialNodeId(row["destination_id"]),
            None if row.get("demand_id") is None else EntityId(row["demand_id"]),
            row["owner_kind"],
            EntityId(row["owner_id"]),
            int(row["priority"]),
            tuple(row["service_ids"]),
            tuple(SpatialNodeId(value) for value in row["service_destinations"]),
            int(row["departure_day"]),
            int(row["ready_day"]),
            CargoFlowStatus(row.get("status", "in_transit")),
        )
        for row in data.get("cargo_flows", [])
    }
    lg.procurement_deliveries = {
        EntityId(row["id"]): ProcurementDeliveryBatch(
            EntityId(row["id"]),
            DefinitionId(row["service_id"]),
            EntityId(row["demand_id"]),
            row["owner_kind"],
            EntityId(row["owner_id"]),
            SpatialNodeId(row["delivery_node_id"]),
            DefinitionId(row["resource_id"]),
            float(row["amount_t"]),
            int(row["order_day"]),
            int(row["ready_day"]),
            ProcurementDeliveryStatus(row.get("status", "in_transit")),
        )
        for row in data.get("procurement_deliveries", [])
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
    lg.supply_policies = {
        EntityId(row["id"]): SupplyPolicy(
            EntityId(row["id"]),
            SpatialNodeId(row["destination_id"]),
            DefinitionId(row["resource_id"]),
            (
                None
                if row.get("preferred_source_id") is None
                else SpatialNodeId(row["preferred_source_id"])
            ),
            PathPolicy(row.get("path_policy", "fastest")),
            (
                None
                if row.get("explicit_path") is None
                else tuple(RouteId(value) for value in row["explicit_path"])
            ),
        )
        for row in data.get("supply_policies", [])
    }


def validate_logistics_runtime(sim: Any) -> None:
    lg = sim.logistics
    tr = sim.transport
    for flow_id, flow in lg.cargo_flows.items():
        _require(flow_id == flow.id, f"cargo flow key mismatch: {flow_id}")
        _require(
            sim.graph.has_operational_node(flow.source_id)
            and sim.graph.has_operational_node(flow.destination_id),
            f"cargo flow references unknown endpoint: {flow_id}",
        )
        _require(flow.amount_t > 0, f"cargo flow has non-positive amount: {flow_id}")
        _require(
            flow.ready_day >= flow.departure_day,
            f"cargo flow arrives before departure: {flow_id}",
        )
        _require(
            1 <= int(flow.priority) <= 5,
            f"cargo flow priority must be 1..5: {flow_id}",
        )
    for delivery_id, delivery in lg.procurement_deliveries.items():
        _require(delivery_id == delivery.id, f"procurement delivery key mismatch: {delivery_id}")
        service = lg.procurement_services.get(delivery.service_id)
        _require(
            service is not None,
            f"procurement delivery references unknown service: {delivery_id}/{delivery.service_id}",
        )
        _require(
            sim.graph.has_operational_node(delivery.delivery_node_id),
            f"procurement delivery references unknown node: {delivery_id}/{delivery.delivery_node_id}",
        )
        if service is not None:
            _require(
                delivery.delivery_node_id == service.delivery_node_id,
                f"procurement delivery node does not match service: {delivery_id}",
            )
            _require(
                service.unit_price_musd_per_t(delivery.resource_id) is not None,
                f"procurement delivery resource is not offered by service: {delivery_id}/{delivery.resource_id}",
            )
        _require(
            delivery.amount_t > 0,
            f"procurement delivery has non-positive amount: {delivery_id}",
        )
        _require(
            delivery.ready_day > delivery.order_day,
            f"procurement delivery has non-positive latency: {delivery_id}",
        )
    for policy_id, policy in lg.target_stocks.items():
        _require(policy_id == policy.id, f"target stock key mismatch: {policy_id}")
        _require(
            sim.graph.has_operational_node(policy.destination_id),
            f"target stock references unknown destination: {policy_id}",
        )
        _require(
            policy.target_quantity_t >= 0,
            f"target stock has negative quantity: {policy_id}",
        )
        _require(
            1 <= int(policy.priority) <= 5,
            f"target stock priority must be 1..5: {policy_id}",
        )
    for policy_id, policy in lg.supply_policies.items():
        _require(policy_id == policy.id, f"supply policy key mismatch: {policy_id}")
        _require(
            sim.graph.has_operational_node(policy.destination_id),
            f"supply policy references unknown destination: {policy_id}",
        )
        if policy.preferred_source_id is not None:
            _require(
                sim.graph.has_operational_node(policy.preferred_source_id),
                f"supply policy references unknown source: {policy_id}",
            )
            _require(
                policy.preferred_source_id != policy.destination_id,
                f"supply policy loops to same location: {policy_id}",
            )
        if policy.explicit_path is not None:
            _require(
                policy.preferred_source_id is not None,
                f"explicit supply path has no preferred source: {policy_id}",
            )
            if policy.preferred_source_id is not None:
                tr.validate_movement_path_structure(
                    policy.preferred_source_id,
                    policy.destination_id,
                    policy.explicit_path,
                )


LOGISTICS_STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension(
    "logistics",
    state_codec=LOGISTICS_STATE_CODEC,
    runtime_validator=validate_logistics_runtime,
)
