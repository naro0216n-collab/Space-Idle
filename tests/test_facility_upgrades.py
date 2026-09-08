from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    GetLocation,
    GetProjects,
    PauseBuild,
    PlanFacilityUpgrade,
    ResumeBuild,
    SetConstructionWeight,
    build_game_application,
)
from space_idle.application_commands import ApplicationError
from space_idle.content.base_game import EARTH, EARTH_RESEARCH_LAB
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import EntityId


def _earth_lab(app):
    row = next(
        facility
        for facility in app.query(GetLocation(str(EARTH))).facilities
        if facility.definition_id == str(EARTH_RESEARCH_LAB)
    )
    state = app._simulation.facilities.facilities[EntityId(row.id)]
    return row, state


def _unlock_next_upgrade(app, facility_state):
    recipe = app._simulation.projects.next_upgrade_recipe(facility_state.id)
    assert recipe is not None
    app._simulation.technology.completed.update(recipe.prerequisite_technologies)
    return recipe


def _project(app, project_id):
    return next(row for row in app.query(GetProjects()).items if row.id == project_id)


def test_facility_upgrade_is_a_resource_backed_construction_project():
    app = build_game_application()
    before_row, facility = _earth_lab(app)
    recipe = _unlock_next_upgrade(app, facility)
    provider = app._simulation.research.providers[facility.definition_id]
    before_provider_spec = provider.level_spec(facility.level)
    next_provider_spec = provider.level_spec(facility.level + 1)
    assert (
        before_provider_spec.generation_points_per_day,
        before_provider_spec.storage_capacity_points,
    ) != (
        next_provider_spec.generation_points_per_day,
        next_provider_spec.storage_capacity_points,
    )

    stock_before = {
        component.import_resource_id: app._simulation.inventory.amount(
            facility.location_id, component.import_resource_id
        )
        for component in recipe.components
    }

    result = app.execute(
        PlanFacilityUpgrade(
            before_row.id,
            priority=100,
            sourcing_policy="import_now",
        )
    )
    assert result.created_id is not None
    project_id = result.created_id

    planned = _project(app, project_id)
    assert planned.target_kind == "facility_upgrade"
    assert planned.target_facility_id == before_row.id
    assert planned.target_level == facility.level + 1
    assert facility.level == 1
    assert not planned.materials_committed

    # Pausing uses the same project state machine and cannot mutate the facility level.
    app.execute(PauseBuild(project_id))
    app.execute(AdvanceTime(3))
    paused = _project(app, project_id)
    assert paused.paused
    assert paused.construction_done == 0
    assert facility.level == 1

    app.execute(ResumeBuild(project_id))
    for _ in range(20):
        app.execute(AdvanceTime(1))
        if _project(app, project_id).status == "complete":
            break
    else:
        raise AssertionError("facility upgrade did not complete")

    completed = _project(app, project_id)
    assert completed.materials_committed
    assert completed.construction_done >= completed.construction_required - 1e-9
    assert completed.completed_facility_id == before_row.id
    assert facility.level == 2

    # Existing standard components at the construction site are consumed directly;
    # they are not routed through a fake same-location logistics order.
    for requirement, component in zip(recipe.components, completed.components, strict=True):
        assert component.committed_primary_t >= requirement.amount_t - 1e-9
        assert component.committed_import_t <= 1e-9
        assert component.import_order_id is None
        after = app._simulation.inventory.amount(
            facility.location_id, requirement.import_resource_id
        )
        assert after < stock_before[requirement.import_resource_id]

    after_row, _ = _earth_lab(app)
    power = app._simulation.power.snapshot(
        facility.location_id, app._simulation.facilities, app._simulation.day
    )
    assert after_row.research_generation_points_per_day == pytest.approx(
        app._simulation.research.provider_generation(
            facility.id, {facility.location_id: power}, app._simulation.day
        )
    )
    assert after_row.research_storage_capacity_points == pytest.approx(
        app._simulation.research.provider_storage_capacity(
            facility.id, {facility.location_id: power}, app._simulation.day
        )
    )
    assert (
        after_row.research_generation_points_per_day,
        after_row.research_storage_capacity_points,
    ) != (
        before_row.research_generation_points_per_day,
        before_row.research_storage_capacity_points,
    )


def test_active_upgrade_roundtrips_without_applying_level_early(tmp_path):
    app = build_game_application()
    row, facility = _earth_lab(app)
    _unlock_next_upgrade(app, facility)

    result = app.execute(
        PlanFacilityUpgrade(row.id, priority=100, sourcing_policy="import_now")
    )
    assert result.created_id is not None
    project_id = result.created_id
    app.execute(SetConstructionWeight(project_id, 0.0))
    app.execute(AdvanceTime(1))

    active = _project(app, project_id)
    assert active.status in {"procuring", "ready"}
    assert facility.level == 1
    assert any(component.reserved_primary_t > 0 for component in active.components)

    path = tmp_path / "active-upgrade.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, offline = load_game(path, build_game_application)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    loaded_row, loaded_facility = _earth_lab(loaded)
    loaded_project = _project(loaded, project_id)
    assert loaded_row.id == row.id
    assert loaded_facility.level == 1
    assert loaded_project.target_kind == "facility_upgrade"
    assert loaded_project.target_facility_id == row.id
    assert loaded_project.target_level == 2


def test_duplicate_active_upgrade_is_rejected_at_application_boundary():
    app = build_game_application()
    row, facility = _earth_lab(app)
    _unlock_next_upgrade(app, facility)
    first = app.execute(PlanFacilityUpgrade(row.id, sourcing_policy="import_now"))
    assert first.created_id is not None

    with pytest.raises(ApplicationError):
        app.execute(PlanFacilityUpgrade(row.id, sourcing_policy="import_now"))
