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
from space_idle.construction.models import ConstructionRecipe
from space_idle.execution_requirements import ServiceCapacityRequirement
from space_idle.facilities import CapabilitySupply, FacilityDef, ServiceCapacitySupply
from space_idle.shared import DefinitionId
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError
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


def test_authored_prototype_and_operational_experience_link_physical_site_allocation_and_save(tmp_path):
    """An actual late Content method uses its typed stages in the real Application."""
    from datetime import datetime, timezone
    from space_idle.bootstrap import build_game_application_for_load, build_game_application_for_scenario
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.persistence import capture_state, load_game, save_game
    from space_idle.scenario import (
        ScenarioFacility, ScenarioInventoryStock, ScenarioStorageInfrastructure, ScenarioSurfaceLocation,
    )
    from space_idle.shared import SpatialNodeId

    base = build_standard_scenario_definition()
    moon_node = SpatialNodeId("test.research.moon_site")
    target = ids.RP_RESOURCE_CHAIN_13
    definition = build_game_application()._simulation.research.definitions[target]
    scenario = replace(
        base,
        completed_technologies=tuple(sorted(definition.prerequisites)),
        surface_locations=base.surface_locations + (
            ScenarioSurfaceLocation(moon_node, "Research test site", ids.MOON,
                                    ids.MOON_CELL_SOUTH_POLAR_RIDGE),
        ),
        facilities=base.facilities + (
            ScenarioFacility(ids.VACUUM_REGOLITH_PROCESS_LABORATORY, moon_node),
            ScenarioFacility(ids.INDUSTRIAL_POWER_BLOCK, moon_node),
        ),
        storage_infrastructure=base.storage_infrastructure + (
            ScenarioStorageInfrastructure(moon_node, "default", 10),
        ),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(moon_node, ids.MINERAL_FEEDSTOCK, 2),
            ScenarioInventoryStock(moon_node, ids.MACHINERY, 2),
        ),
    )

    # Only shorten an experiment input: the method, site, and Research Stage
    # definitions used by gameplay are otherwise identical to authored Content.
    def short_theory(sim, _catalog):
        original = sim.research.definitions[target]
        sim.research.definitions[target] = replace(
            original, stage_specs=(ResearchTheoryStageSpec("theory", 0.5),) + original.stage_specs[1:]
        )

    app = build_game_application_for_scenario(scenario, definition_transform=short_theory)
    sim = app._simulation
    sim.research.stored_points = 5.0  # test fixture's acquired RP, not an alternate Research solver
    app.execute(StartResearch(str(target)))
    app.execute(AdvanceTime(1))
    row = _research_row(app, target)
    assert row.current_stage_id == "oxide-reduction-prototype"
    assert any(blocker.code == "prototype_site" for blocker in row.current_blockers)
    app.execute(SetResearchPrototypeSite(str(target), "oxide-reduction-prototype", str(moon_node)))
    app.execute(AdvanceTime(1))
    assert sim.research.prototype_reserved_t(
        target, "oxide-reduction-prototype", moon_node, ids.MINERAL_FEEDSTOCK
    ) == pytest.approx(0.5)
    assert sim.inventory.amount(moon_node, ids.MINERAL_FEEDSTOCK) == pytest.approx(2.0)

    path = tmp_path / "typed-research.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    def load_factory():
        loaded = build_game_application_for_load()
        short_theory(loaded._simulation, loaded._catalog)
        return loaded
    loaded, offline = load_game(path, load_factory)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert loaded._simulation.research.prototype_reserved_t(
        target, "oxide-reduction-prototype", moon_node, ids.MINERAL_FEEDSTOCK
    ) == pytest.approx(0.5)

    for _ in range(4):
        app.execute(AdvanceTime(1))
        loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert target in sim.technology.completed
    assert _research_row(app, target).status == "complete"
    # Stage inputs are permanently consumed once, not duplicated by Load.
    assert sim.inventory.amount(moon_node, ids.MINERAL_FEEDSTOCK) == pytest.approx(1.5)


