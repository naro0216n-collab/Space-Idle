from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CreateLogisticsLane,
    CreateTransportAllocation,
    GetBottlenecks,
    GetBuildOptions,
    GetCargoFlows,
    GetCatalog,
    GetContracts,
    GetFleet,
    GetFlowReport,
    GetLocation,
    GetLogistics,
    GetLogisticsLanes,
    GetLogisticsSummary,
    GetProjects,
    GetResearch,
    GetRoutes,
    GetScientificExplorations,
    GetSurveys,
    GetTransportAllocations,
    GetWorld,
    PauseLogisticsLane,
    PlanBuild,
    ProduceVehicle,
    SetConstructionWeight,
    SetProjectImportSource,
    SetProjectPriority,
    SetProjectSourcingPolicy,
    SetVehicleProductionSettings,
    UpdateLogisticsLane,
    UpdateTransportAllocation,
    RelocateFleet,
    build_game_application,
)
from space_idle.api import GameRuntime
from space_idle.api.codec import to_jsonable
from space_idle.content.base_game import EARTH, LEO
from space_idle.content import base_ids as ids


def test_vehicle_definition_identity_is_consistent_across_catalog_fleet_and_route_modes():
    app = build_game_application()
    catalog = app.query(GetCatalog())
    fleet = app.query(GetFleet())
    routes = app.query(GetRoutes(include_modes=True))

    definitions = {row.id: row for row in catalog.vehicles}
    assert definitions
    assert all(pool.vehicle_definition_id in definitions for pool in fleet.pools)
    for route in routes.items:
        for mode in route.modes:
            if mode.vehicle_definition_id is not None:
                assert mode.vehicle_definition_id in definitions


def test_transport_allocation_projection_exposes_target_fulfillment_and_derived_capacity():
    app = build_game_application()
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
        priority=70, control_mode="units", target_units=2,
    )).created_id
    assert allocation_id is not None

    row = next(item for item in app.query(GetTransportAllocations()).items if item.id == allocation_id)
    assert row.control_mode == "units"
    assert row.target_units == 2
    assert row.target_capacity is None
    assert row.required_units == 2
    assert row.active_units == 1
    assert row.unfilled_units == 1
    assert row.nominal.forward_t_per_day > 0
    assert row.available.forward_t_per_day <= row.nominal.forward_t_per_day
    assert row.spare.forward_t_per_day == pytest.approx(
        row.available.forward_t_per_day - row.used.forward_t_per_day
    )


def test_transport_allocation_priority_and_routing_policy_update_through_application():
    app = build_game_application()
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(LEO), str(ids.LUNAR_ORBIT),
        priority=30, control_mode="units", target_units=1, path_policy="fastest",
    )).created_id
    assert allocation_id is not None

    app.execute(UpdateTransportAllocation(
        allocation_id, priority=85, target_units=1, path_policy="lowest_propellant"
    ))
    row = next(item for item in app.query(GetTransportAllocations()).items if item.id == allocation_id)
    assert row.priority == 85
    assert row.path_policy == "lowest_propellant"
    assert row.target_units == 1


def test_lane_capacity_and_priority_can_be_updated_without_replacing_lane():
    app = build_game_application()
    lane_id = app.execute(CreateLogisticsLane(str(EARTH), str(LEO), 1.0, priority=40)).created_id
    assert lane_id is not None
    app.execute(PauseLogisticsLane(lane_id))

    before = next(row for row in app.query(GetLogisticsLanes()).items if row.id == lane_id)
    app.execute(UpdateLogisticsLane(lane_id, 3.5, priority=80))
    after = next(row for row in app.query(GetLogisticsLanes()).items if row.id == lane_id)

    assert after.id == before.id
    assert after.source_id == before.source_id
    assert after.destination_id == before.destination_id
    assert after.path == before.path
    assert after.path_policy == before.path_policy
    assert after.paused is True
    assert after.requested_capacity_t_per_day == 3.5
    assert after.priority == 80


