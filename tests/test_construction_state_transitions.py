from __future__ import annotations

import pytest

from space_idle import AdvanceTime, CancelBuild, PauseBuild, PlanBuild, build_game_application
from space_idle.content import base_ids as ids
from space_idle.construction import ProjectStatus
from space_idle.validation import validate_runtime_state


def _project(sim):
    return next(iter(sim.projects.projects.values()))



def test_partial_construction_procurement_is_project_owned_until_cancelled():
    app = build_game_application()
    sim = app._simulation
    result = app.execute(
        PlanBuild(str(ids.EARTH), str(ids.SURFACE_POWER_GRID), sourcing_policy="local_priority")
    )
    project = _project(sim)
    recipe = sim.projects.recipe_for_project(project)
    for requirement in recipe.resources:
        available = sim.inventory.available(ids.EARTH, requirement.resource_id)
        if available > 1e-12:
            sim.inventory.consume_allocated(ids.EARTH, requirement.resource_id, available)
    sim.inventory.add(ids.EARTH, ids.STRUCTURAL_COMPONENTS, 0.5)

    app.execute(AdvanceTime(1))
    staged = sim.projects.staged_resource_t(project, ids.STRUCTURAL_COMPONENTS)
    assert staged > 0.0
    assert sim.projects.staged_resource_t(project, ids.STRUCTURAL_COMPONENTS) >= staged
    assert project.resources[ids.STRUCTURAL_COMPONENTS].committed_t == pytest.approx(0.0)

    app.execute(PauseBuild(result.created_id))
    app.execute(AdvanceTime(1))
    assert sim.projects.staged_resource_t(project, ids.STRUCTURAL_COMPONENTS) == pytest.approx(staged)
    stock_before_cancel = sim.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS)
    app.execute(CancelBuild(result.created_id))
    assert sim.inventory.amount(ids.EARTH, ids.STRUCTURAL_COMPONENTS) == pytest.approx(
        stock_before_cancel + staged
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
        sim.projects.staged_resource_t(project, requirement.resource_id)
        == pytest.approx(0.0)
        for requirement in recipe.resources
    )
    assert sim.projects.resource_demands(sim.day) == ()
    validate_runtime_state(sim)


def test_parallel_same_priority_projects_share_construction_service_capacity():
    app = build_game_application()
    first = app.execute(
        PlanBuild(str(ids.EARTH), str(ids.WATER_STORAGE), priority=100, sourcing_policy="local_priority")
    ).created_id
    second = app.execute(
        PlanBuild(str(ids.EARTH), str(ids.BULK_STORAGE), priority=100, sourcing_policy="local_priority")
    ).created_id
    assert first is not None and second is not None

    projects = {str(project.id): project for project in app._simulation.projects.projects.values()}
    for _ in range(5):
        app.execute(AdvanceTime(1))
        if all(project.status is ProjectStatus.BUILDING for project in projects.values()):
            break

    assert projects[first].status is ProjectStatus.BUILDING
    assert projects[second].status is ProjectStatus.BUILDING
    first_done = projects[first].construction_done
    second_done = projects[second].construction_done
    assert first_done > 0.0 and second_done > 0.0
    # Same-priority continuous Service Requests both receive capacity; no project-local
    # allocation weight decides the result.
    assert first_done / app._simulation.projects.recipe_for_project(projects[first]).construction_work == pytest.approx(
        second_done / app._simulation.projects.recipe_for_project(projects[second]).construction_work
    )
