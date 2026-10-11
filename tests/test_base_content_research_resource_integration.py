from __future__ import annotations

from space_idle import build_game_application
from space_idle.content.base_research import build_research_definitions
from space_idle.content.base_spatial import build_world_definition






def test_base_content_limits_resource_families_per_recipe():
    """An acquisition or production decision has at most three material inputs.

    Specialized assemblies carry their own upstream commodity demand rather
    than causing every late-game asset to need five unrelated cargo families.
    The limit belongs to authored Content, not to Generic Core's ability to
    represent arbitrary physical resource requirements.
    """
    from space_idle.content.base_construction import (
        build_facility_decommission_recipes,
        build_facility_upgrade_recipes,
        build_spatial_development_recipes,
    )
    from space_idle.content.base_research import build_research_definitions
    from space_idle.research_models import ResearchPrototypeStageSpec

    sim = build_game_application()._simulation
    recipe_inputs = {
        **{f"process:{key}": set(process.inputs_per_day)
           for key, process in sim.industry.processes.items()},
        **{f"construction:{key}": {row.resource_id for row in recipe.resources}
           for key, recipe in sim.projects.recipes.items()},
        **{f"upgrade:{key}": {row.resource_id for row in recipe.resources}
           for key, recipe in build_facility_upgrade_recipes().items()},
        **{f"decommission:{key}": {row.resource_id for row in recipe.resources}
           for key, recipe in build_facility_decommission_recipes(sim.facilities.definitions).items()},
        **{f"development:{key}": {row.resource_id for row in recipe.resources}
           for key, recipe in build_spatial_development_recipes().items()},
        **{f"vehicle:{key}": {resource for resource, _ in vehicle.production.resources}
           for key, vehicle in sim.transport.vehicle_defs.items() if vehicle.production},
        **{f"founding:{key}": set(recipe.investment_totals()) | set(recipe.initial_inventory_totals())
           for key, recipe in sim.founding.deployment_recipes.items()},
        **{f"research:{key}:{stage.stage_id}": set(stage.resources)
           for key, research in build_research_definitions().items()
           for stage in research.stage_specs if isinstance(stage, ResearchPrototypeStageSpec)},
    }
    assert recipe_inputs
    assert all(len(resources) <= 3 for resources in recipe_inputs.values()), {
        name: len(resources) for name, resources in recipe_inputs.items() if len(resources) > 3
    }
    for vehicle in sim.transport.vehicle_defs.values():
        if vehicle.production is None or vehicle.retirement is None:
            continue
        invested = dict(vehicle.production.resources)
        recovered = dict(vehicle.retirement.recovery_resources_per_unit)
        # Reduced-input manufacturing must not recover equipment that was
        # never invested in the vehicle or multiply goods on retirement.
        assert recovered.keys() <= invested.keys()
        assert all(0 <= amount <= invested[resource] for resource, amount in recovered.items())
    # Single-feed physical extraction/separation is not padded with fictional inputs.
    assert any(len(process.inputs_per_day) == 1 for process in sim.industry.processes.values())


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
    vehicle = sim.transport.vehicle_defs[ids.ORBITAL_RESOURCE_MAPPING_SPACECRAFT]
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
    provider_id = ids.ORBITAL_RESOURCE_MAPPING_PROVIDER
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




