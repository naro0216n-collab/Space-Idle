from __future__ import annotations

import pytest

from space_idle.inventory import InventoryBook
from space_idle.supply import (
    SupplyRequirement,
    external_supply_requirements,
    resolve_local_supply,
)
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId


SITE = SpatialNodeId("site")
SOURCE = SpatialNodeId("source")
RESOURCE = DefinitionId("resource")


def _requirement(requirement_id: str, amount_t: float, priority: int, source_id=None) -> SupplyRequirement:
    return SupplyRequirement(
        EntityId(requirement_id),
        "test",
        EntityId(f"owner:{requirement_id}"),
        SITE,
        RESOURCE,
        amount_t,
        priority,
        source_id,
    )


def test_local_supply_is_planning_credit_before_external_transport_by_priority():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 5.0)
    high = _requirement("requirement.high", 4.0, 5)
    low = _requirement("requirement.low", 4.0, 3)

    resolutions = resolve_local_supply((low, high), inventory)
    by_id = {row.requirement.id: row for row in resolutions}

    assert by_id[high.id].local_supply_t == pytest.approx(4.0)
    assert by_id[high.id].external_required_t == pytest.approx(0.0)
    assert by_id[low.id].local_supply_t == pytest.approx(1.0)
    assert by_id[low.id].external_required_t == pytest.approx(3.0)
    assert inventory.reserved == {}


def test_local_netting_is_registration_order_independent_and_preserves_source_constraint():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 2.0)
    first = _requirement("requirement.a", 3.0, 3, SOURCE)
    second = _requirement("requirement.b", 3.0, 3)

    forward = external_supply_requirements((first, second), inventory)
    reverse = external_supply_requirements((second, first), inventory)

    assert forward == reverse
    assert [(row.id, row.amount_t) for row in forward] == [
        (first.id, pytest.approx(2.0)),
        (second.id, pytest.approx(2.0)),
    ]
    assert forward[0].source_id == SOURCE
    assert inventory.reserved == {}


def test_durable_inventory_reservation_is_unavailable_to_future_demand_planning():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 5.0)
    inventory.reserve(EntityId("project"), SITE, RESOURCE, 4.0)

    requirement = _requirement("requirement.other", 3.0, 3)
    resolution = resolve_local_supply((requirement,), inventory)[0]

    assert resolution.local_supply_t == pytest.approx(1.0)
    assert resolution.external_required_t == pytest.approx(2.0)
