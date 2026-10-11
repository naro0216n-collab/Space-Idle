from __future__ import annotations

from space_idle import build_game_application
from space_idle.content.base_research import build_research_definitions
from space_idle.content.base_spatial import build_world_definition


def test_base_technology_content_preserves_dag_and_stage_independence():
    """Content validation, not a snapshot of its current size or research order."""
    definitions = build_research_definitions()
    assert definitions
    assert all(definition.progression_stage >= 1 and definition.category and definition.series
               for definition in definitions.values())

    visiting = set()
    visited = set()

    def visit(research_id):
        if research_id in visited:
            return
        assert research_id not in visiting
        visiting.add(research_id)
        for prerequisite_id in definitions[research_id].prerequisites:
            assert prerequisite_id in definitions
            assert definitions[prerequisite_id].progression_stage <= definitions[research_id].progression_stage
            visit(prerequisite_id)
        visiting.remove(research_id)
        visited.add(research_id)

    for research_id in definitions:
        visit(research_id)

    # The graph permits independent starts and interdisciplinary prerequisites;
    # neither stage metadata nor series identity imposes a linear unlock order.
    assert len([row for row in definitions.values() if not row.prerequisites]) > 1
    assert any(
        any(definitions[prerequisite].category != row.category for prerequisite in row.prerequisites)
        for row in definitions.values()
    )



def test_base_resource_methods_connect_surveyed_geology_to_processing_and_construction():
    """Check playable content connectivity without preserving old IDs or balance values."""
    app = build_game_application()
    sim = app._simulation
    graph, _ = build_world_definition()
    definitions = build_research_definitions()
    resource_ids = set(sim.inventory.resource_definitions)
    potential_resources = {
        resource_id
        for cell in graph.surface_cells.values()
        for resource_id in cell.resource_potential_by_resource
    }

    extraction_outputs = {
        spec.output_resource_id for spec in sim.extraction.specs.values()
        if spec.resource_id in potential_resources
    }
    assert extraction_outputs
    assert extraction_outputs <= resource_ids

    processes = tuple(sim.industry.processes.values())
    assert processes
    assert all(set(process.inputs_per_day) | set(process.outputs_per_day) <= resource_ids
               for process in processes)
    assert all(any(process in sim.industry.compatible_processes(definition_id)
                   for definition_id in sim.facilities.definitions) for process in processes)

    # Reachability is through explicitly described input/output edges. There is
    # no assumption that all resources substitute for one another.
    reachable = set(extraction_outputs)
    while True:
        newly_reachable = reachable | {
            output_id
            for process in processes
            if set(process.inputs_per_day) <= reachable
            for output_id in process.outputs_per_day
        }
        if newly_reachable == reachable:
            break
        reachable = newly_reachable

    construction_resources = {
        requirement.resource_id
        for recipe in sim.projects.recipes.values()
        for requirement in recipe.resources
    }
    assert (reachable - extraction_outputs) & construction_resources

    # Technology gates operational methods; resource definitions remain usable
    # independent of the game's particular DAG/content naming scheme.
    assert any(recipe.prerequisite_technologies for recipe in sim.projects.recipes.values())
    assert all(
        recipe.prerequisite_technologies <= definitions.keys()
        and recipe.prerequisite_technologies.isdisjoint(resource_ids)
        for recipe in sim.projects.recipes.values()
    )


