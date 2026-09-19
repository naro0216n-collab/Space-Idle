from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CreateTransportAllocation,
    GetAttention,
    GetBottlenecks,
    GetBuildOptions,
    GetCargoFlows,
    GetCatalog,
    GetContracts,
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
    GetTargetStockOptions,
    GetWorld,
    PlanBuild,
    ProduceVehicle,
    SetProjectPriority,
    SetProjectProcurementPolicy,
    SetVehicleProductionSettings,
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
from space_idle.spatial import AtmosphereField, GravityField
from space_idle.transport import PoweredAscentCapability, TransportPerformanceProfile, VehicleDef
from space_idle.transport.movement import MovementResolver



def _capacity_command_kwargs(app, vehicle_definition_id, source_id, destination_id, units):
    capacity = app._simulation.transport.transport_capacity_for_units(
        vehicle_definition_id, source_id, destination_id, units, day=app._simulation.day
    )
    return {
        "target_forward_t_per_day": capacity.forward_t_per_day,
        "target_reverse_t_per_day": capacity.reverse_t_per_day,
    }

def test_vehicle_catalog_and_movement_modes_follow_definition_and_capability_contracts():
    app = build_game_application()
    sim = app._simulation
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

    plan = min(
        sim.transport.movement_plan_candidates(ids.EARTH, ids.LEO),
        key=lambda row: str(row.id),
    )
    movement_plan_view = app.query(
        GetMovementPlans(movement_plan_id=str(plan.id), include_modes=True)
    ).items[0]
    lander_mode = next(
        mode
        for mode in movement_plan_view.modes
        if mode.id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert not lander_mode.service_feasible
    assert any("operation:powered_ascent" in blocker for blocker in lander_mode.blockers)

    origin_context = sim.transport.movement_geometry(plan.id).origin.environment_context_id
    gravity = sim.environment.require(origin_context, GravityField).local_acceleration_m_s2
    pressure = sim.environment.require(origin_context, AtmosphereField).pressure_pa
    definition_id = DefinitionId("test.vehicle.integrated_spacecraft")
    sim.transport.vehicle_defs[definition_id] = VehicleDef(
        id=definition_id,
        display_name="統合型試験宇宙船",
        performance=TransportPerformanceProfile(
            dry_mass_t=10.0,
            payload_t=2.0,
            endurance_days=30.0,
            operation_capabilities=(
                PoweredAscentCapability(
                    plan.delta_v_km_s + 1.0, gravity + 1.0, pressure + 1000.0
                ),
            ),
        ),
    )
    sim.transport.add_fleet_units(definition_id, 1, ids.EARTH)
    assert not sim.transport.vehicle_movement_failures(plan.id, definition_id, sim.day)
    mode = next(
        row
        for row in app.query(
            GetMovementPlans(movement_plan_id=str(plan.id), include_modes=True)
        ).items[0].modes
        if row.id == str(definition_id)
    )
    assert mode.fleet_total_units == 1
    assert mode.nominal_capacity.forward_t_per_day > 0


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
        include_modes=False,
    ))

    assert view.items
    assert {row.origin_id for row in view.items} == {str(EARTH)}
    assert {row.destination_id for row in view.items} == {str(LEO)}

