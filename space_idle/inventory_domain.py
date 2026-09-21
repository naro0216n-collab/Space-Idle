from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec, decode_float, decode_list, decode_str, require_fields
from .validation_support import ValidationContext, require as _require
from .shared import DefinitionId, EntityId, SpatialNodeId


def capture_inventory(sim: Any) -> dict[str, Any]:
    return {
        "stock": [
            {"operational_node_id": str(loc), "resource_id": str(res), "amount": amount}
            for (loc, res), amount in sorted(sim.inventory.stock.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))
        ],
        "reserved": [
            {"owner_id": str(owner), "operational_node_id": str(loc), "resource_id": str(res), "amount": amount}
            for (owner, loc, res), amount in sorted(sim.inventory.reserved.items(), key=lambda x: (str(x[0][0]), str(x[0][1]), str(x[0][2])))
        ],
        "external_occupancy": [
            {"owner_id": str(owner), "operational_node_id": str(loc), "resource_id": str(res), "amount": amount}
            for (owner, loc, res), amount in sorted(sim.inventory.external_occupancy.items(), key=lambda x: (str(x[0][0]), str(x[0][1]), str(x[0][2])))
        ],
    }


def _restore_inventory_rows(
    value: Any, fields: set[str], label: str, key_fields: tuple[str, ...]
) -> dict[tuple[Any, ...], float]:
    restored: dict[tuple[Any, ...], float] = {}
    for index, raw in enumerate(decode_list(value, f"inventory {label}")):
        row = require_fields(raw, fields, f"inventory {label}[{index}]")
        key_parts: list[Any] = []
        for field in key_fields:
            decoded = decode_str(row[field], f"inventory {label} {field}")
            if field == "resource_id":
                key_parts.append(DefinitionId(decoded))
            elif field == "operational_node_id":
                key_parts.append(SpatialNodeId(decoded))
            else:
                key_parts.append(EntityId(decoded))
        key = tuple(key_parts)
        if key in restored:
            raise ValueError(f"duplicate inventory {label} key: {key}")
        restored[key] = decode_float(row["amount"], f"inventory {label} amount")
    return restored


def restore_inventory(sim: Any, data: dict[str, Any]) -> None:
    sim.inventory.stock = _restore_inventory_rows(
        data["stock"],
        {"operational_node_id", "resource_id", "amount"},
        "stock",
        ("operational_node_id", "resource_id"),
    )
    sim.inventory.reserved = _restore_inventory_rows(
        data["reserved"],
        {"owner_id", "operational_node_id", "resource_id", "amount"},
        "reserved",
        ("owner_id", "operational_node_id", "resource_id"),
    )
    sim.inventory.external_occupancy = _restore_inventory_rows(
        data["external_occupancy"],
        {"owner_id", "operational_node_id", "resource_id", "amount"},
        "external_occupancy",
        ("owner_id", "operational_node_id", "resource_id"),
    )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return set(sim.inventory.resource_definitions) | {
        resource_id for (_operational_node_id, resource_id) in sim.inventory.stock
    }


STATE_CODEC = StateCodec("inventory", capture_inventory, restore_inventory)


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    for resource_id, definition in sim.inventory.resource_definitions.items():
        _require(resource_id == definition.id, f"inventory resource definition key mismatch: {resource_id}")
        if definition.storage_pool_key is not None:
            _require(bool(definition.storage_pool_key), f"empty storage pool key for resource: {resource_id}")
    for (operational_node_id, pool_key), amount in sim.inventory.physical_storage_capacity_t.items():
        _require(operational_node_id in ctx.operational_nodes, f"storage capacity references unknown location: {operational_node_id}")
        _require(bool(pool_key), f"empty storage pool key at {operational_node_id}")
        _require(amount >= 0, "negative storage capacity")
    for key, usable in sim.inventory.usable_storage_capacity_t.items():
        _require(key in sim.inventory.physical_storage_capacity_t, f"usable storage capacity has no physical capacity: {key}")
        _require(usable >= 0, f"negative usable storage capacity: {key}")
        _require(usable <= sim.inventory.physical_storage_capacity_t[key] + 1e-9, f"usable storage capacity exceeds physical capacity: {key}")


def validate_runtime(sim: Any) -> None:
    for (operational_node_id, resource_id), amount in sim.inventory.stock.items():
        _require(sim.graph.has_operational_node(operational_node_id), f"inventory references unknown location: {operational_node_id}")
        _require(amount >= -1e-9, f"negative inventory: {operational_node_id}/{resource_id}")
        reserved = sim.inventory.reserved_total(operational_node_id, resource_id)
        _require(reserved >= -1e-9, f"negative reservation: {operational_node_id}/{resource_id}")
        _require(reserved <= amount + 1e-8, f"reservations exceed stock: {operational_node_id}/{resource_id}")
    for (_owner, operational_node_id, resource_id), amount in sim.inventory.reserved.items():
        _require(sim.graph.has_operational_node(operational_node_id), f"reservation references unknown location: {operational_node_id}/{resource_id}")
        _require(amount >= -1e-9, f"negative reservation row: {operational_node_id}/{resource_id}")
    for (_owner, operational_node_id, resource_id), amount in sim.inventory.external_occupancy.items():
        _require(sim.graph.has_operational_node(operational_node_id), f"external storage occupancy references unknown operational node: {operational_node_id}/{resource_id}")
        _require(amount >= -1e-9, f"negative external storage occupancy: {operational_node_id}/{resource_id}")
    for (operational_node_id, pool_key), capacity in sim.inventory.physical_storage_capacity_t.items():
        _require(sim.graph.has_operational_node(operational_node_id), f"storage capacity references unknown operational node: {operational_node_id}/{pool_key}")
        stored = sim.inventory.stored_in_pool(operational_node_id, pool_key)
        _require(stored <= capacity + 1e-8, f"physical storage capacity exceeded: {operational_node_id}/{pool_key}")
        usable = sim.inventory.usable_storage_capacity_t.get((operational_node_id, pool_key), 0.0)
        _require(0 <= usable <= capacity + 1e-8, f"invalid usable storage capacity: {operational_node_id}/{pool_key}")


DOMAIN_EXTENSION = DomainExtension(
    "inventory", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    runtime_validator=validate_runtime, referenced_resources=referenced_resources,
)
