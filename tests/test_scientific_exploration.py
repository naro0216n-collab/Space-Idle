from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    AssignExplorationFleet,
    CreateTransportAllocation,
    GetFleet,
    GetScientificExplorations,
    GetTransportAllocations,
    PauseFacility,
    StartScientificExploration,
    UnassignExplorationFleet,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.site import CapabilityRequirement, SiteRequirements
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError


def _row(app):
    return next(
        item for item in app.query(GetScientificExplorations()).items
        if item.id == str(ids.CISLUNAR_SCIENCE_EXPLORATION)
    )


def _fleet_row(app, definition_id, location_id):
    return next(
        item for item in app.query(GetFleet()).pools
        if item.vehicle_definition_id == str(definition_id)
        and item.location_id == str(location_id)
    )


def test_scientific_exploration_is_separate_from_survey_and_uses_fleet_performance():
    app = build_game_application()
    sim = app._simulation
    before_survey = capture_state(sim)["survey"]

    row = _row(app)
    launch_vehicle = next(
        option for option in row.fleet_options
        if option.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
    )
    tug = next(
        option for option in row.fleet_options
        if option.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    )
    assert any("spaceflight:unsupported" in blocker for blocker in launch_vehicle.blockers)
    assert tug.blockers == ()
    assert tug.can_assign is False  # Campaign state must exist first.

    definition = sim.scientific_exploration.definitions[ids.CISLUNAR_SCIENCE_EXPLORATION]
    assert row.mission_duration_days == definition.mission_duration_days
    assert row.minimum_payload_t == definition.minimum_payload_t
    assert row.required_vehicle_capabilities == definition.required_vehicle_capabilities
    assert row.research_points_per_day == pytest.approx(definition.points_per_day)
    assert row.required_units == definition.required_units == 1
    assert row.can_start is True

    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    started = _row(app)
    tug = next(
        option for option in started.fleet_options
        if option.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    )
    assert tug.can_assign is True
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    assigned = _row(app)
    assert assigned.assigned_vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    assert assigned.reserved_units == 1
    assert assigned.can_unassign is True
    fleet = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert fleet.exploration_units == 1
    assert fleet.free_units == 0

    app.execute(AdvanceTime(1))
    assert _row(app).can_unassign is False
    assert capture_state(sim)["survey"] == before_survey


def test_scientific_exploration_fleet_contract_checks_usable_payload_and_generic_capability():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.scientific_exploration.definitions[exploration_id]
    vehicle = sim.logistics.vehicle_defs[vehicle_id]

    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        minimum_payload_t=vehicle.max_cargo_for_route(definition.compatibility_route()) + 0.1,
        required_vehicle_capabilities=("docking",),
    )
    failures = sim.scientific_exploration.fleet_failures(
        exploration_id, vehicle_id, day=sim.day
    )
    assert any(blocker.startswith("payload_capacity:") for blocker in failures)
    assert "vehicle_capability:docking" in failures

    sim.logistics.vehicle_defs[vehicle_id] = replace(
        vehicle,
        performance=replace(vehicle.performance, generic_capabilities=("docking",)),
    )
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        minimum_payload_t=vehicle.max_cargo_for_route(definition.compatibility_route()),
        required_vehicle_capabilities=("docking",),
    )
    row = _row(app)
    tug = next(
        option for option in row.fleet_options
        if option.vehicle_definition_id == str(vehicle_id)
    )
    assert tug.blockers == ()
    assert row.minimum_payload_t == pytest.approx(
        vehicle.max_cargo_for_route(definition.compatibility_route())
    )
    assert row.required_vehicle_capabilities == ("docking",)


def test_exploration_reservation_excludes_transport_and_release_refills_target():
    app = build_game_application()
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
        str(ids.LEO),
        str(ids.LUNAR_ORBIT),
        target_units=1,
    )).created_id
    assert allocation_id is not None
    allocation = next(
        row for row in app.query(GetTransportAllocations()).items
        if row.id == allocation_id
    )
    assert allocation.active_units == 0
    assert allocation.unfilled_units == 1

    app.execute(UnassignExplorationFleet(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    allocation = next(
        row for row in app.query(GetTransportAllocations()).items
        if row.id == allocation_id
    )
    assert allocation.active_units == 1
    assert allocation.unfilled_units == 0


def test_scientific_exploration_save_load_preserves_fleet_reservation_and_future_result(tmp_path):
    app = build_game_application()
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    app.execute(AdvanceTime(2))

    path = tmp_path / "scientific-exploration.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    assert _fleet_row(loaded, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).exploration_units == 1

    app.execute(AdvanceTime(6))
    loaded.execute(AdvanceTime(6))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    state = loaded._simulation.scientific_exploration.campaigns[ids.CISLUNAR_SCIENCE_EXPLORATION]
    assert state.phase.value == "complete"
    assert state.research_points_awarded == pytest.approx(
        loaded._simulation.scientific_exploration.definitions[
            ids.CISLUNAR_SCIENCE_EXPLORATION
        ].research_points_total
    )


def test_scientific_exploration_mission_duration_is_independent_of_campaign_duration():
    sim = build_game_application()._simulation
    definition = sim.scientific_exploration.definitions[ids.CISLUNAR_SCIENCE_EXPLORATION]
    route = definition.compatibility_route()
    assert route.transit_days == definition.mission_duration_days
    assert definition.mission_duration_days != definition.duration_days


def test_runtime_blocker_prevents_input_consumption_and_keeps_fleet_reserved():
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

    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    state = sim.scientific_exploration.campaigns[exploration_id]
    app.execute(PauseFacility(str(servicing_id)))
    assert any(
        blocker.startswith("origin:capability:available:spacecraft_servicing:")
        for blocker in sim.scientific_exploration.blockers(exploration_id, day=sim.day)
    )

    app.execute(AdvanceTime(1))
    assert state.inputs_consumed is False
    assert state.progress_days == pytest.approx(0.0)
    fleet = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert fleet.exploration_units == 1
    assert fleet.free_units == 0


def test_scientific_exploration_rejects_duplicate_consumable_resources():
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


def test_scientific_exploration_rejects_invalid_vehicle_capability_requirements():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        required_vehicle_capabilities=("docking", "docking"),
    )
    with pytest.raises(ConfigurationError, match="duplicate vehicle capability requirement"):
        validate_simulation_configuration(sim)


def test_rp_storage_blocker_prevents_input_consumption_and_keeps_fleet_reserved():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    state = sim.scientific_exploration.campaigns[exploration_id]

    capacity = sim.research.storage_capacity(day=sim.day)
    sim.research.store_generated_points(capacity, day=sim.day)
    assert "rp_storage_full" in sim.scientific_exploration.blockers(
        exploration_id, day=sim.day
    )
    app.execute(AdvanceTime(1))
    assert state.inputs_consumed is False
    assert state.progress_days == pytest.approx(0.0)
    assert _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).exploration_units == 1
