from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    GetResearch,
    PauseFacility,
    ResumeFacility,
    SetResearchDemonstrationSite,
    SetResearchPrototypeSite,
    StartResearch,
    build_game_application,
)
from space_idle.content import base_requirements as req
from space_idle.content.base_game import EARTH, LEO
from space_idle.research import (
    ResearchDefinition,
    ResearchDemonstrationSpec,
    ResearchPrototypeSpec,
    ResearchStage,
)
from space_idle.facilities import CapabilitySupply, FacilityDef, ServiceCapacitySupply
from space_idle.shared import DefinitionId
from space_idle.site import (
    CapabilityRequirement,
    CapabilityRequirementState,
    ServiceCapacityRequirement,
    SiteRequirements,
)


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


TEST_RESEARCH_SITE_CAPABILITY = "test.research_site_capability"
TEST_RESEARCH_SITE_SERVICE = "test.research_site_service"
TEST_RESEARCH_SITE_FACILITY = DefinitionId("test.facility.research_site")


def _research_site_fixture(sim):
    existing = next(
        (facility for facility in sim.facilities.facilities.values()
         if facility.definition_id == TEST_RESEARCH_SITE_FACILITY),
        None,
    )
    if existing is not None:
        return existing
    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = FacilityDef(
        TEST_RESEARCH_SITE_FACILITY,
        "Research site fixture",
        capability_supplies=(CapabilitySupply(TEST_RESEARCH_SITE_CAPABILITY),),
        service_capacity_supplies=(ServiceCapacitySupply(TEST_RESEARCH_SITE_SERVICE, 1.0),),
    )
    facility_id = sim.facilities.install(TEST_RESEARCH_SITE_FACILITY, EARTH)
    return sim.facilities.facilities[facility_id]


def _remove_research_site_service(sim):
    facility = _research_site_fixture(sim)
    definition = sim.facilities.definitions[facility.definition_id]
    sim.facilities.definitions[facility.definition_id] = replace(
        definition, service_capacity_supplies=()
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


def test_prototype_site_selection_ignores_transient_capacity_but_rejects_structural_mismatch():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.prototype_site_contract")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Prototype Site Contract",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec(
            {},
            SiteRequirements(
                service_capacity_requirements=(
                    ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),
                ),
                spatial_classification_requirements=req.SURFACE_CLASSIFICATION,
            ),
        ),
        stages=(ResearchStage.PROTOTYPE,),
    )
    original = _remove_research_site_service(sim)
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(site for site in row.prototype_sites if site.operational_node_id == str(EARTH))
    assert any(code == "service_capacity:available" for code, _detail in earth.blockers)
    assert earth.can_select

    leo = next(site for site in row.prototype_sites if site.operational_node_id == str(LEO))
    assert leo.blockers
    assert not leo.can_select
    with pytest.raises(ApplicationError, match="prototype site requirements not met"):
        app.execute(SetResearchPrototypeSite(str(research_id), str(LEO)))

    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.prototype_operational_node_id == str(EARTH)
    assert any(
        code == "service_capacity:available"
        for code, _detail in selected.current_blockers
    )
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "prototype"

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "complete"

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
                ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),
            )),
        ),
        stages=(ResearchStage.PROTOTYPE,),
    )
    sim.inventory.add(EARTH, resource_id, 1.0)

    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))
    original = _remove_research_site_service(sim)
    app.execute(AdvanceTime(1))

    row = _research_row(app, research_id)
    assert row.status == "prototype"
    resource = row.prototype_resources[0]
    assert resource.reserved_t == 1.0
    assert resource.requested_t == 0.0
    assert not any(code == "prototype_resource" for code, _detail in row.current_blockers)

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "complete"


def test_demonstration_site_selection_tolerates_transient_blockers_but_progress_requires_runtime_service():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.demonstration_runtime_contract")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Demonstration Runtime Contract",
        research_point_cost=0.0,
        demonstration=ResearchDemonstrationSpec(
            2,
            SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement(
                        TEST_RESEARCH_SITE_CAPABILITY,
                        CapabilityRequirementState.ACTIVE,
                    ),
                ),
                service_capacity_requirements=(
                    ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),
                ),
            ),
        ),
        stages=(ResearchStage.DEMONSTRATION,),
    )
    site = _research_site_fixture(sim)
    app.execute(PauseFacility(str(site.id)))
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(
        candidate
        for candidate in row.demonstration_sites
        if candidate.operational_node_id == str(EARTH)
    )
    assert any(code == "capability:active" for code, _detail in earth.blockers)
    assert earth.can_select
    app.execute(SetResearchDemonstrationSite(str(research_id), str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.demonstration_operational_node_id == str(EARTH)
    assert any(code == "capability:active" for code, _detail in selected.current_blockers)

    app.execute(ResumeFacility(str(site.id)))
    original = _remove_research_site_service(sim)
    app.execute(AdvanceTime(1))
    blocked = _research_row(app, research_id)
    assert any(code == "service_capacity:available" for code, _detail in blocked.current_blockers)
    assert sim.research.active[research_id].stage_progress == 0.0

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    assert sim.research.active[research_id].stage_progress > 0.0

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

    assert sim.research.prototype_reserved_t(research_id, EARTH, resource_id) == 0.25
    assert sim.inventory.amount(EARTH, resource_id) == pytest.approx(0.25)
    assert sim.inventory.available(EARTH, resource_id) == pytest.approx(0.0)

    app.execute(SetResearchPrototypeSite(str(research_id), str(LEO)))

    assert sim.research.prototype_reserved_t(research_id, EARTH, resource_id) == 0.0
    assert sim.inventory.amount(EARTH, resource_id) == pytest.approx(0.25)
    assert sim.inventory.available(EARTH, resource_id) == pytest.approx(0.25)
    assert sim.research.prototype_reserved_t(research_id, LEO, resource_id) == 0.0