def test_completed_technology_enables_process_and_vehicle_methods_without_rewriting_assets(tmp_path):
    """One Technology owner gates physical methods; existing projects retain their obligations."""
    from datetime import datetime, timezone
    import pytest
    from space_idle import (
        ApplicationError, GetLogistics, GetOperationalNode, GetResearch,
        SetFacilityProcess, ProduceVehicle,
    )
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.content import base_ids as ids
    from space_idle.persistence import capture_state, save_game, load_game
    from space_idle.shared import EntityId

    app = build_game_application()
    sim = app._simulation
    process = sim.industry.processes[ids.PROCESS_MINERAL_SINTER]
    vehicle = sim.transport.vehicle_defs[ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT]
    assert process.prerequisite_technologies
    assert vehicle.production.prerequisite_technologies

    facility_id = sim.facilities.install(
        ids.MINERAL_SINTERING, ids.EARTH,
    )
    industry = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                    if row.facility_id == str(facility_id))
    option = next(row for row in industry.process_options if row.process_id == str(process.id))
    assert not option.can_select
    assert {row.subject_id for row in option.blockers if row.kind == "technology"} == {
        str(tech_id) for tech_id in process.prerequisite_technologies
    }
    with pytest.raises(ApplicationError, match="technology"):
        app.execute(SetFacilityProcess(str(facility_id), str(process.id)))

    production_option = next(row for row in app.query(GetLogistics()).vehicle_production_options
                             if row.vehicle_definition_id == str(vehicle.id)
                             and row.operational_node_id == str(ids.EARTH))
    assert not production_option.can_plan
    assert {row.subject_id for row in production_option.blockers if row.kind == "technology"} == {
        str(tech_id) for tech_id in vehicle.production.prerequisite_technologies
    }
    with pytest.raises(ApplicationError, match="technology"):
        app.execute(ProduceVehicle(str(vehicle.id), str(ids.EARTH)))

    unlocks = {
        (unlock.kind, unlock.id)
        for row in app.query(GetResearch()).items
        for unlock in row.unlocks
    }
    assert ("process", str(process.id)) in unlocks
    assert ("vehicle_production", str(vehicle.id)) in unlocks

    sim.technology.completed.update(process.prerequisite_technologies | vehicle.production.prerequisite_technologies)
    assert next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                if row.facility_id == str(facility_id)).process_options[0].can_select
    app.execute(SetFacilityProcess(str(facility_id), str(process.id)))
    sim.inventory.add(ids.EARTH, ids.MINERAL_FEEDSTOCK, 10.0)
    output_before = sim.inventory.amount(ids.EARTH, ids.CERAMICS_GLASS)
    sim.advance_days(1)
    assert sim.inventory.amount(ids.EARTH, ids.CERAMICS_GLASS) > output_before
    project_id = app.execute(ProduceVehicle(str(vehicle.id), str(ids.EARTH))).created_id
    assert project_id
    # Existing process intent and physical manufacturing obligation remain valid
    # if requirements change later; loss of eligibility halts execution only.
    sim.technology.completed.difference_update(process.prerequisite_technologies | vehicle.production.prerequisite_technologies)
    assert sim.facilities.facilities[facility_id].selected_process_id == process.id
    assert any(str(item.id) == project_id for item in sim.transport.vehicle_production_projects.values())
    sim.advance_days(1)
    # Project was validly acquired while the method was eligible; later research
    # changes do not unwind already incurred manufacturing obligations.
    assert sim.transport.vehicle_production_projects[EntityId(project_id)].progress_days > 0
    process_state = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                         if row.facility_id == str(facility_id))
    assert process_state.scale == 0
    assert any(row.kind == "technology" for row in process_state.limiting_factors)

    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    path = tmp_path / "technology-eligibility.json"
    save_game(app, path, saved_at=fixed)
    loaded, _ = load_game(path, build_game_application_for_load, now=fixed)
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_survey_method_technology_blocks_progress_without_discarding_campaign():
    """A mode is a reusable method, not an implicit property of its Provider or body."""
    from space_idle import AdvanceTime, GetResearch, StartSurvey, SurveyProviderConstraintInput
    from space_idle.content import base_ids as ids

    app = build_game_application()
    sim = app._simulation
    provider_id = ids.LUNAR_FLEET_SURVEY_PROVIDER
    mode_id = "interplanetary_remote_spectrometry"
    mode = sim.survey.observation_mode(provider_id, mode_id)
    assert mode.prerequisite_technologies
    cell_id, resource_id = ids.MARS_CELL_EQUATORIAL_PLAIN, ids.MINERAL_FEEDSTOCK
    campaign_id = app.execute(StartSurvey(
        target_cell_ids=(str(cell_id),),
        resource_ids=(str(resource_id),),
        goal_knowledge_level=1,
        provider_constraint=SurveyProviderConstraintInput(str(provider_id), str(ids.LUNAR_ORBIT)),
        observation_mode_constraint=mode_id,
    )).created_id
    campaign = sim.survey.campaigns[campaign_id]
    projection = sim.survey.campaign_projection(campaign, day=sim.day)
    assert projection.resolved_candidate is None
    candidate = next(row for row in projection.candidates
                     if row.provider_definition_id == provider_id and row.observation_mode_id == mode_id)
    assert {f"technology:{tech_id}" for tech_id in mode.prerequisite_technologies} <= set(candidate.blockers)
    assert any(
        unlock.kind == "survey_mode" and unlock.id == f"{provider_id}:{mode_id}"
        for row in app.query(GetResearch()).items for unlock in row.unlocks
    )
    before = sim.survey.progress(cell_id, resource_id)
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(cell_id, resource_id) == before

    sim.technology.completed.update(mode.prerequisite_technologies)
    candidate, blockers = sim.survey.resolve_campaign_candidate(campaign, day=sim.day)
    assert blockers == () and candidate is not None
    app.execute(AdvanceTime(1))
    progress = sim.survey.progress(cell_id, resource_id)
    assert progress > before
    sim.technology.completed.difference_update(mode.prerequisite_technologies)
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(cell_id, resource_id) == progress
    assert campaign.id in sim.survey.campaigns


