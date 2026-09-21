from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    GetLogistics,
    PauseFacility,
    ProduceVehicle,
    SetVehicleProductionSettings,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO, REUSABLE_ORBITAL_CARGO_TUG, ROBOTIC_SURVEY_PACKAGE
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import EntityId
from space_idle.site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements


def test_vehicle_production_application_contract_exposes_planning_blockers_and_priority_lifecycle():
    app = build_game_application()
    option = next(
        row
        for row in app.query(GetLogistics()).vehicle_production_options
        if row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
        and row.operational_node_id == str(LEO)
    )
    service_blocker = next(
        blocker
        for blocker in option.blockers
        if blocker.kind == "service" and blocker.subject_id == "vehicle_assembly"
    )
    assert service_blocker.current == 0
    assert service_blocker.required == "positive"
    assert service_blocker.affected_action == "plan_vehicle_production"
    assert service_blocker.related_entity_kind == "vehicle_definition"
    assert option.can_plan is True
    assert app.execute(
        ProduceVehicle(str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(LEO), priority=3)
    ).created_id is not None

    production_id = app.execute(ProduceVehicle(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(EARTH), priority=2,
    )).created_id
    assert production_id is not None

    row = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert row.priority == 2
    assert row.priority_editable is True
    assert row.production_service_type == "vehicle_assembly"
    demands = tuple(
        demand
        for demand in app.query(GetLogistics()).requirements
        if demand.owner_kind == "vehicle_production" and demand.owner_id == production_id
    )
    assert demands and {d.priority for d in demands} == {2}

    app.execute(SetVehicleProductionSettings(production_id, priority=5))
    updated = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert updated.priority == 5

    app.execute(AdvanceTime(1))
    building = next(
        item for item in app.query(GetLogistics()).vehicle_production
        if item.id == production_id
    )
    assert building.phase == "building"
    assert building.priority_editable is False
    with pytest.raises(
        ApplicationError, match="priority can only change before inputs are consumed"
    ):
        app.execute(SetVehicleProductionSettings(production_id, priority=1))


def test_vehicle_production_progress_uses_same_runtime_site_blockers_as_query():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.transport.vehicle_defs[vehicle_id]
    sim.transport.vehicle_defs[vehicle_id] = replace(
        definition,
        production=replace(
            definition.production,
            site_requirements=SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement("spacecraft_servicing", CapabilityRequirementState.ACTIVE),
                ),
            ),
        ),
    )
    servicing_id = sim.facilities.install(
        ROBOTIC_SURVEY_PACKAGE,
        EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    sim.refresh_storage()

    result = app.execute(ProduceVehicle(str(vehicle_id), str(EARTH)))
    project_id = next(
        pid for pid in sim.transport.vehicle_production_projects
        if str(pid) == result.created_id
    )
    state = sim.transport.vehicle_production_projects[project_id]
    app.execute(AdvanceTime(1))
    assert state.phase.value == "building"
    started_progress = state.progress_days
    assert started_progress > 0

    app.execute(PauseFacility(str(servicing_id)))
    blockers = sim.transport.vehicle_production_blockers(project_id, day=sim.day)
    assert any("spacecraft_servicing" in blocker for blocker in blockers)

    app.execute(AdvanceTime(1))
    assert state.phase.value == "building"
    assert state.progress_days == pytest.approx(started_progress)


def test_save_load_preserves_vehicle_production_staging_and_future_completion(tmp_path):
    app = build_game_application()
    sim = app._simulation
    definition = sim.transport.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG]
    for resource_id, _required_t in definition.production.resources:
        sim.inventory.stock[(EARTH, resource_id)] = 0.0
    partial_resource, required_t = next(
        (resource_id, required_t)
        for resource_id, required_t in definition.production.resources
        if required_t > 0.0
    )
    partial_stock = required_t * 0.5
    sim.inventory.stock[(EARTH, partial_resource)] = partial_stock

    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = EntityId(result.created_id)
    app.execute(AdvanceTime(1))
    original = sim.transport.vehicle_production_projects[production_id]
    remaining_on_hand = sim.inventory.amount(EARTH, partial_resource)
    assert original.phase.value == "awaiting_inputs"
    assert partial_stock - remaining_on_hand > 0.0

    before = capture_state(sim)
    path = tmp_path / "vehicle-production.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)
    loaded_state = capture_state(loaded._simulation)
    assert loaded_state["transport"] == before["transport"]
    assert loaded_state["inventory"] == before["inventory"]

    before_units = loaded._simulation.transport.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units
    for current in (app._simulation, loaded._simulation):
        for resource_id, resource_required_t in definition.production.resources:
            current.inventory.stock[(EARTH, resource_id)] = max(
                current.inventory.amount(EARTH, resource_id), resource_required_t * 2.0
            )

    production_days = int(definition.production.days)
    app.execute(AdvanceTime(production_days))
    loaded.execute(AdvanceTime(production_days))
    state = loaded._simulation.transport.vehicle_production_projects[production_id]
    assert state.phase.value == "complete"
    assert state.completed_units == 1
    assert loaded._simulation.transport.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units == before_units + 1
    loaded_future = capture_state(loaded._simulation)
    original_future = capture_state(app._simulation)
    assert loaded_future["transport"] == original_future["transport"]
    assert loaded_future["inventory"] == original_future["inventory"]

