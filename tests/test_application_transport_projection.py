from __future__ import annotations

from space_idle import (
    GetBottlenecks,
    GetBuildOptions,
    GetCargoOrders,
    GetCatalog,
    GetContracts,
    GetFlowReport,
    GetLocation,
    GetLogistics,
    GetLogisticsSummary,
    GetProjects,
    GetResearch,
    GetRoutes,
    GetSurveys,
    GetTransportMissions,
    GetVehicles,
    GetWorld,
    build_game_application,
)
from space_idle.api import GameRuntime
from space_idle.api.codec import to_jsonable


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
