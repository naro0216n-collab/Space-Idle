from __future__ import annotations

from math import ceil

import pytest

from space_idle import (
    AdvanceTime,
    CreateLogisticsLane,
    DispatchVehicle,
    FundResearchPrototype,
    GetCargoOrders,
    GetLocation,
    GetLogisticsLanes,
    GetProjects,
    GetResearch,
    GetRoutes,
    GetSurveys,
    GetVehicles,
    PlanBuild,
    RefuelVehicle,
    SetConstructionWeight,
    SetResearchDemonstrationSite,
    SetResearchPrototypeSite,
    StartResearch,
    StartSurvey,
    SubmitCargo,
    build_game_application,
)
from space_idle.content.base_game import (
    CRYOGENIC_STORAGE,
    CREWED_ORBITAL_LABORATORY,
    EARTH,
    ELECTROLYSIS_PLANT,
    INDUSTRIAL_POWER_BLOCK,
    LEO,
    LUNAR_ORBIT,
    MICROGRAVITY_EXPERIMENT_PLATFORM,
    ORBITAL_LOGISTICS_NODE,
    POLAR_COLD_TRAP,
    PROPELLANT,
    PROPELLANT_PLANT,
    REUSABLE_ORBITAL_CARGO_TUG,
    REUSABLE_SURFACE_CARGO_LANDER,
    ROBOTIC_GEOLOGY_STATION,
    ROBOTIC_SURVEY_PACKAGE,
    SOUTH_POLAR_RIDGE,
    SURFACE_POWER_GRID,
    TECH_CISLUNAR_LOGISTICS,
    TECH_CREWED_ORBITAL_RESEARCH,
    TECH_INDUSTRIAL_ELECTROLYSIS,
    TECH_LUNAR_PROSPECTING,
    TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS,
    TECH_ORBITAL_OPERATIONS,
    TECH_PROPELLANT_HANDLING,
    TECH_ROBOTIC_FIELD_GEOLOGY,
    TECH_VOLATILE_ISRU,
    VOLATILE_EXTRACTOR,
    WATER,
    WATER_STORAGE,
)
from space_idle.persistence import capture_state, restore_state


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _wait_until_research_startable(app, research_id, max_days=2000):
    elapsed = 0
    while elapsed <= max_days:
        view = app.query(GetResearch())
        row = next(item for item in view.items if item.id == str(research_id))
        if row.can_start:
            return row
        non_time_blockers = [code for code, _detail in row.start_blockers if code != "research_points"]
        if non_time_blockers:
            raise AssertionError(
                f"research cannot become startable by waiting: {research_id}: {non_time_blockers}"
            )
        if view.generation_points_per_day <= 1e-12:
            raise AssertionError(f"research has no RP generation: {research_id}")
        gap = max(0.0, row.research_point_cost - view.stored_points)
        step = max(1, ceil(max(0.0, gap - 1e-9) / view.generation_points_per_day))
        step = min(step, max_days - elapsed)
        if step <= 0:
            break
        app.execute(AdvanceTime(step))
        elapsed += step
    raise AssertionError(f"research never became startable: {research_id}")


def _ensure_lane(app, source_id, destination_id, capacity_t_per_day=50.0):
    if source_id == destination_id:
        return None
    existing = next(
        (
            lane for lane in app.query(GetLogisticsLanes()).items
            if lane.source_id == str(source_id) and lane.destination_id == str(destination_id)
        ),
        None,
    )
    if existing is not None:
        return existing.id
    result = app.execute(CreateLogisticsLane(
        str(source_id), str(destination_id), capacity_t_per_day, priority=100
    ))
    assert result.created_id is not None
    return result.created_id


