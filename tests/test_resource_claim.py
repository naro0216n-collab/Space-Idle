from __future__ import annotations

import pytest

from space_idle.inventory import InventoryBook
from space_idle.resource_claim import ResourceClaim, allocate_resource_claims
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId

SITE = SpatialNodeId("site")
RESOURCE = DefinitionId("resource")


def _claim(claim_id: str, amount: float, priority: int, owner_kind: str = "test", *, minimum=0.0, atomic=False):
    return ResourceClaim(
        EntityId(claim_id), SITE, RESOURCE, amount, priority,
        owner_kind, EntityId(f"owner:{claim_id}"), "test",
        minimum_amount=minimum, atomic=atomic,
    )


def test_cross_domain_priority_allocation_uses_one_inventory_budget():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 5.0)
    maintenance = _claim("claim.maintenance", 4.0, 4, "maintenance")
    industry = _claim("claim.industry", 4.0, 3, "industry")

    plan = allocate_resource_claims((industry, maintenance), inventory)

    assert plan.allocated(maintenance.id) == pytest.approx(4.0)
    assert plan.allocated(industry.id) == pytest.approx(1.0)
    assert inventory.amount(SITE, RESOURCE) == pytest.approx(5.0)
    assert inventory.reserved == {}


def test_equal_priority_shortage_is_proportional_and_registration_order_independent():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 3.0)
    first = _claim("claim.a", 2.0, 3, "industry")
    second = _claim("claim.b", 4.0, 3, "maintenance")

    forward = allocate_resource_claims((first, second), inventory)
    reverse = allocate_resource_claims((second, first), inventory)

    assert forward.allocations == reverse.allocations
    assert forward.allocated(first.id) == pytest.approx(1.0)
    assert forward.allocated(second.id) == pytest.approx(2.0)


def test_unmet_minimum_receives_no_partial_allocation():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 2.0)
    threshold = _claim("claim.threshold", 4.0, 3, minimum=3.0)
    continuous = _claim("claim.continuous", 4.0, 3)

    plan = allocate_resource_claims((threshold, continuous), inventory)

    assert plan.allocated(threshold.id) == pytest.approx(0.0)
    assert plan.allocated(continuous.id) == pytest.approx(2.0)


def test_atomic_claim_is_all_or_nothing():
    inventory = InventoryBook()
    inventory.add(SITE, RESOURCE, 3.0)
    atomic = _claim("claim.atomic", 4.0, 3, atomic=True)
    lower = _claim("claim.lower", 3.0, 3)

    plan = allocate_resource_claims((atomic, lower), inventory)

    assert plan.allocated(atomic.id) == pytest.approx(0.0)
    assert plan.allocated(lower.id) == pytest.approx(3.0)
