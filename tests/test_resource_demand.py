from __future__ import annotations

import pytest

from space_idle.inventory import InventoryBook
from space_idle.resource_demand import (
    ResourceDemand,
    external_resource_demands,
    resolve_local_resource_supply,
)
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId


SITE = SpatialNodeId("site")
SOURCE = SpatialNodeId("source")
RESOURCE = DefinitionId("resource")


def _demand(demand_id: str, amount_t: float, priority: int, source_id=None) -> ResourceDemand:
    return ResourceDemand(
        EntityId(demand_id),
        "test",
        EntityId(f"owner:{demand_id}"),
        SITE,
        RESOURCE,
        amount_t,
        priority,
        source_id,
    )


def test_local_supply_is_planning_credit_before_external_transport_by_priority():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 5.0)
    high = _demand("demand.high", 4.0, 80)
    low = _demand("demand.low", 4.0, 50)

    resolutions = resolve_local_resource_supply((low, high), inventory)
    by_id = {row.demand.id: row for row in resolutions}

    assert by_id[high.id].local_supply_t == pytest.approx(4.0)
    assert by_id[high.id].external_required_t == pytest.approx(0.0)
    assert by_id[low.id].local_supply_t == pytest.approx(1.0)
    assert by_id[low.id].external_required_t == pytest.approx(3.0)
    assert inventory.reserved == {}


def test_local_netting_is_registration_order_independent_and_preserves_source_constraint():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 2.0)
    first = _demand("demand.a", 3.0, 60, SOURCE)
    second = _demand("demand.b", 3.0, 60)

    forward = external_resource_demands((first, second), inventory)
    reverse = external_resource_demands((second, first), inventory)

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

    demand = _demand("demand.other", 3.0, 50)
    resolution = resolve_local_resource_supply((demand,), inventory)[0]

    assert resolution.local_supply_t == pytest.approx(1.0)
    assert resolution.external_required_t == pytest.approx(2.0)