def test_research_projection_exposes_player_facing_unlocks_without_hiding_other_prerequisites():
    app = build_game_application()
    sim = app._simulation
    unlock_source = DefinitionId("test.research.unlock_source")
    other_prerequisite = DefinitionId("test.research.unlock_other")
    immediate_child = DefinitionId("test.research.unlock_immediate")
    compound_child = DefinitionId("test.research.unlock_compound")
    facility_id = DefinitionId("test.facility.unlock_projection")
    for research_id, name, prerequisites in (
        (unlock_source, "Unlock Source", frozenset()),
        (other_prerequisite, "Other Prerequisite", frozenset()),
        (immediate_child, "Immediate Child", frozenset({unlock_source})),
        (compound_child, "Compound Child", frozenset({unlock_source, other_prerequisite})),
    ):
        sim.research.definitions[research_id] = ResearchDefinition(
            research_id,
            name,
            (ResearchTheoryStageSpec("theory", 1.0),),
            prerequisites=prerequisites,
        )
    sim.facilities.definitions[facility_id] = FacilityDef(facility_id, "Unlocked Facility")
    sim.projects.recipes[facility_id] = ConstructionRecipe(
        facility_id,
        (),
        1.0,
        prerequisite_technologies=frozenset({unlock_source}),
    )

    row = _research_row(app, unlock_source)
    unlocks = {(unlock.kind, unlock.id): unlock for unlock in row.unlocks}

    immediate = unlocks[("research", str(immediate_child))]
    assert immediate.display_name == "Immediate Child"
    assert immediate.remaining_prerequisite_ids == ()

    compound = unlocks[("research", str(compound_child))]
    assert compound.display_name == "Compound Child"
    assert compound.remaining_prerequisite_ids == (
        str(other_prerequisite),
    )

    facility = unlocks[("facility", str(facility_id))]
    assert facility.display_name == "Unlocked Facility"
    assert facility.remaining_prerequisite_ids == ()

    # The same dependency graph also determines inspectable blocker state.
    compound = _research_row(app, compound_child)
    assert compound.status == "locked"
    assert compound.current_blockers
    assert compound.primary_blocker == compound.current_blockers[0]
    assert compound.primary_blocker.code == "prerequisite"
    available = _research_row(app, unlock_source)
    assert available.status == "available"
    assert available.current_blockers == () and available.primary_blocker is None
    # Authoritative Application distinguishes a real direct method from a
    # research-only path. Neither classification asserts present Eligibility.
    assert available.registered_outlet_status == "direct_method"
    assert _research_row(app, other_prerequisite).registered_outlet_status == "research_only_no_method"
    assert _research_row(app, immediate_child).registered_outlet_status == "no_downstream_outlet"


def _remove_research_site_service(sim):
    facility = _research_site_fixture(sim)
    definition = sim.facilities.definitions[facility.definition_id]
    sim.facilities.definitions[facility.definition_id] = replace(
        definition, service_capacity_supplies=()
    )
    return definition


def test_typed_research_site_selection_separates_structural_eligibility_from_runtime_capacity():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.site_runtime_contract")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Typed Research Site Runtime Contract",
        (
            ResearchPrototypeStageSpec(
                "prototype",
                {},
                SiteRequirements(
                    spatial_classification_requirements=req.SURFACE_CLASSIFICATION,
                ),
                (ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),),
            ),
            ResearchDemonstrationStageSpec(
                "demonstration",
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
            ),
        ),
        prerequisites=frozenset(),
    )

    original = _remove_research_site_service(sim)
    app.execute(StartResearch(str(research_id)))

    prototype = _research_row(app, research_id)
    earth = next(
        site for site in prototype.execution_context_options
        if site.operational_node_id == str(EARTH)
    )
    assert not any(blocker.code.startswith("service") for blocker in earth.blockers)
    assert earth.can_select
    leo = next(
        site for site in prototype.execution_context_options
        if site.operational_node_id == str(LEO)
    )
    assert leo.blockers
    assert not leo.can_select
    with pytest.raises(ApplicationError, match="prototype site requirements not met"):
        app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(LEO)))

    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    selected = _research_row(app, research_id)
    assert selected.execution_context is not None
    assert selected.execution_context.operational_node_id == str(EARTH)
    assert selected.execution_context.surface_cell_id is None
    assert any(blocker.code == "service:allocation" for blocker in selected.current_blockers)
    app.execute(AdvanceTime(1))
    assert _research_row(app, research_id).status == "prototype"

    sim.facilities.definitions[TEST_RESEARCH_SITE_FACILITY] = original
    app.execute(AdvanceTime(1))
    demonstration = _research_row(app, research_id)
    assert demonstration.status == "demonstration"

    site = _research_site_fixture(sim)
    app.execute(PauseFacility(str(site.id)))
    demonstration = _research_row(app, research_id)
    earth = next(
        candidate for candidate in demonstration.execution_context_options
        if candidate.operational_node_id == str(EARTH)
    )
    assert any(blocker.code == "capability:active" for blocker in earth.blockers)
    assert earth.can_select
    app.execute(
        SetResearchDemonstrationSite(
            str(research_id), "demonstration", str(EARTH)
        )
    )
    selected = _research_row(app, research_id)
    assert selected.execution_context is not None
    assert selected.execution_context.operational_node_id == str(EARTH)
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
    earth_preview = next(site for site in row.execution_context_options if site.operational_node_id == str(EARTH))
    assert earth_preview.resources[0].reserved_t == pytest.approx(0.25)
    assert earth_preview.resources[0].shortfall_t == pytest.approx(0.75)
    assert next(value for value in earth_preview.comparison_values if value.axis_key == "estimated_days").number_value is None

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