def _complete_research(app, research_id, demonstration_site=None, max_days=2000):
    if _research_row(app, research_id).status == "complete":
        return
    _wait_until_research_startable(app, research_id, max_days=max_days)
    app.execute(StartResearch(str(research_id)))
    elapsed = 0
    while elapsed <= max_days:
        row = _research_row(app, research_id)
        if row.status == "complete":
            return
        if row.status == "prototype":
            if row.prototype_location_id is None:
                site = next((candidate for candidate in row.prototype_sites if not candidate.blockers), None)
                if site is None:
                    app.execute(AdvanceTime(1))
                    elapsed += 1
                    continue
                _ensure_lane(app, EARTH, site.location_id)
                app.execute(SetResearchPrototypeSite(str(research_id), site.location_id))
                row = _research_row(app, research_id)
            if not row.prototype_blockers:
                app.execute(FundResearchPrototype(str(research_id)))
                continue
            step = min(3, max_days - elapsed)
        elif row.status == "demonstration":
            if row.demonstration_location_id is None:
                if demonstration_site is None:
                    raise AssertionError(f"research requires a demonstration site: {research_id}")
                app.execute(SetResearchDemonstrationSite(str(research_id), str(demonstration_site)))
                row = _research_row(app, research_id)
            if row.demonstration_blockers:
                step = 1
            else:
                step = max(1, row.demonstration_required_days - row.demonstration_done_days)
                step = min(step, max_days - elapsed)
        else:
            raise AssertionError(f"unexpected research state: {research_id}: {row.status}")
        if step <= 0:
            break
        app.execute(AdvanceTime(step))
        elapsed += step
    raise AssertionError(f"research did not complete: {research_id}")


def _project_row(app, project_id):
    return next(row for row in app.query(GetProjects()).items if row.id == project_id)


def _advance_until_complete(app, project_ids, max_days=2000):
    elapsed = 0
    while elapsed <= max_days:
        rows = [_project_row(app, pid) for pid in project_ids]
        if all(row.status == "complete" for row in rows):
            return
        step = min(5, max_days - elapsed)
        if step <= 0:
            break
        app.execute(AdvanceTime(step))
        elapsed += step
    raise AssertionError("projects did not complete")


def _build_facility_if_absent(app, location_id, facility_definition_id):
    if any(
        row.definition_id == str(facility_definition_id)
        for row in app.query(GetLocation(str(location_id))).facilities
    ):
        return
    _ensure_lane(app, EARTH, location_id)
    project_id = app.execute(PlanBuild(
        str(location_id), str(facility_definition_id), priority=100,
        sourcing_policy="import_now",
        import_source_id=None if location_id == EARTH else str(EARTH),
    )).created_id
    assert project_id is not None
    _advance_until_complete(app, [project_id])


def _establish_orbital_research_capacity(app):
    _complete_research(app, TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS)
    _build_facility_if_absent(app, LEO, MICROGRAVITY_EXPERIMENT_PLATFORM)
    _complete_research(app, TECH_CISLUNAR_LOGISTICS)
    _complete_research(app, TECH_CREWED_ORBITAL_RESEARCH, LEO)
    _build_facility_if_absent(app, LEO, CREWED_ORBITAL_LABORATORY)


def _inventory_row(app, location_id, resource_id):
    location = app.query(GetLocation(str(location_id)))
    return next(row for row in location.inventory if row.resource_id == str(resource_id))


def _app_from_checkpoint(state):
    app = build_game_application()
    restore_state(app._simulation, state)
    return app


@pytest.fixture(scope="module")
def orbital_research_checkpoint():
    app = build_game_application()
    assert not app.query(GetLocation(str(POLAR_COLD_TRAP))).facilities
    _complete_research(app, TECH_ORBITAL_OPERATIONS)
    _establish_orbital_research_capacity(app)
    return capture_state(app._simulation)


@pytest.fixture(scope="module")
def cislunar_checkpoint(orbital_research_checkpoint):
    app = _app_from_checkpoint(orbital_research_checkpoint)
    _build_facility_if_absent(app, LEO, ORBITAL_LOGISTICS_NODE)
    route = app.query(GetRoutes(route_id="base.route.leo_lunar_orbit", include_modes=False)).items[0]
    assert route.available
    return capture_state(app._simulation)


