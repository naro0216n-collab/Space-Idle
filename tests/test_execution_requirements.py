from __future__ import annotations

import pytest

from space_idle.catalog import ResourceDef
from space_idle.disposal import salvage_admission_requirements, settle_salvage_recovery
from space_idle.execution_requirements import (
    ExecutionRequirementBundle,
    PoolRequirement,
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
from space_idle.inventory import DEFAULT_STORAGE_POOL_KEY, InventoryBook
from space_idle.priority import (
    ActivityPriority,
    DEFAULT_ACTIVITY_PRIORITY,
    DEFAULT_PRIORITY_LEVEL,
    DEFAULT_PROVISIONING_PRIORITY,
    PriorityLevel,
    ProvisioningPriority,
)
from space_idle.service_capacity import ServiceCapacityRequest, allocate_service_capacity
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



def test_boundary_settlement_resources_feed_the_next_physical_snapshot_allocation():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids
    from space_idle.facilities import FacilityDef

    app = build_game_application()
    sim = app._simulation

    # Maintenance is only a generic Resource consumer here. The contract is
    # Simulation ordering: Cargo that matures at the boundary is admitted before
    # the next Physical snapshot and therefore participates in normal allocation.
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    definition_id = DefinitionId("test.facility.boundary_consumer")
    sim.facilities.definitions[definition_id] = FacilityDef(
        definition_id,
        "Boundary consumer",
        maintenance_fraction_per_year=365.0,
    )
    facility_id = sim.facilities.install(
        definition_id,
        ids.LEO,
        invested_resources={ids.STRUCTURAL_COMPONENTS: 1.0},
    )
    sim.refresh_storage()
    sim.inventory.stock[(ids.LEO, ids.STRUCTURAL_COMPONENTS)] = 0.0
    sim.inventory.add(ids.EARTH, ids.STRUCTURAL_COMPONENTS, 100.0)

    target_capacity = sim.transport.transport_capacity_for_units(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 1, day=sim.day
    )
    sim.transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE,
        ids.EARTH,
        ids.LEO,
        target_capacity=target_capacity,
        day=sim.day,
    )

    initial = sim.tick_decision_projection().allocations.execution
    maintenance_bundle = next(
        row
        for row in initial.bundles
        if row.owner_kind == "facility_maintenance" and row.owner_id == facility_id
    )
    assert initial.fulfillment(maintenance_bundle.id) == pytest.approx(0.0)

    sim.advance_days(1)
    flow = next(
        row
        for row in sim.logistics.cargo_flows.values()
        if row.owner_id == facility_id
        and row.resource_id == ids.STRUCTURAL_COMPONENTS
    )
    ready_day = flow.first_arrival_day
    assert ready_day > sim.day

    sim.advance_to_day(ready_day)
    assert sim.boundary_settled_day == sim.day == ready_day
    assert sim.inventory.available(ids.LEO, ids.STRUCTURAL_COMPONENTS) > 0.0

    next_allocation = sim.tick_decision_projection().allocations.execution
    maintenance_bundle = next(
        row
        for row in next_allocation.bundles
        if row.owner_kind == "facility_maintenance" and row.owner_id == facility_id
    )
    assert next_allocation.fulfillment(maintenance_bundle.id) > 0.0

