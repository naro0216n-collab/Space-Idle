from __future__ import annotations

from space_idle import (
    AdvanceTime, FundResearchPrototype, GetResearch, PauseFacility, SetResearchDemonstrationSite,
    SetResearchPrototypeSite, StartResearch, build_game_application,
)
from space_idle.research import (
    ResearchDefinition, ResearchDemonstrationSpec, ResearchPhase, ResearchPrototypeSpec,
)
from space_idle.shared import DefinitionId, EntityId
from space_idle.site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO


def test_explicit_empty_prototype_spec_still_creates_prototype_phase():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.explicit_empty_prototype")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Explicit Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({}),
    )

    sim.research.start(research_id, day=sim.day)

    state = sim.research.active[research_id]
    assert state.status is ResearchPhase.PROTOTYPE
    sim.research.set_prototype_site(research_id, EARTH, sim.day)
    sim.research.fund_prototype(research_id, sim.day)
    assert research_id in sim.research.completed
    assert research_id not in sim.research.active


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def test_prototype_funding_eligibility_uses_durable_staging_not_unallocated_stock():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.reserved_prototype")
    resource_id = DefinitionId("test.resource.prototype_material")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Reserved Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({resource_id: 1.0}),
    )
    sim.inventory.add(EARTH, resource_id, 1.0)

    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    app.execute(AdvanceTime(1))

    staging_owner = EntityId(f"research.prototype:{research_id}")
    assert sim.inventory.reserved == {}
    assert sim.inventory.staged_for(staging_owner, EARTH, resource_id) == 1.0
    assert sim.inventory.amount(EARTH, resource_id) == 0.0

    row = _research_row(app, research_id)
    assert row.can_fund_prototype
    assert not any(code == "prototype_resource" for code, _detail in row.current_blockers)

    app.execute(FundResearchPrototype(str(research_id)))
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
    )
    lab = next(
        facility for facility in sim.facilities.facilities.values()
        if facility.definition_id == ids.EARTH_RESEARCH_LAB
    )
    app.execute(PauseFacility(str(lab.id)))
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(site for site in row.demonstration_sites if site.location_id == str(EARTH))
    assert any(code == "capability:active" for code, _detail in earth.blockers)
    assert earth.can_select

    app.execute(SetResearchDemonstrationSite(str(research_id), str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.demonstration_location_id == str(EARTH)
    assert any(code == "capability:active" for code, _detail in selected.current_blockers)
    assert selected.can_pause
    assert not selected.can_resume


def test_partial_prototype_procurement_is_staged_and_site_change_returns_material_to_old_site():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.partial_prototype")
    resource_id = DefinitionId("test.resource.partial_prototype_material")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Partial Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({resource_id: 1.0}),
    )
    sim.inventory.add(EARTH, resource_id, 0.25)

    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    app.execute(AdvanceTime(1))

    owner_id = sim.research._prototype_staging_owner_id(research_id)
    staged = sim.inventory.staged_for(owner_id, EARTH, resource_id)
    assert staged == 0.25
    assert sim.inventory.amount(EARTH, resource_id) == 0.0
    assert not _research_row(app, research_id).can_fund_prototype

    app.execute(SetResearchPrototypeSite(str(research_id), str(LEO)))

    assert sim.inventory.staged_for(owner_id, EARTH, resource_id) == 0.0
    assert sim.inventory.amount(EARTH, resource_id) == 0.25
    assert sim.inventory.staged_for(owner_id, LEO, resource_id) == 0.0


def test_demonstration_progress_requires_allocated_research_execution_service():
    from dataclasses import replace

    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.execution_capacity")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Research Execution Capacity",
        research_point_cost=0.0,
        demonstration=ResearchDemonstrationSpec(
            2,
            SiteRequirements(capability_requirements=(
                CapabilityRequirement("research_lab", CapabilityRequirementState.ACTIVE),
            )),
        ),
    )
    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchDemonstrationSite(str(research_id), str(EARTH)))

    lab = next(
        facility for facility in sim.facilities.facilities.values()
        if facility.definition_id == ids.EARTH_RESEARCH_LAB
    )
    definition = sim.facilities.definitions[lab.definition_id]
    sim.facilities.definitions[lab.definition_id] = replace(
        definition,
        service_capacity_supplies=tuple(
            supply for supply in definition.service_capacity_supplies
            if supply.service_type != "research_execution"
        ),
    )

    app.execute(AdvanceTime(1))
    assert sim.research.active[research_id].demonstration_done_days == 0
