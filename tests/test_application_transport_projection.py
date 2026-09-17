from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CreateTransportAllocation,
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
    GetWorld,
    PlanBuild,
    ProduceVehicle,
    SetProjectPriority,
    SetProjectSourcingPolicy,
    SetVehicleProductionSettings,
    UpdateTransportAllocation,
    RelocateFleet,
    CreateLogisticsPolicy, AssignLogisticsPolicy, UnassignLogisticsPolicy,
    DeleteLogisticsPolicy, SetTargetStock, DeleteTargetStock,
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


def test_movement_plan_derived_index_is_reused_until_physical_invalidation(monkeypatch):
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


def test_scoped_movement_query_does_not_expand_to_all_operational_node_pairs(monkeypatch):
    app = build_game_application()
    sim = app._simulation
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


def test_single_application_query_reuses_tick_decision_projection(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    original = sim.tick_decision_projection
    calls = 0

    def counted_projection():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(sim, "tick_decision_projection", counted_projection)
    app.query(GetLogistics())
    assert calls == 1


def test_application_decision_queries_are_observational():
    app = build_game_application()
    sim = app._simulation
    before = capture_state(sim)

    for query in (
        GetWorld(),
        GetMovementPlans(include_modes=True),
        GetFleet(),
        GetTransportAllocations(),
        GetTransportAllocationOptions(str(ids.LEO), str(ids.LUNAR_ORBIT)),
        GetLogistics(),
        GetScientificExplorations(),
        GetResearch(),
        GetBottlenecks(),
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)),
    ):
        app.query(query)

    assert capture_state(sim) == before


def test_transport_allocation_projection_exposes_target_capacity_policy_and_plan_requirements():
    app = build_game_application()
    option = next(
        row
        for row in app.query(GetTransportAllocationOptions(str(EARTH), str(LEO))).options
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
        and row.policy == "fastest"
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

    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
        provisioning_priority=4, control_mode="units", target_units=2,
        path_policy="fastest",
    )).created_id
    assert allocation_id is not None

    row = next(item for item in app.query(GetTransportAllocations()).items if item.id == allocation_id)
    assert row.control_mode == "units"
    assert row.target_units == 2
    assert row.target_capacity is None
    assert row.required_units == row.target_units
    assert row.active_units + row.unfilled_units == row.required_units
    assert row.nominal.forward_t_per_day > 0
    assert row.available.forward_t_per_day <= row.nominal.forward_t_per_day
    assert row.spare.forward_t_per_day == pytest.approx(
        row.available.forward_t_per_day - row.used.forward_t_per_day
    )
    assert row.infrastructure_requirements == option.infrastructure_requirements

    app.execute(UpdateTransportAllocation(
        allocation_id, provisioning_priority=5, target_units=1,
        path_policy="lowest_propellant",
    ))
    updated = next(
        item for item in app.query(GetTransportAllocations()).items
        if item.id == allocation_id
    )
    assert updated.provisioning_priority == 5
    assert updated.path_policy == "lowest_propellant"
    assert updated.target_units == 1
    assert updated.required_units == updated.target_units
    assert updated.active_units + updated.unfilled_units == updated.required_units

def test_fleet_relocation_preview_exposes_the_same_plan_used_by_command():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    sim.transport.fleet_pool(vehicle_id, ids.LEO).total_units = 1
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)

    preview = app.query(GetFleetRelocationPreview(
        str(vehicle_id), 1, str(ids.LEO), str(ids.LUNAR_ORBIT), "fastest"
    ))
    assert preview.feasible
    assert preview.path
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
        str(vehicle_id), 1, str(ids.LEO), str(ids.LUNAR_ORBIT), path_policy="fastest"
    )).created_id
    relocation = next(row for row in app.query(GetFleet()).relocations if row.id == relocation_id)
    assert relocation.departure_day is None
    assert relocation.arrival_day is None

    sim.advance_days(1)
    relocation = next(row for row in app.query(GetFleet()).relocations if row.id == relocation_id)
    assert relocation.departure_day == 0
    assert relocation.arrival_day == preview.arrival_day