def test_surface_mobility_assets_have_real_service_and_exclusive_survey_fleet():
    from dataclasses import replace
    from space_idle import AdvanceTime, PlanBuild, ProduceVehicle, SetSurveyProviderFleetQuantity
    from space_idle.bootstrap import build_game_application_for_scenario
    from space_idle.content import base_ids as ids
    from space_idle.content.base_scenario import build_standard_scenario_definition

    scenario = build_standard_scenario_definition()
    # These test sites stand in for a supplied industrial base; the integrated
    # manufacturing path for this input is tested with actual operating mills.
    from space_idle.scenario import ScenarioInventoryStock
    app = build_game_application_for_scenario(replace(
        scenario, completed_technologies=tuple(build_research_definitions()),
        inventory_stock=scenario.inventory_stock + (
            ScenarioInventoryStock(ids.EARTH, ids.OPTICAL_INSTRUMENT_PACKAGES, 4.0),
        ),
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


def test_physical_content_can_be_reused_across_bodies_without_name_based_exceptions():
    """Every acquired asset uses physical site/operation criteria, not its first Scenario."""
    from space_idle.content import base_ids as ids
    from space_idle.site import evaluate_physical_site_requirements
    from space_idle.shared import SurfaceCellId

    sim = build_game_application()._simulation
    environment = sim.facilities.environment
    surface_contexts = (
        ids.EARTH_CELL_INDUSTRIAL,
        ids.MOON_CELL_SOUTH_POLAR_PLAIN,
        ids.MARS_CELL_EQUATORIAL_PLAIN,
        SurfaceCellId('base.cell.venus.highland'),
    )
    # A robotic staging package and enclosed oxide processor are not Moon
    # properties. Outpost thermal limits reject extreme sites, while the
    # enclosed oxide reactor is governed by its own power and materials.
    deploy = sim.founding.deployment_recipes[ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE]
    oxide = sim.facilities.definitions[ids.MOLTEN_OXIDE_ELECTROLYZER]
    for cell in surface_contexts:
        assert bool(evaluate_physical_site_requirements(deploy.target_requirements, cell, sim.day, environment)) == (cell == SurfaceCellId("base.cell.venus.highland"))
        assert not evaluate_physical_site_requirements(oxide.installation_requirements, cell, sim.day, environment)
        assert not evaluate_physical_site_requirements(oxide.operating_requirements, cell, sim.day, environment)
    assert evaluate_physical_site_requirements(oxide.installation_requirements, ids.LEO, sim.day, environment)

    # Cold volatile deposits occur in both near-vacuum icy regions and dense
    # cold atmospheres. Pressure alone must not turn a Titan resource into an
    # unobtainable, Moon-specific raw material.
    from space_idle.content import base_requirements as req
    titan = SurfaceCellId('base.cell.titan.highland')
    assert not evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, titan, sim.day, environment)
    assert not evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, ids.MOON_CELL_POLAR_COLD_TRAP, sim.day, environment)
    assert evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS, sim.day, environment)
    assert not evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, SurfaceCellId("base.cell.mercury.polar"), sim.day, environment)

    # Atmospheric and low-pressure infrastructure stay physically distinct.
    low_pressure = sim.facilities.definitions[ids.VACUUM_CARGO_HANDLING_TERMINAL]
    ambient = sim.facilities.definitions[ids.BREATHABLE_SURFACE_LIFE_SUPPORT]
    for cell in (ids.MOON_CELL_SOUTH_POLAR_PLAIN, ids.MARS_CELL_EQUATORIAL_PLAIN):
        assert not evaluate_physical_site_requirements(low_pressure.installation_requirements, cell, sim.day, environment)
        assert evaluate_physical_site_requirements(ambient.operating_requirements, cell, sim.day, environment)
    for cell in (ids.EARTH_CELL_INDUSTRIAL, SurfaceCellId('base.cell.venus.highland')):
        assert evaluate_physical_site_requirements(low_pressure.installation_requirements, cell, sim.day, environment)
    assert not evaluate_physical_site_requirements(ambient.operating_requirements, ids.EARTH_CELL_INDUSTRIAL, sim.day, environment)

    # Asset and method IDs describe reusable engineering roles. World geography,
    # one-shot targeted science, initial Scenario and Market location remain
    # separate Content, rather than silently constraining an asset's identity.
    owned = (sim.facilities.definitions, sim.transport.vehicle_defs,
             sim.founding.deployment_recipes, sim.survey.providers,
             sim.industry.processes, sim.extraction.specs)
    assert all(not any(planet in str(key) for planet in ('earth', 'lunar', 'moon', 'mars'))
               for definitions in owned for key in definitions)
    assert sim.transport.vehicle_defs[ids.ORBITAL_RESOURCE_MAPPING_SPACECRAFT].performance.generic_capabilities
    assert sim.survey.providers[ids.ORBITAL_RESOURCE_MAPPING_PROVIDER].observation_modes

    # Physical eligibility is tested above; now settle real Resource ownership
    # at unlike Worlds using the same Extraction and physical infrastructure.
    from dataclasses import replace
    from space_idle import AdvanceTime, GetOperationalNode
    from space_idle.bootstrap import build_game_application_for_scenario
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.scenario import (
        ScenarioSurfaceLocation, ScenarioFacility,
    )
    from space_idle.shared import SpatialNodeId, CelestialBodyId
    base = build_standard_scenario_definition()
    regions = (
        (ids.MOON, ids.MOON_CELL_POLAR_COLD_TRAP),
        (CelestialBodyId('base.body.titan'), titan),
        (CelestialBodyId('base.body.mercury'), SurfaceCellId('base.cell.mercury.polar')),
    )
    for body, cell in regions:
        location = SpatialNodeId(f'test.cold_volatile.{body}')
        scenario = replace(
            base,
            surface_locations=base.surface_locations + (
                ScenarioSurfaceLocation(location, 'Volatile production site', body, cell),
            ),
            facilities=base.facilities + (
                ScenarioFacility(ids.INDUSTRIAL_POWER_BLOCK, location),
                ScenarioFacility(ids.SURFACE_DISTRIBUTION_HUB, location, cell),
                ScenarioFacility(ids.VOLATILE_EXTRACTOR, location, cell),
            ),
            known_surface_resources=base.known_surface_resources + (
                (cell, ids.VOLATILE_BEARING_MATERIAL),
            ),
        )
        case = build_game_application_for_scenario(scenario)
        actual = case._simulation
        before = actual.inventory.amount(location, ids.VOLATILE_BEARING_MATERIAL)
        case.execute(AdvanceTime(3))
        after = actual.inventory.amount(location, ids.VOLATILE_BEARING_MATERIAL)
        assert after > before
        production = next(row for row in case.query(GetOperationalNode(str(location))).extraction
                          if row.resource_id == str(ids.VOLATILE_BEARING_MATERIAL))
        assert production.output_t_per_day > 0


