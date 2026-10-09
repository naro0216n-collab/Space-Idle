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
from space_idle.facilities import CapabilitySupply, FacilityDef
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


def test_exploration_assignment_owns_fleet_and_partial_inputs_until_unassigned():
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

    machinery = ids.MACHINERY
    electronics = ids.PRECISION_ELECTRONICS
    sim.inventory.stock[(definition.origin_id, machinery)] = 0.05
    sim.inventory.stock[(definition.origin_id, electronics)] = 0.0

    app.execute(StartScientificExploration(str(exploration_id)))
    app.execute(AssignExplorationFleet(
        str(exploration_id), str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    ))
    committed = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    required_units = _row(app).required_units
    assert committed.exploration_units == required_units > 0

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
    allocation = next(
        row for row in app.query(GetTransportAllocations()).items
        if row.id == allocation_id
    )
    assert allocation.active_units == committed.free_units
    assert allocation.unfilled_units == committed.exploration_units

    app.execute(AdvanceTime(1))
    reservations = [
        (owner_id, amount)
        for (owner_id, node_id, resource_id), amount in sim.inventory.reserved.items()
        if node_id == definition.origin_id and resource_id == machinery and amount > 0.0
    ]
    assert len(reservations) == 1
    owner_id, reserved = reservations[0]
    assert sim.inventory.amount(definition.origin_id, machinery) == pytest.approx(0.05)
    assert reserved == pytest.approx(0.05)
    assert sim.inventory.available(definition.origin_id, machinery) == pytest.approx(0.0)
    state = sim.scientific_exploration.campaigns[exploration_id]
    assert state.inputs_consumed is False
    assert state.progress_days == pytest.approx(0.0)

    app.execute(PauseFacility(str(servicing_id)))
    assert any(
        blocker == "origin:capability:active:spacecraft_servicing"
        for blocker in sim.scientific_exploration.blockers(exploration_id, day=sim.day)
    )
    app.execute(AdvanceTime(1))
    assert state.inputs_consumed is False
    assert state.progress_days == pytest.approx(0.0)
    still_committed = _fleet_row(app, ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert still_committed.exploration_units == required_units

    app.execute(UnassignExplorationFleet(str(exploration_id)))
    assert sim.inventory.amount(definition.origin_id, machinery) == pytest.approx(0.05)
    assert sim.inventory.reserved_for(
        owner_id, definition.origin_id, machinery
    ) == pytest.approx(0.0)
    assert sim.inventory.available(definition.origin_id, machinery) == pytest.approx(0.05)
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

def test_rp_admission_blocks_only_active_science_and_shares_recovered_headroom():
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
        storage_definition_id, "Exploration RP storage fixture",
        capability_supplies=(CapabilitySupply("test_exploration_research_storage"),),
    )
    for assignment in tuple(sim.research.provider_assignments.values()):
        sim.research.release_provider_assignment(assignment.id, day=sim.day)
    sim.research.providers = {
        storage_provider_id: ResearchProviderSpec(
            storage_provider_id,
            ResearchProviderSourceKind.FACILITY,
            frozenset({"test_exploration_research_storage"}),
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 4.0, 100.0, 0.0),),
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
    assert full.rp_admission_blocker is not None
    assert full.rp_admission_blocker.code == "research_point_pool_headroom"
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
    assert _row(app).rp_admission_blocker is not None
    assert _row(app).rp_admission_blocker.code == "research_point_pool_headroom"
    app.execute(AdvanceTime(1))
    assert state.progress_days == pytest.approx(before_progress)
    assert state.research_points_awarded == pytest.approx(before_awarded)
    assert sim.research.stored_points == pytest.approx(capacity)

    # Provider generation and active exploration consume the same RP admission
    # headroom. This is the cross-domain contract; provider-only fairness is
    # covered by the common admission allocator tests.
    headroom = 2.0
    sim.research.stored_points = capacity - headroom
    provider = app.query(GetResearch()).providers[0]
    recovered = _row(app)
    assert provider.admitted_generation_points_per_day > 0.0
    assert recovered.rp_admitted_today > 0.0
    assert recovered.rp_admitted_today < recovered.rp_requested_today
    assert (
        provider.admitted_generation_points_per_day + recovered.rp_admitted_today
        == pytest.approx(headroom)
    )
    admitted_science = recovered.rp_admitted_today
    app.execute(AdvanceTime(1))
    assert state.progress_days == pytest.approx(before_progress + admitted_science / definition.points_per_day)
    assert state.research_points_awarded == pytest.approx(before_awarded + admitted_science)
    assert sim.research.stored_points == pytest.approx(capacity)

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


