from __future__ import annotations

from stock_support import service_target_for_test_units, add_preexisting_stock

import pytest
from unittest.mock import patch

from space_idle import (
    AdvanceTime,
    CreateTransportAllocation,
    GetAttention,
    GetBottlenecks,
    GetBuildOptions,
    GetCargoFlows,
    GetCatalog,
    GetDependencyAnalytics,
    GetFleet,
    GetFleetRelocationPreview,
    GetFlowReport,
    GetOperationalNode,
    GetLogistics,
    GetLogisticsSummary,
    GetProjects,
    GetResearch,
    GetMovementPlans,
    GetScientificExplorations,
    GetSurveys,
    GetTransportAllocations,
    GetTransportAllocationOptions,
    GetTransportAllocationPreview,
    GetTargetStockContext,
    GetWorld,
    PlanBuild,
    SetProjectPriority,
    SetProjectProcurementPolicy,
    UpdateTransportAllocation,
    SetTransportMovementConstraint, ClearTransportMovementConstraint,
    RelocateFleet,
    SetSupplyRoutingConstraint, ClearSupplyRoutingConstraint,
    SetTargetStock, DeleteTargetStock,
    build_game_application,
)
from space_idle.simulation import OfflineProgressPolicy
from space_idle.persistence import capture_state
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import GameRuntime
from space_idle.api.codec import to_jsonable
from space_idle.content.base_game import EARTH, LEO
from space_idle.content import base_ids as ids
from space_idle.shared import DefinitionId
from space_idle.transport import TransportPerformanceProfile, VehicleDef
from space_idle.transport.movement import MovementResolver



def _capacity_command_kwargs(app, vehicle_definition_id, source_id, destination_id, units):
    capacity = service_target_for_test_units(
        app._simulation.transport,
        vehicle_definition_id, source_id, destination_id, units, day=app._simulation.day
    )
    return {
        "target_forward_t_per_day": capacity.forward_t_per_day,
        "target_reverse_t_per_day": capacity.reverse_t_per_day,
    }

def test_vehicle_catalog_and_movement_modes_follow_definition_and_capability_contracts():
    app = build_game_application()
    catalog = app.query(GetCatalog())
    fleet = app.query(GetFleet())
    movement_plans = app.query(GetMovementPlans(include_modes=True))

    definitions = {row.id: row for row in catalog.vehicles}
    assert definitions
    assert all(pool.vehicle_definition_id in definitions for pool in fleet.pools)
    for movement_plan in movement_plans.items:
        for mode in movement_plan.modes:
            if mode.vehicle_definition_id is not None:
                assert mode.vehicle_definition_id in definitions

    # Physics and per-operation limits are Domain-owned. The Application
    # obligation here is referential integrity and explaining unusable modes.
    assert all(
        mode.service_feasible or mode.blockers
        for plan in movement_plans.items for mode in plan.modes
    )


