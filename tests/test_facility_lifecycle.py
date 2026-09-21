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
from space_idle.app_contracts.construction import CancelBuild, PlanFacilityDecommission
from space_idle.application_commands import ApplicationError
from space_idle.content import base_ids as ids
from space_idle.construction import (
    BuildResourceRequirement,
    ConstructionProviderSpec,
    FacilityDecommissionRecipe,
    FacilityUpgradeRecipe,
)
from space_idle.facilities import FacilityDef, FacilityLifecycle
from space_idle.facility_lifecycle import FacilityLifecycleBlocker
from space_idle.persistence import load_game, save_game
from space_idle.research import (
    ResearchDefinition,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
    ResearchProviderSpec,
    ResearchTheoryStageSpec,
)
from space_idle.shared import DefinitionId, EntityId
from space_idle.storage import StorageProviderSpec

DECOMMISSION_TARGET = DefinitionId("test.facility.decommission_target")
STORAGE_DECOMMISSION_TARGET = DefinitionId("test.facility.storage_decommission_target")
SALVAGE_RESOURCE = DefinitionId("test.resource.decommission_salvage")


def _build_decommission_fixture_application(*, for_load: bool = False):
    app = build_game_application_for_load() if for_load else build_game_application()
    sim = app._simulation
    sim.facilities.definitions[DECOMMISSION_TARGET] = FacilityDef(
        DECOMMISSION_TARGET, "Decommission target", decommission_recovery_fraction=0.5
    )
    sim.projects.decommission_recipes[DECOMMISSION_TARGET] = FacilityDecommissionRecipe(
        DECOMMISSION_TARGET, construction_work=12.0
    )
    sim.facilities.definitions[STORAGE_DECOMMISSION_TARGET] = FacilityDef(
        STORAGE_DECOMMISSION_TARGET,
        "Storage decommission target",
        decommission_recovery_fraction=0.5,
    )
    sim.projects.decommission_recipes[STORAGE_DECOMMISSION_TARGET] = FacilityDecommissionRecipe(
        STORAGE_DECOMMISSION_TARGET, construction_work=2.0
    )
    sim.storage.providers[STORAGE_DECOMMISSION_TARGET] = StorageProviderSpec(
        STORAGE_DECOMMISSION_TARGET, {"default": 10.0}
    )
    return app


def _project_row(app, project_id):
    return next(row for row in app.query(GetProjects()).items if row.id == project_id)


def test_decommission_lifecycle_salvage_and_roundtrip_preserve_asset_conservation(tmp_path):
    app = _build_decommission_fixture_application()
    sim = app._simulation
    facility_id = sim.facilities.install(
        DECOMMISSION_TARGET, ids.EARTH, invested_resources={SALVAGE_RESOURCE: 10.0}
    )
    facility_row = next(
        row for row in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if row.id == str(facility_id)
    )
    expected_salvage = dict(facility_row.expected_salvage)
    assert facility_row.lifecycle == FacilityLifecycle.NORMAL.value
    assert expected_salvage == {str(SALVAGE_RESOURCE): 5.0}
    assert facility_row.can_decommission
    assert facility_row.active_decommission_project_id is None

    # Planning is reversible and must not change the Facility lifecycle.
    first = app.execute(PlanFacilityDecommission(facility_row.id, priority=5, procurement_policy="extended_wait"))
    assert first.created_id is not None
    planned_facility_row = next(
        row for row in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if row.id == str(facility_id)
    )
    assert not planned_facility_row.can_decommission
    assert planned_facility_row.active_decommission_project_id == first.created_id
    app.execute(CancelBuild(first.created_id))
    assert sim.facilities.facilities[facility_id].lifecycle is FacilityLifecycle.NORMAL

    result = app.execute(PlanFacilityDecommission(facility_row.id, priority=5, procurement_policy="extended_wait"))
    assert result.created_id is not None
    project_id = result.created_id

    app.execute(AdvanceTime(2))
    active = _project_row(app, project_id)
    assert active.target_kind == "facility_decommission"
    assert active.irreversible_started
    assert sim.facilities.facilities[facility_id].lifecycle is FacilityLifecycle.DECOMMISSIONING
    assert not sim.facilities.is_active_and_compatible(sim.facilities.facilities[facility_id], sim.day)
    with pytest.raises(ApplicationError):
        app.execute(CancelBuild(project_id))

    path = tmp_path / "decommissioning.json"
    before_stock = sim.inventory.amount(ids.EARTH, SALVAGE_RESOURCE)
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, offline = load_game(path, lambda: _build_decommission_fixture_application(for_load=True))
    assert offline is None
    assert loaded._simulation.facilities.facilities[facility_id].lifecycle is FacilityLifecycle.DECOMMISSIONING
    assert _project_row(loaded, project_id).irreversible_started

    loaded.execute(AdvanceTime(2))
    completed = _project_row(loaded, project_id)
    assert completed.status == "complete"
    assert completed.actual_salvage_fraction == pytest.approx(1.0)
    assert dict(completed.actual_salvage) == {str(SALVAGE_RESOURCE): pytest.approx(5.0)}
    assert facility_id not in loaded._simulation.facilities.facilities
    assert loaded._simulation.inventory.amount(ids.EARTH, SALVAGE_RESOURCE) == pytest.approx(before_stock + 5.0)


