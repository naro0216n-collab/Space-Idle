from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import AdvanceTime, GetOperationalNode, GetProjects, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.app_contracts.construction import CancelBuild, PlanFacilityDecommission
from space_idle.application_commands import ApplicationError
from space_idle.content import base_ids as ids
from space_idle.construction import FacilityDecommissionRecipe
from space_idle.facilities import FacilityDef, FacilityLifecycle
from space_idle.facility_lifecycle import FacilityLifecycleBlocker
from space_idle.persistence import load_game, save_game
from space_idle.shared import DefinitionId, EntityId

DECOMMISSION_TARGET = DefinitionId("test.facility.decommission_target")
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

    # Planning is reversible and must not change the Facility lifecycle.
    first = app.execute(PlanFacilityDecommission(facility_row.id, priority=5, procurement_policy="extended_wait"))
    assert first.created_id is not None
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
    assert facility_id not in loaded._simulation.facilities.facilities
    assert loaded._simulation.inventory.amount(ids.EARTH, SALVAGE_RESOURCE) == pytest.approx(before_stock + 5.0)


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
