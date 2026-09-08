from __future__ import annotations

from . import base_ids as ids


def configure_initial_inventory(inventory) -> None:
    for resource in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS, ids.CONSTRUCTION_EQUIPMENT):
        inventory.register_storage_class(resource, "general_cargo")
    for resource in (ids.BULK_STRUCTURE, ids.FABRICATED_STRUCTURE, ids.BASIC_MACHINE_PARTS, ids.REGOLITH, ids.METAL_FEEDSTOCK):
        inventory.register_storage_class(resource, "bulk")
    inventory.register_storage_class(ids.WATER, "liquid")
    for resource in (ids.OXYGEN, ids.HYDROGEN, ids.PROPELLANT):
        inventory.register_storage_class(resource, "cryogenic")

    for storage_class in ("general_cargo", "bulk", "liquid", "cryogenic"):
        inventory.add_capacity(ids.EARTH, storage_class, 100000.0)
    for node in (ids.LEO, ids.LUNAR_ORBIT):
        inventory.add_capacity(node, "general_cargo", 1000.0)
        inventory.add_capacity(node, "cryogenic", 120.0)
    for node in (ids.SOUTH_POLAR_RIDGE, ids.POLAR_COLD_TRAP, ids.NEARSIDE_MARE):
        inventory.add_capacity(node, "general_cargo", 40.0)
        inventory.add_capacity(node, "bulk", 30.0)

    # Initial imported industrial stock supports the opening research/logistics
    # investments but is deliberately finite. Sustained midgame expansion must
    # transition toward production, extraction, and logistics rather than draw
    # from an effectively unlimited starting warehouse.
    inventory.add(ids.EARTH, ids.STRUCTURAL_COMPONENTS, 120.0)
    inventory.add(ids.EARTH, ids.MACHINERY, 100.0)
    inventory.add(ids.EARTH, ids.PRECISION_ELECTRONICS, 70.0)
    inventory.add(ids.EARTH, ids.CONSTRUCTION_EQUIPMENT, 120.0)
    inventory.add(ids.EARTH, ids.WATER, 5000.0)
    inventory.add(ids.EARTH, ids.OXYGEN, 5000.0)
    inventory.add(ids.EARTH, ids.HYDROGEN, 2000.0)
    inventory.add(ids.EARTH, ids.PROPELLANT, 5000.0)
