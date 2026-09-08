from __future__ import annotations

from space_idle import (
    build_game_application,
    AdvanceTime,
    DispatchVehicle,
    RefuelVehicle,
    FundResearchPrototype,
    GetLocation,
    GetLogistics,
    GetProjects,
    GetResearch,
    GetSurveys,
    PlanBuild,
    SetConstructionWeight,
    SetResearchDemonstrationSite,
    StartResearch,
    StartSurvey,
    SubmitCargo,
)
from space_idle.content.base_game import (
    REUSABLE_ORBITAL_CARGO_TUG,
    CRYOGENIC_STORAGE,
    CREWED_ORBITAL_LABORATORY,
    EARTH,
    ELECTROLYSIS_PLANT,
    INDUSTRIAL_POWER_BLOCK,
    LEO,
    MICROGRAVITY_EXPERIMENT_PLATFORM,
    REUSABLE_SURFACE_CARGO_LANDER,
    ROBOTIC_GEOLOGY_STATION,
    LUNAR_ORBIT,
    ORBITAL_LOGISTICS_NODE,
    POLAR_COLD_TRAP,
    PROPELLANT,
    PROPELLANT_PLANT,
    ROBOTIC_SURVEY_PACKAGE,
    SURFACE_POWER_GRID,
    SOUTH_POLAR_RIDGE,
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


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _wait_until_research_startable(app, research_id, max_days=2000):
    for _ in range(max_days + 1):
        row = _research_row(app, research_id)
        if row.can_start:
            return row
        app.execute(AdvanceTime(1))
    raise AssertionError(f"research never became startable: {research_id}")


def _complete_research(app, research_id, demonstration_site=None, max_days=2000):
    if _research_row(app, research_id).status == "complete":
        return
    _wait_until_research_startable(app, research_id, max_days=max_days)
    app.execute(StartResearch(str(research_id)))
    for _ in range(max_days):
        row = _research_row(app, research_id)
        if row.status == "complete":
            return
        if row.status == "prototype":
            app.execute(FundResearchPrototype(str(research_id), str(EARTH)))
        elif row.status == "demonstration" and row.demonstration_location_id is None:
            if demonstration_site is None:
                raise AssertionError(f"research requires a demonstration site: {research_id}")
            app.execute(SetResearchDemonstrationSite(str(research_id), str(demonstration_site)))
        app.execute(AdvanceTime(1))
    raise AssertionError(f"research did not complete: {research_id}")


def _project_row(app, project_id):
    return next(row for row in app.query(GetProjects()).items if row.id == project_id)


def _advance_until_complete(app, project_ids, max_days=2000):
    for _ in range(max_days):
        if all(_project_row(app, pid).status == "complete" for pid in project_ids):
            return
        app.execute(AdvanceTime(1))
    raise AssertionError("projects did not complete")


def _build_facility_if_absent(app, location_id, facility_definition_id):
    if any(
        row.definition_id == str(facility_definition_id)
        for row in app.query(GetLocation(str(location_id))).facilities
    ):
        return
    project_id = app.execute(PlanBuild(
        str(location_id), str(facility_definition_id), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH),
    )).created_id
    assert project_id is not None
    _advance_until_complete(app, [project_id])


def _establish_orbital_research_capacity(app):
    # Research capacity is itself part of progression: the initial laboratory
    # and observation satellite can fund the first orbital experiment system,
    # whose platform then provides enough RP capacity for larger orbital work.
    _complete_research(app, TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS)
    _build_facility_if_absent(app, LEO, MICROGRAVITY_EXPERIMENT_PLATFORM)
    _complete_research(app, TECH_CISLUNAR_LOGISTICS)
    _complete_research(app, TECH_CREWED_ORBITAL_RESEARCH, LEO)
    _build_facility_if_absent(app, LEO, CREWED_ORBITAL_LABORATORY)


def _establish_cislunar_access(app):
    _complete_research(app, TECH_ORBITAL_OPERATIONS)
    _establish_orbital_research_capacity(app)
    _build_facility_if_absent(app, LEO, ORBITAL_LOGISTICS_NODE)
    route = next(r for r in app.query(GetLogistics()).routes if r.id == "base.route.leo_lunar_orbit")
    assert route.available


