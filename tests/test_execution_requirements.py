from __future__ import annotations

import pytest

from space_idle.execution_requirements import (
    ExecutionRequirementBundle,
    FundsOrPoolRequirement,
    ReservationAcquisitionRequirement,
    ResourceRequirement,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
    admission_constraint,
    allocate_execution_requirements,
    pool_constraint,
    resource_constraint,
    service_constraint,
)
from space_idle.priority import ActivityPriority
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId


NODE = SpatialNodeId("node")
ORE = DefinitionId("ore")


def bundle(name: str, requested: float, *requirements, priority: int = 3, **kwargs):
    return ExecutionRequirementBundle(
        id=EntityId(name),
        owner_kind="test",
        owner_id=EntityId(name),
        purpose="run",
        operational_node_id=NODE,
        requested_execution=requested,
        priority=ActivityPriority(priority),
        requirements=tuple(requirements),
        **kwargs,
    )


def test_execution_bundle_settlement_uses_one_rate_and_requires_explicit_capacities():
    row = bundle(
        "process",
        10,
        ResourceRequirement(ORE, 2),
        ServiceCapacityRequirement("power", 1),
        StockOrPoolAdmissionRequirement("bulk", 1.5),
    )
    plan = allocate_execution_requirements(
        [row],
        {
            resource_constraint(NODE, ORE): 100,
            service_constraint(NODE, "power"): 4,
            admission_constraint(NODE, "bulk"): 100,
        },
    )
    assert plan.allocated(row.id) == pytest.approx(4)
    assert plan.used_by_constraint[resource_constraint(NODE, ORE)] == pytest.approx(8)
    assert plan.used_by_constraint[service_constraint(NODE, "power")] == pytest.approx(4)
    assert plan.used_by_constraint[admission_constraint(NODE, "bulk")] == pytest.approx(6)

    missing = bundle("missing", 1, ServiceCapacityRequirement("lab", 1))
    with pytest.raises(KeyError, match="missing allocation capacities"):
        allocate_execution_requirements([missing], {})


def test_allocator_preserves_priority_progressive_fairness_and_registration_independence():
    high = bundle("high", 10, ResourceRequirement(ORE, 1), priority=5)
    low = bundle("low", 10, ResourceRequirement(ORE, 1), priority=1)
    priority_plan = allocate_execution_requirements(
        [low, high], {resource_constraint(NODE, ORE): 12}
    )
    assert priority_plan.allocated(high.id) == pytest.approx(10)
    assert priority_plan.allocated(low.id) == pytest.approx(2)

    copper = DefinitionId("copper")
    a = bundle("a", 10, ResourceRequirement(ORE, 1))
    b = bundle("b", 10, ResourceRequirement(ORE, 1), ResourceRequirement(copper, 1))
    c = bundle("c", 10, ResourceRequirement(copper, 1))
    progressive = allocate_execution_requirements(
        [a, b, c],
        {
            resource_constraint(NODE, ORE): 10,
            resource_constraint(NODE, copper): 20,
        },
    )
    assert progressive.allocated(a.id) == pytest.approx(5)
    assert progressive.allocated(b.id) == pytest.approx(5)
    assert progressive.allocated(c.id) == pytest.approx(10)

    rows = [bundle(name, 10, ResourceRequirement(ORE, 1)) for name in ("d", "e", "f")]
    capacity = {resource_constraint(NODE, ORE): 12}
    forward = allocate_execution_requirements(rows, capacity)
    reverse = allocate_execution_requirements(reversed(rows), capacity)
    assert {r.bundle_id: r.allocated_execution for r in forward.allocations} == {
        r.bundle_id: r.allocated_execution for r in reverse.allocations
    }


def test_atomic_admission_requires_persistent_age_and_uses_age_then_stable_key():
    with pytest.raises(ValueError, match="wait_started_day"):
        bundle("atomic", 1, ResourceRequirement(ORE, 1), atomic=True)

    older = bundle(
        "older", 1, ResourceRequirement(ORE, 1), atomic=True, wait_started_day=3
    )
    newer = bundle(
        "newer", 1, ResourceRequirement(ORE, 1), atomic=True, wait_started_day=4
    )
    plan = allocate_execution_requirements(
        [newer, older], {resource_constraint(NODE, ORE): 1}
    )
    assert plan.allocated(older.id) == pytest.approx(1)
    assert plan.allocated(newer.id) == pytest.approx(0)


