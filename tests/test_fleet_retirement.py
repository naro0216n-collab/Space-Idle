from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from math import ceil

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
from space_idle.facilities import CapabilitySupply, FacilityDef
from space_idle.site import (
    CapabilityRequirement,
    CapabilityRequirementState,
    SiteRequirements,
)
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import DefinitionId, EntityId
from space_idle.transport.models import FleetActivityRef, FleetRetirementPhase


def test_fleet_retirement_lifecycle_preserves_commitment_across_projection_save_load_and_settles_salvage(tmp_path):
    reversible = build_game_application()
    sim = reversible._simulation
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
        reversible.execute(RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 2, str(ids.EARTH)))

    retirement_id = reversible.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=4)
    ).created_id
    assert retirement_id is not None
    snapshot = sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    assert snapshot.total_units == 2
    assert snapshot.free_units == 0
    assert snapshot.retirement_units == 1

    reversible.execute(CancelFleetRetirement(retirement_id))
    snapshot = sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    assert snapshot.total_units == 2
    assert snapshot.retirement_units == 0
    assert snapshot.free_units == 1

    app = build_game_application()
    sim = app._simulation
    control = build_game_application()
    retirement_id = app.execute(
        RetireFleet(str(ids.REUSABLE_LAUNCH_VEHICLE), 1, str(ids.EARTH), priority=5)
    ).created_id
    assert retirement_id is not None
    retirement_entity_id = EntityId(retirement_id)
    work_bundle = next(
        row
        for row in sim.transport.fleet_retirement_execution_requirement_bundles(sim.day)
        if row.owner_id == retirement_entity_id and row.purpose == "dismantling"
    )
    assert int(work_bundle.priority) == 5
    assert any(
        key.kind == "service" and key.name == "vehicle_assembly"
        for key, _coefficient in work_bundle.coefficients()
    )

    fleet = app.query(GetFleet())
    retirement = next(row for row in fleet.retirements if row.id == retirement_id)
    assert retirement.phase == "committed"
    assert not retirement.irreversible_started
    retirement_spec = sim.transport.vehicle_defs[ids.REUSABLE_LAUNCH_VEHICLE].retirement
    assert retirement.required_work == pytest.approx(retirement_spec.work_days_per_unit)
    assert retirement.expected_salvage
    assert next(
        row for row in fleet.pools
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE)
    ).retirement_units == 1

    path = tmp_path / "retirement.json"
    save_game(app, path, saved_at=datetime(2026, 9, 17, tzinfo=timezone.utc))
    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    app = loaded
    sim = loaded._simulation
    loaded_retirement = sim.transport.fleet_retirements[EntityId(retirement_id)]
    assert loaded_retirement.phase is FleetRetirementPhase.COMMITTED
    assert loaded_retirement.requested_units == 1

    app.execute(AdvanceTime(1))
    state = sim.transport.fleet_retirements[EntityId(retirement_id)]
    assert state.irreversible_started
    assert state.phase is FleetRetirementPhase.DISMANTLING
    assert sim.transport.fleet_pool_snapshot(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH
    ).total_units == 1
    with pytest.raises(ApplicationError, match="cannot be cancelled"):
        app.execute(CancelFleetRetirement(retirement_id))

    finish_days = ceil(retirement_spec.work_days_per_unit) + 1
    app.execute(AdvanceTime(finish_days))
    state = sim.transport.fleet_retirements[EntityId(retirement_id)]
    assert state.phase is FleetRetirementPhase.COMPLETE
    assert state.salvage_recovered_fraction == pytest.approx(1.0)
    snapshot = sim.transport.fleet_pool_snapshot(ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH)
    assert snapshot.total_units == 0
    assert snapshot.retirement_units == 0
    control.execute(AdvanceTime(1 + finish_days))
    for resource_id, quantity in retirement_spec.recovery_resources_per_unit:
        assert sim.inventory.amount(ids.EARTH, resource_id) == pytest.approx(
            control._simulation.inventory.amount(ids.EARTH, resource_id) + quantity
        )

    completed_stock = {
        resource_id: sim.inventory.amount(ids.EARTH, resource_id)
        for resource_id, _amount in sim.transport.vehicle_defs[
            ids.REUSABLE_LAUNCH_VEHICLE
        ].retirement.recovery_resources_per_unit
    }
    completed_path = tmp_path / "retirement-complete.json"
    save_game(app, completed_path, saved_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
    reloaded, offline = load_game(completed_path, build_game_application_for_load)
    assert offline is None
    control_after_load, offline = load_game(completed_path, build_game_application_for_load)
    assert offline is None
    control_after_load._simulation.transport.fleet_retirements.pop(EntityId(retirement_id))
    reloaded.execute(AdvanceTime(1))
    control_after_load.execute(AdvanceTime(1))
    reloaded_state = reloaded._simulation.transport.fleet_retirements[EntityId(retirement_id)]
    assert reloaded_state.phase is FleetRetirementPhase.COMPLETE
    assert reloaded_state.salvage_recovered_fraction == pytest.approx(1.0)
    assert reloaded._simulation.transport.fleet_pool_snapshot(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH
    ).total_units == 0
    for resource_id in completed_stock:
        assert reloaded._simulation.inventory.amount(ids.EARTH, resource_id) == pytest.approx(
            control_after_load._simulation.inventory.amount(ids.EARTH, resource_id)
        )




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