def test_research_configuration_rejects_display_stage_reversal_in_dependency_dag():
    app = build_game_application()
    sim = app._simulation
    later = DefinitionId("test.research.display_stage.later")
    earlier = DefinitionId("test.research.display_stage.earlier")
    sim.research.definitions[later] = ResearchDefinition(
        later,
        "Later display stage prerequisite",
        (ResearchTheoryStageSpec("theory", 1.0),),
        progression_stage=3,
    )
    sim.research.definitions[earlier] = ResearchDefinition(
        earlier,
        "Earlier display stage dependent",
        (ResearchTheoryStageSpec("theory", 1.0),),
        prerequisites=frozenset({later}),
        progression_stage=2,
    )

    with pytest.raises(ConfigurationError, match="display stage contradicts prerequisite direction"):
        validate_simulation_configuration(sim)

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

    app.execute(AdvanceTime(1))
    assert research_id in sim.research.completed
    assert research_id not in sim.research.active


def test_prototype_site_comparison_uses_per_resource_readiness_and_does_not_promise_unfunded_progress():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.comparison_multiple_resources")
    rare = DefinitionId("test.resource.comparison_rare")
    common = DefinitionId("test.resource.comparison_common")
    _research_site_fixture(sim)
    sim.inventory.add(EARTH, rare, 1.0)
    sim.inventory.add(EARTH, common, 20.0)
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id, "Mixed Resource Readiness", (
            ResearchPrototypeStageSpec(
                "prototype", {common: 2.0, rare: 3.0}, SiteRequirements(),
                (ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),),
                required_work=2.0,
            ),
        ), prerequisites=frozenset(),
    )
    app.execute(StartResearch(str(research_id)))
    before = sim.inventory.stock.copy()
    row = _research_row(app, research_id)
    earth = next(option for option in row.execution_context_options if option.operational_node_id == str(EARTH))
    resources = {item.resource_id: item for item in earth.resources}
    assert tuple(item.resource_id for item in earth.resources) == tuple(sorted((str(rare), str(common))))
    assert resources[str(rare)].shortfall_t == pytest.approx(2.0)
    assert resources[str(common)].shortfall_t == pytest.approx(0.0)
    assert resources[str(common)].available_t > sum(item.required_t for item in earth.resources)
    values = {value.axis_key: value.number_value for value in earth.comparison_values}
    assert values["resource_shortfall_t"] == pytest.approx(2.0)
    assert values["estimated_days"] is None
    assert next(value for value in earth.comparison_values if value.axis_key == "estimated_days").text_value
    assert earth.can_select  # Shortage blocks operation, not planning a site.
    assert sim.inventory.stock == before  # Read projections never reserve material.

    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    app.execute(AdvanceTime(1))
    assert sim.research.active[research_id].stage_progress == 0.0
    selected = next(option for option in _research_row(app, research_id).execution_context_options
                    if option.operational_node_id == str(EARTH))
    statuses = {item.resource_id: item for item in selected.resources}
    assert statuses[str(rare)].reserved_t == pytest.approx(1.0)
    assert statuses[str(rare)].shortfall_t == pytest.approx(2.0)
    assert statuses[str(common)].reserved_t == pytest.approx(2.0)
    assert statuses[str(common)].shortfall_t == pytest.approx(0.0)
    assert next(value for value in selected.comparison_values if value.axis_key == "estimated_days").number_value is None

    sim.inventory.add(EARTH, rare, 2.0)
    ready = next(option for option in _research_row(app, research_id).execution_context_options
                 if option.operational_node_id == str(EARTH))
    assert all(item.shortfall_t == pytest.approx(0) for item in ready.resources)
    assert next(value for value in ready.comparison_values if value.axis_key == "estimated_days").number_value == pytest.approx(2.0)


