from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CreateLogisticsLane,
    GetBottlenecks,
    GetBuildOptions,
    GetCargoOrders,
    GetCatalog,
    GetContracts,
    GetFlowReport,
    GetLocation,
    GetLogistics,
    GetLogisticsLanes,
    GetLogisticsSummary,
    GetProjects,
    GetResearch,
    GetRoutes,
    GetSurveys,
    GetTransportMissions,
    GetVehicles,
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
    build_game_application,
)
from space_idle.api import GameRuntime
from space_idle.api.codec import to_jsonable
from space_idle.content.base_game import EARTH, LEO
from space_idle.content import base_ids as ids


def test_vehicle_concept_is_consistent_across_catalog_and_runtime_projections():
    app = build_game_application()
    catalog = app.query(GetCatalog())
    logistics = app.query(GetLogistics())

    catalog_concepts = {row.id: row.concept for row in catalog.vehicles}
    assert catalog_concepts
    for vehicle in logistics.vehicles:
        assert vehicle.concept == catalog_concepts[vehicle.definition_id]

    for route in logistics.routes:
        for mode in route.modes:
            if mode.vehicle_definition_id is not None:
                assert mode.kind == catalog_concepts[mode.vehicle_definition_id]


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
    assert after.route_modes == before.route_modes
    assert after.path_policy == before.path_policy
    assert after.paused is True
    assert after.requested_capacity_t_per_day == 3.5
    assert after.priority == 80


def test_vehicle_production_exposes_resource_priority_and_capability_allocation_controls():
    app = build_game_application()

    production_id = app.execute(
        ProduceVehicle(
            str(ids.REUSABLE_ORBITAL_CARGO_TUG),
            str(EARTH),
            priority=37,
            allocation_weight=2.5,
        )
    ).created_id
    assert production_id is not None

    row = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert row.priority == 37
    assert row.allocation_weight == pytest.approx(2.5)
    assert row.priority_editable is True
    assert row.allocation_editable is True
    demands = tuple(
        demand for demand in app.query(GetLogistics()).demands
        if demand.owner_kind == "vehicle_production" and demand.owner_id == production_id
    )
    assert demands
    assert {demand.priority for demand in demands} == {37}

    app.execute(SetVehicleProductionSettings(
        production_id,
        priority=81,
        allocation_weight=3.0,
    ))
    updated = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert updated.priority == 81
    assert updated.allocation_weight == pytest.approx(3.0)
    assert {
        demand.priority
        for demand in app.query(GetLogistics()).demands
        if demand.owner_kind == "vehicle_production" and demand.owner_id == production_id
    } == {81}

    app.execute(AdvanceTime(1))
    building = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert building.phase == "building"
    assert building.priority_editable is False
    assert building.allocation_editable is True
    with pytest.raises(ApplicationError, match="priority can only change before inputs are consumed"):
        app.execute(SetVehicleProductionSettings(production_id, priority=10))
    app.execute(SetVehicleProductionSettings(production_id, allocation_weight=1.25))
    assert next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    ).allocation_weight == pytest.approx(1.25)


def test_ui_snapshot_is_json_safe_at_application_boundary(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
    location_id = runtime.query(GetWorld()).data.locations[0].id
    queries = {
        "world": GetWorld(),
        "global_issues": GetBottlenecks(),
        "research": GetResearch(),
        "contracts": GetContracts(),
        "logistics_summary": GetLogisticsSummary(),
        "routes": GetRoutes(include_modes=True),
        "vehicles": GetVehicles(),
        "orders": GetCargoOrders(),
        "missions": GetTransportMissions(),
        "location": GetLocation(location_id),
        "flow": GetFlowReport(location_id),
        "projects": GetProjects(location_id),
        "build_options": GetBuildOptions(location_id),
        "bottlenecks": GetBottlenecks(location_id),
        "surveys": GetSurveys(location_id),
    }

    result = runtime.snapshot(queries)
    payload = to_jsonable(result.data)

    assert payload["session"]["day"] == payload["world"]["day"]
    assert payload["location"]["id"] == location_id


def test_construction_queries_expose_authoritative_project_controls():
    app = build_game_application()

    build_options = app.query(GetBuildOptions(str(EARTH)))
    assert set(build_options.sourcing_policy_options) == {"import_now", "mixed", "local_priority"}
    assert str(EARTH) not in build_options.import_source_options
    assert str(LEO) in build_options.import_source_options

    project_id = app.execute(
        PlanBuild(
            str(EARTH),
            str(ids.SURFACE_POWER_GRID),
            priority=37,
            sourcing_policy="local_priority",
            import_source_id=str(LEO),
        )
    ).created_id
    assert project_id is not None

    row = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert row.settings_editable is True
    assert row.sourcing_editable is True
    assert row.priority == 37
    assert row.construction_weight == 1.0
    assert row.sourcing_policy == "local_priority"
    assert row.import_source_id == str(LEO)
    assert set(row.sourcing_policy_options) == set(build_options.sourcing_policy_options)
    assert row.import_source_options == build_options.import_source_options

    app.execute(SetProjectPriority(project_id, 81))
    app.execute(SetConstructionWeight(project_id, 2.5))
    app.execute(SetProjectSourcingPolicy(project_id, "import_now"))
    app.execute(SetProjectImportSource(project_id, None))

    updated = next(item for item in app.query(GetProjects(str(EARTH))).items if item.id == project_id)
    assert updated.priority == 81
    assert updated.construction_weight == 2.5
    assert updated.sourcing_policy == "import_now"
    assert updated.import_source_id is None


def test_vehicle_catalog_exposes_endurance_and_operation_asset_recovery_semantics():
    app = build_game_application()
    catalog = app.query(GetCatalog())

    launch = next(
        row for row in catalog.vehicles
        if row.id == str(ids.REUSABLE_LAUNCH_VEHICLE)
    )
    tug = next(
        row for row in catalog.vehicles
        if row.id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    )
    ascent = next(
        capability for capability in launch.operation_capability_details
        if capability.operation_type == "powered_ascent"
    )

    assert tug.endurance_days == pytest.approx(60.0)
    assert ("asset_disposition", "origin") in ascent.parameters
