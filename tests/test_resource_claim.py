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


def test_real_maintenance_and_industry_claims_compete_in_the_same_allocator():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids

    sim = build_game_application()._simulation
    industry_claims = tuple(
        claim for claim in sim.industry.resource_claims(ids.EARTH, sim.facilities, sim.day)
        if claim.resource_id == ids.STRUCTURAL_COMPONENTS
    )
    assert industry_claims

    maintenance_claims = tuple(
        claim for claim in sim.maintenance.resource_claims(sim.day)
        if claim.operational_node_id == ids.EARTH
        and claim.resource_id == ids.STRUCTURAL_COMPONENTS
    )
    assert maintenance_claims
    for claim in maintenance_claims:
        sim.facilities.facilities[claim.owner_id].maintenance_priority = 4
    maintenance_claims = tuple(
        claim for claim in sim.maintenance.resource_claims(sim.day)
        if claim.operational_node_id == ids.EARTH
        and claim.resource_id == ids.STRUCTURAL_COMPONENTS
    )

    maintenance_total = sum(claim.requested_amount for claim in maintenance_claims)
    sim.inventory.stock[(ids.EARTH, ids.STRUCTURAL_COMPONENTS)] = maintenance_total
    combined = maintenance_claims + industry_claims
    forward = allocate_resource_claims(combined, sim.inventory)
    reverse = allocate_resource_claims(tuple(reversed(combined)), sim.inventory)

    assert forward.allocations == reverse.allocations
    assert sum(forward.allocated(claim.id) for claim in maintenance_claims) == pytest.approx(
        maintenance_total
    )
    assert sum(forward.allocated(claim.id) for claim in industry_claims) == pytest.approx(0.0)


def test_operational_node_query_exposes_shared_resource_claim_allocation_decision_surface():
    from space_idle import GetOperationalNode, build_game_application
    from space_idle.content import base_ids as ids

    app = build_game_application()
    sim = app._simulation
    maintenance_claims = tuple(
        claim for claim in sim.maintenance.resource_claims(sim.day)
        if claim.operational_node_id == ids.EARTH
        and claim.resource_id == ids.STRUCTURAL_COMPONENTS
    )
    industry_claims = tuple(
        claim for claim in sim.industry.resource_claims(
            ids.EARTH, sim.facilities, sim.day
        )
        if claim.resource_id == ids.STRUCTURAL_COMPONENTS
    )
    assert maintenance_claims and industry_claims
    for claim in maintenance_claims:
        sim.facilities.facilities[claim.owner_id].maintenance_priority = 4
    maintenance_claims = tuple(
        claim for claim in sim.maintenance.resource_claims(sim.day)
        if claim.operational_node_id == ids.EARTH
        and claim.resource_id == ids.STRUCTURAL_COMPONENTS
    )
    maintenance_total = sum(claim.requested_amount for claim in maintenance_claims)
    sim.inventory.stock[(ids.EARTH, ids.STRUCTURAL_COMPONENTS)] = maintenance_total

    view = app.query(GetOperationalNode(str(ids.EARTH)))
    rows = tuple(
        row for row in view.resource_claims
        if row.resource_id == str(ids.STRUCTURAL_COMPONENTS)
        and row.owner_kind in {"facility_maintenance", "industry_process"}
    )

    assert rows
    assert all(row.requested == pytest.approx(row.allocated + row.unmet) for row in rows)
    maintenance_rows = tuple(row for row in rows if row.owner_kind == "facility_maintenance")
    industry_rows = tuple(row for row in rows if row.owner_kind == "industry_process")
    assert sum(row.allocated for row in maintenance_rows) == pytest.approx(maintenance_total)
    assert sum(row.allocated for row in industry_rows) == pytest.approx(0.0)
    assert all(row.priority == 4 for row in maintenance_rows)
    assert all(row.unmet > 0.0 for row in industry_rows)