def test_common_allocator_handles_reservation_acquisition_and_shared_owner_pools():
    intent = ReservationAcquisitionRequirement(
        id=EntityId("reserve"),
        owner_id=EntityId("project"),
        operational_node_id=NODE,
        resource_id=ORE,
        requested_amount=7,
        priority=ActivityPriority(3),
    )
    reservation = allocate_execution_requirements(
        [intent], {resource_constraint(NODE, ORE): 3}
    )
    assert reservation.allocated(intent.id) == pytest.approx(3)

    shared_pool = bundle(
        "research",
        10,
        FundsOrPoolRequirement("research_points", 1, scope_id="organization"),
    )
    pool_plan = allocate_execution_requirements(
        [shared_pool], {pool_constraint("research_points", "organization"): 4}
    )
    assert pool_plan.allocated(shared_pool.id) == pytest.approx(4)


def test_canonical_tick_shares_resource_constraint_across_maintenance_and_industry_priority():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids

    sim = build_game_application()._simulation
    structural_key = resource_constraint(ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    maintenance = tuple(
        row for row in sim.maintenance.execution_requirement_bundles(sim.day)
        if row.operational_node_id == ids.EARTH
        and any(key == structural_key for key, _coefficient in row.coefficients())
    )
    industry = tuple(
        row for row in sim.industry.execution_requirement_bundles(
            ids.EARTH, sim.facilities, sim.inventory, sim.day
        )
        if any(key == structural_key for key, _coefficient in row.coefficients())
    )
    assert maintenance and industry

    for row in maintenance:
        sim.facilities.facilities[row.owner_id].maintenance_priority = ActivityPriority(4)
    for row in industry:
        sim.facilities.facilities[row.owner_id].activity_priority = ActivityPriority(1)

    maintenance = tuple(
        row for row in sim.maintenance.execution_requirement_bundles(sim.day)
        if row.operational_node_id == ids.EARTH
        and any(key == structural_key for key, _coefficient in row.coefficients())
    )
    maintenance_need = sum(
        coefficient * row.requested_execution
        for row in maintenance
        for key, coefficient in row.coefficients()
        if key == structural_key
    )
    sim.inventory.stock[(ids.EARTH, ids.STRUCTURAL_COMPONENTS)] = maintenance_need

    plan = sim.tick_decision_projection().allocations.execution
    maintenance_rows = tuple(
        row for row in plan.bundles
        if row.owner_kind == "facility_maintenance"
        and row.operational_node_id == ids.EARTH
        and any(key == structural_key for key, _coefficient in row.coefficients())
    )
    industry_rows = tuple(
        row for row in plan.bundles
        if row.owner_kind == "industry_process"
        and row.operational_node_id == ids.EARTH
        and any(key == structural_key for key, _coefficient in row.coefficients())
    )

    assert maintenance_rows and industry_rows
    assert all(plan.fulfillment(row.id) == pytest.approx(1.0) for row in maintenance_rows)
    assert all(plan.fulfillment(row.id) == pytest.approx(0.0) for row in industry_rows)
    assert plan.used_by_constraint[structural_key] == pytest.approx(maintenance_need)

def test_real_industry_and_extraction_requirements_are_settled_by_execution_plan():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids

    sim = build_game_application()._simulation
    decision = sim.tick_decision_projection()
    plan = decision.allocations.execution
    industry = tuple(
        bundle for bundle in plan.bundles
        if bundle.owner_kind == "industry_process" and bundle.operational_node_id == ids.EARTH
    )
    extraction = tuple(
        bundle for bundle in plan.bundles
        if bundle.owner_kind == "extraction" and bundle.operational_node_id == ids.EARTH
    )
    assert industry and extraction
    assert all(
        any(key.kind == "service" and key.name.startswith("process:") for key, _ in row.coefficients())
        for row in industry
    )
    assert all(
        any(key.kind == "service" and key.name.startswith("extraction:") for key, _ in row.coefficients())
        for row in extraction
    )
    assert all(0.0 <= plan.fulfillment(row.id) <= 1.0 for row in industry + extraction)