def test_research_execution_context_projects_strategic_comparison_axes_from_application_state():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.execution_context_comparison")
    resource_id = DefinitionId("test.resource.context_comparison")
    _research_site_fixture(sim)
    sim.inventory.add(EARTH, resource_id, 2.0)
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Execution Context Comparison",
        (
            ResearchPrototypeStageSpec(
                "prototype",
                {resource_id: 2.0},
                SiteRequirements(),
                (ServiceCapacityRequirement(TEST_RESEARCH_SITE_SERVICE, 1.0),),
                required_work=2.0,
            ),
        ),
        prerequisites=frozenset(),
    )

    app.execute(StartResearch(str(research_id)))
    row = _research_row(app, research_id)

    axis_keys = {axis.key for axis in row.execution_context_comparison_axes}
    assert "location" in axis_keys
    assert "resource_shortfall_t" in axis_keys
    assert "service_work_capacity" in axis_keys
    assert "estimated_days" in axis_keys
    resource_required_axis = next(axis for axis in row.execution_context_comparison_axes if axis.key == "resource_required_t")
    assert not resource_required_axis.differs  # shared demand remains visible but is not highlighted as a strategic difference

    earth = next(site for site in row.execution_context_options if site.operational_node_id == str(EARTH))
    leo = next(site for site in row.execution_context_options if site.operational_node_id == str(LEO))
    earth_values = {value.axis_key: value for value in earth.comparison_values}
    leo_values = {value.axis_key: value for value in leo.comparison_values}
    assert earth_values["resource_shortfall_t"].number_value == pytest.approx(0.0)
    assert leo_values["resource_shortfall_t"].number_value == pytest.approx(2.0)
    assert earth_values["service_work_capacity"].number_value == pytest.approx(1.0)
    assert leo_values["service_work_capacity"].number_value == pytest.approx(0.0)
    assert earth_values["estimated_days"].number_value == pytest.approx(2.0)
    assert leo_values["estimated_days"].number_value is None
    assert earth_values["estimated_days"].text_value is None
    assert leo_values["estimated_days"].text_value
    assert [(item.required_t, item.reserved_t, item.available_t, item.shortfall_t)
            for item in earth.resources] == [(2.0, 0.0, 2.0, 0.0)]
    assert [(item.required_t, item.reserved_t, item.available_t, item.shortfall_t)
            for item in leo.resources] == [(2.0, 0.0, 0.0, 2.0)]


