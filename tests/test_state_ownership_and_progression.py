from __future__ import annotations

import pytest

from space_idle import GetResearch, GetRoutes, GetSurveys, GetWorld, StartSurvey, build_game_application
from space_idle.api import GameRuntime
from space_idle.content import base_ids as ids
from space_idle.research import ResearchPhase
from space_idle.resource_demand import ResourceDemand
from space_idle.shared import EntityId, RouteId
from space_idle.simulation import OfflineProgressPolicy


def test_full_research_point_payment_transitions_directly_to_visible_prototype_and_can_complete():
    app = build_game_application()
    sim = app._simulation
    assert sim.research is not None

    for _ in range(2000):
        if sim.research.can_start(ids.TECH_ORBITAL_OPERATIONS, day=sim.day):
            break
        sim.advance_days(1)
    else:
        raise AssertionError("research never became startable")

    definition = sim.research.definitions[ids.TECH_ORBITAL_OPERATIONS]
    points_before = sim.research.stored_points
    sim.research.start(ids.TECH_ORBITAL_OPERATIONS, day=sim.day)

    state = sim.research.active[ids.TECH_ORBITAL_OPERATIONS]
    assert state.status is ResearchPhase.PROTOTYPE
    assert sim.research.stored_points == points_before - definition.research_point_cost
    assert ids.TECH_ORBITAL_OPERATIONS not in sim.research.completed

    view = app.query(GetResearch())
    row = next(item for item in view.items if item.id == str(ids.TECH_ORBITAL_OPERATIONS))
    assert row.status == "prototype"
    earth = next(site for site in row.prototype_sites if site.location_id == str(ids.EARTH))
    assert not earth.blockers

    sim.research.set_prototype_site(ids.TECH_ORBITAL_OPERATIONS, ids.EARTH, sim.day)
    sim.refresh_resource_claims()
    sim.research.fund_prototype(ids.TECH_ORBITAL_OPERATIONS, sim.day)
    assert ids.TECH_ORBITAL_OPERATIONS in sim.research.completed
    assert ids.TECH_ORBITAL_OPERATIONS not in sim.research.active

    completed_row = next(item for item in app.query(GetResearch()).items if item.id == str(ids.TECH_ORBITAL_OPERATIONS))
    assert completed_row.status == "complete"


def test_research_definitions_have_granular_engineering_outcomes():
    app = build_game_application()
    sim = app._simulation
    assert sim.research is not None
    assert len(sim.research.definitions) >= 13

    single_outcomes = {
        ids.REGOLITH_HARVESTER: ids.TECH_REGOLITH_EXCAVATION,
        ids.REGOLITH_SINTERING: ids.TECH_LUNAR_MATERIALS,
        ids.ORE_PROCESSING: ids.TECH_ORE_BENEFICIATION,
        ids.METALLURGY: ids.TECH_HIGH_TEMPERATURE_METALLURGY,
        ids.FABRICATION_WORKSHOP: ids.TECH_STRUCTURAL_FABRICATION,
        ids.MACHINE_SHOP: ids.TECH_PRECISION_MACHINING,
        ids.HEAVY_EQUIPMENT_ASSEMBLY: ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY,
        ids.ELECTROLYSIS_PLANT: ids.TECH_INDUSTRIAL_ELECTROLYSIS,
        ids.PROPELLANT_PLANT: ids.TECH_PROPELLANT_HANDLING,
    }
    for facility_id, technology_id in single_outcomes.items():
        assert sim.projects.recipes[facility_id].prerequisite_technologies == frozenset({technology_id})

    assert sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE].prerequisite_technologies == frozenset({
        ids.TECH_ORBITAL_OPERATIONS,
        ids.TECH_CISLUNAR_LOGISTICS,
    })


