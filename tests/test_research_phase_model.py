from __future__ import annotations

from space_idle import (
    FundResearchPrototype, GetResearch, PauseFacility, SetResearchDemonstrationSite,
    SetResearchPrototypeSite, StartResearch, build_game_application,
)
from space_idle.research import (
    ResearchDefinition, ResearchDemonstrationSpec, ResearchPhase, ResearchPrototypeSpec,
)
from space_idle.shared import DefinitionId, EntityId
from space_idle.site import CapabilityRequirement, SiteRequirements
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH


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


def test_prototype_funding_eligibility_uses_owned_reservation_not_unreserved_stock():
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
    sim.refresh_resource_claims()

    demand_id = EntityId(f"demand.research:{research_id}:{resource_id}")
    assert sim.inventory.reserved_for(demand_id, EARTH, resource_id) == 1.0
    assert sim.inventory.available(EARTH, resource_id) == 0.0

    row = _research_row(app, research_id)
    assert row.can_fund_prototype
    assert not any(code == "prototype_resource" for code, _detail in row.current_blockers)

    app.execute(FundResearchPrototype(str(research_id)))
    assert _research_row(app, research_id).status == "complete"


def test_demonstration_site_can_be_selected_despite_transient_available_capability_blocker():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.available_capability_demo")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Available Capability Demonstration",
        research_point_cost=0.0,
        demonstration=ResearchDemonstrationSpec(
            2,
            SiteRequirements(capability_requirements=(
                CapabilityRequirement("research_lab", 0.01, "available"),
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
    assert any(code == "capability:available" for code, _detail in earth.blockers)
    assert earth.can_select

    app.execute(SetResearchDemonstrationSite(str(research_id), str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.demonstration_location_id == str(EARTH)
    assert any(code == "capability:available" for code, _detail in selected.current_blockers)
    assert selected.can_pause
    assert not selected.can_resume
