from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CancelFleetRetirement,
    GetFleet,
    RetireFleet,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.facilities import CapabilitySupply, FacilityDef, ServiceCapacitySupply
from space_idle.site import (
    CapabilityRequirement,
    CapabilityRequirementState,
    SiteRequirements,
)
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import DefinitionId, EntityId
from space_idle.transport.models import FleetActivityRef, FleetRetirementPhase


def test_fleet_retirement_commits_only_free_units_and_is_reversible_before_dismantling():
    app = build_game_application()
    sim = app._simulation
    pool = sim.transport.fleet_pool(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    pool.total_units = 2

    sim.transport.commit_fleet_units(
        EntityId("test.exploration"),
        FleetActivityRef("test_exploration", EntityId("test.owner")),
        ids.REUSABLE_LAUNCH_VEHICLE,
        ids.EARTH,
        1,
    )
    with pytest.raises(ApplicationError, match="free Fleet"):
        app.execute(RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 2, str(ids.EARTH)))

    retirement_id = app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=4)
    ).created_id
    assert retirement_id is not None
    snapshot = sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    assert snapshot.total_units == 2
    assert snapshot.free_units == 0
    assert snapshot.retirement_units == 1

    app.execute(CancelFleetRetirement(retirement_id))
    snapshot = sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    assert snapshot.total_units == 2
    assert snapshot.retirement_units == 0
    assert snapshot.free_units == 1


def test_fleet_retirement_becomes_irreversible_and_settles_salvage_before_decrement():
    app = build_game_application()
    sim = app._simulation
    control = build_game_application()
    retirement_id = app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=5)
    ).created_id
    assert retirement_id is not None

    app.execute(AdvanceTime(1))
    state = sim.transport.fleet_retirements[EntityId(retirement_id)]
    assert state.irreversible_started
    assert state.phase is FleetRetirementPhase.DISMANTLING
    assert sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH).total_units == 1
    with pytest.raises(ApplicationError, match="cannot be cancelled"):
        app.execute(CancelFleetRetirement(retirement_id))

    app.execute(AdvanceTime(5))
    state = sim.transport.fleet_retirements[EntityId(retirement_id)]
    assert state.phase is FleetRetirementPhase.COMPLETE
    snapshot = sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    assert snapshot.total_units == 0
    assert snapshot.retirement_units == 0
    control.execute(AdvanceTime(6))
    assert sim.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS) == pytest.approx(
        control._simulation.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS) + 10.0
    )


def test_fleet_retirement_application_projection_and_save_load_preserve_commitment(tmp_path):
    app = build_game_application()
    retirement_id = app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=2)
    ).created_id
    assert retirement_id is not None

    fleet = app.query(GetFleet())
    retirement = next(row for row in fleet.retirements if row.id == retirement_id)
    assert retirement.phase == "committed"
    assert not retirement.irreversible_started
    assert retirement.required_work == pytest.approx(5.0)
    assert retirement.expected_salvage
    assert next(row for row in fleet.pools if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)).retirement_units == 1

    path = tmp_path / "retirement.json"
    save_game(app, path, saved_at=datetime(2026, 9, 17, tzinfo=timezone.utc))
    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    loaded_retirement = loaded._simulation.transport.fleet_retirements[EntityId(retirement_id)]
    assert loaded_retirement.phase is FleetRetirementPhase.COMMITTED
    assert loaded_retirement.requested_units == 1


def test_fleet_retirement_rechecks_site_requirements_during_execution():
    app = build_game_application()
    sim = app._simulation
    capability = "test.retirement_access"
    provider_definition_id = DefinitionId("test.facility.retirement_access")
    sim.facilities.definitions[provider_definition_id] = FacilityDef(
        provider_definition_id,
        "Retirement access provider",
        capability_supplies=(CapabilitySupply(capability),),
    )
    provider_id = sim.facilities.install(provider_definition_id, ids.EARTH)

    base = sim.transport.vehicle_defs[ids.REUSABLE_LAUNCH_VEHICLE]
    sim.transport.vehicle_defs[ids.REUSABLE_LAUNCH_VEHICLE] = replace(
        base,
        retirement=replace(
            base.retirement,
            site_requirements=SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement(capability, CapabilityRequirementState.ACTIVE),
                )
            ),
        ),
    )

    retirement_id = app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=5)
    ).created_id
    assert retirement_id is not None
    sim.facilities.pause(provider_id)

    app.execute(AdvanceTime(1))
    state = sim.transport.fleet_retirements[EntityId(retirement_id)]
    assert state.progress_work == pytest.approx(0.0)
    assert not state.irreversible_started
    assert any(blocker.startswith("site:capability:active:") for blocker in sim.transport.fleet_retirement_blockers(state.id, day=sim.day))

    sim.facilities.resume(provider_id)
    app.execute(AdvanceTime(1))
    assert state.progress_work > 0.0
    assert state.irreversible_started


