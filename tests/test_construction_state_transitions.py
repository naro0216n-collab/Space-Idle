from __future__ import annotations

import pytest

from space_idle import AdvanceTime, CancelBuild, PauseBuild, PlanBuild, build_game_application
from space_idle.content import base_ids as ids
from space_idle.construction import BuildResourceRequirement, ConstructionRecipe, ProjectStatus
from space_idle.facilities import FacilityDef
from space_idle.research import ResearchDefinition, ResearchStage
from space_idle.shared import DefinitionId
from space_idle.validation import validate_runtime_state, validate_simulation_configuration


def _project(sim):
    return next(iter(sim.projects.projects.values()))



def test_partial_construction_procurement_is_project_owned_until_cancelled():
    app = build_game_application()
    sim = app._simulation
    result = app.execute(
        PlanBuild(
            str(ids.EARTH),
            str(ids.SURFACE_POWER_GRID),
            procurement_policy="extended_wait",
            site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
        )
    )
    project = _project(sim)
    recipe = sim.projects.recipe_for_project(project)
    for requirement in recipe.resources:
        available = sim.inventory.available(ids.EARTH, requirement.resource_id)
        if available > 1e-12:
            sim.inventory.consume_allocated(ids.EARTH, requirement.resource_id, available)
    partial_requirement = recipe.resources[0]
    partial_amount = partial_requirement.amount_t / 2.0
    sim.inventory.add(ids.EARTH, partial_requirement.resource_id, partial_amount)

    app.execute(AdvanceTime(1))
    staged = sim.projects.reserved_resource_t(project, partial_requirement.resource_id)
    assert staged > 0.0
    assert sim.projects.reserved_resource_t(project, partial_requirement.resource_id) >= staged
    assert project.resources[partial_requirement.resource_id].committed_t == pytest.approx(0.0)

    app.execute(PauseBuild(result.created_id))
    app.execute(AdvanceTime(1))
    assert sim.projects.reserved_resource_t(project, partial_requirement.resource_id) == pytest.approx(staged)
    stock_before_cancel = sim.inventory.amount(ids.EARTH, partial_requirement.resource_id)
    available_before_cancel = sim.inventory.available(ids.EARTH, partial_requirement.resource_id)
    app.execute(CancelBuild(result.created_id))
    assert sim.inventory.amount(ids.EARTH, partial_requirement.resource_id) == pytest.approx(stock_before_cancel)
    assert sim.inventory.available(ids.EARTH, partial_requirement.resource_id) == pytest.approx(
        available_before_cancel + staged
    )
    validate_runtime_state(sim)

def test_planned_project_with_unmet_technology_does_not_claim_inventory():
    app = build_game_application()
    sim = app._simulation
    facility_id = DefinitionId("test.facility.technology_locked")
    technology_id = DefinitionId("test.technology.required")
    sim.facilities.definitions[facility_id] = FacilityDef(
        facility_id, "Technology-locked fixture"
    )
    sim.research.definitions[technology_id] = ResearchDefinition(
        technology_id, "Required technology fixture",
        research_point_cost=1.0, stages=(ResearchStage.THEORY,),
    )
    sim.projects.recipes[facility_id] = ConstructionRecipe(
        facility_id,
        (
            BuildResourceRequirement(ids.STRUCTURAL_COMPONENTS, 1.0),
            BuildResourceRequirement(ids.MACHINERY, 0.5),
        ),
        construction_work=1.0,
        prerequisite_technologies=frozenset({technology_id}),
    )
    app.execute(
        PlanBuild(str(ids.EARTH), str(facility_id), procurement_policy="extended_wait")
    )

    app.execute(AdvanceTime(1))

    project = _project(sim)
    recipe = sim.projects.recipe_for_project(project)
    assert project.status is ProjectStatus.PLANNED
    assert ("technology", str(technology_id)) in {
        (blocker.code, blocker.detail) for blocker in sim.projects.blockers(project.id, sim.day)
    }
    assert all(
        sim.projects.reserved_resource_t(project, requirement.resource_id)
        == pytest.approx(0.0)
        for requirement in recipe.resources
    )
    assert sim.projects.supplys(sim.day) == ()
    validate_runtime_state(sim)


def test_parallel_same_priority_projects_share_construction_service_capacity():
    app = build_game_application()
    first = app.execute(
        PlanBuild(str(ids.EARTH), str(ids.WATER_STORAGE), priority=5, procurement_policy="extended_wait")
    ).created_id
    second = app.execute(
        PlanBuild(str(ids.EARTH), str(ids.BULK_STORAGE), priority=5, procurement_policy="extended_wait")
    ).created_id
    assert first is not None and second is not None

    sim = app._simulation
    projects = {str(project.id): project for project in sim.projects.projects.values()}
    required = {}
    for project_id in (first, second):
        project = projects[project_id]
        for requirement in sim.projects.recipe_for_project(project).resources:
            required[requirement.resource_id] = (
                required.get(requirement.resource_id, 0.0) + requirement.amount_t
            )
    for resource_id, amount_t in required.items():
        sim.inventory.stock[(ids.EARTH, resource_id)] = max(
            sim.inventory.amount(ids.EARTH, resource_id), amount_t
        )

    # Reservation/readiness is one canonical tick boundary; construction then
    # consumes the next tick's shared service allocation.
    app.execute(AdvanceTime(2))

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


def test_construction_recipe_resource_count_is_content_not_core_validation():
    app = build_game_application()
    sim = app._simulation
    facility_id = DefinitionId("test.facility.four_resource_recipe")
    sim.facilities.definitions[facility_id] = FacilityDef(
        facility_id, "Four-resource construction fixture"
    )
    sim.projects.recipes[facility_id] = ConstructionRecipe(
        facility_id,
        (
            BuildResourceRequirement(ids.STRUCTURAL_COMPONENTS, 1.0),
            BuildResourceRequirement(ids.MACHINERY, 1.0),
            BuildResourceRequirement(ids.PRECISION_ELECTRONICS, 1.0),
            BuildResourceRequirement(ids.BULK_STRUCTURE, 1.0),
        ),
        construction_work=1.0,
    )

    validate_simulation_configuration(sim)
