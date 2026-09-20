from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    GetOperationalNode,
    GetProjects,
    PlanFacilityUpgrade,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.application_commands import ApplicationError
from space_idle.construction import (
    BuildResourceRequirement,
    ConstructionProviderSpec,
    FacilityUpgradeRecipe,
)
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.persistence import load_game, save_game
from space_idle.research import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
    ResearchProviderSpec,
    ResearchStage,
)
from space_idle.shared import DefinitionId, EntityId


UPGRADE_FACILITY = DefinitionId("test.facility.upgrade_target")
UPGRADE_CONTRACTOR = DefinitionId("test.facility.upgrade_contractor")
UPGRADE_TECHNOLOGY = DefinitionId("test.technology.facility_upgrade")
UPGRADE_RESOURCE_A = DefinitionId("test.resource.upgrade_a")
UPGRADE_RESOURCE_B = DefinitionId("test.resource.upgrade_b")


def _build_upgrade_fixture_application(*, for_load: bool = False):
    app = build_game_application_for_load() if for_load else build_game_application()
    sim = app._simulation

    sim.facilities.definitions[UPGRADE_FACILITY] = FacilityDef(
        UPGRADE_FACILITY,
        "Upgrade target fixture",
    )
    sim.facilities.definitions[UPGRADE_CONTRACTOR] = FacilityDef(
        UPGRADE_CONTRACTOR,
        "Upgrade contractor fixture",
    )
    sim.research.definitions[UPGRADE_TECHNOLOGY] = ResearchDefinition(UPGRADE_TECHNOLOGY, "Upgrade prerequisite fixture", (ResearchTheoryStageSpec("theory", 1.0),), prerequisites=frozenset())
    sim.research.providers[UPGRADE_FACILITY] = ResearchProviderSpec(
        UPGRADE_FACILITY,
        ResearchProviderSourceKind.FACILITY,
        UPGRADE_FACILITY,
        tier=1,
        levels=(
            ResearchProviderLevelSpec(1, 2.0, 10.0, 0.5),
            ResearchProviderLevelSpec(2, 5.0, 25.0, 1.0),
        ),
    )
    sim.projects.upgrade_recipes[(UPGRADE_FACILITY, 2)] = FacilityUpgradeRecipe(
        UPGRADE_FACILITY,
        2,
        (
            BuildResourceRequirement(UPGRADE_RESOURCE_A, 1.0),
            BuildResourceRequirement(UPGRADE_RESOURCE_B, 1.0),
        ),
        construction_work=1.0,
        prerequisite_technologies=frozenset({UPGRADE_TECHNOLOGY}),
    )
    sim.projects.construction_providers[UPGRADE_CONTRACTOR] = ConstructionProviderSpec(
        UPGRADE_CONTRACTOR,
        work_per_day=10.0,
    )
    if not for_load:
        sim.facilities.install(UPGRADE_CONTRACTOR, ids.EARTH)
        sim.facilities.install(UPGRADE_FACILITY, ids.EARTH)
    return app


def _upgrade_target(app):
    row = next(
        facility
        for facility in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if facility.definition_id == str(UPGRADE_FACILITY)
    )
    state = app._simulation.facilities.facilities[EntityId(row.id)]
    return row, state


def _unlock_next_upgrade(app, facility_state):
    recipe = app._simulation.projects.next_upgrade_recipe(facility_state.id)
    assert recipe is not None
    app._simulation.technology.completed.update(recipe.prerequisite_technologies)
    return recipe


def _seed_upgrade_materials(app, facility_state, recipe):
    inventory = app._simulation.inventory
    for requirement in recipe.resources:
        key = (facility_state.operational_node_id, requirement.resource_id)
        inventory.stock[key] = inventory.amount(*key) + requirement.amount_t


def _project(app, project_id):
    return next(row for row in app.query(GetProjects()).items if row.id == project_id)


