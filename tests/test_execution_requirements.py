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


def test_bundle_settles_resource_service_and_admission_at_one_execution_rate():
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


def test_higher_priority_band_is_allocated_first():
    high = bundle("high", 10, ResourceRequirement(ORE, 1), priority=5)
    low = bundle("low", 10, ResourceRequirement(ORE, 1), priority=1)
    plan = allocate_execution_requirements(
        [low, high], {resource_constraint(NODE, ORE): 12}
    )
    assert plan.allocated(high.id) == pytest.approx(10)
    assert plan.allocated(low.id) == pytest.approx(2)


def test_progressive_max_min_freezes_only_bundles_on_saturated_constraint():
    copper = DefinitionId("copper")
    a = bundle("a", 10, ResourceRequirement(ORE, 1))
    b = bundle("b", 10, ResourceRequirement(ORE, 1), ResourceRequirement(copper, 1))
    c = bundle("c", 10, ResourceRequirement(copper, 1))
    plan = allocate_execution_requirements(
        [a, b, c],
        {
            resource_constraint(NODE, ORE): 10,
            resource_constraint(NODE, copper): 20,
        },
    )
    # Ore freezes A/B at 50%; C can continue on independent residual copper.
    assert plan.allocated(a.id) == pytest.approx(5)
    assert plan.allocated(b.id) == pytest.approx(5)
    assert plan.allocated(c.id) == pytest.approx(10)


def test_same_band_result_is_registration_order_independent():
    rows = [bundle(name, 10, ResourceRequirement(ORE, 1)) for name in ("a", "b", "c")]
    capacity = {resource_constraint(NODE, ORE): 12}
    first = allocate_execution_requirements(rows, capacity)
    second = allocate_execution_requirements(reversed(rows), capacity)
    assert {r.bundle_id: r.allocated_execution for r in first.allocations} == {
        r.bundle_id: r.allocated_execution for r in second.allocations
    }


def test_atomic_admission_uses_persistent_wait_age_then_stable_key():
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


def test_atomic_bundle_requires_persistent_fairness_age():
    with pytest.raises(ValueError, match="wait_started_day"):
        bundle("atomic", 1, ResourceRequirement(ORE, 1), atomic=True)


def test_reservation_acquisition_is_a_normal_resource_constraint_bundle():
    intent = ReservationAcquisitionRequirement(
        id=EntityId("reserve"),
        owner_id=EntityId("project"),
        operational_node_id=NODE,
        resource_id=ORE,
        requested_amount=7,
        priority=ActivityPriority(3),
    )
    plan = allocate_execution_requirements(
        [intent], {resource_constraint(NODE, ORE): 3}
    )
    assert plan.allocated(intent.id) == pytest.approx(3)


def test_shared_owner_pool_does_not_require_a_fake_operational_node():
    row = bundle(
        "research",
        10,
        FundsOrPoolRequirement("research_points", 1, scope_id="organization"),
    )
    plan = allocate_execution_requirements(
        [row], {pool_constraint("research_points", "organization"): 4}
    )
    assert plan.allocated(row.id) == pytest.approx(4)


def test_missing_constraint_capacity_is_rejected_instead_of_assumed_infinite():
    row = bundle("x", 1, ServiceCapacityRequirement("lab", 1))
    with pytest.raises(KeyError, match="missing allocation capacities"):
        allocate_execution_requirements([row], {})


def test_real_maintenance_and_industry_bundles_share_one_resource_constraint():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids

    sim = build_game_application()._simulation
    maintenance = tuple(
        bundle for bundle in sim.maintenance.execution_requirement_bundles(sim.day)
        if bundle.operational_node_id == ids.EARTH
        and any(key.kind == "resource" and key.name == str(ids.STRUCTURAL_COMPONENTS)
                for key, _ in bundle.coefficients())
    )
    assert maintenance
    for bundle_row in maintenance:
        sim.facilities.facilities[bundle_row.owner_id].maintenance_priority = ActivityPriority(4)
    maintenance = tuple(
        bundle for bundle in sim.maintenance.execution_requirement_bundles(sim.day)
        if bundle.operational_node_id == ids.EARTH
        and any(key.kind == "resource" and key.name == str(ids.STRUCTURAL_COMPONENTS)
                for key, _ in bundle.coefficients())
    )
    industry = tuple(
        bundle for bundle in sim.industry.execution_requirement_bundles(
            ids.EARTH, sim.facilities, sim.inventory, sim.day
        )
        if any(key.kind == "resource" and key.name == str(ids.STRUCTURAL_COMPONENTS)
               for key, _ in bundle.coefficients())
    )
    assert industry

    rows = maintenance + industry
    capacities = {
        key: float("inf")
        for row in rows
        for key, _coefficient in row.coefficients()
    }
    structural_key = resource_constraint(ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    maintenance_need = sum(
        coefficient * row.requested_execution
        for row in maintenance
        for key, coefficient in row.coefficients()
        if key == structural_key
    )
    capacities[structural_key] = maintenance_need
    plan = allocate_execution_requirements(rows, capacities)

    assert all(plan.fulfillment(row.id) == pytest.approx(1.0) for row in maintenance)
    assert all(plan.fulfillment(row.id) == pytest.approx(0.0) for row in industry)
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
