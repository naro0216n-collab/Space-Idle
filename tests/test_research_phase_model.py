from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    GetResearch,
    PauseFacility,
    PauseResearch,
    ResumeFacility,
    ResumeResearch,
    SetResearchDemonstrationSite,
    SetResearchPrototypeSite,
    StartResearch,
    build_game_application,
)
from space_idle.content import base_ids as ids, base_requirements as req
from space_idle.content.base_game import EARTH, LEO
from space_idle.research import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchDemonstrationStageSpec,
    ResearchPrototypeStageSpec,
    ResearchStage,
)
from space_idle.execution_requirements import ServiceCapacityRequirement
from space_idle.facilities import CapabilitySupply, FacilityDef, ServiceCapacitySupply
from space_idle.shared import DefinitionId
from space_idle.site import (
    CapabilityRequirement,
    CapabilityRequirementState,
    FacetValueRange,
    SiteRequirements,
)
from space_idle.spatial import ThermalField


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
    sim.research.definitions[research_id] = ResearchDefinition(research_id, "Explicit Prototype", (ResearchPrototypeStageSpec("prototype", {}),), prerequisites=frozenset())

    sim.research.start(research_id, day=sim.day)
    assert sim.research.active[research_id].current_stage_id == "prototype"
    assert tuple((stage.stage_id, stage.stage_type) for stage in _research_row(app, research_id).stages) == (("prototype", "prototype"),)
    sim.research.set_prototype_site(research_id, "prototype", EARTH, sim.day)

    sim.advance_days(1)

    assert research_id in sim.research.completed
    assert research_id not in sim.research.active


def test_prototype_site_selection_ignores_transient_capacity_but_rejects_structural_mismatch():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.prototype_site_contract")
    sim.research.definitions[research_id] = ResearchDefinition(research_id, "Prototype Site Contract", (ResearchPrototypeStageSpec("prototype",
            {},
            SiteRequirements(
                spatial_classification_requirements=req.SURFACE_CLASSIFICATION,
            ),
            (ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),),
        ),), prerequisites=frozenset())
    original = _remove_research_site_service(sim)
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(site for site in row.execution_context_options if site.operational_node_id == str(EARTH))
    assert not any(blocker.code.startswith("service") for blocker in earth.blockers)
    assert earth.can_select

    leo = next(site for site in row.execution_context_options if site.operational_node_id == str(LEO))
    assert leo.blockers
    assert not leo.can_select
    with pytest.raises(ApplicationError, match="prototype site requirements not met"):
        app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(LEO)))

    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.execution_context is not None
    assert selected.execution_context.operational_node_id == str(EARTH)
    assert selected.execution_context.surface_cell_id is None
    assert any(
        blocker.code == "service:allocation"
        for blocker in selected.current_blockers
    )
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "prototype"

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "complete"


def test_cell_local_research_site_requires_and_persists_explicit_developed_cell():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.cell_local_site")
    sim.research.definitions[research_id] = ResearchDefinition(research_id, "Cell-local Site", (ResearchPrototypeStageSpec("prototype",
            {},
            SiteRequirements(
                environment=(
                    FacetValueRange(
                        ThermalField,
                        "nominal_temperature_k",
                        "environment:any_thermal",
                        "cell-local thermal context required",
                        minimum=0.0,
                    ),
                ),
                spatial_classification_requirements=req.SURFACE_CLASSIFICATION,
            ),
        ),), prerequisites=frozenset())
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth_options = [
        candidate
        for candidate in row.execution_context_options
        if candidate.operational_node_id == str(EARTH)
    ]
    assert [candidate.surface_cell_id for candidate in earth_options] == [
        str(ids.EARTH_CELL_INDUSTRIAL)
    ]
    with pytest.raises(ApplicationError, match="prototype site requirements not met"):
        app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))

    app.execute(SetResearchPrototypeSite(
        str(research_id), "prototype", str(EARTH), str(ids.EARTH_CELL_INDUSTRIAL)
    ))
    selected = _research_row(app, research_id).execution_context
    assert selected is not None
    assert selected.operational_node_id == str(EARTH)
    assert selected.surface_cell_id == str(ids.EARTH_CELL_INDUSTRIAL)