@pytest.fixture(scope="module")
def survey_ready_checkpoint(cislunar_checkpoint):
    app = _app_from_checkpoint(cislunar_checkpoint)
    _complete_research(app, TECH_LUNAR_PROSPECTING, LEO)
    _ensure_lane(app, EARTH, POLAR_COLD_TRAP)
    survey_pkg = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(ROBOTIC_SURVEY_PACKAGE), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert survey_pkg is not None
    _advance_until_complete(app, [survey_pkg])
    return capture_state(app._simulation)


@pytest.fixture(scope="module")
def isru_checkpoint(survey_ready_checkpoint):
    app = _app_from_checkpoint(survey_ready_checkpoint)
    app.execute(StartSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    for _ in range(400):
        row = next(
            x for x in app.query(GetSurveys(str(POLAR_COLD_TRAP))).items
            if x.resource_id == str(WATER)
        )
        if row.knowledge_level >= 3:
            break
        app.execute(AdvanceTime(5))
    else:
        raise AssertionError("survey did not reach extraction-grade knowledge")

    _complete_research(app, TECH_ROBOTIC_FIELD_GEOLOGY, POLAR_COLD_TRAP)
    _build_facility_if_absent(app, POLAR_COLD_TRAP, ROBOTIC_GEOLOGY_STATION)
    _complete_research(app, TECH_VOLATILE_ISRU, POLAR_COLD_TRAP)
    power = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(INDUSTRIAL_POWER_BLOCK), priority=105,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    extractor = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(VOLATILE_EXTRACTOR), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    tank = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(WATER_STORAGE), priority=95,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert power and extractor and tank
    _advance_until_complete(app, [power, extractor, tank])
    return capture_state(app._simulation)


def test_research_survey_and_isru_form_a_playable_dependency_chain_through_application_api(isru_checkpoint):
    app = _app_from_checkpoint(isru_checkpoint)
    before = _inventory_row(app, POLAR_COLD_TRAP, WATER).amount
    app.execute(AdvanceTime(10))
    after = _inventory_row(app, POLAR_COLD_TRAP, WATER).amount
    assert after > before


def test_storage_capacity_stops_output_without_creating_or_destroying_capacity(isru_checkpoint):
    app = _app_from_checkpoint(isru_checkpoint)
    location = app.query(GetLocation(str(POLAR_COLD_TRAP)))
    water = next(row for row in location.inventory if row.resource_id == str(WATER))
    output = sum(row.output_t_per_day for row in location.extraction if row.output_resource_id == str(WATER))
    assert water.free_capacity is not None and output > 0
    days_to_fill = max(1, ceil(water.free_capacity / output) + 1)
    app.execute(AdvanceTime(days_to_fill))
    full = _inventory_row(app, POLAR_COLD_TRAP, WATER)
    assert full.physical_capacity is not None and full.amount <= full.physical_capacity + 1e-9
    assert full.service_capacity is not None and full.service_capacity <= full.physical_capacity + 1e-9
    assert full.free_capacity is not None and full.free_capacity <= 1e-9
    app.execute(AdvanceTime(20))
    later = _inventory_row(app, POLAR_COLD_TRAP, WATER)
    assert later.amount == full.amount


def test_construction_capacity_is_allocatable_between_parallel_projects(isru_checkpoint):
    app = _app_from_checkpoint(isru_checkpoint)
    p1 = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(CRYOGENIC_STORAGE), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    p2 = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(WATER_STORAGE), priority=90,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert p1 and p2
    app.execute(SetConstructionWeight(p1, 3.0))
    app.execute(SetConstructionWeight(p2, 1.0))
    for _ in range(150):
        app.execute(AdvanceTime(2))
        a, b = _project_row(app, p1), _project_row(app, p2)
        if a.status == "building" and b.status == "building":
            assert a.construction_done > 0 and b.construction_done > 0
            assert a.construction_done > b.construction_done
            return
    raise AssertionError("projects never shared construction flow")


def test_launch_vehicle_and_spacecraft_have_distinct_state_transitions(cislunar_checkpoint):
    app = build_game_application()
    sim = app._simulation

    launch_route = "base.route.earth_leo"
    launch_vehicle = next(v for v in app.query(GetVehicles()).items if v.concept == "launch_vehicle")
    order = app.execute(SubmitCargo(
        str(EARTH), str(LEO), str(WATER), 1.0, 100, (launch_route,),
        ((launch_route, launch_vehicle.definition_id),),
    )).created_id
    assert order
    app.execute(AdvanceTime(1))
    launch_vehicle = next(v for v in app.query(GetVehicles()).items if v.id == launch_vehicle.id)
    assert launch_vehicle.location_id == str(EARTH) and launch_vehicle.status == "transit_return"
    app.execute(AdvanceTime(1))
    launch_vehicle = next(v for v in app.query(GetVehicles()).items if v.id == launch_vehicle.id)
    assert launch_vehicle.location_id == str(EARTH) and launch_vehicle.status == "turnaround"

    app.execute(AdvanceTime(max(0, launch_vehicle.available_day - app._simulation.day)))
    ground_tug_id = sim.logistics.add_vehicle(REUSABLE_ORBITAL_CARGO_TUG, EARTH)
    launch_vehicle = next(v for v in app.query(GetVehicles()).items if v.id == launch_vehicle.id)
    app.execute(DispatchVehicle(str(ground_tug_id), launch_route, launch_vehicle.id))
    carried = next(v for v in app.query(GetVehicles()).items if v.id == str(ground_tug_id))
    carrier = next(v for v in app.query(GetVehicles()).items if v.id == launch_vehicle.id)
    assert carried.status == "transit" and carried.location_id is None
    assert carrier.location_id == str(EARTH) and carrier.status == "transit_return"
    app.execute(AdvanceTime(2))
    carried = next(v for v in app.query(GetVehicles()).items if v.id == str(ground_tug_id))
    assert carried.location_id == str(LEO) and carried.status == "available"

    lunar_app = _app_from_checkpoint(cislunar_checkpoint)
    lunar_sim = lunar_app._simulation
    lunar_sim.inventory.add(LEO, PROPELLANT, 20.0)
    lander = next(
        v for v in lunar_app.query(GetVehicles()).items
        if v.definition_id == str(REUSABLE_SURFACE_CARGO_LANDER)
    )
    lunar_app.execute(RefuelVehicle(lander.id))
    fueled = next(v for v in lunar_app.query(GetVehicles()).items if v.id == lander.id)
    assert fueled.propellant_t == fueled.propellant_capacity_t > 0
    lunar_app.execute(DispatchVehicle(lander.id, "base.route.leo_lunar_orbit"))
    lunar_app.execute(AdvanceTime(1))
    moving = next(v for v in lunar_app.query(GetVehicles()).items if v.id == lander.id)
    assert moving.location_id is None and moving.status == "transit"
    assert moving.transit_destination_id == str(LUNAR_ORBIT)
    assert 0 <= moving.propellant_t < moving.propellant_capacity_t
    lunar_app.execute(AdvanceTime(5))
    arrived = next(v for v in lunar_app.query(GetVehicles()).items if v.id == lander.id)
    assert arrived.location_id == str(LUNAR_ORBIT)


def test_lunar_propellant_changes_usable_export_logistics(isru_checkpoint):
    app = _app_from_checkpoint(isru_checkpoint)
    _complete_research(app, TECH_INDUSTRIAL_ELECTROLYSIS, POLAR_COLD_TRAP)

    grid = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(SURFACE_POWER_GRID), priority=110,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    cryogenic = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(CRYOGENIC_STORAGE), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    electrolysis = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(ELECTROLYSIS_PLANT), priority=95,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert grid and cryogenic and electrolysis
    _advance_until_complete(app, [grid, cryogenic, electrolysis])

    _complete_research(app, TECH_PROPELLANT_HANDLING, POLAR_COLD_TRAP)
    propellant_plant = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(PROPELLANT_PLANT), priority=90,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert propellant_plant
    _advance_until_complete(app, [propellant_plant])
    app.execute(AdvanceTime(20))
    produced = _inventory_row(app, POLAR_COLD_TRAP, PROPELLANT).amount
    assert produced > 0

    sim = app._simulation
    sim.inventory.add(LEO, PROPELLANT, 20.0)
    lander = next(
        v for v in app.query(GetVehicles()).items
        if v.definition_id == str(REUSABLE_SURFACE_CARGO_LANDER)
    )
    app.execute(DispatchVehicle(lander.id, "base.route.leo_cold_trap"))
    app.execute(AdvanceTime(8))
    lander = next(v for v in app.query(GetVehicles()).items if v.id == lander.id)
    assert lander.location_id == str(POLAR_COLD_TRAP) and lander.status == "available"

    return_route = "base.route.cold_trap_lunar_orbit"
    order = app.execute(SubmitCargo(
        str(POLAR_COLD_TRAP), str(LUNAR_ORBIT), str(PROPELLANT), produced * 0.5, 100,
        (return_route,), ((return_route, str(REUSABLE_SURFACE_CARGO_LANDER)),),
    )).created_id
    assert order
    for _ in range(1000):
        order_row = next(o for o in app.query(GetCargoOrders()).items if o.id == order)
        if order_row.delivered_t + 1e-9 >= order_row.amount_t:
            break
        app.execute(AdvanceTime(3))
    else:
        raise AssertionError("propellant export did not complete")
    assert _inventory_row(app, LUNAR_ORBIT, PROPELLANT).amount > 0


def test_query_exposes_physical_bottleneck_without_prescribing_a_solution(isru_checkpoint):
    app = _app_from_checkpoint(isru_checkpoint)
    _complete_research(app, TECH_INDUSTRIAL_ELECTROLYSIS, POLAR_COLD_TRAP)
    electrolysis = app.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(ELECTROLYSIS_PLANT), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert electrolysis
    _advance_until_complete(app, [electrolysis])
    app.execute(AdvanceTime(100))
    row = next(
        x for x in app.query(GetLocation(str(POLAR_COLD_TRAP))).industry
        if x.facility_definition_id == str(ELECTROLYSIS_PLANT)
    )
    assert 0.0 <= row.scale <= 1.0
    assert row.limiting_factors


def test_manual_pause_resume_controls_preserve_configuration_and_halt_autonomous_progress(
    orbital_research_checkpoint, survey_ready_checkpoint
):
    from space_idle import (
        PauseBuild,
        PauseFacility,
        PauseLogisticsLane,
        PauseResearch,
        PauseSurvey,
        ResumeBuild,
        ResumeFacility,
        ResumeLogisticsLane,
        ResumeResearch,
        ResumeSurvey,
    )
    from space_idle.content.base_game import EARTH_RESEARCH_LAB

    app = build_game_application()
    app.execute(AdvanceTime(2))
    research_before_pause = app.query(GetResearch())
    lab = next(
        row for row in app.query(GetLocation(str(EARTH))).facilities
        if row.definition_id == str(EARTH_RESEARCH_LAB)
    )
    lab_provider = next(row for row in research_before_pause.providers if row.facility_id == lab.id)
    app.execute(PauseFacility(lab.id))
    stopped_lab = next(row for row in app.query(GetLocation(str(EARTH))).facilities if row.id == lab.id)
    stopped_research = app.query(GetResearch())
    assert stopped_lab.paused and ("manual_pause", "設備が手動停止中") in stopped_lab.activation_blockers
    assert stopped_research.stored_points == research_before_pause.stored_points
    assert stopped_research.generation_points_per_day < research_before_pause.generation_points_per_day
    assert stopped_research.storage_capacity_points < research_before_pause.storage_capacity_points
    assert stopped_research.generation_points_per_day <= (
        research_before_pause.generation_points_per_day - lab_provider.generation_points_per_day + 1e-9
    )
    app.execute(AdvanceTime(3))
    progressed_without_lab = app.query(GetResearch())
    assert progressed_without_lab.stored_points >= stopped_research.stored_points
    if stopped_research.generation_points_per_day > 1e-9:
        assert progressed_without_lab.stored_points > stopped_research.stored_points
    app.execute(ResumeFacility(lab.id))
    resumed_research = app.query(GetResearch())
    assert resumed_research.generation_points_per_day > stopped_research.generation_points_per_day
    app.execute(AdvanceTime(1))
    assert app.query(GetResearch()).stored_points > progressed_without_lab.stored_points

    _wait_until_research_startable(app, TECH_ORBITAL_OPERATIONS)
    points_before_start = app.query(GetResearch()).stored_points
    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS)))
    started = _research_row(app, TECH_ORBITAL_OPERATIONS)
    points_after_start = app.query(GetResearch()).stored_points
    assert started.status == "prototype"
    assert points_after_start < points_before_start
    app.execute(PauseResearch(str(TECH_ORBITAL_OPERATIONS)))
    app.execute(AdvanceTime(3))
    paused = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert paused.paused and paused.status == "prototype"
    app.execute(ResumeResearch(str(TECH_ORBITAL_OPERATIONS)))
    resumed = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert not resumed.paused and resumed.status == "prototype"
    app.execute(SetResearchPrototypeSite(str(TECH_ORBITAL_OPERATIONS), str(EARTH)))
    app.execute(FundResearchPrototype(str(TECH_ORBITAL_OPERATIONS)))
    assert _research_row(app, TECH_ORBITAL_OPERATIONS).status == "complete"

    project_app = _app_from_checkpoint(orbital_research_checkpoint)
    project_id = project_app.execute(PlanBuild(
        str(LEO), str(ORBITAL_LOGISTICS_NODE),
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert project_id is not None
    project_app.execute(PauseBuild(project_id))
    project_before = _project_row(project_app, project_id)
    project_app.execute(AdvanceTime(3))
    project_paused = _project_row(project_app, project_id)
    assert project_paused.paused
    assert project_paused.status == project_before.status
    assert project_paused.construction_done == project_before.construction_done
    assert any(code == "manual_pause" for code, _ in project_paused.blockers)
    project_app.execute(ResumeBuild(project_id))
    project_app.execute(AdvanceTime(1))
    assert not _project_row(project_app, project_id).paused

    lane_app = build_game_application()
    lane_app._simulation.technology.completed.update({TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS})
    lane_id = lane_app.execute(CreateLogisticsLane(
        str(EARTH), str(LEO), requested_capacity_t_per_day=5.0
    )).created_id
    demand_project = lane_app.execute(PlanBuild(
        str(LEO), str(ORBITAL_LOGISTICS_NODE), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert lane_id is not None and demand_project is not None
    lane_app.execute(PauseLogisticsLane(lane_id))
    orders_before = len(lane_app.query(GetCargoOrders()).items)
    lane_app.execute(AdvanceTime(2))
    lane = next(row for row in lane_app.query(GetLogisticsLanes()).items if row.id == lane_id)
    assert lane.paused and len(lane_app.query(GetCargoOrders()).items) == orders_before
    lane_app.execute(ResumeLogisticsLane(lane_id))
    lane_app.execute(AdvanceTime(1))
    lane = next(row for row in lane_app.query(GetLogisticsLanes()).items if row.id == lane_id)
    assert not lane.paused
    assert len(lane_app.query(GetCargoOrders()).items) > orders_before

    survey_app = _app_from_checkpoint(survey_ready_checkpoint)
    survey_app.execute(StartSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    survey_app.execute(PauseSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    survey_before = next(
        x for x in survey_app.query(GetSurveys(str(POLAR_COLD_TRAP))).items
        if x.resource_id == str(WATER)
    )
    survey_app.execute(AdvanceTime(3))
    survey_paused = next(
        x for x in survey_app.query(GetSurveys(str(POLAR_COLD_TRAP))).items
        if x.resource_id == str(WATER)
    )
    assert survey_paused.paused and survey_paused.progress == survey_before.progress
    survey_app.execute(ResumeSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    survey_app.execute(AdvanceTime(1))
    survey_resumed = next(
        x for x in survey_app.query(GetSurveys(str(POLAR_COLD_TRAP))).items
        if x.resource_id == str(WATER)
    )
    assert not survey_resumed.paused and survey_resumed.progress > survey_paused.progress


def test_vehicle_eligibility_is_derived_from_physical_ascent_capability_not_concept_name():
    from space_idle.logistics import (
        PoweredAscentCapability, TransportPerformanceProfile, VehicleDef, VehicleDisposition
    )
    from space_idle.shared import DefinitionId, RouteId
    from space_idle.spatial import AtmosphereField, GravityField

    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.earth_leo")
    route = sim.logistics.routes[route_id]

    route_view = app.query(GetRoutes(route_id=str(route_id), include_modes=True)).items[0]
    lander_mode = next(mode for mode in route_view.modes if mode.id == str(REUSABLE_SURFACE_CARGO_LANDER))
    assert not lander_mode.usable_now
    assert any("operation:powered_ascent" in blocker for blocker in lander_mode.blockers)

    gravity = sim.environment.require(route.origin_id, GravityField).local_acceleration_m_s2
    pressure = sim.environment.require(route.origin_id, AtmosphereField).pressure_pa
    definition_id = DefinitionId("test.vehicle.integrated_spacecraft")
    sim.logistics.vehicle_defs[definition_id] = VehicleDef(
        id=definition_id, display_name="統合型試験宇宙船",
        performance=TransportPerformanceProfile(
            dry_mass_t=10.0, payload_t=2.0,
            operation_capabilities=(
                PoweredAscentCapability(route.delta_v_km_s + 1.0, gravity + 1.0, pressure + 1000.0),
            ),
            default_disposition=VehicleDisposition.DESTINATION,
        ),
    )
    vehicle_id = sim.logistics.add_vehicle(definition_id, EARTH)
    assert not sim.logistics.vehicle_route_failures(route_id, definition_id, sim.day)

    order_id = app.execute(SubmitCargo(
        str(EARTH), str(LEO), str(WATER), 1.0, 100, (str(route_id),),
        ((str(route_id), str(definition_id)),)
    )).created_id
    assert order_id
    app.execute(AdvanceTime(2))
    vehicle = next(v for v in app.query(GetVehicles()).items if v.id == str(vehicle_id))
    assert vehicle.location_id == str(LEO)


def test_end_to_end_lunar_shipment_does_not_require_leo_or_research_gate():
    app = build_game_application()

    assert not app._simulation.technology.completed
    assert all(
        row.definition_id != str(ORBITAL_LOGISTICS_NODE)
        for row in app.query(GetLocation(str(LEO))).facilities
    )

    order_id = app.execute(SubmitCargo(
        str(EARTH), str(SOUTH_POLAR_RIDGE), str(WATER), 1.0, 100
    )).created_id
    assert order_id is not None

    order = next(row for row in app.query(GetCargoOrders()).items if row.id == order_id)
    routes = {row.id: row for row in app.query(GetRoutes(include_modes=False)).items}
    assert order.path
    assert routes[order.path[0]].origin_id == str(EARTH)
    assert routes[order.path[-1]].destination_id == str(SOUTH_POLAR_RIDGE)
    assert all(
        routes[route_id].origin_id != str(LEO)
        and routes[route_id].destination_id != str(LEO)
        for route_id in order.path
    )