def _establish_survey_and_isru(app):
    _establish_cislunar_access(app)
    _complete_research(app, TECH_LUNAR_PROSPECTING, LEO)
    survey_pkg = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(ROBOTIC_SURVEY_PACKAGE), priority=100, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    assert survey_pkg is not None
    _advance_until_complete(app, [survey_pkg])
    app.execute(StartSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    for _ in range(2000):
        row = next(x for x in app.query(GetSurveys(str(POLAR_COLD_TRAP))).items if x.resource_id == str(WATER))
        if row.knowledge_level >= 3:
            break
        app.execute(AdvanceTime(1))
    else:
        raise AssertionError("survey did not reach extraction-grade knowledge")

    # Field geology is both a better survey instrument and a research asset.
    # Building it expands the RP ceiling for later industrial research instead
    # of granting that capacity as an abstract progression bonus.
    _complete_research(app, TECH_ROBOTIC_FIELD_GEOLOGY, POLAR_COLD_TRAP)
    _build_facility_if_absent(app, POLAR_COLD_TRAP, ROBOTIC_GEOLOGY_STATION)
    _complete_research(app, TECH_VOLATILE_ISRU, POLAR_COLD_TRAP)
    power = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(INDUSTRIAL_POWER_BLOCK), priority=105, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    extractor = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(VOLATILE_EXTRACTOR), priority=100, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    tank = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(WATER_STORAGE), priority=95, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    assert power and extractor and tank
    _advance_until_complete(app, [power, extractor, tank])


def _inventory_row(app, location_id, resource_id):
    location = app.query(GetLocation(str(location_id)))
    return next(row for row in location.inventory if row.resource_id == str(resource_id))


def test_research_survey_and_isru_form_a_playable_dependency_chain_through_application_api():
    app = build_game_application()
    assert not app.query(GetLocation(str(POLAR_COLD_TRAP))).facilities

    _establish_survey_and_isru(app)
    before = _inventory_row(app, POLAR_COLD_TRAP, WATER).amount
    app.execute(AdvanceTime(10))
    after = _inventory_row(app, POLAR_COLD_TRAP, WATER).amount
    assert after > before


def test_storage_capacity_stops_output_without_creating_or_destroying_capacity():
    app = build_game_application()
    _establish_survey_and_isru(app)
    for _ in range(5000):
        row = _inventory_row(app, POLAR_COLD_TRAP, WATER)
        if row.free_capacity is not None and row.free_capacity <= 1e-9:
            break
        app.execute(AdvanceTime(1))
    full = _inventory_row(app, POLAR_COLD_TRAP, WATER)
    assert full.physical_capacity is not None and full.amount <= full.physical_capacity + 1e-9
    assert full.service_capacity is not None and full.service_capacity <= full.physical_capacity + 1e-9
    app.execute(AdvanceTime(20))
    later = _inventory_row(app, POLAR_COLD_TRAP, WATER)
    assert later.amount == full.amount


def test_construction_capacity_is_allocatable_between_parallel_projects():
    app = build_game_application()
    _establish_survey_and_isru(app)
    p1 = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(CRYOGENIC_STORAGE), priority=100, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    p2 = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(WATER_STORAGE), priority=90, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    assert p1 and p2
    app.execute(SetConstructionWeight(p1, 3.0))
    app.execute(SetConstructionWeight(p2, 1.0))
    for _ in range(300):
        app.execute(AdvanceTime(1))
        a, b = _project_row(app, p1), _project_row(app, p2)
        if a.status == "building" and b.status == "building":
            assert a.construction_done > 0 and b.construction_done > 0
            assert a.construction_done > b.construction_done
            return
    raise AssertionError("projects never shared construction flow")


def test_launch_vehicle_and_spacecraft_have_distinct_state_transitions():
    app = build_game_application()
    sim = app._simulation

    # A launch vehicle provides the launch operation but remains on the surface
    # and enters turnaround instead of becoming an orbital spacecraft.
    launch_route = "base.route.earth_leo"
    launch_vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.concept == "launch_vehicle")
    order = app.execute(SubmitCargo(
        str(EARTH), str(LEO), str(WATER), 1.0, 100, (launch_route,),
        ((launch_route, launch_vehicle.definition_id),),
    )).created_id
    assert order
    app.execute(AdvanceTime(1))
    launch_vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.id == launch_vehicle.id)
    assert launch_vehicle.location_id == str(EARTH) and launch_vehicle.status == "transit_return"
    app.execute(AdvanceTime(1))
    launch_vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.id == launch_vehicle.id)
    assert launch_vehicle.location_id == str(EARTH) and launch_vehicle.status == "turnaround"

    # An orbital-only spacecraft can be transported to orbit as payload of the
    # launch vehicle; it does not need a symbolic "launch-capable" category.
    app.execute(AdvanceTime(max(0, launch_vehicle.available_day - app._simulation.day)))
    ground_tug_id = sim.logistics.add_vehicle(REUSABLE_ORBITAL_CARGO_TUG, EARTH)
    launch_vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.id == launch_vehicle.id)
    app.execute(DispatchVehicle(str(ground_tug_id), launch_route, launch_vehicle.id))
    carried = next(v for v in app.query(GetLogistics()).vehicles if v.id == str(ground_tug_id))
    carrier = next(v for v in app.query(GetLogistics()).vehicles if v.id == launch_vehicle.id)
    assert carried.status == "transit" and carried.location_id is None
    assert carrier.location_id == str(EARTH) and carrier.status == "transit_return"
    app.execute(AdvanceTime(2))
    carried = next(v for v in app.query(GetLogistics()).vehicles if v.id == str(ground_tug_id))
    assert carried.location_id == str(LEO) and carried.status == "available"

    _establish_cislunar_access(app)
    sim.inventory.add(LEO, PROPELLANT, 20.0)
    lander = next(v for v in app.query(GetLogistics()).vehicles if v.definition_id == str(REUSABLE_SURFACE_CARGO_LANDER))
    app.execute(RefuelVehicle(lander.id))
    fueled = next(v for v in app.query(GetLogistics()).vehicles if v.id == lander.id)
    assert fueled.propellant_t == fueled.propellant_capacity_t > 0
    app.execute(DispatchVehicle(lander.id, "base.route.leo_lunar_orbit"))
    app.execute(AdvanceTime(1))
    moving = next(v for v in app.query(GetLogistics()).vehicles if v.id == lander.id)
    assert moving.location_id is None and moving.status == "transit" and moving.transit_destination_id == str(LUNAR_ORBIT)
    assert 0 <= moving.propellant_t < moving.propellant_capacity_t
    app.execute(AdvanceTime(5))
    arrived = next(v for v in app.query(GetLogistics()).vehicles if v.id == lander.id)
    assert arrived.location_id == str(LUNAR_ORBIT)


