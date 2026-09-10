from __future__ import annotations

import pytest

from space_idle import AdvanceTime, PlanBuild, SetConstructionWeight, build_game_application
from space_idle.content import base_ids as ids
from space_idle.construction import ProjectStatus
from space_idle.validation import validate_runtime_state


def _project(sim):
    return next(iter(sim.projects.projects.values()))


def test_ready_project_keeps_materials_reserved_until_construction_starts():
    app = build_game_application()
    sim = app._simulation
    result = app.execute(
        PlanBuild(str(ids.EARTH), str(ids.SURFACE_POWER_GRID), sourcing_policy="import_now")
    )
    app.execute(SetConstructionWeight(result.created_id, 0.0))

    app.execute(AdvanceTime(1))

    project = _project(sim)
    recipe = sim.projects.recipe_for_project(project)
    assert project.status is ProjectStatus.READY
    assert project.materials_committed is False
    assert project.construction_done == pytest.approx(0.0)
    assert all(state.committed_t == pytest.approx(0.0) for state in project.resources.values())
    assert all(
        sim.projects.reserved_resource_t(project, requirement.resource_id)
        == pytest.approx(requirement.amount_t)
        for requirement in recipe.resources
    )
    assert "construction_allocation" in {
        blocker.code for blocker in sim.projects.blockers(project.id, sim.day)
    }
    validate_runtime_state(sim)

    app.execute(SetConstructionWeight(result.created_id, 1.0))
    app.execute(AdvanceTime(1))

    assert project.status is ProjectStatus.BUILDING
    assert project.materials_committed is True
    assert project.construction_done > 0
    assert all(
        state.committed_t == pytest.approx(requirement.amount_t)
        for requirement in recipe.resources
        for state in (project.resources[requirement.resource_id],)
    )
    assert all(
        sim.projects.reserved_resource_t(project, requirement.resource_id)
        == pytest.approx(0.0)
        for requirement in recipe.resources
    )
    validate_runtime_state(sim)


def test_planned_project_with_unmet_technology_does_not_claim_inventory():
    app = build_game_application()
    sim = app._simulation
    app.execute(
        PlanBuild(str(ids.EARTH), str(ids.VOLATILE_EXTRACTOR), sourcing_policy="import_now")
    )

    app.execute(AdvanceTime(1))

    project = _project(sim)
    recipe = sim.projects.recipe_for_project(project)
    assert project.status is ProjectStatus.PLANNED
    assert "technology" in {blocker.code for blocker in sim.projects.blockers(project.id, sim.day)}
    assert all(
        sim.projects.reserved_resource_t(project, requirement.resource_id)
        == pytest.approx(0.0)
        for requirement in recipe.resources
    )
    assert sim.projects.resource_demands(sim.day) == ()
    validate_runtime_state(sim)