def test_decommission_storage_provider_blocks_only_for_existing_stock_and_settles_partial_salvage():
    app = _build_decommission_fixture_application()
    sim = app._simulation
    facility_id = sim.facilities.install(
        STORAGE_DECOMMISSION_TARGET,
        ids.EARTH,
        invested_resources={SALVAGE_RESOURCE: 8.0},
    )
    sim.refresh_storage()

    pool = sim.inventory.storage_pool_for_resource(SALVAGE_RESOURCE)
    physical_with_target = sim.inventory.physical_storage_capacity_t[(ids.EARTH, pool)]
    remaining_physical = physical_with_target - 10.0
    filler = ids.CONSTRUCTION_EQUIPMENT
    original_filler = sim.inventory.amount(ids.EARTH, filler)
    occupied = sim.inventory.stored_in_pool(ids.EARTH, pool)

    # Existing Player-owned stock that cannot survive removal is the hard blocker.
    sim.inventory.add(
        ids.EARTH, filler, remaining_physical + 1.0 - occupied
    )
    failures = sim.projects.decommission_plan_failures(facility_id)
    assert [row.code for row in failures] == ["storage_stock"]
    blocked_row = next(
        row for row in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if row.id == str(facility_id)
    )
    assert any(blocker.code == "storage_stock" for blocker in blocked_row.decommission_blockers)
    with pytest.raises(ApplicationError, match="storage_stock"):
        app.execute(
            PlanFacilityDecommission(
                str(facility_id), priority=5, procurement_policy="extended_wait"
            )
        )
    assert sim.facilities.facilities[facility_id].lifecycle is FacilityLifecycle.NORMAL

    # Salvage potential itself is soft: projected headroom reduces the recoverable
    # fraction rather than preventing the decommission from being planned.
    sim.inventory.stock[(ids.EARTH, filler)] = original_filler
    occupied = sim.inventory.stored_in_pool(ids.EARTH, pool)
    sim.inventory.add(ids.EARTH, filler, remaining_physical - 2.0 - occupied)
    facility_row = next(
        row for row in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if row.id == str(facility_id)
    )
    assert dict(facility_row.expected_salvage) == {
        str(SALVAGE_RESOURCE): pytest.approx(4.0)
    }
    assert facility_row.projected_salvage_fraction == pytest.approx(0.5)
    assert dict(facility_row.projected_salvage) == {
        str(SALVAGE_RESOURCE): pytest.approx(2.0)
    }
    sim.inventory.stock[(ids.EARTH, filler)] = original_filler

    project_id = app.execute(
        PlanFacilityDecommission(
            str(facility_id), priority=5, procurement_policy="extended_wait"
        )
    ).created_id
    assert project_id is not None

    for _ in range(20):
        project = sim.projects.projects[EntityId(project_id)]
        recipe = sim.projects.decommission_recipes[STORAGE_DECOMMISSION_TARGET]
        if (
            project.irreversible_started
            and project.construction_done + 1e-9 >= recipe.construction_work
        ):
            break
        app.execute(AdvanceTime(1))
    else:
        pytest.fail("decommission work did not reach salvage settlement")

    assert sim.facilities.facilities[facility_id].lifecycle is FacilityLifecycle.DECOMMISSIONING
    assert sim.inventory.physical_storage_capacity_t[(ids.EARTH, pool)] == pytest.approx(
        remaining_physical
    )
    admission = sim.inventory.admission_state_for_pool(ids.EARTH, pool)
    assert admission.admission_capacity_t > 2.0
    sim.inventory.add(ids.EARTH, filler, admission.admission_capacity_t - 2.0)

    salvage_bundle = next(
        row for row in sim.projects.execution_requirement_bundles(sim.day)
        if row.id == sim.projects.decommission_salvage_bundle_id(EntityId(project_id))
    )
    assert not salvage_bundle.atomic
    assert salvage_bundle.minimum_execution == pytest.approx(0.0)
    expected_fraction = sim.tick_decision_projection().allocations.execution.fulfillment(
        salvage_bundle.id
    )
    assert 0.0 < expected_fraction < 1.0
    stock_before = sim.inventory.amount(ids.EARTH, SALVAGE_RESOURCE)

    app.execute(AdvanceTime(1))
    completed = _project_row(app, project_id)
    assert completed.status == "complete"
    assert completed.actual_salvage_fraction == pytest.approx(expected_fraction)
    assert dict(completed.actual_salvage) == {
        str(SALVAGE_RESOURCE): pytest.approx(4.0 * expected_fraction)
    }
    assert facility_id not in sim.facilities.facilities
    assert sim.inventory.amount(ids.EARTH, SALVAGE_RESOURCE) == pytest.approx(
        stock_before + 4.0 * expected_fraction
    )

    stock_after = sim.inventory.amount(ids.EARTH, SALVAGE_RESOURCE)
    app.execute(AdvanceTime(1))
    assert sim.inventory.amount(ids.EARTH, SALVAGE_RESOURCE) == pytest.approx(stock_after)
    assert facility_id not in sim.facilities.facilities