def test_movement_plan_projection_reuses_derived_state_and_scoped_queries_avoid_global_enumeration(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    original = MovementResolver.all_direct_plans
    calls = 0

    def counted_all_direct_plans(resolver):
        nonlocal calls
        calls += 1
        return original(resolver)

    monkeypatch.setattr(MovementResolver, "all_direct_plans", counted_all_direct_plans)
    sim.transport.invalidate_movement_plans()

    plans = sim.transport.movement_plan_options()
    assert plans
    assert calls == 1
    for plan in plans:
        assert sim.transport.movement_plan(plan.id) is not None
    app.query(GetMovementPlans(include_modes=True))
    assert calls == 1

    app.execute(AdvanceTime(1))
    app.query(GetMovementPlans(include_modes=True))
    assert calls == 1

    sim.transport.invalidate_movement_plans()
    sim.transport.movement_plan_options()
    assert calls == 2

    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
        str(ids.LEO),
        str(ids.LUNAR_ORBIT),
        **_capacity_command_kwargs(
            app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT, 1
        ),
    )).created_id
    assert allocation_id is not None
    allocation_entity_id = next(
        row_id for row_id in sim.transport.transport_allocations
        if str(row_id) == allocation_id
    )
    with sim.transport.derived_projection_scope():
        service_plan = sim.transport.derive_transport_service_plan(
            allocation_entity_id, sim.day
        )
        assert sim.transport.derive_transport_service_plan(
            allocation_entity_id, sim.day
        ) is service_plan
        supplies = sim.transport.transport_service_supplies(sim.day)
        assert sim.transport.transport_service_supplies(sim.day) is supplies
        dependencies = sim.transport.transport_operation_dependencies(sim.day)
        assert sim.transport.transport_operation_dependencies(sim.day) is dependencies

    sim.transport.invalidate_movement_plans()

    def reject_global_enumeration(_resolver):
        raise AssertionError("scoped Movement query must not enumerate every OD pair")

    monkeypatch.setattr(MovementResolver, "all_direct_plans", reject_global_enumeration)
    view = app.query(GetMovementPlans(
        origin_id=str(EARTH),
        destination_id=str(LEO),
        vehicle_definition_id=str(ids.REUSABLE_LAUNCH_VEHICLE),
        include_modes=True,
    ))

    assert view.items
    assert {row.origin_id for row in view.items} == {str(EARTH)}
    assert {row.destination_id for row in view.items} == {str(LEO)}
    for row in view.items:
        assert row.comparison_key == row.id
        value_keys = {value.axis_key for value in row.comparison_values}
        assert {
            "transit_days",
            "delta_v_km_s",
            "service_feasible",
            "cycle_days",
            "nominal_forward_t_per_day",
            "full_load_propellant_t",
        } <= value_keys

    # Node-neighbourhood and OD views share the scoped Movement contract.
    touching = app.query(GetMovementPlans(
        touching_node_id=str(EARTH), include_modes=True,
    )).items
    assert touching
    assert all(str(EARTH) in (row.origin_id, row.destination_id) for row in touching)
    assert len({row.id for row in touching}) == len(touching)

def test_application_decision_queries_are_observational_and_reuse_projection_within_query(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    original = sim.tick_decision_projection
    original_dependencies = sim.service_capacity_dependencies
    calls = 0
    dependency_derivations = 0

    def counted_dependencies():
        nonlocal dependency_derivations
        dependency_derivations += 1
        return original_dependencies()

    monkeypatch.setattr(sim, "service_capacity_dependencies", counted_dependencies)

    def counted_projection():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(sim, "tick_decision_projection", counted_projection)
    before = capture_state(sim)

    app.query(GetLogistics())
    assert calls == 1
    # Maintenance/transport feedback must not rebuild the invariant provider
    # dependency graph for every allocation attempt within the same query.
    assert dependency_derivations == 1

    for query in (
        GetWorld(),
        GetMovementPlans(include_modes=True),
        GetFleet(),
        GetTransportAllocations(),
        GetTransportAllocationOptions(str(ids.LEO), str(ids.LUNAR_ORBIT)),
        GetTransportAllocationPreview(
            vehicle_definition_id=str(ids.REUSABLE_LAUNCH_VEHICLE),
            source_id=str(ids.EARTH),
            destination_id=str(ids.LEO),
            target_forward_t_per_day=0.0,
            target_reverse_t_per_day=0.0,
        ),
        GetScientificExplorations(),
        GetResearch(),
        GetBottlenecks(),
        GetAttention(),
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)),
    ):
        app.query(query)

    assert capture_state(sim) == before




def test_global_attention_filters_diagnostic_blockers_and_exposes_decision_context():
    """Attention selects actionable issues without encoding a particular opening Content state."""
    app = build_game_application()
    bottlenecks = app.query(GetBottlenecks()).items
    attention = app.query(GetAttention()).items

    assert attention == tuple(issue for issue in bottlenecks if issue.attention_required)
    assert all(issue.navigation is not None and issue.navigation.decision_area
               for issue in attention)
    for issue in attention:
        if issue.source == "industry":
            assert issue.navigation.decision_area == "location"
            assert issue.navigation.operational_node_id == issue.operational_node_id
            assert issue.navigation.subject_kind == "facility"
            assert issue.navigation.subject_id == issue.entity_id
    assert to_jsonable(app.query(GetAttention()))["items"] == [
        to_jsonable(issue) for issue in attention
    ]