def test_direct_earth_to_south_pole_cargo_actually_dispatches_and_arrives():
    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.earth_ridge_direct")
    demand_id = EntityId("test.demand.direct_lunar")
    route = app.query(GetRoutes(route_id=str(route_id), include_modes=True)).items[0]
    external_mode = next(
        mode for mode in route.modes
        if mode.kind == "external_service" and mode.service_feasible
    )
    amount_t = external_mode.nominal_capacity.forward_t_per_day / 2.0
    assert amount_t > 0
    destination_before = sim.inventory.amount(
        ids.SOUTH_POLAR_RIDGE, ids.STRUCTURAL_COMPONENTS
    )
    if sim.inventory.available(ids.EARTH, ids.STRUCTURAL_COMPONENTS) < amount_t:
        sim.inventory.add(ids.EARTH, ids.STRUCTURAL_COMPONENTS, amount_t)

    lane_id = sim.logistics.create_lane(
        ids.EARTH,
        ids.SOUTH_POLAR_RIDGE,
        requested_capacity_t_per_day=1.0,
        priority=50,
        path=(route_id,),
    )
    demand = ResourceDemand(
        demand_id,
        "test",
        EntityId("test.owner"),
        ids.SOUTH_POLAR_RIDGE,
        ids.STRUCTURAL_COMPONENTS,
        amount_t,
        priority=50,
        source_id=ids.EARTH,
        local_claim_t=0.0,
    )

    sim.logistics.advance_capacity_logistics(sim.day, (demand,))
    flows = tuple(sim.logistics.cargo_flows.values())
    assert len(flows) == 1
    assert flows[0].lane_id == lane_id
    assert flows[0].demand_id == demand_id
    assert flows[0].amount_t == pytest.approx(amount_t)

    sim.advance_days(20)
    assert not sim.logistics.cargo_flows
    assert sim.inventory.amount(
        ids.SOUTH_POLAR_RIDGE, ids.STRUCTURAL_COMPONENTS
    ) == pytest.approx(destination_before + amount_t)


def test_runtime_snapshot_reads_all_projections_at_one_clock_sync(tmp_path):
    now = [0.0]
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=tmp_path,
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
        clock=lambda: now[0],
    )
    now[0] = 3.2
    result = runtime.snapshot({"world": GetWorld(), "research": GetResearch()})
    assert result.data["session"]["day"] == 3
    assert result.data["world"].day == 3
    assert result.revision == 1


def test_initial_known_deposits_are_knowledge_without_active_survey_campaigns():
    app = build_game_application()
    sim = app._simulation
    key = (ids.EARTH, ids.WATER)

    assert sim.survey.is_complete(*key)
    assert key in sim.survey.knowledge_progress
    assert key not in sim.survey.campaigns

    row = next(
        item for item in app.query(GetSurveys(str(ids.EARTH))).items
        if item.resource_id == str(ids.WATER)
    )
    assert row.complete is True
    assert row.active is False
    assert row.can_start is False
    assert row.can_pause is False
    assert row.can_resume is False
    assert row.can_set_allocation is False


def test_survey_campaign_updates_knowledge_and_is_removed_when_complete():
    app = build_game_application()
    sim = app._simulation
    key = (ids.SOUTH_POLAR_RIDGE, ids.WATER)
    target = sim.survey.targets[key]

    sim.survey.start(*key, allocation_weight=2.0)
    assert key in sim.survey.campaigns
    assert sim.survey.progress(*key) == 0.0

    sim.survey.knowledge_progress[key] = target.thresholds[-1] - 0.5
    original_capacity = sim.survey.capacity_at
    sim.survey.capacity_at = lambda *_args, **_kwargs: 1.0
    try:
        sim.survey.advance_day({}, sim.day)
    finally:
        sim.survey.capacity_at = original_capacity

    assert sim.survey.progress(*key) == target.thresholds[-1]
    assert sim.survey.is_complete(*key)
    assert key not in sim.survey.campaigns

    row = next(
        item for item in app.query(GetSurveys(str(ids.SOUTH_POLAR_RIDGE))).items
        if item.resource_id == str(ids.WATER)
    )
    assert row.complete is True
    assert row.active is False
    assert row.blockers == ()