def test_prototype_resource_staging_is_site_owned_durable_and_completes_when_runtime_service_recovers():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.reserved_prototype")
    resource_id = DefinitionId("test.resource.prototype_material")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Reserved Prototype",
        (
            ResearchPrototypeStageSpec(
                "prototype",
                {resource_id: 1.0},
                SiteRequirements(),
                (ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),),
            ),
        ),
        prerequisites=frozenset(),
    )
    sim.inventory.add(EARTH, resource_id, 0.25)

    app.execute(StartResearch(str(research_id)))
    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    original = _remove_research_site_service(sim)
    app.execute(AdvanceTime(1))

    row = _research_row(app, research_id)
    assert row.status == "prototype"
    resource = row.stage_resources[0]
    assert resource.reserved_t == pytest.approx(0.25)
    assert resource.requested_t == pytest.approx(0.75)
    assert sim.inventory.available(EARTH, resource_id) == pytest.approx(0.0)

    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(LEO)))
    assert sim.research.prototype_reserved_t(
        research_id, "prototype", EARTH, resource_id
    ) == pytest.approx(0.0)
    assert sim.inventory.available(EARTH, resource_id) == pytest.approx(0.25)
    assert sim.research.prototype_reserved_t(
        research_id, "prototype", LEO, resource_id
    ) == pytest.approx(0.0)

    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    sim.inventory.add(EARTH, resource_id, 0.75)
    app.execute(AdvanceTime(1))
    row = _research_row(app, research_id)
    resource = row.stage_resources[0]
    assert resource.reserved_t == pytest.approx(1.0)
    assert resource.requested_t == pytest.approx(0.0)
    assert not any(blocker.code == "prototype_resource" for blocker in row.current_blockers)

    app.execute(PauseResearch(str(research_id)))
    paused_reserved = sim.research.prototype_reserved_t(
        research_id, "prototype", EARTH, resource_id
    )
    app.execute(AdvanceTime(1))
    assert sim.research.prototype_reserved_t(
        research_id, "prototype", EARTH, resource_id
    ) == paused_reserved == pytest.approx(1.0)
    app.execute(ResumeResearch(str(research_id)))

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "complete"


def test_demonstration_site_selection_tolerates_transient_blockers_but_progress_requires_runtime_service():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.demonstration_runtime_contract")
    sim.research.definitions[research_id] = ResearchDefinition(research_id, "Demonstration Runtime Contract", (ResearchDemonstrationStageSpec("demonstration",
            2,
            SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement(
                        TEST_RESEARCH_SITE_CAPABILITY,
                        CapabilityRequirementState.ACTIVE,
                    ),
                ),
            ),
            (ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),),
        ),), prerequisites=frozenset())
    site = _research_site_fixture(sim)
    app.execute(PauseFacility(str(site.id)))
    app.execute(StartResearch(str(research_id)))

    row = _research_row(app, research_id)
    earth = next(
        candidate
        for candidate in row.execution_context_options
        if candidate.operational_node_id == str(EARTH)
    )
    assert any(blocker.code == "capability:active" for blocker in earth.blockers)
    assert earth.can_select
    app.execute(SetResearchDemonstrationSite(str(research_id), "demonstration", str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.execution_context is not None
    assert selected.execution_context.operational_node_id == str(EARTH)
    assert selected.execution_context.surface_cell_id is None
    assert any(blocker.code == "capability:active" for blocker in selected.current_blockers)

    app.execute(ResumeFacility(str(site.id)))
    original = _remove_research_site_service(sim)
    app.execute(AdvanceTime(1))
    blocked = _research_row(app, research_id)
    assert any(blocker.code == "service:allocation" for blocker in blocked.current_blockers)
    assert sim.research.active[research_id].stage_progress == 0.0

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    assert sim.research.active[research_id].stage_progress > 0.0

def test_research_stage_identity_is_explicit_unique_and_stable_across_repeated_stage_types():
    invalid_id = DefinitionId("test.research.invalid_stage_contract")
    with pytest.raises(ValueError, match="explicitly define its stages"):
        ResearchDefinition(invalid_id, "Implicit Stage Forbidden", (), prerequisites=frozenset())
    with pytest.raises(ValueError, match="stage ids must be unique"):
        ResearchDefinition(
            invalid_id,
            "Duplicate Stage ID",
            (
                ResearchPrototypeStageSpec("same", {}),
                ResearchPrototypeStageSpec("same", {}),
            ),
        )

    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.repeated_prototype")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Repeated Prototype",
        (
            ResearchPrototypeStageSpec("prototype-a", {}),
            ResearchPrototypeStageSpec("prototype-b", {}),
        ),
    )

    app.execute(StartResearch(str(research_id)))
    row = _research_row(app, research_id)
    assert tuple((stage.stage_id, stage.stage_type) for stage in row.stages) == (
        ("prototype-a", "prototype"), ("prototype-b", "prototype")
    )
    assert sim.research.active[research_id].current_stage_id == "prototype-a"
    app.execute(SetResearchPrototypeSite(str(research_id), "prototype-a", str(EARTH)))
    first_bundle = sim.research.execution_requirement_bundles(sim.day)[0]
    assert ":prototype-a:" in str(first_bundle.id)

    app.execute(AdvanceTime(1))
    state = sim.research.active[research_id]
    assert state.current_stage_id == "prototype-b"
    assert state.execution_context is None
    with pytest.raises(ApplicationError, match="stage changed"):
        app.execute(SetResearchPrototypeSite(str(research_id), "prototype-a", str(EARTH)))
    app.execute(SetResearchPrototypeSite(str(research_id), "prototype-b", str(EARTH)))
    second_bundle = sim.research.execution_requirement_bundles(sim.day)[0]
    assert ":prototype-b:" in str(second_bundle.id)
    assert second_bundle.id != first_bundle.id

    resource_id = DefinitionId("test.resource.repeated_stage_identity")
    assert sim.research.prototype_requirement_id(
        research_id, "prototype-a", resource_id
    ) != sim.research.prototype_requirement_id(
        research_id, "prototype-b", resource_id
    )
    assert sim.research.prototype_reservation_requirement_id(
        research_id, "prototype-a", resource_id
    ) != sim.research.prototype_reservation_requirement_id(
        research_id, "prototype-b", resource_id
    )