def test_target_stock_context_exposes_physical_quantities_without_picking_a_reserve_strategy():
    app = build_game_application()
    destination_id = str(ids.EARTH)
    resource_id = str(ids.STRUCTURAL_COMPONENTS)

    view = app.query(GetTargetStockContext(destination_id, resource_id))

    assert view.destination_id == destination_id
    assert view.resource_id == resource_id
    assert view.current_stock_t == pytest.approx(
        app._simulation.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    )
    assert view.normal_demand_t_per_day > 0
    assert view.current_target_quantity_t == 0.0
    stock_before = app._simulation.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    normal_demand_before = view.normal_demand_t_per_day
    inbound_before = view.inbound_t

    app.execute(SetTargetStock(destination_id, resource_id, 5.0, priority=4))
    updated = app.query(GetTargetStockContext(destination_id, resource_id))
    assert updated.current_target_quantity_t == pytest.approx(5.0)
    assert int(updated.priority) == 4
    assert updated.current_stock_t == pytest.approx(stock_before)
    assert updated.normal_demand_t_per_day == pytest.approx(normal_demand_before)
    assert updated.inbound_t == pytest.approx(inbound_before)
    # Additional reserve is a planning intent, not a stock reservation or a
    # second source of ordinary recurring demand.
    assert app._simulation.inventory.available(ids.EARTH, ids.STRUCTURAL_COMPONENTS) == pytest.approx(stock_before)


def test_transport_allocation_projection_exposes_capacity_target_and_canonical_plan_requirements():
    app = build_game_application()
    option = next(
        row
        for row in app.query(GetTransportAllocationOptions(str(EARTH), str(LEO))).options
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
    )
    requirements = {
        (row.operational_node_id, row.capability_id, row.required_state)
        for row in option.infrastructure_requirements
    }
    assert (str(EARTH), "launch_operations", "ACTIVE") in requirements
    assert (str(EARTH), "vehicle_refueling", "ACTIVE") in requirements
    assert any(
        location_id == str(EARTH)
        and resource_id == str(ids.PROPELLANT)
        and amount > 0
        for location_id, resource_id, amount
        in option.operational_supply_at_full_unit
    )

    assert option.nominal_capacity.forward_t_per_day > 0
    assert option.fleet_free_units <= option.fleet_total_units
    assert option.fleet_total_units >= 0

    two_unit_capacity = service_target_for_test_units(
        app._simulation.transport,
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=app._simulation.day
    )
    preview = app.query(GetTransportAllocationPreview(
        vehicle_definition_id=str(ids.REUSABLE_LAUNCH_VEHICLE),
        source_id=str(EARTH),
        destination_id=str(LEO),
        target_forward_t_per_day=two_unit_capacity.forward_t_per_day,
        target_reverse_t_per_day=two_unit_capacity.reverse_t_per_day,
    ))
    assert preview.required_units == 2
    assert preview.target_capacity.forward_t_per_day == pytest.approx(two_unit_capacity.forward_t_per_day)
    assert preview.selected_forward_path == option.forward_path
    assert preview.achievable_capacity.forward_t_per_day <= preview.target_capacity.forward_t_per_day
    assert preview.available_units >= 0

    two_unit_capacity = service_target_for_test_units(
        app._simulation.transport,
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 2, day=app._simulation.day
    )
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
        provisioning_priority=4,
        target_forward_t_per_day=two_unit_capacity.forward_t_per_day,
        target_reverse_t_per_day=two_unit_capacity.reverse_t_per_day,
    )).created_id
    assert allocation_id is not None

    row = next(item for item in app.query(GetTransportAllocations()).items if item.id == allocation_id)
    assert row.target_capacity.forward_t_per_day == pytest.approx(two_unit_capacity.forward_t_per_day)
    assert row.target_capacity.reverse_t_per_day == pytest.approx(two_unit_capacity.reverse_t_per_day)
    assert row.required_units == 2
    assert row.active_units + row.unfilled_units == row.required_units
    assert row.movement_hard_constraint is None
    assert row.selected_forward_path == option.forward_path
    assert row.nominal.forward_t_per_day > 0
    assert row.available.forward_t_per_day <= row.nominal.forward_t_per_day
    assert row.spare.forward_t_per_day == pytest.approx(
        row.available.forward_t_per_day - row.used.forward_t_per_day
    )
    assert row.infrastructure_requirements == option.infrastructure_requirements

    app.execute(SetTransportMovementConstraint(allocation_id, option.forward_path))
    constrained = next(
        item for item in app.query(GetTransportAllocations()).items
        if item.id == allocation_id
    )
    assert constrained.movement_hard_constraint == option.forward_path
    assert constrained.selected_forward_path == option.forward_path

    one_unit_capacity = service_target_for_test_units(
        app._simulation.transport,
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 1,
        day=app._simulation.day,
        movement_hard_constraint=tuple(
            app._simulation.transport.require_movement_plan(value).id
            for value in option.forward_path
        ),
    )
    app.execute(UpdateTransportAllocation(
        allocation_id, provisioning_priority=5,
        target_forward_t_per_day=one_unit_capacity.forward_t_per_day,
        target_reverse_t_per_day=one_unit_capacity.reverse_t_per_day,
    ))
    updated = next(
        item for item in app.query(GetTransportAllocations()).items
        if item.id == allocation_id
    )
    assert updated.provisioning_priority == 5
    assert updated.required_units == 1
    assert updated.active_units + updated.unfilled_units == updated.required_units

    app.execute(ClearTransportMovementConstraint(allocation_id))
    cleared = next(item for item in app.query(GetTransportAllocations()).items if item.id == allocation_id)
    assert cleared.movement_hard_constraint is None

