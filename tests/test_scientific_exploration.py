from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle.validation import validate_runtime_state

from space_idle import (
    AdvanceTime,
    AbortScientificExploration,
    AssignExplorationFleet,
    ReturnScientificExploration,
    SetScientificExplorationCompletionDisposition,
    CreateTransportAllocation,
    GetFleet,
    GetResearch,
    GetScientificExplorations,
    GetTransportAllocations,
    PauseFacility,
    PauseScientificExploration,
    ResumeScientificExploration,
    StartScientificExploration,
    UnassignExplorationFleet,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.facilities import FacilityDef
from space_idle.research import (
    ResearchProviderLevelSpec, ResearchProviderSourceKind, ResearchProviderSpec,
)
from space_idle.shared import DefinitionId
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


def _advance_outbound_campaign_to_completion(app, exploration_id) -> None:
    sim = app._simulation
    state = sim.scientific_exploration.campaigns[exploration_id]
    definition = sim.scientific_exploration.definitions[exploration_id]

    assert state.phase.value == "outbound"
    execution = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(execution.completion_day - sim.day))
    assert state.phase.value == "active"

    while state.phase.value == "active":
        progress_before = state.progress_days
        app.execute(AdvanceTime(1))
        assert (
            state.phase.value != "active"
            or state.progress_days > progress_before + 1e-12
        ), "active scientific exploration made no canonical-tick progress"

    if definition.return_to_origin:
        assert state.phase.value == "return_preparing"
        _seed_exploration_movement_resources(app, returning=True)
        # Reservation acquisition and departure are separate canonical tick
        # results, already covered by the preparation ordering contract.
        app.execute(AdvanceTime(2))
        assert state.phase.value == "returning"
        execution = sim.transport.movement_executions[state.movement_execution_id]
        app.execute(AdvanceTime(execution.completion_day - sim.day))

    assert state.phase.value == "complete"


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
    assert any(blocker.code.startswith("movement_path:") for blocker in launch_vehicle.blockers)
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
    assert assigned.committed_units == required_units
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


def test_exploration_commitment_excludes_transport_and_release_refills_target():
    app = build_game_application()
    sim = app._simulation
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    committed = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert committed.exploration_units > 0
    capacity = sim.transport.transport_capacity_for_units(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO, ids.LUNAR_ORBIT,
        committed.total_units, day=sim.day,
    )
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
        str(ids.LEO),
        str(ids.LUNAR_ORBIT),
        target_forward_t_per_day=capacity.forward_t_per_day,
        target_reverse_t_per_day=capacity.reverse_t_per_day,
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


def test_scientific_exploration_save_load_preserves_fleet_commitment_and_future_result(tmp_path):
    app = build_game_application()
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(ids.CISLUNAR_SCIENCE_EXPLORATION)))
    app.execute(AssignExplorationFleet(
        str(ids.CISLUNAR_SCIENCE_EXPLORATION),
        str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))

    app.execute(AdvanceTime(2))
    assert (
        app._simulation.scientific_exploration.campaigns[
            ids.CISLUNAR_SCIENCE_EXPLORATION
        ].phase.value
        == "outbound"
    )

    path = tmp_path / "scientific-exploration.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)
    original_state = capture_state(app._simulation)
    loaded_state = capture_state(loaded._simulation)
    assert loaded_state["scientific_exploration"] == original_state["scientific_exploration"]
    assert loaded_state["transport"] == original_state["transport"]
    loaded_campaign = loaded._simulation.scientific_exploration.campaigns[
        ids.CISLUNAR_SCIENCE_EXPLORATION
    ]
    loaded_commitment = loaded._simulation.transport.fleet_commitment_snapshot(
        loaded_campaign.fleet_commitment_id
    )
    assert loaded_commitment is not None
    assert loaded_commitment.quantity == _row(loaded).required_units
    assert loaded_campaign.movement_execution_id in loaded._simulation.transport.movement_executions

    _advance_outbound_campaign_to_completion(app, ids.CISLUNAR_SCIENCE_EXPLORATION)
    _advance_outbound_campaign_to_completion(loaded, ids.CISLUNAR_SCIENCE_EXPLORATION)
    loaded_campaign = loaded._simulation.scientific_exploration.campaigns[ids.CISLUNAR_SCIENCE_EXPLORATION]
    original_campaign = app._simulation.scientific_exploration.campaigns[ids.CISLUNAR_SCIENCE_EXPLORATION]
    assert loaded_campaign == original_campaign
    assert capture_state(loaded._simulation)["transport"] == capture_state(app._simulation)["transport"]
    state = loaded_campaign
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