def test_fleet_retirement_priority_competes_for_shared_work_capacity():
    app = build_game_application()
    sim = app._simulation
    sim.transport.fleet_pool(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH).total_units = 2

    high_id = EntityId(app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=5)
    ).created_id)
    low_id = EntityId(app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=1)
    ).created_id)

    app.execute(AdvanceTime(1))
    high = sim.transport.fleet_retirements[high_id]
    low = sim.transport.fleet_retirements[low_id]
    assert high.progress_work > 0.0
    assert low.progress_work == pytest.approx(0.0)
    assert high.irreversible_started
    assert not low.irreversible_started


def test_fleet_retirement_salvage_blocker_uses_shared_storage_class_headroom():
    app = build_game_application()
    sim = app._simulation
    sim.transport.fleet_pool(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH).total_units = 1

    retirement_id = EntityId(app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=5)
    ).created_id)
    state = sim.transport.fleet_retirements[retirement_id]
    definition = sim.transport.vehicle_defs[state.vehicle_definition_id]
    required_work = definition.retirement.work_days_per_unit * state.requested_units

    for _ in range(10):
        app.execute(AdvanceTime(1))
        if state.progress_work + 1e-9 >= required_work:
            break
    assert state.progress_work == pytest.approx(required_work)
    assert state.phase is FleetRetirementPhase.DISMANTLING

    storage_class = sim.inventory.resource_storage_class[ids.STRUCTURAL_COMPONENTS]
    salvage = tuple(
        (resource_id, amount_per_unit * state.requested_units)
        for resource_id, amount_per_unit in definition.retirement.recovery_resources_per_unit
        if amount_per_unit * state.requested_units > 0.0
    )
    salvage_total = sum(
        amount
        for resource_id, amount in salvage
        if sim.inventory.resource_storage_class.get(resource_id) == storage_class
    )
    largest_component = max(
        amount
        for resource_id, amount in salvage
        if sim.inventory.resource_storage_class.get(resource_id) == storage_class
    )
    assert salvage_total > largest_component

    admission = sim.inventory.admission_state_for_class(ids.EARTH, storage_class)
    assert admission.admission_capacity_t is not None
    target_headroom = (salvage_total + largest_component) / 2.0
    filler = ids.CONSTRUCTION_EQUIPMENT
    sim.inventory.stock[(ids.EARTH, filler)] = sim.inventory.amount(ids.EARTH, filler) + (
        admission.admission_capacity_t - target_headroom
    )

    admission = sim.inventory.admission_state_for_class(ids.EARTH, storage_class)
    assert admission.admission_capacity_t is not None
    assert largest_component < admission.admission_capacity_t < salvage_total
    assert f"salvage_admission:{storage_class}" in sim.transport.fleet_retirement_blockers(
        retirement_id, day=sim.day
    )


def test_fleet_retirement_at_non_earth_node_waits_for_salvage_admission():
    app = build_game_application()
    sim = app._simulation
    workshop_definition_id = DefinitionId("test.facility.orbital_vehicle_workshop")
    sim.facilities.definitions[workshop_definition_id] = FacilityDef(
        workshop_definition_id,
        "Orbital vehicle workshop",
        service_capacity_supplies=(ServiceCapacitySupply("vehicle_assembly", 1.0),),
    )
    sim.facilities.install(workshop_definition_id, ids.LUNAR_ORBIT)
    sim.transport.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT).total_units = 1

    storage_class = sim.inventory.resource_storage_class[ids.STRUCTURAL_COMPONENTS]
    capacity = sim.inventory.usable_storage_capacity_t[(ids.LUNAR_ORBIT, storage_class)]
    occupied_without_structural = sim.inventory.stored_in_class(ids.LUNAR_ORBIT, storage_class) - sim.inventory.amount(
        ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS
    )
    sim.inventory.stock[(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS)] = max(
        0.0, capacity - occupied_without_structural - 1.0
    )

    retirement_id = EntityId(app.execute(
        RetireFleet(
            str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1, str(ids.LUNAR_ORBIT), priority=5
        )
    ).created_id)

    app.execute(AdvanceTime(3))
    state = sim.transport.fleet_retirements[retirement_id]
    assert state.progress_work == pytest.approx(2.0)
    assert state.phase is FleetRetirementPhase.DISMANTLING
    assert sim.transport.fleet_pool_snapshot(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT
    ).total_units == 1
    assert any(
        blocker.startswith("salvage_admission:")
        for blocker in sim.transport.fleet_retirement_blockers(retirement_id, day=sim.day)
    )

    key = (ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS)
    sim.inventory.stock[key] = sim.inventory.stock[key] - 10.0
    app.execute(AdvanceTime(1))
    assert sim.transport.fleet_retirements[retirement_id].phase is FleetRetirementPhase.COMPLETE
    assert sim.transport.fleet_pool_snapshot(
        ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LUNAR_ORBIT
    ).total_units == 0