def test_fleet_relocation_preview_exposes_the_same_plan_used_by_command():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    sim.transport.fleet_pool(vehicle_id, ids.LEO).total_units = 1
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    add_preexisting_stock(sim, ids.LEO, ids.PROPELLANT, 100.0)
    add_preexisting_stock(sim, ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

    auto_preview = app.query(GetFleetRelocationPreview(
        str(vehicle_id), 1, str(ids.LEO), str(ids.LUNAR_ORBIT)
    ))
    assert auto_preview.feasible
    assert auto_preview.path
    preview = app.query(GetFleetRelocationPreview(
        str(vehicle_id), 1, str(ids.LEO), str(ids.LUNAR_ORBIT), auto_preview.path
    ))
    assert preview.feasible
    assert preview.path == auto_preview.path
    assert preview.movement_hard_constraint == auto_preview.path
    assert preview.arrival_day == sim.day + preview.travel_days
    assert any(
        row.capability_id == "vehicle_refueling"
        for row in preview.infrastructure_requirements
    )
    assert any(
        row.resource_id == str(ids.PROPELLANT) and row.required_t > 0
        for row in preview.resource_requirements
    )

    relocation_id = app.execute(RelocateFleet(
        str(vehicle_id), 1, str(ids.LEO), str(ids.LUNAR_ORBIT),
        movement_hard_constraint=auto_preview.path,
    )).created_id
    relocation = next(row for row in app.query(GetFleet()).relocations if row.id == relocation_id)
    assert relocation.departure_day is None
    assert relocation.arrival_day is None

    sim.advance_days(1)
    relocation = next(row for row in app.query(GetFleet()).relocations if row.id == relocation_id)
    assert relocation.departure_day == 0
    assert relocation.arrival_day == preview.arrival_day

def test_supply_routing_constraint_and_target_stock_update_planning_intent_without_transport_reprovisioning():
    app = build_game_application()
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
        target_forward_t_per_day=1.0,
        target_reverse_t_per_day=0.0, provisioning_priority=4,
    )).created_id
    assert allocation_id is not None

    before_allocations = app.query(GetTransportAllocations()).items
    before_allocation = next(row for row in before_allocations if row.id == allocation_id)
    before_pool = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.operational_node_id == str(EARTH)
    )

    target_id = app.execute(SetTargetStock(
        str(LEO), str(ids.MACHINERY), 3.5, priority=4,
    )).created_id
    assert target_id is not None
    app.execute(SetSupplyRoutingConstraint(
        destination_id=str(LEO), owner_kind="target_stock", owner_id=target_id,
        resource_id=str(ids.MACHINERY), source_node_id=str(EARTH),
        required_transport_allocation_ids=(allocation_id,),
    ))

    view = app.query(GetLogistics())
    constraint = next(row for row in view.routing_constraints if row.owner_id == target_id)
    target = next(row for row in view.target_stocks if row.id == target_id)
    requirement = next(
        row for row in view.requirements
        if row.owner_kind == "target_stock" and row.owner_id == target_id
    )
    after_allocations = app.query(GetTransportAllocations()).items
    after_allocation = next(row for row in after_allocations if row.id == allocation_id)
    after_pool = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.operational_node_id == str(EARTH)
    )

    assert constraint.source_node_id == str(EARTH)
    assert constraint.required_transport_allocation_ids == (allocation_id,)
    assert requirement.routing_constraint_source_id == str(EARTH)
    assert requirement.routing_constraint_transport_allocation_ids == (allocation_id,)
    assert target.target_quantity_t == 3.5
    assert target.priority == 4
    assert requirement.priority == 4
    assert requirement.forecast_requirement_day == app.query(GetWorld()).day
    assert {row.id for row in after_allocations} == {row.id for row in before_allocations}
    assert after_allocation.target_capacity == before_allocation.target_capacity
    assert after_allocation.required_units == before_allocation.required_units
    assert after_allocation.active_units == before_allocation.active_units
    assert after_pool.transport_units == before_pool.transport_units
    assert after_pool.free_units == before_pool.free_units

    app.execute(ClearSupplyRoutingConstraint(
        destination_id=str(LEO), owner_kind="target_stock", owner_id=target_id,
        resource_id=str(ids.MACHINERY),
    ))
    app.execute(DeleteTargetStock(str(LEO), str(ids.MACHINERY)))
    cleared = app.query(GetLogistics())
    assert not cleared.routing_constraints
    assert not cleared.target_stocks



