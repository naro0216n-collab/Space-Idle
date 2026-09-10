from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require
from .shared import DefinitionId, EntityId, SpatialNodeId


def capture_inventory(sim: Any) -> dict[str, Any]:
    return {
        "stock": [
            {"location_id": str(loc), "resource_id": str(res), "amount": amount}
            for (loc, res), amount in sorted(sim.inventory.stock.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))
        ],
        "external_occupancy": [
            {"owner_id": str(owner), "location_id": str(loc), "resource_id": str(res), "amount": amount}
            for (owner, loc, res), amount in sorted(sim.inventory.external_occupancy.items(), key=lambda x: (str(x[0][0]), str(x[0][1]), str(x[0][2])))
        ],
    }


def restore_inventory(sim: Any, data: dict[str, Any]) -> None:
    sim.inventory.stock = {
        (SpatialNodeId(r["location_id"]), DefinitionId(r["resource_id"])): float(r["amount"])
        for r in data["stock"]
    }
    sim.inventory.reserved = {}
    sim.inventory.external_occupancy = {
        (EntityId(r["owner_id"]), SpatialNodeId(r["location_id"]), DefinitionId(r["resource_id"])): float(r["amount"])
        for r in data.get("external_occupancy", [])
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result = set(sim.inventory.resource_storage_class)
    result.update(resource_id for (_location_id, resource_id) in sim.inventory.stock)
    return result


STATE_CODEC = StateCodec("inventory", capture_inventory, restore_inventory)
def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    nodes = ctx.nodes
    for (location_id, storage_class), amount in sim.inventory.base_storage_capacity_t.items():
        _require(location_id in nodes, f"base storage capacity references unknown location: {location_id}")
        _require(bool(storage_class), f"empty storage class at {location_id}")
        _require(amount >= 0, "negative base storage capacity")
    for (location_id, storage_class), amount in sim.inventory.storage_capacity_t.items():
        _require(location_id in nodes, f"storage capacity references unknown location: {location_id}")
        _require(bool(storage_class), f"empty storage class at {location_id}")
        _require(amount >= 0, "negative storage capacity")
    for key, service in sim.inventory.storage_service_capacity_t.items():
        _require(key in sim.inventory.storage_capacity_t, f"storage service capacity has no physical capacity: {key}")
        _require(service >= 0, f"negative storage service capacity: {key}")
        _require(service <= sim.inventory.storage_capacity_t[key] + 1e-9, f"storage service exceeds physical capacity: {key}")
    for resource_id, storage_class in sim.inventory.resource_storage_class.items():
        _require(bool(storage_class), f"empty storage class for resource: {resource_id}")
    for (location_id, _resource_id), amount in sim.inventory.stock.items():
        _require(location_id in nodes, f"initial inventory references unknown location: {location_id}")
        _require(amount >= -1e-9, "negative initial inventory")


def validate_runtime(sim: Any) -> None:
    for (location_id, resource_id), amount in sim.inventory.stock.items():
        _require(location_id in sim.graph.nodes, f"inventory references unknown location: {location_id}")
        _require(amount >= -1e-9, f"negative inventory: {location_id}/{resource_id}")
        reserved = sim.inventory.reserved_total(location_id, resource_id)
        _require(reserved >= -1e-9, f"negative reservation: {location_id}/{resource_id}")
        _require(reserved <= amount + 1e-8, f"reservations exceed stock: {location_id}/{resource_id}")
    for (_owner, location_id, resource_id), amount in sim.inventory.reserved.items():
        _require(location_id in sim.graph.nodes, f"reservation references unknown location: {location_id}/{resource_id}")
        _require(amount >= -1e-9, f"negative reservation row: {location_id}/{resource_id}")
    for (_owner, location_id, resource_id), amount in sim.inventory.external_occupancy.items():
        _require(amount >= -1e-9, f"negative external storage occupancy: {location_id}/{resource_id}")
    for (location_id, storage_class), capacity in sim.inventory.storage_capacity_t.items():
        stored = sim.inventory.stored_in_class(location_id, storage_class)
        _require(stored <= capacity + 1e-8, f"physical storage capacity exceeded: {location_id}/{storage_class}")
        service = sim.inventory.storage_service_capacity_t.get((location_id, storage_class), 0.0)
        _require(0 <= service <= capacity + 1e-8, f"invalid storage service capacity: {location_id}/{storage_class}")


DOMAIN_EXTENSION = DomainExtension(
    "inventory", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    runtime_validator=validate_runtime, referenced_resources=referenced_resources,
)