def test_lunar_propellant_changes_usable_export_logistics():
    app = build_game_application()
    _establish_survey_and_isru(app)
    _complete_research(app, TECH_INDUSTRIAL_ELECTROLYSIS, POLAR_COLD_TRAP)

    grid = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(SURFACE_POWER_GRID), priority=110, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    cryogenic = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(CRYOGENIC_STORAGE), priority=100, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    electrolysis = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(ELECTROLYSIS_PLANT), priority=95, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    assert grid and cryogenic and electrolysis
    _advance_until_complete(app, [grid, cryogenic, electrolysis])

    _complete_research(app, TECH_PROPELLANT_HANDLING, POLAR_COLD_TRAP)
    propellant_plant = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(PROPELLANT_PLANT), priority=90, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    assert propellant_plant
    _advance_until_complete(app, [propellant_plant])
    app.execute(AdvanceTime(20))
    produced = _inventory_row(app, POLAR_COLD_TRAP, PROPELLANT).amount
    assert produced > 0

    # The lander is a persistent spacecraft. Move it from LEO to the production
    # site first; it is not assigned to a route as an abstract capacity pool.
    sim = app._simulation
    sim.inventory.add(LEO, PROPELLANT, 20.0)
    lander = next(v for v in app.query(GetLogistics()).vehicles if v.definition_id == str(REUSABLE_SURFACE_CARGO_LANDER))
    app.execute(DispatchVehicle(lander.id, "base.route.leo_cold_trap"))
    app.execute(AdvanceTime(8))
    lander = next(v for v in app.query(GetLogistics()).vehicles if v.id == lander.id)
    assert lander.location_id == str(POLAR_COLD_TRAP) and lander.status == "available"

    return_route = "base.route.cold_trap_lunar_orbit"
    order = app.execute(SubmitCargo(
        str(POLAR_COLD_TRAP), str(LUNAR_ORBIT), str(PROPELLANT), produced * 0.5, 100, (return_route,),
        ((return_route, str(REUSABLE_SURFACE_CARGO_LANDER)),),
    )).created_id
    assert order
    for _ in range(10000):
        order_row = next(o for o in app.query(GetLogistics()).orders if o.id == order)
        if order_row.delivered_t + 1e-9 >= order_row.amount_t:
            break
        app.execute(AdvanceTime(1))
    else:
        raise AssertionError("propellant export did not complete")
    assert _inventory_row(app, LUNAR_ORBIT, PROPELLANT).amount > 0