def test_ui_snapshot_is_json_safe_and_clock_consistent_at_application_boundary(tmp_path):
    now = [0.0]
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=tmp_path,
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
        clock=lambda: now[0],
    )
    location_id = runtime.query(GetWorld()).data.operational_nodes[0].id
    now[0] = 3.2
    queries = {
        "world": GetWorld(), "global_issues": GetAttention(), "research": GetResearch(),
        "scientific_explorations": GetScientificExplorations(), 
        "logistics_summary": GetLogisticsSummary(), "logistics": GetLogistics(),
        "movement_plans": GetMovementPlans(include_modes=True), "fleet": GetFleet(),
        "transport_allocations": GetTransportAllocations(), "cargo_flows": GetCargoFlows(),
"operational_node": GetOperationalNode(location_id),
        "flow": GetFlowReport(location_id), "projects": GetProjects(location_id),
        "build_options": GetBuildOptions(location_id), "bottlenecks": GetBottlenecks(location_id),
        "surveys": GetSurveys(location_id),
    }
    result = runtime.snapshot(queries)
    payload = to_jsonable(result.data)
    assert payload["session"]["day"] == payload["world"]["day"] == 3
    assert payload["operational_node"]["id"] == location_id


def test_logistics_projections_share_scoped_derivations_without_changing_read_contracts():
    app = build_game_application()
    sim = app._simulation
    # A logistics-only read does not need to generate unrelated Movement modes.
    with patch.object(app, "_movement_plan_rows", side_effect=AssertionError(
        "logistics summary/details must not expand Movement candidates",
    )):
        logistics_only = app.query_many({
            "logistics": GetLogistics(), "summary": GetLogisticsSummary(),
        })
    assert logistics_only["logistics"].fleet_pools
    assert logistics_only["summary"].fleet_units >= 0

    # The batched view must match individually requested decisions. Do not
    # specify an internal helper's exact invocation count or module location;
    # scoped, non-expanding requests are checked above and in the Movement suite.
    batched = app.query_many({
        "summary": GetLogisticsSummary(),
        "logistics": GetLogistics(),
        "movement": GetMovementPlans(include_modes=True),
        "fleet": GetFleet(),
        "allocations": GetTransportAllocations(),
        "cargo": GetCargoFlows(),
    })
    assert batched["logistics"] == app.query(GetLogistics())
    assert batched["movement"] == app.query(GetMovementPlans(include_modes=True))
    assert batched["fleet"] == app.query(GetFleet())
    assert batched["allocations"] == app.query(GetTransportAllocations())
    assert batched["cargo"] == app.query(GetCargoFlows())

    # The cache belongs to one query snapshot, not the authoritative state.
    app.execute(AdvanceTime(1))
    assert app.query(GetLogisticsSummary()) == app.query_many({"summary": GetLogisticsSummary()})["summary"]