def test_shared_allocators_preserve_priority_progressive_fairness_and_registration_independence():
    assert tuple(int(level) for level in PriorityLevel) == (1, 2, 3, 4, 5)
    assert DEFAULT_PRIORITY_LEVEL is PriorityLevel.NORMAL
    assert int(DEFAULT_ACTIVITY_PRIORITY) == 3
    assert int(DEFAULT_PROVISIONING_PRIORITY) == 3

    for value in (0, 6, -1, True, 1.5):
        with pytest.raises(ValueError):
            ActivityPriority(value)
        with pytest.raises(ValueError):
            ProvisioningPriority(value)

    activity = ActivityPriority(4)
    provisioning = ProvisioningPriority(4)
    with pytest.raises(ValueError, match="different priority role"):
        ProvisioningPriority(activity)
    with pytest.raises(ValueError, match="different priority role"):
        ActivityPriority(provisioning)

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

    # Root Service Capacity demand is a separate request surface, but it obeys
    # the same Activity Priority and same-band proportional fairness contract.
    def service_request(name: str, requested: float, priority: int = 3):
        return ServiceCapacityRequest(
            EntityId(f"service.{name}"),
            NODE,
            "test_service",
            requested,
            ActivityPriority(priority),
            "test",
            EntityId(name),
            "work",
        )

    first = service_request("first", 6.0)
    second = service_request("second", 3.0)
    service_supply = {(NODE, "test_service"): 3.0}
    forward_service = allocate_service_capacity(
        (first, second), nominal_supply=service_supply
    )
    reverse_service = allocate_service_capacity(
        (second, first), nominal_supply=service_supply
    )
    assert forward_service.allocated(first.id) == pytest.approx(2.0)
    assert forward_service.allocated(second.id) == pytest.approx(1.0)
    assert reverse_service.allocated(first.id) == pytest.approx(2.0)
    assert reverse_service.allocated(second.id) == pytest.approx(1.0)

    high_service = service_request("high", 3.0, 5)
    low_service = service_request("low", 3.0, 1)
    prioritized_service = allocate_service_capacity(
        (low_service, high_service),
        nominal_supply={(NODE, "test_service"): 4.0},
    )
    assert prioritized_service.allocated(high_service.id) == pytest.approx(3.0)
    assert prioritized_service.allocated(low_service.id) == pytest.approx(1.0)


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
        PoolRequirement("research_points", 1, scope_id="organization"),
    )
    pool_plan = allocate_execution_requirements(
        [shared_pool], {pool_constraint("research_points", "organization"): 4}
    )
    assert pool_plan.allocated(shared_pool.id) == pytest.approx(4)


def test_canonical_tick_routes_domain_requirements_through_common_execution_allocation():
    from space_idle import AdvanceTime, PlanBuild, build_game_application
    from space_idle.content import base_ids as ids

    app = build_game_application()
    sim = app._simulation
    project_id = app.execute(PlanBuild(
        str(ids.EARTH), str(ids.WATER_STORAGE), priority=3,
        procurement_policy="extended_wait",
    )).created_id
    project = next(row for row in sim.projects.projects.values() if str(row.id) == project_id)
    recipe = sim.projects.recipe_for_project(project)
    for requirement in recipe.resources:
        current = sim.inventory.amount(ids.EARTH, requirement.resource_id)
        if current + 1e-9 < requirement.amount_t:
            sim.inventory.add(
                ids.EARTH, requirement.resource_id, requirement.amount_t - current
            )
    app.execute(AdvanceTime(1))

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
    construction_reserved = sim.projects.reserved_resource_t(
        project, ids.STRUCTURAL_COMPONENTS
    )
    sim.inventory.stock[(ids.EARTH, ids.STRUCTURAL_COMPONENTS)] = (
        maintenance_need + construction_reserved
    )

    plan = sim.tick_decision_projection().allocations.execution
    maintenance_rows = tuple(
        row for row in plan.bundles
        if row.owner_kind == "facility_maintenance"
        and row.operational_node_id == ids.EARTH
        and any(key == structural_key for key, _coefficient in row.coefficients())
    )
    industry_rows = tuple(
        row for row in plan.bundles
        if row.owner_kind == "industry_process" and row.operational_node_id == ids.EARTH
    )
    extraction_rows = tuple(
        row for row in plan.bundles
        if row.owner_kind == "extraction" and row.operational_node_id == ids.EARTH
    )
    construction_rows = tuple(
        row for row in plan.bundles
        if row.owner_kind == "construction" and str(row.owner_id) == project_id
    )

    assert maintenance_rows and industry_rows and extraction_rows and construction_rows
    assert all(plan.fulfillment(row.id) == pytest.approx(1.0) for row in maintenance_rows)
    structural_industry = tuple(
        row for row in industry_rows
        if any(key == structural_key for key, _coefficient in row.coefficients())
    )
    assert structural_industry
    assert all(plan.fulfillment(row.id) == pytest.approx(0.0) for row in structural_industry)
    assert plan.used_by_constraint[structural_key] == pytest.approx(maintenance_need)
    assert all(
        any(key.kind == "service" and key.name.startswith("process:") for key, _ in row.coefficients())
        for row in industry_rows
    )
    assert all(
        any(key.kind == "service" and key.name.startswith("extraction:") for key, _ in row.coefficients())
        for row in extraction_rows
    )
    assert all(
        any(key.kind == "service" and key.name == "construction_work" for key, _ in row.coefficients())
        for row in construction_rows
    )
    assert all(
        0.0 <= plan.fulfillment(row.id) <= 1.0
        for row in industry_rows + extraction_rows + construction_rows
    )