def test_query_exposes_physical_bottleneck_without_prescribing_a_solution():
    app = build_game_application()
    _establish_survey_and_isru(app)
    _complete_research(app, TECH_INDUSTRIAL_ELECTROLYSIS, POLAR_COLD_TRAP)
    electrolysis = app.execute(PlanBuild(str(POLAR_COLD_TRAP), str(ELECTROLYSIS_PLANT), priority=100, sourcing_policy="import_now", import_source_id=str(EARTH))).created_id
    assert electrolysis
    _advance_until_complete(app, [electrolysis])
    app.execute(AdvanceTime(100))
    row = next(x for x in app.query(GetLocation(str(POLAR_COLD_TRAP))).industry if x.facility_definition_id == str(ELECTROLYSIS_PLANT))
    assert 0.0 <= row.scale <= 1.0
    assert row.limiting_factors


def test_manual_pause_resume_controls_preserve_configuration_and_halt_autonomous_progress():
    from space_idle import (
        CreateLogisticsRule,
        PauseBuild,
        PauseFacility,
        PauseLogisticsRule,
        PauseResearch,
        PauseSurvey,
        ResumeBuild,
        ResumeFacility,
        ResumeLogisticsRule,
        ResumeResearch,
        ResumeSurvey,
    )
    from space_idle.content.base_game import EARTH_RESEARCH_LAB

    app = build_game_application()

    # Pausing one provider removes only that asset's contribution. Other research
    # assets continue operating, and stored RP is never deleted by the capacity drop.
    app.execute(AdvanceTime(2))
    research_before_pause = app.query(GetResearch())
    lab = next(
        row for row in app.query(GetLocation(str(EARTH))).facilities
        if row.definition_id == str(EARTH_RESEARCH_LAB)
    )
    lab_provider = next(row for row in research_before_pause.providers if row.facility_id == lab.id)
    app.execute(PauseFacility(lab.id))
    stopped_lab = next(
        row for row in app.query(GetLocation(str(EARTH))).facilities
        if row.id == lab.id
    )
    stopped_research = app.query(GetResearch())
    assert stopped_lab.paused and ("manual_pause", "設備が手動停止中") in stopped_lab.activation_blockers
    assert stopped_research.stored_points == research_before_pause.stored_points
    assert stopped_research.generation_points_per_day < research_before_pause.generation_points_per_day
    assert stopped_research.storage_capacity_points < research_before_pause.storage_capacity_points
    assert stopped_research.generation_points_per_day <= research_before_pause.generation_points_per_day - lab_provider.generation_points_per_day + 1e-9
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

    # Research pause applies to an already-funded physical phase. It does not
    # recreate Theory progress or refund the RP payment.
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
    app.execute(FundResearchPrototype(str(TECH_ORBITAL_OPERATIONS), str(EARTH)))
    assert _research_row(app, TECH_ORBITAL_OPERATIONS).status == "complete"
    _establish_orbital_research_capacity(app)

    # Construction pause stops procurement/construction state advancement and
    # resume continues the same project rather than recreating it.
    project_id = app.execute(PlanBuild(
        str(LEO), str(ORBITAL_LOGISTICS_NODE), sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert project_id is not None
    app.execute(PauseBuild(project_id))
    project_before = _project_row(app, project_id)
    app.execute(AdvanceTime(3))
    project_paused = _project_row(app, project_id)
    assert project_paused.paused
    assert project_paused.status == project_before.status
    assert project_paused.construction_done == project_before.construction_done
    assert any(code == "manual_pause" for code, _ in project_paused.blockers)
    app.execute(ResumeBuild(project_id))
    app.execute(AdvanceTime(1))
    assert not _project_row(app, project_id).paused

    # Recurring logistics automation can be stopped without deleting its rule.
    rule_id = app.execute(CreateLogisticsRule(
        str(EARTH), str(LEO), str(WATER), target_stock_t=1.0, batch_t=1.0
    )).created_id
    assert rule_id is not None
    app.execute(PauseLogisticsRule(rule_id))
    orders_before = len(app.query(GetLogistics()).orders)
    app.execute(AdvanceTime(2))
    rule = next(row for row in app.query(GetLogistics()).rules if row.id == rule_id)
    assert rule.paused and len(app.query(GetLogistics()).orders) == orders_before
    app.execute(ResumeLogisticsRule(rule_id))
    app.execute(AdvanceTime(1))
    rule = next(row for row in app.query(GetLogistics()).rules if row.id == rule_id)
    assert not rule.paused and len(app.query(GetLogistics()).orders) > orders_before

    # Survey allocation is preserved while paused and resumes from the same progress.
    app2 = build_game_application()
    _establish_cislunar_access(app2)
    _complete_research(app2, TECH_LUNAR_PROSPECTING, LEO)
    survey_pkg = app2.execute(PlanBuild(
        str(POLAR_COLD_TRAP), str(ROBOTIC_SURVEY_PACKAGE), priority=100,
        sourcing_policy="import_now", import_source_id=str(EARTH)
    )).created_id
    assert survey_pkg is not None
    _advance_until_complete(app2, [survey_pkg])
    app2.execute(StartSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    app2.execute(PauseSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    survey_before = next(x for x in app2.query(GetSurveys(str(POLAR_COLD_TRAP))).items if x.resource_id == str(WATER))
    app2.execute(AdvanceTime(3))
    survey_paused = next(x for x in app2.query(GetSurveys(str(POLAR_COLD_TRAP))).items if x.resource_id == str(WATER))
    assert survey_paused.paused and survey_paused.progress == survey_before.progress
    app2.execute(ResumeSurvey(str(POLAR_COLD_TRAP), str(WATER)))
    app2.execute(AdvanceTime(1))
    survey_resumed = next(x for x in app2.query(GetSurveys(str(POLAR_COLD_TRAP))).items if x.resource_id == str(WATER))
    assert not survey_resumed.paused and survey_resumed.progress > survey_paused.progress


def test_vehicle_eligibility_is_derived_from_physical_ascent_capability_not_concept_name():
    from space_idle.logistics import PoweredAscentCapability, TransportPerformanceProfile, VehicleDef, VehicleDisposition
    from space_idle.shared import DefinitionId, RouteId
    from space_idle.spatial import AtmosphereField, GravityField

    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.earth_leo")
    route = sim.logistics.routes[route_id]

    route_view = next(row for row in app.query(GetLogistics()).routes if row.id == str(route_id))
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
            operation_capabilities=(PoweredAscentCapability(route.delta_v_km_s + 1.0, gravity + 1.0, pressure + 1000.0),),
            default_disposition=VehicleDisposition.DESTINATION,
        ),
    )
    vehicle_id = sim.logistics.add_vehicle(definition_id, EARTH)
    assert not sim.logistics.vehicle_route_failures(route_id, definition_id, sim.day)

    order_id = app.execute(SubmitCargo(
        str(EARTH), str(LEO), str(WATER), 1.0, 100, (str(route_id),), ((str(route_id), str(definition_id)),)
    )).created_id
    assert order_id
    app.execute(AdvanceTime(2))
    vehicle = next(v for v in app.query(GetLogistics()).vehicles if v.id == str(vehicle_id))
    assert vehicle.location_id == str(LEO)


def test_end_to_end_lunar_shipment_does_not_require_leo_or_research_gate():
    app = build_game_application()

    # Research assets may already operate in LEO, but direct external transport
    # must not require a logistics node or a research unlock when its physical
    # service can satisfy the whole mission independently.
    assert not app._simulation.technology.completed
    assert all(
        row.definition_id != str(ORBITAL_LOGISTICS_NODE)
        for row in app.query(GetLocation(str(LEO))).facilities
    )

    order_id = app.execute(SubmitCargo(
        str(EARTH), str(SOUTH_POLAR_RIDGE), str(WATER), 1.0, 100
    )).created_id
    assert order_id is not None

    order = next(row for row in app.query(GetLogistics()).orders if row.id == order_id)
    routes = {row.id: row for row in app.query(GetLogistics()).routes}
    assert order.path
    assert routes[order.path[0]].origin_id == str(EARTH)
    assert routes[order.path[-1]].destination_id == str(SOUTH_POLAR_RIDGE)
    assert all(
        routes[route_id].origin_id != str(LEO) and routes[route_id].destination_id != str(LEO)
        for route_id in order.path
    )