def test_construction_queries_expose_authoritative_project_controls():
    app = build_game_application()
    build_options = app.query(GetBuildOptions(str(EARTH)))
    assert tuple(build_options.procurement_policy_options) == app._simulation.projects.procurement_policy_options()

    project_id = app.execute(PlanBuild(
        str(EARTH), str(ids.CONSTRUCTION_YARD), priority=2,
        procurement_policy="immediate",
    )).created_id
    assert project_id is not None
    row = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert row.settings_editable and row.procurement_editable
    assert row.projected_material_readiness_day == app.query(GetWorld()).day

    requirement = next(
        item for item in app.query(GetLogistics()).requirements
        if item.owner_kind == "project" and item.owner_id == project_id
    )
    app.execute(SetSupplyRoutingConstraint(
        destination_id=requirement.destination_id, owner_kind="project", owner_id=project_id,
        resource_id=requirement.resource_id, source_node_id=str(LEO),
    ))
    constrained = next(
        item for item in app.query(GetLogistics()).requirements
        if item.id == requirement.id
    )
    assert constrained.routing_constraint_source_id == str(LEO)

    app.execute(SetProjectPriority(project_id, 5))
    app.execute(SetProjectProcurementPolicy(project_id, "extended_wait"))
    updated = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert (updated.priority, updated.procurement_policy) == (5, "extended_wait")


def test_survey_service_catalog_uses_physical_source_names_for_new_content():
    app = build_game_application()
    sim = app._simulation
    assert sim.survey is not None

    catalog = app.query(GetCatalog())
    projected = {row.id: row.display_name for row in catalog.service_capacities}
    assert set(projected) == set(sim.survey.service_capacity_types())
    assert all("survey_observation:" not in name for name in projected.values())
    assert all(name for name in projected.values())

    source_id = DefinitionId("test.vehicle.survey_platform")
    sim.transport.vehicle_defs[source_id] = VehicleDef(
        id=source_id,
        display_name="追加観測プラットフォーム",
        performance=TransportPerformanceProfile(
            dry_mass_t=2.0, payload_t=0.0,
            generic_capabilities=("survey_sensor",),
        ),
    )
    expanded = {row.id: row.display_name for row in app.query(GetCatalog()).service_capacities}
    compatible_providers = (
        provider for provider in sim.survey.providers.values()
        if provider.source_kind.value == "fleet"
        and provider.required_source_capabilities <= {"survey_sensor"}
    )
    service_ids = {
        sim.survey.service_type_for_provider(provider.id, source_id)
        for provider in compatible_providers
    }
    assert service_ids
    assert set(expanded) - set(projected) == service_ids
    assert all(sim.transport.vehicle_defs[source_id].display_name in expanded[service_id]
               for service_id in service_ids)
    assert all(expanded[key] == name for key, name in projected.items())