def test_vehicle_production_exposes_resource_priority_and_capability_allocation_controls():
    app = build_game_application()
    production_id = app.execute(ProduceVehicle(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(EARTH), priority=37, allocation_weight=2.5,
    )).created_id
    assert production_id is not None

    row = next(item for item in app.query(GetLogistics()).vehicle_production if item.id == production_id)
    assert row.priority == 37
    assert row.allocation_weight == pytest.approx(2.5)
    assert row.priority_editable is True
    assert row.allocation_editable is True
    demands = tuple(d for d in app.query(GetLogistics()).demands if d.owner_kind == "vehicle_production" and d.owner_id == production_id)
    assert demands and {d.priority for d in demands} == {37}

    app.execute(SetVehicleProductionSettings(production_id, priority=81, allocation_weight=3.0))
    updated = next(item for item in app.query(GetLogistics()).vehicle_production if item.id == production_id)
    assert updated.priority == 81
    assert updated.allocation_weight == pytest.approx(3.0)

    app.execute(AdvanceTime(1))
    building = next(item for item in app.query(GetLogistics()).vehicle_production if item.id == production_id)
    assert building.phase == "building"
    assert building.priority_editable is False
    with pytest.raises(ApplicationError, match="priority can only change before inputs are consumed"):
        app.execute(SetVehicleProductionSettings(production_id, priority=10))
    app.execute(SetVehicleProductionSettings(production_id, allocation_weight=1.25))


def test_ui_snapshot_is_json_safe_at_application_boundary(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
    location_id = runtime.query(GetWorld()).data.locations[0].id
    queries = {
        "world": GetWorld(), "global_issues": GetBottlenecks(), "research": GetResearch(),
        "scientific_explorations": GetScientificExplorations(), "contracts": GetContracts(),
        "logistics_summary": GetLogisticsSummary(), "logistics": GetLogistics(),
        "routes": GetRoutes(include_modes=True), "fleet": GetFleet(),
        "transport_allocations": GetTransportAllocations(), "cargo_flows": GetCargoFlows(),
        "lanes": GetLogisticsLanes(), "location": GetLocation(location_id),
        "flow": GetFlowReport(location_id), "projects": GetProjects(location_id),
        "build_options": GetBuildOptions(location_id), "bottlenecks": GetBottlenecks(location_id),
        "surveys": GetSurveys(location_id),
    }
    result = runtime.snapshot(queries)
    payload = to_jsonable(result.data)
    assert payload["session"]["day"] == payload["world"]["day"]
    assert payload["location"]["id"] == location_id
    assert "pools" in payload["fleet"]
    assert "items" in payload["transport_allocations"]
    assert "items" in payload["cargo_flows"]


def test_construction_queries_expose_authoritative_project_controls():
    app = build_game_application()
    build_options = app.query(GetBuildOptions(str(EARTH)))
    assert set(build_options.sourcing_policy_options) == {"import_now", "mixed", "local_priority"}
    assert str(EARTH) not in build_options.import_source_options
    assert str(LEO) in build_options.import_source_options

    project_id = app.execute(PlanBuild(str(EARTH), str(ids.SURFACE_POWER_GRID), priority=37, sourcing_policy="local_priority", import_source_id=str(LEO))).created_id
    assert project_id is not None
    row = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert row.settings_editable and row.sourcing_editable
    app.execute(SetProjectPriority(project_id, 81)); app.execute(SetConstructionWeight(project_id, 2.5))
    app.execute(SetProjectSourcingPolicy(project_id, "import_now")); app.execute(SetProjectImportSource(project_id, None))
    updated = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert (updated.priority, updated.construction_weight, updated.sourcing_policy, updated.import_source_id) == (81, 2.5, "import_now", None)


def test_vehicle_catalog_exposes_endurance_and_operation_asset_recovery_semantics():
    app = build_game_application(); catalog = app.query(GetCatalog())
    launch = next(row for row in catalog.vehicles if row.id == str(ids.REUSABLE_LAUNCH_VEHICLE))
    tug = next(row for row in catalog.vehicles if row.id == str(ids.REUSABLE_ORBITAL_CARGO_TUG))
    ascent = next(capability for capability in launch.operation_capability_details if capability.operation_type == "powered_ascent")
    assert tug.endurance_days == pytest.approx(60.0)
    assert ("asset_disposition", "origin") in ascent.parameters