def test_multi_pool_admission_uses_one_fraction_and_is_order_independent():
    default_admission = StockOrPoolAdmissionRequirement("default", 10.0)
    cryogenic_admission = StockOrPoolAdmissionRequirement("cryogenic", 6.0)
    multi_pool = bundle(
        "multi_pool",
        1.0,
        default_admission,
        cryogenic_admission,
    )
    concurrent = bundle(
        "concurrent_admission",
        1.0,
        StockOrPoolAdmissionRequirement("default", 2.0),
        priority=5,
    )
    capacities = {
        admission_constraint(NODE, "default"): 8.0,
        admission_constraint(NODE, "cryogenic"): 6.0,
    }

    forward = allocate_execution_requirements((multi_pool, concurrent), capacities)
    reverse = allocate_execution_requirements((concurrent, multi_pool), capacities)
    requirements_reversed = bundle(
        "multi_pool_reversed",
        1.0,
        cryogenic_admission,
        default_admission,
    )
    reversed_requirements = allocate_execution_requirements(
        (requirements_reversed, concurrent), capacities
    )

    assert forward.fulfillment(concurrent.id) == pytest.approx(1.0)
    assert forward.fulfillment(multi_pool.id) == pytest.approx(0.6)
    assert reverse.fulfillment(multi_pool.id) == pytest.approx(0.6)
    assert reversed_requirements.fulfillment(requirements_reversed.id) == pytest.approx(0.6)
    assert forward.used_by_constraint[admission_constraint(NODE, "default")] == pytest.approx(8.0)
    assert forward.used_by_constraint[admission_constraint(NODE, "cryogenic")] == pytest.approx(3.6)


def test_shared_recovery_settlement_applies_allocated_fraction_independent_of_resource_order():
    default_salvage = DefinitionId("test.resource.salvage.default")
    cryogenic_salvage = DefinitionId("test.resource.salvage.cryogenic")
    inventory = InventoryBook(
        {
            default_salvage: ResourceDef(default_salvage, "Default salvage"),
            cryogenic_salvage: ResourceDef(
                cryogenic_salvage,
                "Cryogenic salvage",
                storage_pool_key="cryogenic",
            ),
        }
    )
    inventory.set_capacity_snapshot(
        {
            (NODE, DEFAULT_STORAGE_POOL_KEY): 10.0,
            (NODE, "cryogenic"): 6.0,
        },
        {
            (NODE, DEFAULT_STORAGE_POOL_KEY): 10.0,
            (NODE, "cryogenic"): 6.0,
        },
    )
    potential = ((default_salvage, 10.0), (cryogenic_salvage, 6.0))

    assert salvage_admission_requirements(inventory, potential) == salvage_admission_requirements(
        inventory, reversed(potential)
    )
    recovered = dict(
        settle_salvage_recovery(
            inventory,
            NODE,
            reversed(potential),
            0.6,
        )
    )

    assert recovered == {
        default_salvage: pytest.approx(6.0),
        cryogenic_salvage: pytest.approx(3.6),
    }
    assert inventory.amount(NODE, default_salvage) == pytest.approx(6.0)
    assert inventory.amount(NODE, cryogenic_salvage) == pytest.approx(3.6)