def test_authored_hardware_research_stages_require_real_site_resources_and_survive_load(tmp_path):
    """Independent physical research tasks cannot be completed by RP alone.

    Propulsion tests consume a physical prototype input; tracking and power
    demonstrations require an operating source that already exists before their
    unlocked Vehicle or Facility is acquired. The same Application boundary
    owns preview, stage-site decision, progress and Save/Load.
    """
    from datetime import datetime, timezone

    from space_idle.bootstrap import build_game_application_for_load, build_game_application_for_scenario
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.persistence import save_game, load_game, capture_state
    from space_idle.scenario import ScenarioFacility
    from space_idle.research import ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec
    from space_idle.shared import DefinitionId

    base = build_standard_scenario_definition()
    originals = build_game_application()._simulation.research.definitions
    cases = (
        (DefinitionId("CH-COMBUSTION-06"), ids.PROPULSION_TEST_FACILITY,
         "restart-propellant-test", ResearchPrototypeStageSpec),
        (DefinitionId("GN-NAVIGATION-06"), ids.DEEP_SPACE_TRACKING_ARRAY,
         "deep-space-tracking-demonstration", ResearchDemonstrationStageSpec),
        (DefinitionId("FP-REACTOR-POWER-04"), ids.INDUSTRIAL_POWER_BLOCK,
         "reactor-load-following-demonstration", ResearchDemonstrationStageSpec),
    )

    for target, required_facility, stage_id, stage_class in cases:
        definition = originals[target]
        assert len(definition.stage_specs) == 2
        assert isinstance(definition.stage_specs[1], stage_class)
        assert definition.stage_specs[1].stage_id == stage_id
        prerequisites = set()
        pending = list(definition.prerequisites)
        while pending:
            technology = pending.pop()
            if technology in prerequisites:
                continue
            prerequisites.add(technology)
            pending.extend(originals[technology].prerequisites)

        # Keep the physical second stage unmodified; only shorten the Theory
        # test input to reach the investment decision without balance coupling.
        def short_theory(sim, _catalog):
            item = sim.research.definitions[target]
            sim.research.definitions[target] = replace(
                item, stage_specs=(ResearchTheoryStageSpec("theory", 0.5),) + item.stage_specs[1:],
            )

        without = replace(base, completed_technologies=tuple(sorted(prerequisites)))
        missing = build_game_application_for_scenario(without, definition_transform=short_theory)
        missing._simulation.research.stored_points = 5.0
        missing.execute(StartResearch(str(target)))
        missing.execute(AdvanceTime(1))
        blocked = _research_row(missing, target)
        assert blocked.current_stage_id == stage_id
        unavailable_site = next(option for option in blocked.execution_context_options
                                if option.operational_node_id == str(ids.EARTH))
        assert any("capability" in blocker.code for blocker in unavailable_site.blockers)

        equipped = replace(without, facilities=without.facilities + (
            ScenarioFacility(required_facility, ids.EARTH),
        ))
        app = build_game_application_for_scenario(equipped, definition_transform=short_theory)
        from space_idle.analysis_graph import DependencyNode
        from space_idle.analysis_coverage import inspect_definition_coverage
        from space_idle.composition.analysis_graph import build_definition_dependency_graph
        dependency_graph = build_definition_dependency_graph(app._simulation, app._catalog)
        assert not dependency_graph.diagnostics
        stage_node = DependencyNode("research_stage", f"{target}/{stage_id}")
        assert any(edge.kind == "requires_site_capability" and edge.target == stage_node
                   and edge.condition == "required_state:ACTIVE"
                   for edge in dependency_graph.relations)
        assert any(edge.kind == "research_stage" and edge.source == stage_node
                   and edge.target.id == str(target) for edge in dependency_graph.relations)
        assert not any(row.code == "potential_research_supply_acquisition_cycle"
                       and row.subject.id == str(target)
                       for row in inspect_definition_coverage(dependency_graph))
        app._simulation.research.stored_points = 5.0
        app.execute(StartResearch(str(target)))
        app.execute(AdvanceTime(1))
        row = _research_row(app, target)
        site = next(option for option in row.execution_context_options
                    if option.operational_node_id == str(ids.EARTH))
        assert site.can_select
        if isinstance(definition.stage_specs[1], ResearchPrototypeStageSpec):
            app.execute(SetResearchPrototypeSite(str(target), stage_id, str(ids.EARTH)))
        else:
            app.execute(SetResearchDemonstrationSite(str(target), stage_id, str(ids.EARTH)))
        app.execute(AdvanceTime(1))
        assert _research_row(app, target).execution_context is not None
        if isinstance(definition.stage_specs[1], ResearchPrototypeStageSpec):
            stage = definition.stage_specs[1]
            for resource_id, amount in stage.resources.items():
                assert app._simulation.research.prototype_reserved_t(
                    target, stage_id, ids.EARTH, resource_id,
                ) == pytest.approx(amount)

        # Operating capability is a live site requirement, not a one-time
        # selection gate. Pausing the actual installed Facility must block
        # further Stage work without clearing the player's selected site.
        equipment = next(row for row in app._simulation.facilities.all_at(ids.EARTH)
                         if row.definition_id == required_facility)
        app.execute(PauseFacility(str(equipment.id)))
        paused_progress = app._simulation.research.active[target].stage_progress
        app.execute(AdvanceTime(1))
        assert app._simulation.research.active[target].stage_progress == paused_progress
        assert any("capability:active" in item.code
                   for item in _research_row(app, target).current_blockers)
        app.execute(ResumeFacility(str(equipment.id)))

        path = tmp_path / f"{target}.json"
        now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        save_game(app, path, saved_at=now)
        loaded, offline = load_game(path, lambda: build_game_application_for_load(
            scenario=equipped, definition_transform=short_theory,
        ), now=now)
        assert offline is None
        assert capture_state(loaded._simulation) == capture_state(app._simulation)
        assert target not in loaded._simulation.technology.completed
        for _ in range(8):
            app.execute(AdvanceTime(1))
            loaded.execute(AdvanceTime(1))
        assert capture_state(loaded._simulation) == capture_state(app._simulation)
        assert target in app._simulation.technology.completed
