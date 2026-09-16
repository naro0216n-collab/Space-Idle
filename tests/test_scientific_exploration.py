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
from space_idle.site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements
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
        and item.operational_node_id == str(location_id)
    )


def _advance_until_complete(app, exploration_id, *, max_days: int = 200) -> int:
    state = app._simulation.scientific_exploration.campaigns[exploration_id]
    for elapsed in range(max_days + 1):
        if state.phase.value == "complete":
            return elapsed
        app.execute(AdvanceTime(1))
    raise AssertionError(f"scientific exploration did not complete within {max_days} days: {exploration_id}")


def _seed_exploration_movement_resources(app, *, returning: bool = False) -> None:
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.scientific_exploration.definitions[exploration_id]
    plans = sim.scientific_exploration.movement_path(
        definition, vehicle_id, sim.day, reverse=returning
    )
    for requirement in sim.transport.movement_resource_requirements_for_plans(
        vehicle_id,
        definition.required_units,
        plans,
        payload_t_per_unit=definition.minimum_payload_t,
    ):
        sim.inventory.add(
            requirement.operational_node_id,
            requirement.resource_id,
            requirement.required_t,
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
    assert any(blocker.startswith("movement_path:") for blocker in launch_vehicle.blockers)
    assert tug.blockers == ()
    assert tug.outbound_latency_days is not None and tug.outbound_latency_days > 0
    assert tug.can_assign is False  # Campaign state must exist first.

    definition = sim.scientific_exploration.definitions[ids.CISLUNAR_SCIENCE_EXPLORATION]
    assert row.minimum_payload_t == definition.minimum_payload_t
    assert row.required_vehicle_capabilities == definition.required_vehicle_capabilities
    assert row.research_points_per_day == pytest.approx(definition.points_per_day)
    assert row.required_units == definition.required_units
    assert row.required_units > 0
    assert row.can_start is True

    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    started = _row(app)
    tug = next(
        option for option in started.fleet_options
        if option.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    )
    assert tug.can_assign is True
    fleet_before = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    required_units = started.required_units
    assert fleet_before.free_units >= required_units

    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    assigned = _row(app)
    assert assigned.assigned_vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    assert assigned.reserved_units == required_units
    assert assigned.can_unassign is True
    fleet = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert fleet.exploration_units == required_units
    assert fleet.free_units == fleet_before.free_units - required_units
    assert assigned.outbound_latency_days == tug.outbound_latency_days
    assert assigned.movement_operations

    _seed_exploration_movement_resources(app)

    app.execute(AdvanceTime(1))
    # Reservation acquisition is a separate tick result; newly reserved inputs
    # cannot make the campaign execute retroactively in the same tick.
    assert _row(app).can_unassign is True
    app.execute(AdvanceTime(1))
    assert _row(app).can_unassign is False
    assert capture_state(sim)["survey"] == before_survey


def test_scientific_exploration_fleet_contract_checks_usable_payload_and_generic_capability():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.scientific_exploration.definitions[exploration_id]
    vehicle = sim.transport.vehicle_defs[vehicle_id]
    plan = sim.scientific_exploration.movement_path(
        definition, vehicle_id, sim.day
    )[0]
    usable_payload = vehicle.max_cargo_for_movement(plan)

    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        minimum_payload_t=usable_payload + 0.1,
        required_vehicle_capabilities=("docking",),
    )
    failures = sim.scientific_exploration.fleet_failures(
        exploration_id, vehicle_id, day=sim.day
    )
    assert any(blocker.startswith("payload_capacity:") for blocker in failures)
    assert "vehicle_capability:docking" in failures

    sim.transport.vehicle_defs[vehicle_id] = replace(
        vehicle,
        performance=replace(vehicle.performance, generic_capabilities=("docking",)),
    )
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        minimum_payload_t=usable_payload,
        required_vehicle_capabilities=("docking",),
    )
    row = _row(app)
    tug = next(
        option for option in row.fleet_options
        if option.vehicle_definition_id == str(vehicle_id)
    )
    assert tug.blockers == ()
    assert row.minimum_payload_t == pytest.approx(usable_payload)
    assert row.required_vehicle_capabilities == ("docking",)


def test_exploration_reservation_excludes_transport_and_release_refills_target():
    app = build_game_application()
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    committed = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert committed.exploration_units > 0
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
        str(ids.LEO),
        str(ids.LUNAR_ORBIT),
        target_units=committed.total_units,
    )).created_id
    assert allocation_id is not None
    allocation = next(
        row for row in app.query(GetTransportAllocations()).items
        if row.id == allocation_id
    )
    assert allocation.active_units == committed.free_units
    assert allocation.unfilled_units == committed.exploration_units

    app.execute(UnassignExplorationFleet(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    allocation = next(
        row for row in app.query(GetTransportAllocations()).items
        if row.id == allocation_id
    )
    assert allocation.active_units == committed.total_units
    assert allocation.unfilled_units == 0


def test_scientific_exploration_save_load_preserves_fleet_reservation_and_future_result(tmp_path):
    app = build_game_application()
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))

    path = tmp_path / "scientific-exploration.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    assert _fleet_row(loaded, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).exploration_units == _row(loaded).required_units

    remaining_days = _advance_until_complete(app, ids.CISLUNAR_SCIENCE_EXPLORATION)
    assert remaining_days > 0
    loaded.execute(AdvanceTime(remaining_days))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    state = loaded._simulation.scientific_exploration.campaigns[ids.CISLUNAR_SCIENCE_EXPLORATION]
    assert state.phase.value == "complete"
    assert state.research_points_awarded == pytest.approx(
        loaded._simulation.scientific_exploration.definitions[
            ids.CISLUNAR_SCIENCE_EXPLORATION
        ].research_points_total
    )