def test_space_asset_portfolio_uses_same_construction_production_provider_and_save_contract(tmp_path):
    """An orbit-owned asset portfolio follows ordinary procurement, power and Fleet lifecycle.

    A scenario with delivered materials exercises physical industry instead of
    minting a replacement Fleet directly at the destination as a research reward.
    """
    from dataclasses import replace
    from datetime import datetime, timezone

    from space_idle import (
        AdvanceTime, GetBuildOptions, GetLogistics, PlanBuild, ProduceVehicle,
        SetSurveyProviderFleetQuantity,
    )
    from space_idle.bootstrap import build_game_application_for_scenario, build_game_application_for_load
    from space_idle.content import base_ids as ids
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.persistence import capture_state, save_game, load_game
    from space_idle.scenario import ScenarioInventoryStock

    baseline = build_standard_scenario_definition()
    delivered = tuple(
        ScenarioInventoryStock(ids.LUNAR_ORBIT, resource_id, 300.0)
        for resource_id in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS)
    )
    scenario = replace(
        baseline,
        inventory_stock=baseline.inventory_stock + delivered,
        completed_technologies=tuple(build_research_definitions()),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation

    orbital_assets = (
        ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.ORBITAL_SOLAR_ARRAY,
        ids.ORBITAL_ASSEMBLY_YARD, ids.ORBITAL_PROPELLANT_DEPOT, ids.ORBITAL_HABITAT,
    )
    for definition_id in orbital_assets:
        option = next(
            row for row in app.query(GetBuildOptions(str(ids.LUNAR_ORBIT))).items
            if row.facility_definition_id == str(definition_id)
        )
        assert not any(row.kind in ("spatial", "technology") for row in option.blockers)
        assert app.execute(PlanBuild(str(ids.LUNAR_ORBIT), str(definition_id))).created_id

    # All construction competes for the one robotic platform and real local stock.
    app.execute(AdvanceTime(200))
    installed = {row.definition_id for row in sim.facilities.all_at(ids.LUNAR_ORBIT)}
    assert set(orbital_assets) <= installed
    for vehicle_id in (ids.CREW_TRANSFER_SPACECRAFT, ids.RADAR_MAPPING_ORBITER):
        option = next(
            row for row in app.query(GetLogistics()).vehicle_production_options
            if row.vehicle_definition_id == str(vehicle_id)
            and row.operational_node_id == str(ids.LUNAR_ORBIT)
        )
        assert not any(row.kind in ("spatial", "technology") for row in option.blockers)
        assert app.execute(ProduceVehicle(str(vehicle_id), str(ids.LUNAR_ORBIT))).created_id

    app.execute(AdvanceTime(45))
    for vehicle_id in (ids.CREW_TRANSFER_SPACECRAFT, ids.RADAR_MAPPING_ORBITER):
        assert sim.transport.fleet_pool(vehicle_id, ids.LUNAR_ORBIT).total_units == 1
    assert app.execute(SetSurveyProviderFleetQuantity(
        str(ids.RADAR_MAPPING_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT),
        str(ids.RADAR_MAPPING_ORBITER), 1,
    )).created_id
    assert sim.transport.fleet_free_units(ids.RADAR_MAPPING_ORBITER, ids.LUNAR_ORBIT) == 0

    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    path = tmp_path / "physical-portfolio.json"
    save_game(app, path, saved_at=moment)
    restored, _ = load_game(path, build_game_application_for_load, now=moment)
    assert capture_state(restored._simulation) == capture_state(sim)
    restored.execute(AdvanceTime(1))
    app.execute(AdvanceTime(1))
    assert capture_state(restored._simulation) == capture_state(sim)


def test_surface_mobility_assets_have_real_service_and_exclusive_survey_fleet():
    from dataclasses import replace
    from space_idle import AdvanceTime, PlanBuild, ProduceVehicle, SetSurveyProviderFleetQuantity
    from space_idle.bootstrap import build_game_application_for_scenario
    from space_idle.content import base_ids as ids
    from space_idle.content.base_scenario import build_standard_scenario_definition

    scenario = build_standard_scenario_definition()
    app = build_game_application_for_scenario(replace(
        scenario, completed_technologies=tuple(build_research_definitions()),
    ))
    sim = app._simulation
    assert app.execute(PlanBuild(str(ids.EARTH), str(ids.SURFACE_ROVER_SERVICE_DEPOT))).created_id
    app.execute(AdvanceTime(35))
    assert any(row.definition_id == ids.SURFACE_ROVER_SERVICE_DEPOT
               for row in sim.facilities.all_at(ids.EARTH))
    for vehicle_id in (ids.ROBOTIC_SURFACE_PROSPECTOR, ids.PRESSURIZED_SURFACE_ROVER):
        assert app.execute(ProduceVehicle(str(vehicle_id), str(ids.EARTH))).created_id
    app.execute(AdvanceTime(25))
    assert sim.transport.fleet_pool(ids.ROBOTIC_SURFACE_PROSPECTOR, ids.EARTH).total_units == 1
    assert sim.transport.fleet_pool(ids.PRESSURIZED_SURFACE_ROVER, ids.EARTH).total_units == 1
    assert app.execute(SetSurveyProviderFleetQuantity(
        str(ids.SURFACE_PROSPECTOR_SURVEY_PROVIDER), str(ids.EARTH),
        str(ids.ROBOTIC_SURFACE_PROSPECTOR), 1,
    )).created_id
    assert sim.transport.fleet_free_units(ids.ROBOTIC_SURFACE_PROSPECTOR, ids.EARTH) == 0
    assert sim.transport.fleet_free_units(ids.PRESSURIZED_SURFACE_ROVER, ids.EARTH) == 1

    # Physical communication/propulsion test laboratories contribute RP through
    # the normal installed Facility -> Research Provider path, not a technology buff.
    for facility_id in (ids.PROPULSION_TEST_FACILITY, ids.DEEP_SPACE_TRACKING_ARRAY):
        assert app.execute(PlanBuild(str(ids.EARTH), str(facility_id))).created_id
    app.execute(AdvanceTime(85))
    from space_idle import GetResearch
    providers = {row.provider_definition_id: row for row in app.query(GetResearch()).providers}
    assert providers[str(ids.PROPULSION_TEST_RESEARCH_PROVIDER)].generation_points_per_day > 0
    assert providers[str(ids.DEEP_SPACE_TRACKING_RESEARCH_PROVIDER)].generation_points_per_day > 0