class _ToggleLifecycleBlocker:
    def __init__(self):
        self.active = True

    def facility_decommission_blockers(self, facility_id):
        if not self.active:
            return ()
        return (FacilityLifecycleBlocker("test_commitment", str(facility_id)),)


class _TrackingReferenceReleaser:
    def __init__(self):
        self.released = []

    def release_facility_reference(self, facility_id):
        self.released.append(facility_id)


def test_decommission_lifecycle_registry_accepts_new_participants_without_project_wiring():
    app = _build_decommission_fixture_application()
    sim = app._simulation
    blocker = _ToggleLifecycleBlocker()
    releaser = _TrackingReferenceReleaser()
    registry = sim.projects.facility_lifecycle_registry
    registry.register_blocker_provider("test_blocker", blocker)
    registry.register_reference_releaser("test_releaser", releaser)

    facility_id = sim.facilities.install(DECOMMISSION_TARGET, ids.EARTH)
    failures = sim.projects.decommission_plan_failures(facility_id)
    assert any(row.code == "test_commitment" for row in failures)

    blocker.active = False
    result = app.execute(PlanFacilityDecommission(str(facility_id), priority=5, procurement_policy="extended_wait"))
    assert result.created_id is not None
    for _ in range(30):
        row = _project_row(app, result.created_id)
        if row.status == "complete":
            break
        before = (row.status, row.construction_done, row.irreversible_started)
        app.execute(AdvanceTime(1))
        after = _project_row(app, result.created_id)
        assert (after.status, after.construction_done, after.irreversible_started) != before
    else:
        pytest.fail("decommission project did not complete")

    assert releaser.released == [facility_id]
    assert facility_id not in sim.facilities.facilities


# Facility upgrade shares the same lifecycle/project ownership surface.

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


def test_upgrade_planning_roundtrip_and_completion_apply_resources_and_level_once(tmp_path):
    app = _build_upgrade_fixture_application()
    before_row, facility = _upgrade_target(app)
    recipe = _unlock_next_upgrade(app, facility)
    option = before_row.next_upgrade
    assert option is not None
    assert option.can_plan
    assert option.active_project_id is None
    difference_values = {
        (row.kind, float(row.current_value), float(row.target_value))
        for row in option.differences
    }
    assert ("level", 1.0, 2.0) in difference_values
    assert ("capacity", 2.0, 5.0) in difference_values
    assert ("capacity", 10.0, 25.0) in difference_values
    assert ("service", 0.5, 1.0) in difference_values
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
    ready = _project_row(app, project_id)
    assert ready.status == "ready"
    assert facility.level == 1

    path = tmp_path / "active-upgrade.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, offline = load_game(path, lambda: _build_upgrade_fixture_application(for_load=True))
    assert offline is None

    loaded_row, loaded_facility = _upgrade_target(loaded)
    loaded_project = _project_row(loaded, project_id)
    assert loaded_row.id == before_row.id
    assert loaded_project.target_kind == "facility_upgrade"
    assert loaded_project.target_facility_id == before_row.id
    assert loaded_project.target_level == 2
    assert loaded_facility.level == 1

    loaded.execute(AdvanceTime(1))
    completed = _project_row(loaded, project_id)
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