def test_supply_policy_and_target_stock_update_planning_intent_without_transport_reprovisioning():
    app = build_game_application()
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
        control_mode="capacity", target_forward_t_per_day=1.0,
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

    policy_id = "logistics.policy.application"
    app.execute(CreateLogisticsPolicy(
        policy_id, source_mode="preferred", preferred_source_id=str(EARTH),
        path_mode="preferred", path_preference="lowest_propellant",
    ))
    target_id = app.execute(SetTargetStock(
        str(LEO), str(ids.MACHINERY), 3.5, priority=4,
    )).created_id
    assert target_id is not None
    app.execute(AssignLogisticsPolicy("target_stock", target_id, policy_id))

    view = app.query(GetLogistics())
    policy = next(row for row in view.logistics_policies if row.id == policy_id)
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

    assert policy.preferred_source_id == str(EARTH)
    assert policy.source_mode == "preferred"
    assert policy.path_preference == "lowest_propellant"
    assert requirement.assigned_policy_id == policy_id
    assert requirement.resolved_policy_id == policy_id
    assert requirement.preferred_source_id == str(EARTH)
    assert requirement.path_preference == "lowest_propellant"
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

    with pytest.raises(ApplicationError):
        app.execute(DeleteLogisticsPolicy(policy_id))
    app.execute(UnassignLogisticsPolicy("target_stock", target_id))
    app.execute(DeleteLogisticsPolicy(policy_id))
    app.execute(DeleteTargetStock(str(LEO), str(ids.MACHINERY)))
    cleared = app.query(GetLogistics())
    assert all(row.id != policy_id for row in cleared.logistics_policies)
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
        "world": GetWorld(), "global_issues": GetBottlenecks(), "research": GetResearch(),
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
    assert "pools" in payload["fleet"]
    assert "items" in payload["transport_allocations"]
    assert "items" in payload["cargo_flows"]


def test_construction_command_rejects_unknown_logistics_policy_before_creating_project():
    app = build_game_application()
    before = tuple(row.id for row in app.query(GetProjects(str(EARTH))).items)

    with pytest.raises(ApplicationError):
        app.execute(PlanBuild(
            str(EARTH),
            str(ids.SURFACE_POWER_GRID),
            logistics_policy_id="logistics.policy.missing",
            site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
        ))

    after = tuple(row.id for row in app.query(GetProjects(str(EARTH))).items)
    assert after == before


def test_construction_queries_expose_authoritative_project_controls():
    app = build_game_application()
    build_options = app.query(GetBuildOptions(str(EARTH)))
    assert tuple(build_options.sourcing_policy_options) == app._simulation.projects.sourcing_policy_options()
    assert str(app._simulation.logistics.global_policy_id) in build_options.logistics_policy_options
    policy_id = "logistics.policy.project-query"
    app.execute(CreateLogisticsPolicy(
        policy_id, source_mode="pinned", allowed_source_ids=(str(LEO),),
    ))

    project_id = app.execute(PlanBuild(
        str(EARTH), str(ids.SURFACE_POWER_GRID), priority=2,
        sourcing_policy="local_priority", logistics_policy_id=policy_id,
        site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
    )).created_id
    assert project_id is not None
    row = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert row.settings_editable and row.sourcing_editable
    assert row.projected_material_readiness_day is None
    assert row.logistics_policy_id == policy_id
    assert row.resolved_logistics_policy_id == policy_id
    app.execute(SetProjectPriority(project_id, 5))
    app.execute(SetProjectSourcingPolicy(project_id, "import_now"))
    app.execute(UnassignLogisticsPolicy("project", project_id))
    updated = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert (updated.priority, updated.sourcing_policy, updated.logistics_policy_id) == (5, "import_now", None)
    assert updated.resolved_logistics_policy_id == str(app._simulation.logistics.global_policy_id)
    assert updated.projected_material_readiness_day == app.query(GetWorld()).day
