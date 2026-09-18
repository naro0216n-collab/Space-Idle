from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .shared import SpatialNodeId
from .validation_support import ValidationContext, require as _require


def capture_storage(sim: Any) -> dict[str, Any]:
    return {
        "infrastructure_capacity": [
            {"operational_node_id": str(node_id), "storage_pool_key": pool_key, "amount": amount}
            for (node_id, pool_key), amount in sorted(
                sim.storage.infrastructure_capacity_t.items(), key=lambda item: (str(item[0][0]), item[0][1])
            )
        ]
    }


def restore_storage(sim: Any, data: dict[str, Any]) -> None:
    rows = data["infrastructure_capacity"]
    expected_fields = {"operational_node_id", "storage_pool_key", "amount"}
    if any(set(row) != expected_fields for row in rows):
        raise ValueError("storage infrastructure capacity has invalid fields")
    sim.storage.infrastructure_capacity_t = {
        (SpatialNodeId(row["operational_node_id"]), str(row["storage_pool_key"])): float(row["amount"])
        for row in rows
    }


STATE_CODEC = StateCodec("storage", capture_storage, restore_storage)


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    facility_defs = ctx.facility_defs
    _require(sim.storage.inventory is sim.inventory, "storage/inventory service mismatch")
    _require(sim.storage.facilities is sim.facilities, "storage/facility service mismatch")
    for definition_id, spec in sim.storage.providers.items():
        _require(definition_id == spec.facility_def_id, f"storage provider key mismatch: {definition_id}")
        _require(definition_id in facility_defs, f"storage provider references unknown facility: {definition_id}")
        _require(all(v >= 0 for v in spec.capacity_t_by_pool.values()), f"negative storage capacity: {definition_id}")
        _require(spec.power_sensitive_pools.issubset(spec.capacity_t_by_pool), f"unknown power-sensitive storage pool: {definition_id}")


def validate_runtime(sim: Any) -> None:
    for (node_id, pool_key), amount in sim.storage.infrastructure_capacity_t.items():
        _require(sim.graph.has_operational_node(node_id), f"storage infrastructure references unknown operational node: {node_id}/{pool_key}")
        _require(bool(pool_key), f"empty storage pool key at {node_id}")
        _require(amount >= 0, f"negative storage infrastructure capacity: {node_id}/{pool_key}")


DOMAIN_EXTENSION = DomainExtension(
    "storage", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
)
