from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    GetResearch,
    PauseFacility,
    SetResearchDemonstrationSite,
    SetResearchPrototypeSite,
    StartResearch,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.content import base_requirements as req
from space_idle.content.base_game import EARTH, LEO
from space_idle.research import (
    ResearchDefinition,
    ResearchDemonstrationSpec,
    ResearchPrototypeSpec,
    ResearchStage,
)
from space_idle.shared import DefinitionId
from space_idle.site import (
    CapabilityRequirement,
    CapabilityRequirementState,
    ServiceCapacityRequirement,
    SiteRequirements,
)


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _earth_lab(sim):
    return next(
        facility for facility in sim.facilities.facilities.values()
        if facility.definition_id == ids.EARTH_RESEARCH_LAB
    )


def _remove_earth_research_execution(sim):
    lab = _earth_lab(sim)
    definition = sim.facilities.definitions[lab.definition_id]
    sim.facilities.definitions[lab.definition_id] = replace(
        definition,
        service_capacity_supplies=tuple(
            supply for supply in definition.service_capacity_supplies
            if supply.service_type != "research_execution"
        ),
    )
    return definition


def test_explicit_empty_prototype_stage_progresses_automatically_after_site_selection():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.explicit_empty_prototype")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Explicit Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({}),
        stages=(ResearchStage.PROTOTYPE,),
    )

    sim.research.start(research_id, day=sim.day)
    assert sim.research.active[research_id].stage is ResearchStage.PROTOTYPE
    assert _research_row(app, research_id).stages == ("prototype",)
    sim.research.set_prototype_site(research_id, EARTH, sim.day)

    sim.advance_days(1)

    assert research_id in sim.research.completed
    assert research_id not in sim.research.active


def test_research_definition_requires_explicit_stage_composition():
    research_id = DefinitionId("test.research.implicit_stage_forbidden")
    with pytest.raises(ValueError, match="explicitly define its stages"):
        ResearchDefinition(
            research_id,
            "Implicit Stage Forbidden",
            research_point_cost=1.0,
        )


def test_prototype_site_can_be_selected_before_transient_service_capacity_is_available():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.prototype_waits_for_execution")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Prototype Waits For Execution",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec(
            {},
            SiteRequirements(service_capacity_requirements=(
                ServiceCapacityRequirement("research_execution", 1.0),
            )),
        ),
        stages=(ResearchStage.PROTOTYPE,),
    )
    original = _remove_earth_research_execution(sim)
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(site for site in row.prototype_sites if site.operational_node_id == str(EARTH))
    assert any(code == "service_capacity:available" for code, _detail in earth.blockers)
    assert earth.can_select

    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.prototype_operational_node_id == str(EARTH)
    assert any(
        code == "service_capacity:available"
        for code, _detail in selected.current_blockers
    )
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "prototype"

    sim.facilities.definitions[_earth_lab(sim).definition_id] = original
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "complete"


def test_prototype_site_selection_still_rejects_structural_environment_mismatch():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.prototype_surface_only")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Surface-only Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({}, SiteRequirements(req.SURFACE_ENV)),
        stages=(ResearchStage.PROTOTYPE,),
    )
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    leo = next(site for site in row.prototype_sites if site.operational_node_id == str(LEO))
    assert leo.blockers
    assert not leo.can_select
    with pytest.raises(ApplicationError, match="prototype site requirements not met"):
        app.execute(SetResearchPrototypeSite(str(research_id), str(LEO)))


def test_prototype_resources_stage_durably_and_complete_without_manual_funding():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.reserved_prototype")
    resource_id = DefinitionId("test.resource.prototype_material")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Reserved Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec(
            {resource_id: 1.0},
            SiteRequirements(service_capacity_requirements=(
                ServiceCapacityRequirement("research_execution", 1.0),
            )),
        ),
        stages=(ResearchStage.PROTOTYPE,),
    )
    sim.inventory.add(EARTH, resource_id, 1.0)

    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    original = _remove_earth_research_execution(sim)
    app.execute(AdvanceTime(1))

    row = _research_row(app, research_id)
    assert row.status == "prototype"
    resource = row.prototype_resources[0]
    assert resource.staged_t == 1.0
    assert resource.requested_t == 0.0
    assert not any(code == "prototype_resource" for code, _detail in row.current_blockers)

    sim.facilities.definitions[_earth_lab(sim).definition_id] = original
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "complete"


def test_demonstration_site_can_be_selected_despite_transient_active_capability_blocker():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.active_capability_demo")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Active Capability Demonstration",
        research_point_cost=0.0,
        demonstration=ResearchDemonstrationSpec(
            2,
            SiteRequirements(capability_requirements=(
                CapabilityRequirement("research_lab", CapabilityRequirementState.ACTIVE),
            )),
        ),
        stages=(ResearchStage.DEMONSTRATION,),
    )
    lab = _earth_lab(sim)
    app.execute(PauseFacility(str(lab.id)))
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(site for site in row.demonstration_sites if site.operational_node_id == str(EARTH))
    assert any(code == "capability:active" for code, _detail in earth.blockers)
    assert earth.can_select

    app.execute(SetResearchDemonstrationSite(str(research_id), str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.demonstration_operational_node_id == str(EARTH)
    assert any(code == "capability:active" for code, _detail in selected.current_blockers)
    assert selected.can_pause
    assert not selected.can_resume


def test_partial_prototype_staging_returns_to_previous_site_when_site_changes():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.partial_prototype")
    resource_id = DefinitionId("test.resource.partial_prototype_material")
    missing_id = DefinitionId("test.resource.missing_prototype_material")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Partial Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({resource_id: 1.0, missing_id: 1.0}),
        stages=(ResearchStage.PROTOTYPE,),
    )
    sim.inventory.add(EARTH, resource_id, 0.25)

    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    app.execute(AdvanceTime(1))

    owner_id = sim.research._prototype_staging_owner_id(research_id)
    assert sim.inventory.staged_for(owner_id, EARTH, resource_id) == 0.25
    assert sim.inventory.amount(EARTH, resource_id) == 0.0

    app.execute(SetResearchPrototypeSite(str(research_id), str(LEO)))

    assert sim.inventory.staged_for(owner_id, EARTH, resource_id) == 0.0
    assert sim.inventory.amount(EARTH, resource_id) == 0.25
    assert sim.inventory.staged_for(owner_id, LEO, resource_id) == 0.0


def test_demonstration_progress_requires_allocated_research_execution_service():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.execution_capacity")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Research Execution Capacity",
        research_point_cost=0.0,
        demonstration=ResearchDemonstrationSpec(
            2,
            SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement("research_lab", CapabilityRequirementState.ACTIVE),
                ),
                service_capacity_requirements=(
                    ServiceCapacityRequirement("research_execution", 1.0),
                ),
            ),
        ),
        stages=(ResearchStage.DEMONSTRATION,),
    )
    app.execute(StartResearch(str(research_id)))
    _remove_earth_research_execution(sim)
    row = _research_row(app, research_id)
    earth = next(site for site in row.demonstration_sites if site.operational_node_id == str(EARTH))
    assert any(code == "service_capacity:available" for code, _detail in earth.blockers)
    assert earth.can_select
    app.execute(SetResearchDemonstrationSite(str(research_id), str(EARTH)))

    app.execute(AdvanceTime(1))

    assert sim.research.active[research_id].stage_progress == 0.0