def test_scientific_exploration_technology_is_a_start_requirement_not_an_in_flight_lock():
    from space_idle.app_contracts.common import ApplicationError

    app = build_game_application()
    sim = app._simulation
    mission_id = ids.MARS_ORBIT_SCIENCE_EXPLORATION
    definition = sim.scientific_exploration.definitions[mission_id]
    assert definition.prerequisite_technologies
    mission = next(row for row in app.query(GetScientificExplorations()).items
                   if row.id == str(mission_id))
    assert not mission.can_start
    assert set(mission.prerequisite_technologies) == set(map(str, definition.prerequisite_technologies))
    assert {f"technology:{tech_id}" for tech_id in definition.prerequisite_technologies} <= {
        row.code for row in mission.blockers
    }
    with pytest.raises(ApplicationError, match="technology"):
        app.execute(StartScientificExploration(str(mission_id)))
    assert mission_id not in sim.scientific_exploration.campaigns
    assert any(
        unlock.kind == "scientific_exploration" and unlock.id == str(mission_id)
        for research in app.query(GetResearch()).items for unlock in research.unlocks
    )

    sim.technology.completed.update(definition.prerequisite_technologies)
    assert next(row for row in app.query(GetScientificExplorations()).items
                if row.id == str(mission_id)).can_start
    app.execute(StartScientificExploration(str(mission_id)))
    sim.technology.completed.difference_update(definition.prerequisite_technologies)
    assert sim.scientific_exploration.blockers(mission_id) == ("fleet_unassigned",)
    assert sim.scientific_exploration.campaigns[mission_id].phase.value == "awaiting_fleet"
    assert not next(row for row in app.query(GetScientificExplorations()).items
                    if row.id == str(mission_id)).can_start


def _start_unoperated_science(app):
    sim = app._simulation
    mission_id = ids.MARS_ORBIT_SCIENCE_EXPLORATION
    # The scenario under test concerns Fleet ownership after a legitimate
    # campaign acquisition, not whether the method has been researched.
    sim.technology.completed.update(
        sim.scientific_exploration.definitions[mission_id].prerequisite_technologies
    )
    vehicle_id = ids.DEEP_SPACE_PROBE
    sim.transport.add_fleet_units(vehicle_id, 1, ids.LEO)
    app.execute(StartScientificExploration(str(mission_id)))
    app.execute(AssignExplorationFleet(str(mission_id), str(vehicle_id)))
    definition = sim.scientific_exploration.definitions[mission_id]
    state = sim.scientific_exploration.campaigns[mission_id]
    needs = sim.scientific_exploration._preparation_requirements(definition, state, sim.day)
    for node, resource, amount, _ in needs:
        sim.inventory.add(node, resource, amount + 1.0)
    start_balances = {(node, resource): sim.inventory.amount(node, resource)
                      for node, resource, _amount, _ in needs}
    app.execute(AdvanceTime(2))
    assert state.phase.value == "outbound"
    return state, start_balances, needs


def _arrive_unoperated_science(app):
    sim = app._simulation
    state = sim.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION]
    execution = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(execution.completion_day - sim.day))
    assert state.phase.value == "active"
    commitment = sim.transport.fleet_commitment_snapshot(state.fleet_commitment_id)
    assert commitment.operational_node_id is None
    assert commitment.physical_target.physical_target_node_id == ids.MARS_ORBIT
    view = next(row for row in app.query(GetScientificExplorations()).items
                if row.id == str(ids.MARS_ORBIT_SCIENCE_EXPLORATION))
    assert view.destination_kind == "non_surface_spatial_node"
    assert view.fleet_location_kind == "physical_target"
    assert view.fleet_location_id == str(ids.MARS_ORBIT)
    assert not view.can_set_completion_disposition
    assert ids.MARS_ORBIT not in sim.graph.operational_node_ids()
    assert not any(node == ids.MARS_ORBIT for node, _vehicle in sim.transport.fleet_pools)
    assert not any(node == ids.MARS_ORBIT for node, _resource in sim.inventory.stock)
    validate_runtime_state(sim)


