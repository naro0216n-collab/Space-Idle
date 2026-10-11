from __future__ import annotations

from space_idle import build_game_application


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


def test_completed_technology_enables_process_and_vehicle_methods_without_rewriting_assets():
    """One Technology owner gates physical methods; existing projects retain their obligations."""
    import pytest
    from space_idle import (
        ApplicationError, GetLogistics, GetOperationalNode, GetResearch,
        SetFacilityProcess, ProduceVehicle,
    )
    from space_idle.content import base_ids as ids
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