def test_runtime_blocker_prevents_input_consumption_and_keeps_fleet_reserved():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        origin_requirements=SiteRequirements(
            definition.origin_requirements.environment,
            (CapabilityRequirement("spacecraft_servicing", CapabilityRequirementState.ACTIVE),),
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
        blocker == "origin:capability:active:spacecraft_servicing"
        for blocker in sim.scientific_exploration.blockers(exploration_id, day=sim.day)
    )

    app.execute(AdvanceTime(1))
    assert state.inputs_consumed is False
    assert state.progress_days == pytest.approx(0.0)
    fleet = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    required_units = _row(app).required_units
    assert fleet.exploration_units == required_units
    assert fleet.free_units == fleet.total_units - required_units


def test_scientific_exploration_definition_rejects_duplicate_resource_and_capability_requirements():
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

    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition,
        required_vehicle_capabilities=("docking", "docking"),
    )
    with pytest.raises(
        ConfigurationError, match="duplicate vehicle capability requirement"
    ):
        validate_simulation_configuration(sim)

def test_full_rp_storage_constrains_reward_retention_but_does_not_freeze_campaign():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    for resource_id, amount_t in definition.consumable_resources:
        sim.inventory.add(definition.origin_id, resource_id, amount_t)
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    state = sim.scientific_exploration.campaigns[exploration_id]

    capacity = sim.research.storage_capacity(day=sim.day)
    sim.research.store_generated_points(capacity, day=sim.day)
    assert "rp_storage_full" not in sim.scientific_exploration.blockers(
        exploration_id, day=sim.day
    )
    before_points = sim.research.stored_points
    app.execute(AdvanceTime(7))

    assert state.inputs_consumed is True
    assert state.progress_days > 0.0
    assert state.research_points_awarded > 0.0
    assert sim.research.stored_points == pytest.approx(before_points)
    assert _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT).exploration_units == _row(app).required_units


def test_started_exploration_movement_keeps_frozen_latency_after_vehicle_definition_change():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    vehicle_id = ids.REUSABLE_ORBITAL_CARGO_TUG
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(str(exploration_id), str(vehicle_id)))
    app.execute(AdvanceTime(2))

    state = sim.scientific_exploration.campaigns[exploration_id]
    execution = sim.transport.movement_executions[state.movement_execution_id]
    frozen_completion = execution.completion_day
    frozen_latency = execution.latency_days
    frozen_operations = tuple(
        (operation.operation_type, operation.delta_v_km_s)
        for leg in execution.legs
        for operation in leg.operations
    )
    vehicle = sim.transport.vehicle_defs[vehicle_id]
    sim.transport.vehicle_defs[vehicle_id] = replace(
        vehicle,
        performance=replace(vehicle.performance, transit_time_multiplier=9.0),
    )
    sim.transport.invalidate_movement_plans()

    row = _row(app)
    assert row.outbound_latency_days == frozen_latency
    assert row.movement_operations == frozen_operations

    app.execute(AdvanceTime(frozen_completion - sim.day))
    assert state.phase.value == "active"
    assert state.movement_execution_id is None
    assert _fleet_row(app, vehicle_id, ids.LUNAR_ORBIT).exploration_units == state.reserved_units


def test_partial_exploration_inputs_are_reserved_and_unassign_releases_them():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    machinery = ids.MACHINERY
    electronics = ids.PRECISION_ELECTRONICS
    sim.inventory.stock[(definition.origin_id, machinery)] = 0.05
    sim.inventory.stock[(definition.origin_id, electronics)] = 0.0

    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    app.execute(AdvanceTime(1))

    initial_stock = 0.05
    owner_id = sim.scientific_exploration._input_reservation_owner_id(exploration_id)
    assert sim.inventory.amount(definition.origin_id, machinery) == pytest.approx(initial_stock)
    assert sim.inventory.reserved_for(owner_id, definition.origin_id, machinery) == pytest.approx(initial_stock)
    assert sim.inventory.available(definition.origin_id, machinery) == pytest.approx(0.0)
    state = sim.scientific_exploration.campaigns[exploration_id]
    assert state.inputs_consumed is False
    assert state.progress_days == 0.0

    app.execute(UnassignExplorationFleet(str(exploration_id)))

    assert sim.inventory.amount(definition.origin_id, machinery) == pytest.approx(initial_stock)
    assert sim.inventory.reserved_for(owner_id, definition.origin_id, machinery) == pytest.approx(0.0)
    assert sim.inventory.available(definition.origin_id, machinery) == pytest.approx(initial_stock)