def _finish_unoperated_science(app):
    sim = app._simulation
    state = sim.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION]
    if state.phase.value == "active":
        sim.research.stored_points = 0.0
        app.execute(AdvanceTime(12))
        assert state.phase.value == "return_preparing"
    app.execute(AdvanceTime(1))
    assert state.phase.value == "returning"
    execution = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(execution.completion_day - sim.day))
    validate_runtime_state(sim)
    assert state.fleet_commitment_id is None
    assert state.movement_execution_id is None
    assert sim.transport.fleet_free_units(ids.DEEP_SPACE_PROBE, ids.LEO) == 1
    assert ids.MARS_ORBIT not in sim.graph.operational_node_ids()


def test_unoperated_science_conserves_fleet_resources_and_state_through_replay_and_abort(
    tmp_path, short_interplanetary_transit,
):
    app = build_game_application()
    sim = app._simulation
    before_survey = capture_state(sim)["survey"]
    initial_owned_nodes = set(sim.graph.operational_node_ids())
    assert ids.MARS_ORBIT not in initial_owned_nodes
    state, initial_balances, needs = _start_unoperated_science(app)
    assert needs and all(node == ids.LEO for node, _, _, _ in needs)
    for node, resource, amount, _ in needs:
        # Ordinary facility maintenance can also draw from the same inventory.
        assert initial_balances[node, resource] - sim.inventory.amount(node, resource) + 1e-9 >= amount
    _arrive_unoperated_science(app)
    path = tmp_path / "unoperated-science.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)
    assert capture_state(loaded._simulation)["transport"] == capture_state(app._simulation)["transport"]
    assert capture_state(loaded._simulation)["scientific_exploration"] == capture_state(app._simulation)["scientific_exploration"]
    for current in (app, loaded):
        current._simulation.research.stored_points = 0.0
        current.execute(AdvanceTime(12))
        assert current._simulation.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION].phase.value == "return_preparing"
        current.execute(AdvanceTime(1))
        assert current._simulation.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION].phase.value == "returning"
    assert capture_state(loaded._simulation)["transport"] == capture_state(app._simulation)["transport"]
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    returning_load, _ = load_game(path, build_game_application_for_load)
    assert capture_state(returning_load._simulation)["transport"] == capture_state(app._simulation)["transport"]
    for current in (app, loaded, returning_load):
        _finish_unoperated_science(current)
    assert capture_state(loaded._simulation)["transport"] == capture_state(app._simulation)["transport"]
    assert capture_state(returning_load._simulation)["transport"] == capture_state(app._simulation)["transport"]
    assert capture_state(loaded._simulation)["scientific_exploration"] == capture_state(app._simulation)["scientific_exploration"]
    assert state.phase.value == "complete"
    definition = sim.scientific_exploration.definitions[ids.MARS_ORBIT_SCIENCE_EXPLORATION]
    assert state.research_points_awarded == pytest.approx(definition.research_points_total)
    assert capture_state(sim)["survey"] == before_survey
    assert set(sim.graph.operational_node_ids()) == initial_owned_nodes
    for node, resource, _, _ in needs:
        assert sim.inventory.amount(node, resource) <= initial_balances[node, resource]

    aborted = build_game_application()
    _start_unoperated_science(aborted)
    aborted.execute(AbortScientificExploration(str(ids.MARS_ORBIT_SCIENCE_EXPLORATION)))
    assert aborted._simulation.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION].phase.value == "outbound"
    _arrive_unoperated_science_on_abort(aborted)
    _finish_unoperated_science(aborted)
    assert aborted._simulation.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION].phase.value == "aborted"


def _arrive_unoperated_science_on_abort(app):
    sim = app._simulation
    state = sim.scientific_exploration.campaigns[ids.MARS_ORBIT_SCIENCE_EXPLORATION]
    execution = sim.transport.movement_executions[state.movement_execution_id]
    app.execute(AdvanceTime(execution.completion_day - sim.day))
    assert state.phase.value == "return_preparing"
    commitment = sim.transport.fleet_commitment_snapshot(state.fleet_commitment_id)
    assert commitment.physical_target.physical_target_node_id == ids.MARS_ORBIT
    validate_runtime_state(sim)