def test_upgrade_planning_roundtrip_and_completion_apply_resources_and_level_once(tmp_path):
    app = _build_upgrade_fixture_application()
    before_row, facility = _upgrade_target(app)
    recipe = _unlock_next_upgrade(app, facility)
    option = before_row.next_upgrade
    assert option is not None
    assert option.can_plan
    assert option.active_project_id is None
    differences = {row.label: row for row in option.differences}
    assert differences["Level"].current_value == 1
    assert differences["Level"].target_value == 2
    assert differences["研究RP生成Capacity"].current_value == pytest.approx(2.0)
    assert differences["研究RP生成Capacity"].target_value == pytest.approx(5.0)
    assert differences["研究RP貯蔵Capacity"].current_value == pytest.approx(10.0)
    assert differences["研究RP貯蔵Capacity"].target_value == pytest.approx(25.0)
    assert differences["研究実行Service供給"].current_value == pytest.approx(0.5)
    assert differences["研究実行Service供給"].target_value == pytest.approx(1.0)
    _seed_upgrade_materials(app, facility, recipe)

    provider = app._simulation.research.providers[facility.definition_id]
    before_provider_spec = provider.level_spec(facility.level)
    next_provider_spec = provider.level_spec(facility.level + 1)
    assert before_provider_spec != next_provider_spec
    investment_before = dict(facility.invested_resources)

    result = app.execute(
        PlanFacilityUpgrade(before_row.id, priority=5, procurement_policy="extended_wait")
    )
    assert result.created_id is not None
    project_id = result.created_id

    active_row, _ = _upgrade_target(app)
    active = active_row.next_upgrade
    assert active is not None
    assert not active.can_plan
    assert active.active_project_id == project_id
    assert any(
        blocker.code == "active_upgrade_project" and blocker.subject_id == project_id
        for blocker in active.blockers
    )
    with pytest.raises(ApplicationError):
        app.execute(PlanFacilityUpgrade(before_row.id, procurement_policy="extended_wait"))

    # The first canonical boundary acquires the inputs; level application belongs
    # to the following construction boundary. Persist between those boundaries so
    # the upgrade-specific target state is verified without a separate save/load case.
    app.execute(AdvanceTime(1))
    ready = _project(app, project_id)
    assert ready.status == "ready"
    assert facility.level == 1

    path = tmp_path / "active-upgrade.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, offline = load_game(path, lambda: _build_upgrade_fixture_application(for_load=True))
    assert offline is None

    loaded_row, loaded_facility = _upgrade_target(loaded)
    loaded_project = _project(loaded, project_id)
    assert loaded_row.id == before_row.id
    assert loaded_project.target_kind == "facility_upgrade"
    assert loaded_project.target_facility_id == before_row.id
    assert loaded_project.target_level == 2
    assert loaded_facility.level == 1

    loaded.execute(AdvanceTime(1))
    completed = _project(loaded, project_id)
    assert completed.status == "complete"
    assert completed.materials_committed
    assert completed.completed_facility_id == before_row.id
    assert loaded_facility.level == 2

    for requirement, resource in zip(recipe.resources, completed.resources, strict=True):
        assert resource.resource_id == str(requirement.resource_id)
        assert resource.committed_t == pytest.approx(requirement.amount_t)
        assert loaded_facility.invested_resources[requirement.resource_id] == pytest.approx(
            investment_before.get(requirement.resource_id, 0.0) + requirement.amount_t
        )

    after_row, _ = _upgrade_target(loaded)
    power = loaded._simulation.power.snapshot(
        loaded_facility.operational_node_id,
        loaded._simulation.facilities,
        loaded._simulation.day,
    )
    assert after_row.research_generation_points_per_day == pytest.approx(
        loaded._simulation.research.provider_generation(
            loaded_facility.id, {loaded_facility.operational_node_id: power}, loaded._simulation.day
        )
    )
    assert after_row.research_storage_capacity_points == pytest.approx(
        loaded._simulation.research.provider_storage_capacity(
            loaded_facility.id, {loaded_facility.operational_node_id: power}, loaded._simulation.day
        )
    )
    assert (
        after_row.research_generation_points_per_day,
        after_row.research_storage_capacity_points,
    ) != (
        before_row.research_generation_points_per_day,
        before_row.research_storage_capacity_points,
    )