def test_materials_thermal_and_biomedical_science_capital_creates_distinct_physical_research_capacity(tmp_path):
    """Three expensive research routes consume real construction, power and crew.

    Research output and admission are physical facility effects; no completed
    Technology silently improves the original laboratories. Both Earth-based
    and orbital infrastructure run through the same Application/Owner State.
    """
    from dataclasses import replace
    from datetime import datetime, timezone

    from space_idle import (AdvanceTime, GetBuildOptions, GetResearch, PlanBuild,
                            PauseFacility, StartResearch, SetResearchPrototypeSite)
    from space_idle.bootstrap import build_game_application_for_load, build_game_application_for_scenario
    from space_idle.content import base_ids as ids
    from space_idle.content.base_ids import research_id
    from space_idle.content.base_research import build_research_definitions
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.persistence import capture_state, load_game, save_game
    from space_idle.scenario import ScenarioFacility, ScenarioInventoryStock

    equipment = (
        (ids.MATERIALS_FATIGUE_BEAMLINE, ids.EARTH),
        (ids.ORBITAL_THERMAL_VACUUM_LAB, ids.LEO),
        (ids.BIOREGENERATIVE_BIOMEDICAL_LAB, ids.EARTH),
    )
    research = build_research_definitions()
    needed = {
        research_id(code) for code in (
            "MS-MATERIALS-07", "TH-THERMAL-TRANSPORT-05",
            "TH-THERMAL-TRANSPORT-06", "MC-MANUFACTURING-CONSTRUCTION-05",
            "BIO-HUMAN-BIOLOGY-MEDICINE-09", "LS-ATMOSPHERE-WATER-WASTE-09",
        )
    }
    # The experimental work must be researchable only after its real prereqs;
    # constructing the equipment is not a shortcut to completed Technology.
    material_research = research_id("MS-MATERIALS-10")
    needed.update(research[material_research].prerequisites)
    frontier = list(needed)
    while frontier:
        extra = research[frontier.pop()].prerequisites - needed
        needed.update(extra)
        frontier.extend(extra)
    setup = build_standard_scenario_definition()
    facilities = (
        ScenarioFacility(ids.MACHINE_SHOP, ids.EARTH,
                         invested_resources=((ids.STRUCTURAL_COMPONENTS, 9.0), (ids.MACHINERY, 9.0))),
        ScenarioFacility(ids.CLOSED_CYCLE_HABITAT, ids.EARTH,
                         invested_resources=((ids.STRUCTURAL_COMPONENTS, 17.0),
                                             (ids.RADIATION_SHIELDING_PANELS, 4.0),
                                             (ids.THERMAL_CONTROL_ASSEMBLIES, 1.0))),
        ScenarioFacility(ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.LEO,
                         invested_resources=((ids.STRUCTURAL_COMPONENTS, 4.0), (ids.MACHINERY, 3.0),
                                             (ids.PRECISION_ELECTRONICS, 1.5))),
        ScenarioFacility(ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER, ids.LEO,
                         invested_resources=((ids.STRUCTURAL_COMPONENTS, 9.0),
                                             (ids.THERMAL_CONTROL_ASSEMBLIES, 2.0),
                                             (ids.RADIATION_SHIELDING_PANELS, 3.0))),
    )
    stocks = tuple(
        ScenarioInventoryStock(node_id, resource_id, 250.0)
        for node_id in (ids.EARTH, ids.LEO)
        for resource_id in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS)
    )
    scenario = replace(
        setup,
        facilities=setup.facilities + facilities,
        completed_technologies=tuple(sorted(needed)),
        inventory_stock=setup.inventory_stock + stocks + (
            ScenarioInventoryStock(ids.EARTH, ids.CERAMICS_GLASS, 10.0),
            ScenarioInventoryStock(ids.EARTH, ids.PRECISION_COMPONENTS, 10.0),
            ScenarioInventoryStock(ids.EARTH, ids.RADIATION_SHIELDING_PANELS, 15.0),
            ScenarioInventoryStock(ids.EARTH, ids.OPTICAL_INSTRUMENT_PACKAGES, 6.0),
            ScenarioInventoryStock(ids.LEO, ids.THERMAL_CONTROL_ASSEMBLIES, 9.0),
            ScenarioInventoryStock(ids.LEO, ids.OPTICAL_INSTRUMENT_PACKAGES, 3.0),
        ),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation
    for facility_id, node_id in equipment:
        build = next(row for row in app.query(GetBuildOptions(str(node_id))).items
                     if row.facility_definition_id == str(facility_id))
        assert build.resources and build.construction_required > 0
        assert build.power_nominal_load_mw > 2.0
        assert not any(blocker.kind == "technology" for blocker in build.blockers)
        assert not any(row.provider_definition_id == str(facility_id)
                       for row in app.query(GetResearch()).providers)
        assert app.execute(PlanBuild(str(node_id), str(facility_id),
                                     procurement_policy="extended_wait")).created_id

    for _ in range(800):
        app.execute(AdvanceTime(1))
        providers = {row.provider_definition_id: row for row in app.query(GetResearch()).providers}
        if all(str(facility_id) in providers for facility_id, _node_id in equipment):
            break
    else:
        raise AssertionError('physical science infrastructure did not complete')
    assert providers[str(ids.MATERIALS_FATIGUE_BEAMLINE)].generation_points_per_day > 0
    assert providers[str(ids.ORBITAL_THERMAL_VACUUM_LAB)].generation_points_per_day > 0
    # Local population caps biomedical RP; facility's 250 RP/day nominal rate
    # must not create fictitious crew or bypass life support allocation.
    medical = providers[str(ids.BIOREGENERATIVE_BIOMEDICAL_LAB)]
    assert medical.generation_points_per_day > 0
    assert medical.admitted_generation_points_per_day <= medical.generation_points_per_day + 1e-8
    assert app.query(GetResearch()).storage_capacity_points > 18000

    for research_id_str, expected_cap in (
        ('MS-MATERIALS-10', 'material_fatigue_beamline'),
        ('TH-THERMAL-TRANSPORT-07', 'orbital_thermal_vacuum_calorimetry'),
        ('BIO-HUMAN-BIOLOGY-MEDICINE-12', 'bioregenerative_biomedical_research'),
    ):
        stage = research[research_id(research_id_str)].stage_specs[1]
        assert any(requirement.capability_id == expected_cap
                   for requirement in stage.site_requirements.capability_requirements)

    # Use the real RP gained from physical providers for a late-stage materials
    # project, then execute its resource-consuming Prototype on installed
    # hardware. This is not just a static Definition-to-Technology edge.
    app.execute(StartResearch(str(material_research)))
    for _ in range(150):
        app.execute(AdvanceTime(1))
        item = next(row for row in app.query(GetResearch()).items
                    if row.id == str(material_research))
        if item.current_stage_id == "irradiated-material-fatigue-trial":
            break
    else:
        raise AssertionError(f'material research did not reach experiment: {item.status}, '
                             f'{item.current_stage_id}, stored RP={sim.research.stored_points}, '
                             f'execution={app.query(GetResearch()).research_execution_per_day}')
    app.execute(SetResearchPrototypeSite(str(material_research),
                                         "irradiated-material-fatigue-trial", str(ids.EARTH)))
    app.execute(AdvanceTime(1))
    assert sim.research.prototype_reserved_t(
        material_research, "irradiated-material-fatigue-trial", ids.EARTH,
        ids.CERAMICS_GLASS,
    ) > 0
    saved_at = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save_path = tmp_path / 'science-capital.json'
    save_game(app, save_path, saved_at=saved_at)
    restored, offline = load_game(save_path, build_game_application_for_load, now=saved_at)
    assert offline is None
    assert capture_state(restored._simulation) == capture_state(sim)
    app.execute(AdvanceTime(2))
    restored.execute(AdvanceTime(2))
    assert capture_state(restored._simulation) == capture_state(sim)

    orbital = next(f for f in sim.facilities.facilities.values()
                   if f.definition_id == ids.ORBITAL_THERMAL_VACUUM_LAB)
    app.execute(PauseFacility(str(orbital.id)))
    paused = next(row for row in app.query(GetResearch()).providers
                  if row.provider_definition_id == str(ids.ORBITAL_THERMAL_VACUUM_LAB))
    assert paused.generation_points_per_day == 0
    assert paused.storage_capacity_points == 0

    # Medical research also depends on a *currently operating* closed habitat.
    # Existing biomedical instruments remain owned, but cannot claim free
    # inhabited laboratory operations after life support is switched off.
    habitat = next(f for f in sim.facilities.facilities.values()
                   if f.definition_id == ids.CLOSED_CYCLE_HABITAT)
    app.execute(PauseFacility(str(habitat.id)))
    medical_paused = next(row for row in app.query(GetResearch()).providers
                          if row.provider_definition_id == str(ids.BIOREGENERATIVE_BIOMEDICAL_LAB))
    assert medical_paused.generation_points_per_day == 0
