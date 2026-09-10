from __future__ import annotations

import pytest

from space_idle.inventory import InventoryBook
from space_idle.resource_demand import (
    ResourceDemand,
    external_resource_demands,
    reconcile_local_resource_claims,
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


def test_local_supply_is_netted_once_before_external_transport_by_priority():
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
    assert sum(row.external_required_t for row in resolutions) == pytest.approx(3.0)


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


def test_reserved_inventory_is_not_reused_as_local_supply_for_other_demand():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 5.0)
    reserved = inventory.reserve(EntityId("project"), SITE, RESOURCE, 4.0)
    assert reserved == pytest.approx(4.0)

    demand = _demand("demand.other", 3.0, 50)
    resolution = resolve_local_resource_supply((demand,), inventory)[0]

    assert resolution.local_supply_t == pytest.approx(1.0)
    assert resolution.external_required_t == pytest.approx(2.0)


def test_immediate_claim_can_be_smaller_than_transport_replenishment_target():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 10.0)
    maintenance = ResourceDemand(
        EntityId("demand.maintenance"),
        "maintenance",
        EntityId("maintenance"),
        SITE,
        RESOURCE,
        30.0,
        80,
        None,
        1.0,
        True,
    )
    construction = _demand("demand.construction", 8.0, 50)

    resolutions = reconcile_local_resource_claims((construction, maintenance), inventory)
    by_id = {row.demand.id: row for row in resolutions}

    # Immediate claims are protected before buffer replenishment. The high
    # priority maintenance demand gets its one-day claim first, but its 30-day
    # buffer target does not pre-empt the lower-priority construction claim.
    assert by_id[maintenance.id].local_supply_t == pytest.approx(2.0)
    assert by_id[maintenance.id].external_required_t == pytest.approx(28.0)
    assert by_id[construction.id].local_supply_t == pytest.approx(8.0)
    assert inventory.reserved_for(maintenance.id, SITE, RESOURCE) == pytest.approx(1.0)
    assert inventory.reserved_for(construction.id, SITE, RESOURCE) == pytest.approx(8.0)


def test_existing_demand_reservation_counts_as_its_local_supply_not_external_shortage():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 5.0)
    demand = _demand("demand.project", 5.0, 50)
    inventory.reserve(demand.id, SITE, RESOURCE, 3.0)

    resolution = resolve_local_resource_supply((demand,), inventory)[0]

    assert resolution.local_supply_t == pytest.approx(5.0)
    assert resolution.external_required_t == pytest.approx(0.0)


def test_equal_priority_immediate_claims_share_shortage_proportionally():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 3.0)
    first = _demand("demand.a", 2.0, 50)
    second = _demand("demand.b", 4.0, 50)

    resolutions = reconcile_local_resource_claims((second, first), inventory)
    by_id = {row.demand.id: row for row in resolutions}

    assert by_id[first.id].local_supply_t == pytest.approx(1.0)
    assert by_id[second.id].local_supply_t == pytest.approx(2.0)
    assert inventory.reserved_for(first.id, SITE, RESOURCE) == pytest.approx(1.0)
    assert inventory.reserved_for(second.id, SITE, RESOURCE) == pytest.approx(2.0)
