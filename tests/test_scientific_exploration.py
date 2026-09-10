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
    assert sim.logistics.vehicles[next(v.id for v in sim.logistics.vehicles.values() if str(v.id) == tug.vehicle_id)].status.value == "assigned"

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


def test_scientific_exploration_mission_duration_is_independent_of_campaign_duration():
    app = build_game_application()
    sim = app._simulation
    definition = sim.scientific_exploration.definitions[ids.CISLUNAR_SCIENCE_EXPLORATION]

    route = definition.compatibility_route()

    assert route.transit_days == definition.mission_duration_days
    assert definition.mission_duration_days != definition.duration_days


def test_runtime_blocker_prevents_input_consumption_and_vehicle_relocation():
    from dataclasses import replace

    from space_idle import PauseFacility
    from space_idle.site import CapabilityRequirement, SiteRequirements

    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        origin_requirements=SiteRequirements(
            definition.origin_requirements.environment,
            (CapabilityRequirement("spacecraft_servicing", 0.01, "available"),),
        ),
    )
    servicing_id = sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.refresh_storage()
    tug = _orbital_tug(sim)

    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationVehicle(str(exploration_id), str(tug.id)))
    state = sim.scientific_exploration.campaigns[exploration_id]
    demands = sim.scientific_exploration.resource_demands(sim.day)
    assert demands
    assert all(
        sim.inventory.reserved_for(demand.id, demand.destination_id, demand.resource_id) > 0
        for demand in demands
    )

    app.execute(PauseFacility(str(servicing_id)))
    assert any(
        blocker.startswith("origin:capability:available:spacecraft_servicing:")
        for blocker in sim.scientific_exploration.blockers(exploration_id, day=sim.day)
    )

    app.execute(AdvanceTime(1))

    assert state.inputs_consumed is False
    assert state.progress_days == pytest.approx(0.0)
    assert state.research_points_awarded == pytest.approx(0.0)
    assert tug.location_id == ids.LEO
    assert tug.transit_destination_id is None
    assert tug.status.value == "assigned"


def test_scientific_exploration_rejects_duplicate_consumable_resources():
    from dataclasses import replace

    from space_idle.validation import validate_simulation_configuration
    from space_idle.validation_support import ConfigurationError

    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        consumable_resources=((ids.MACHINERY, 0.1), (ids.MACHINERY, 0.2)),
    )

    with pytest.raises(ConfigurationError, match="duplicate consumable resource"):
        validate_simulation_configuration(sim)