def test_application_decision_queries_are_observational_and_reuse_projection_within_query(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    original = sim.tick_decision_projection
    calls = 0

    def counted_projection():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(sim, "tick_decision_projection", counted_projection)
    before = capture_state(sim)

    app.query(GetLogistics())
    assert calls == 1

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
    app = build_game_application()

    bottlenecks = app.query(GetBottlenecks()).items
    attention = app.query(GetAttention()).items

    assert attention
    assert all(row.attention_required for row in attention)
    assert all(row.navigation is not None for row in attention)
    assert len(attention) < len(bottlenecks)

    # Locked future Research is still inspectable through Bottlenecks but does
    # not flood the global Attention surface.
    research_start = next(row for row in bottlenecks if row.source == "research_start")
    assert research_start.attention_required is False
    assert research_start.navigation is not None
    assert research_start.navigation.decision_area == "research"
    assert research_start.navigation.subject_kind == "research"
    assert research_start.navigation.subject_id == research_start.definition_id

    # Active facility/industry constraints lead directly to the affected
    # Location and Facility without the UI parsing the blocker text.
    facility_issue = next(row for row in attention if row.source == "industry")
    assert facility_issue.navigation is not None
    assert facility_issue.navigation.decision_area == "location"
    assert facility_issue.navigation.operational_node_id == facility_issue.operational_node_id
    assert facility_issue.navigation.subject_kind == "facility"
    assert facility_issue.navigation.subject_id == facility_issue.entity_id

    payload = to_jsonable(app.query(GetAttention()))
    assert payload["items"][0]["attention_required"] is True
    assert payload["items"][0]["navigation"]["decision_area"] == "location"

def test_target_stock_options_project_current_state_and_application_owned_presets():
    app = build_game_application()
    destination_id = str(ids.EARTH)
    resource_id = str(ids.STRUCTURAL_COMPONENTS)

    view = app.query(GetTargetStockOptions(destination_id, resource_id))

    assert view.destination_id == destination_id
    assert view.resource_id == resource_id
    assert view.current_stock_t == pytest.approx(
        app._simulation.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    )
    assert view.normal_demand_t_per_day > 0
    assert [preset.days_of_supply for preset in view.presets] == [1.0, 3.0, 7.0]
    for preset in view.presets:
        assert preset.target_quantity_t == pytest.approx(
            view.normal_demand_t_per_day * preset.days_of_supply
        )
    assert view.suggested_max_t >= view.current_stock_t

    app.execute(SetTargetStock(destination_id, resource_id, 5.0, priority=4))
    updated = app.query(GetTargetStockOptions(destination_id, resource_id))
    assert updated.current_target_quantity_t == pytest.approx(5.0)
    assert int(updated.priority) == 4


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

    assert option.suggested_capacity_max.forward_t_per_day >= option.nominal_capacity.forward_t_per_day
    assert option.capacity_presets
    assert any(preset.units == 1 for preset in option.capacity_presets)
    assert all(preset.capacity.forward_t_per_day >= 0 for preset in option.capacity_presets)

    two_unit_capacity = app._simulation.transport.transport_capacity_for_units(
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

    two_unit_capacity = app._simulation.transport.transport_capacity_for_units(
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

    one_unit_capacity = app._simulation.transport.transport_capacity_for_units(
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
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

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


def test_vehicle_production_application_contract_exposes_planning_blockers_and_priority_lifecycle():
    app = build_game_application()
    option = next(
        row
        for row in app.query(GetLogistics()).vehicle_production_options
        if row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
        and row.operational_node_id == str(LEO)
    )
    assert any(blocker.startswith("service:enabled:") for blocker in option.blockers)
    assert option.can_plan is True
    assert app.execute(
        ProduceVehicle(str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(LEO), priority=3)
    ).created_id is not None

    production_id = app.execute(ProduceVehicle(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(EARTH), priority=2,
    )).created_id
    assert production_id is not None

    row = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert row.priority == 2
    assert row.priority_editable is True
    assert row.production_service_type == "vehicle_assembly"
    demands = tuple(
        demand
        for demand in app.query(GetLogistics()).requirements
        if demand.owner_kind == "vehicle_production" and demand.owner_id == production_id
    )
    assert demands and {d.priority for d in demands} == {2}

    app.execute(SetVehicleProductionSettings(production_id, priority=5))
    updated = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert updated.priority == 5

    app.execute(AdvanceTime(1))
    building = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert building.phase == "building"
    assert building.priority_editable is False
    with pytest.raises(
        ApplicationError, match="priority can only change before inputs are consumed"
    ):
        app.execute(SetVehicleProductionSettings(production_id, priority=1))


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
        "scientific_explorations": GetScientificExplorations(), "contracts": GetContracts(),
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
    assert "items" in payload["global_issues"]
    assert "pools" in payload["fleet"]
    assert "items" in payload["transport_allocations"]
    assert "items" in payload["cargo_flows"]


def test_construction_queries_expose_authoritative_project_controls():
    app = build_game_application()
    build_options = app.query(GetBuildOptions(str(EARTH)))
    assert tuple(build_options.procurement_policy_options) == app._simulation.projects.procurement_policy_options()

    project_id = app.execute(PlanBuild(
        str(EARTH), str(ids.SURFACE_POWER_GRID), priority=2,
        procurement_policy="immediate",
        site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
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
