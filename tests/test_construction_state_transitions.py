from __future__ import annotations

import pytest

from space_idle import AdvanceTime, CancelBuild, PauseBuild, PlanBuild, build_game_application
from space_idle.content import base_ids as ids
from space_idle.construction import BuildResourceRequirement, ConstructionRecipe, ProjectStatus
from space_idle.facilities import FacilityDef
from space_idle.research import ResearchDefinition, ResearchTheoryStageSpec
from space_idle.shared import DefinitionId
from space_idle.validation import validate_runtime_state


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
    sim.research.definitions[technology_id] = ResearchDefinition(technology_id, "Required technology fixture", (ResearchTheoryStageSpec("theory", 1.0),), prerequisites=frozenset())
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