def test_rp_admission_blocks_only_active_science_and_resumes_after_headroom_recovers():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    sim.scientific_exploration.definitions[exploration_id] = replace(
        definition, return_to_origin=True
    )
    definition = sim.scientific_exploration.definitions[exploration_id]

    storage_definition_id = DefinitionId("test.facility.exploration_rp_storage")
    storage_provider_id = DefinitionId("test.research_provider.exploration_rp_storage")
    sim.facilities.definitions[storage_definition_id] = FacilityDef(
        storage_definition_id, "Exploration RP storage fixture"
    )
    sim.research.providers = {
        storage_provider_id: ResearchProviderSpec(
            storage_provider_id, ResearchProviderSourceKind.FACILITY,
            storage_definition_id, tier=1,
            levels=(ResearchProviderLevelSpec(1, 0.0, 100.0, 0.0),),
        )
    }
    sim.facilities.install(storage_definition_id, ids.EARTH)

    for resource_id, amount_t in definition.consumable_resources:
        sim.inventory.add(definition.origin_id, resource_id, amount_t)
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    state = sim.scientific_exploration.campaigns[exploration_id]

    capacity = sim.research.storage_capacity(day=sim.day)
    sim.research.stored_points = capacity
    app.execute(AdvanceTime(2))
    assert state.phase.value == "outbound"
    outbound = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(outbound.completion_day - sim.day))
    assert state.phase.value == "active"

    full = _row(app)
    assert full.rp_admission_headroom == pytest.approx(0.0)
    assert full.rp_requested_today == pytest.approx(definition.points_per_day)
    assert full.rp_admitted_today == pytest.approx(0.0)
    assert full.rp_admission_blocker is not None and full.rp_admission_blocker.code == "research_point_pool_headroom"
    before_progress = state.progress_days
    before_awarded = state.research_points_awarded
    commitment_id = state.fleet_commitment_id
    assert commitment_id is not None

    app.execute(PauseScientificExploration(str(exploration_id)))
    paused = _row(app)
    assert paused.can_resume is True
    assert paused.transition_options == ("resume", "abort", "return")
    assert paused.rp_requested_today == pytest.approx(0.0)
    assert paused.rp_admitted_today == pytest.approx(0.0)
    assert paused.fleet_commitment_id == str(commitment_id)
    commitment = sim.transport.fleet_commitment_snapshot(commitment_id)
    assert commitment is not None and commitment.quantity == definition.required_units
    app.execute(AdvanceTime(1))
    assert state.progress_days == pytest.approx(before_progress)
    assert state.research_points_awarded == pytest.approx(before_awarded)
    assert sim.transport.fleet_commitment_snapshot(commitment_id) is not None

    app.execute(ResumeScientificExploration(str(exploration_id)))
    assert _row(app).rp_admission_blocker is not None and _row(app).rp_admission_blocker.code == "research_point_pool_headroom"
    app.execute(AdvanceTime(1))
    assert state.progress_days == pytest.approx(before_progress)
    assert state.research_points_awarded == pytest.approx(before_awarded)
    assert sim.research.stored_points == pytest.approx(capacity)

    sim.research.stored_points = 0.0
    recovered = _row(app)
    assert recovered.rp_admitted_today == pytest.approx(definition.points_per_day)
    assert recovered.rp_admission_blocker is None
    app.execute(AdvanceTime(1))
    assert state.progress_days == pytest.approx(before_progress + 1.0)
    assert state.research_points_awarded == pytest.approx(
        before_awarded + definition.points_per_day
    )
    assert sim.research.stored_points == pytest.approx(definition.points_per_day)

    # Finish ACTIVE science with ample headroom, then prove return Movement is
    # independent from RP admission even when the pool is full again.
    while state.phase.value == "active":
        sim.research.stored_points = 0.0
        app.execute(AdvanceTime(1))
    assert state.phase.value == "return_preparing"
    assert state.research_points_awarded == pytest.approx(definition.research_points_total)
    sim.research.stored_points = sim.research.storage_capacity(day=sim.day)
    _seed_exploration_movement_resources(app, returning=True)
    app.execute(AdvanceTime(2))
    assert state.phase.value == "returning"
    returning = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(returning.completion_day - sim.day))
    assert state.phase.value == "complete"


