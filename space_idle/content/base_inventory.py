from __future__ import annotations

from . import base_ids as ids


def configure_inventory_definitions(inventory) -> None:
    """Register static Resource → storage-class Content definitions.

    Scenario-owned capacities and starting stock are intentionally not applied
    here; they live in ``base_scenario`` and are transferred to runtime State
    only for a new game.
    """
    for resource in (
        ids.STRUCTURAL_COMPONENTS,
        ids.MACHINERY,
        ids.PRECISION_ELECTRONICS,
        ids.CONSTRUCTION_EQUIPMENT,
    ):
        inventory.register_storage_class(resource, "general_cargo")
    for resource in (
        ids.BULK_STRUCTURE,
        ids.FABRICATED_STRUCTURE,
        ids.BASIC_MACHINE_PARTS,
        ids.REGOLITH,
        ids.METAL_FEEDSTOCK,
        ids.AGGREGATE,
        ids.METAL_ORE,
    ):
        inventory.register_storage_class(resource, "bulk")
    inventory.register_storage_class(ids.WATER, "liquid")
    for resource in (ids.OXYGEN, ids.HYDROGEN, ids.PROPELLANT):
        inventory.register_storage_class(resource, "cryogenic")
