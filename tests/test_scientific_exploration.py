from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    AssignExplorationVehicle,
    GetScientificExplorations,
    StartScientificExploration,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from datetime import datetime, timezone


def _orbital_tug(sim):
    return next(
        vehicle
        for vehicle in sim.logistics.vehicles.values()
        if vehicle.definition_id == ids.REUSABLE_ORBITAL_CARGO_TUG
    )


def test_scientific_exploration_is_separate_from_survey_and_uses_vehicle_performance():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    before_survey = capture_state(sim)["survey"]

    view = app.query(GetScientificExplorations())
    row = next(item for item in view.items if item.id == str(exploration_id))
    launch_vehicle = next(
        option for option in row.vehicle_options
        if option.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
    )
    tug = next(
        option for option in row.vehicle_options
        if option.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    )
    assert any("spaceflight:unsupported" in blocker for blocker in launch_vehicle.blockers)
    assert tug.blockers == ()

    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationVehicle(str(exploration_id), tug.vehicle_id))
    assert sim.logistics.vehicles[next(v.id for v in sim.logistics.vehicles.values() if str(v.id) == tug.vehicle_id)].status.value == "exploration"

    app.execute(AdvanceTime(1))
    state = sim.scientific_exploration.campaigns[exploration_id]
    assert state.progress_days > 0
    assert state.research_points_awarded > 0
    assert capture_state(sim)["survey"] == before_survey


def test_exploration_vehicle_cannot_be_used_by_transport_until_campaign_completes():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    tug = _orbital_tug(sim)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationVehicle(str(exploration_id), str(tug.id)))

    assert tug.id not in sim.logistics.available_vehicle_ids(
        next(route_id for route_id, route in sim.logistics.routes.items() if route.origin_id == ids.LEO and route.destination_id == ids.LUNAR_ORBIT),
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        sim.day,
    )
    with pytest.raises(ApplicationError):
        app.execute(__import__("space_idle").DispatchVehicle(str(tug.id), "base.route.leo_lunar_orbit"))

    app.execute(AdvanceTime(8))
    state = sim.scientific_exploration.campaigns[exploration_id]
    assert state.phase.value == "complete"
    assert state.research_points_awarded == pytest.approx(sim.scientific_exploration.definitions[exploration_id].research_points_total)
    assert tug.status.value == "available"
    assert tug.location_id == ids.LUNAR_ORBIT


def test_scientific_exploration_save_load_preserves_vehicle_assignment_and_future_result(tmp_path):
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    tug = _orbital_tug(sim)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationVehicle(str(exploration_id), str(tug.id)))
    app.execute(AdvanceTime(2))

    path = tmp_path / "scientific-exploration.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(sim)

    app.execute(AdvanceTime(6))
    loaded.execute(AdvanceTime(6))
    assert capture_state(loaded._simulation) == capture_state(sim)