def test_scientific_exploration_participates_in_shared_rp_pool_admission():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]

    facility_definition_id = DefinitionId("test.facility.exploration_shared_rp")
    provider_id = DefinitionId("test.research_provider.facility.exploration_shared_rp")
    sim.facilities.definitions[facility_definition_id] = FacilityDef(
        facility_definition_id, "Exploration shared RP fixture"
    )
    sim.research.providers = {
        provider_id: ResearchProviderSpec(
            provider_id,
            ResearchProviderSourceKind.FACILITY,
            facility_definition_id,
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 4.0, 100.0, 0.0),),
        )
    }
    sim.facilities.install(facility_definition_id, ids.EARTH)

    for resource_id, amount_t in definition.consumable_resources:
        sim.inventory.add(definition.origin_id, resource_id, amount_t)
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    app.execute(AdvanceTime(2))
    state = sim.scientific_exploration.campaigns[exploration_id]
    outbound = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(outbound.completion_day - sim.day))
    assert state.phase.value == "active"

    capacity = sim.research.storage_capacity(day=sim.day)
    headroom = 2.0
    sim.research.stored_points = capacity - headroom
    provider = app.query(GetResearch()).providers[0]
    exploration = _row(app)

    assert provider.admitted_generation_points_per_day > 0.0
    assert exploration.rp_admitted_today > 0.0
    assert exploration.rp_admitted_today < exploration.rp_requested_today
    assert provider.admitted_generation_points_per_day + exploration.rp_admitted_today == pytest.approx(headroom)

    before_awarded = state.research_points_awarded
    app.execute(AdvanceTime(1))
    assert sim.research.stored_points == pytest.approx(capacity)
    assert state.research_points_awarded - before_awarded == pytest.approx(
        exploration.rp_admitted_today
    )

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
    commitment = sim.transport.fleet_commitment_snapshot(state.fleet_commitment_id)
    assert commitment is not None
    assert _fleet_row(app, vehicle_id, ids.LUNAR_ORBIT).exploration_units == commitment.quantity


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
    reservations = [
        (owner_id, amount)
        for (owner_id, node_id, resource_id), amount in sim.inventory.reserved.items()
        if node_id == definition.origin_id and resource_id == machinery and amount > 0.0
    ]
    assert len(reservations) == 1
    owner_id, reserved = reservations[0]
    assert sim.inventory.amount(definition.origin_id, machinery) == pytest.approx(initial_stock)
    assert reserved == pytest.approx(initial_stock)
    assert sim.inventory.available(definition.origin_id, machinery) == pytest.approx(0.0)
    state = sim.scientific_exploration.campaigns[exploration_id]
    assert state.inputs_consumed is False
    assert state.progress_days == 0.0

    app.execute(UnassignExplorationFleet(str(exploration_id)))

    assert sim.inventory.amount(definition.origin_id, machinery) == pytest.approx(initial_stock)
    assert sim.inventory.reserved_for(owner_id, definition.origin_id, machinery) == pytest.approx(0.0)
    assert sim.inventory.available(definition.origin_id, machinery) == pytest.approx(initial_stock)


def test_scientific_exploration_abort_return_and_completion_disposition_are_domain_transitions():
    app = build_game_application()
    sim = app._simulation
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[exploration_id]
    for resource_id, amount_t in definition.consumable_resources:
        sim.inventory.add(definition.origin_id, resource_id, amount_t)
    _seed_exploration_movement_resources(app)
    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(SetScientificExplorationCompletionDisposition(str(exploration_id), "return_to_origin"))
    app.execute(AssignExplorationFleet(str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)))
    app.execute(AdvanceTime(2))
    state = sim.scientific_exploration.campaigns[exploration_id]
    assert state.phase.value == "outbound"
    commitment_id = state.fleet_commitment_id
    assert commitment_id is not None

    app.execute(ReturnScientificExploration(str(exploration_id)))
    assert state.termination_intent.value == "return"
    outbound = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(outbound.completion_day - sim.day))
    assert state.phase.value == "return_preparing"
    assert state.progress_days == pytest.approx(0.0)
    assert state.fleet_commitment_id == commitment_id

    _seed_exploration_movement_resources(app, returning=True)
    app.execute(AdvanceTime(2))
    assert state.phase.value == "returning"
    app.execute(AbortScientificExploration(str(exploration_id)))
    assert state.termination_intent.value == "abort"
    returning = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(returning.completion_day - sim.day))
    assert state.phase.value == "aborted"
    assert state.fleet_commitment_id is None
    assert sim.transport.fleet_commitment_snapshot(commitment_id) is None
    validate_runtime_state(sim)