def test_crewed_exploration_keeps_population_and_onboard_resources_until_physical_return(tmp_path):
    """Mission crew cannot be reallocated while the real Fleet is transporting it."""
    app = build_game_application()
    sim = app._simulation
    mission = ids.CREWED_CISLUNAR_EXPEDITION
    craft = ids.REUSABLE_ORBITAL_CARGO_TUG
    service = sim.scientific_exploration
    sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LEO)
    destination_habitat = sim.facilities.install(ids.CREWED_ORBITAL_LABORATORY, ids.LUNAR_ORBIT)
    sim.refresh_storage()
    sim.population.initialize(ids.LEO, 2)
    for resource in (ids.FOOD, ids.WATER, ids.OXYGEN, ids.PROPELLANT):
        sim.inventory.add(ids.LEO, resource, 50.0)
        if resource != ids.PROPELLANT:
            sim.inventory.add(ids.LUNAR_ORBIT, resource, 50.0)

    initial_people = sum(group.count for group in sim.population.groups.values())
    app.execute(StartScientificExploration(str(mission)))
    assert app.query(GetScientificExplorations()).items
    row = next(row for row in app.query(GetScientificExplorations()).items if row.id == str(mission))
    assert row.required_crew == 2 and row.committed_crew == 0
    assert any(option.vehicle_definition_id == str(craft) and not option.blockers for option in row.fleet_options)
    app.execute(AssignExplorationFleet(str(mission), str(craft)))
    state = service.campaigns[mission]
    for node_id, resource, amount, _purpose in service._preparation_requirements(service.definitions[mission], state, sim.day):
        if sim.inventory.available(node_id, resource) + 1e-9 < amount:
            sim.inventory.add(node_id, resource, amount)
    app.execute(AdvanceTime(2))
    assert state.phase.value == 'outbound'
    crew = sim.population.activity_groups(service._crew_owner(service.definitions[mission]))
    assert sum(group.count for group in crew) == 2
    assert sim.population.activity_work_fraction(service._crew_owner(service.definitions[mission]), 2) == pytest.approx(1.0)
    assert all(group.position.kind == 'transport_execution' for group in crew)
    assert sim.population.free_count_at(ids.LEO) == 0
    cabin = sim.transport.fleet_commitment_snapshot(state.fleet_commitment_id)
    assert sum(amount for _, amount in cabin.onboard_resources) > 0
    spec = sim.transport.vehicle_definition(craft).passengers
    assert spec.loaded_payload_mass(2, dict(cabin.onboard_resources)) > 2 * spec.person_mass_t
    assert sum(group.count for group in sim.population.groups.values()) == initial_people
    save_path = tmp_path / 'crewed-science.json'
    save_game(app, save_path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(save_path, build_game_application_for_load)
    assert capture_state(loaded._simulation)['population'] == capture_state(sim)['population']
    assert capture_state(loaded._simulation)['transport'] == capture_state(sim)['transport']
    completion = sim.transport.movement_execution_snapshot(state.movement_execution_id).completion_day
    sim.facilities.pause(destination_habitat)
    app.execute(AdvanceTime(completion - sim.day))
    assert state.phase.value == 'outbound'
    assert all(group.position.kind == 'transport_execution' for group in sim.population.activity_groups(service._crew_owner(service.definitions[mission])))
    sim.facilities.resume(destination_habitat)
    app.execute(AdvanceTime(1))
    assert state.phase.value == 'active'
    assert all(group.position.kind == 'operational_node' for group in sim.population.activity_groups(service._crew_owner(service.definitions[mission])))
    assert all(group.activity_commitment_ref is not None for group in sim.population.activity_groups(service._crew_owner(service.definitions[mission])))
    assert sum(group.count for group in sim.population.groups.values()) == initial_people
    while state.phase.value == 'active':
        app.execute(AdvanceTime(1))
    assert state.phase.value == 'return_preparing'
    # Seed an additional physical onboard provision at the established return
    # port. This tests independent Crew admission and Fleet cargo recovery when
    # the vessel returns with surplus supplies, not a probabilistic mishap.
    sim.inventory.consume_allocated(ids.LUNAR_ORBIT, ids.WATER, 1.0)
    onboard_state = sim.transport.fleet_commitments[state.fleet_commitment_id]
    onboard_state.onboard_resources[ids.WATER] = onboard_state.onboard_resources.get(ids.WATER, 0.0) + 1.0
    for node_id, resource, amount, _purpose in service._preparation_requirements(
        service.definitions[mission], state, sim.day, returning=True
    ):
        if sim.inventory.available(node_id, resource) + 1e-9 < amount:
            sim.inventory.add(node_id, resource, amount)
    app.execute(AdvanceTime(2))
    assert state.phase.value == 'returning'
    returning = sim.transport.movement_execution_snapshot(state.movement_execution_id)
    assert returning is not None
    assert sim.population.free_count_at(ids.LEO) == 0
    # Occupy the actual shared Inventory pool before landing. Crew can
    # disembark, but the Fleet and its leftover physical Resource must stay
    # committed until that pool can receive the cabin provisions.
    pool = sim.inventory.storage_pool_for_resource(ids.WATER)
    fill_amount = sim.inventory.admission_state_for_pool(ids.LEO, pool).admission_capacity_t
    sim.inventory.add(ids.LEO, ids.MINERAL_FEEDSTOCK, fill_amount)
    app.execute(AdvanceTime(returning.completion_day - sim.day))
    assert state.phase.value == 'recovering'
    assert sim.population.free_count_at(ids.LEO) == 2
    assert state.fleet_commitment_id is not None
    assert sim.transport.fleet_commitment_snapshot(state.fleet_commitment_id).onboard_resources
    waiting_row = next(row for row in app.query(GetScientificExplorations()).items if row.id == str(mission))
    assert any(blocker.code == 'onboard_resource_admission' for blocker in waiting_row.blockers)
    recovery_path = tmp_path / 'crewed-recovery.json'
    save_game(app, recovery_path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    recovery_loaded, _ = load_game(recovery_path, build_game_application_for_load)
    assert capture_state(recovery_loaded._simulation) == capture_state(sim)
    sim.inventory.consume_allocated(ids.LEO, ids.MINERAL_FEEDSTOCK, 1.0)
    app.execute(AdvanceTime(1))
    assert state.phase.value == 'complete'
    assert sim.population.free_count_at(ids.LEO) == 2
    assert sim.transport.fleet_free_units(craft, ids.LEO) >= 1
    assert sum(group.count for group in sim.population.groups.values()) == initial_people
    assert not sim.population.activity_groups(service._crew_owner(service.definitions[mission]))
    # Canonical day and offline/save replay preserve crew, Fleet and Resource stock.
    loaded._simulation.facilities.pause(destination_habitat)
    loaded.execute(AdvanceTime(completion - loaded._simulation.day))
    loaded._simulation.facilities.resume(destination_habitat)
    loaded.execute(AdvanceTime(1))
    loaded_science = loaded._simulation.scientific_exploration
    loaded_mission = loaded_science.campaigns[mission]
    assert loaded_mission.phase.value == 'active'
    while loaded_mission.phase.value == 'active':
        loaded.execute(AdvanceTime(1))
    loaded._simulation.inventory.consume_allocated(ids.LUNAR_ORBIT, ids.WATER, 1.0)
    loaded_onboard = loaded._simulation.transport.fleet_commitments[loaded_mission.fleet_commitment_id]
    loaded_onboard.onboard_resources[ids.WATER] = loaded_onboard.onboard_resources.get(ids.WATER, 0.0) + 1.0
    for node_id, resource, amount, _purpose in loaded_science._preparation_requirements(
        loaded_science.definitions[mission], loaded_mission, loaded._simulation.day, returning=True
    ):
        if loaded._simulation.inventory.available(node_id, resource) + 1e-9 < amount:
            loaded._simulation.inventory.add(node_id, resource, amount)
    loaded.execute(AdvanceTime(2))
    back = loaded._simulation.transport.movement_execution_snapshot(loaded_mission.movement_execution_id)
    loaded_pool = loaded._simulation.inventory.storage_pool_for_resource(ids.WATER)
    loaded_fill = loaded._simulation.inventory.admission_state_for_pool(ids.LEO, loaded_pool).admission_capacity_t
    loaded._simulation.inventory.add(ids.LEO, ids.MINERAL_FEEDSTOCK, loaded_fill)
    loaded.execute(AdvanceTime(back.completion_day - loaded._simulation.day))
    assert loaded_mission.phase.value == 'recovering'
    loaded._simulation.inventory.consume_allocated(ids.LEO, ids.MINERAL_FEEDSTOCK, 1.0)
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(sim)
