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


def test_unfounded_lunar_surface_cell_is_not_a_normal_logistics_destination():
    app = build_game_application()
    sim = app._simulation
    cell_id = ids.MOON_CELL_SOUTH_POLAR_RIDGE
    assert cell_id not in sim.graph.operational_node_ids()
    assert all(location_id != cell_id for location_id, _resource_id in sim.inventory.stock)
    assert not any(
        cell_id in {route.origin_id, route.destination_id}
        for route in sim.logistics.routes.values()
    )


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


def test_initial_surface_resource_knowledge_has_no_active_survey_campaigns():
    app = build_game_application()
    sim = app._simulation
    key = (ids.EARTH_CELL_INDUSTRIAL, ids.WATER)

    assert sim.survey.is_complete(*key)
    assert key in sim.survey.knowledge_progress
    assert key not in sim.survey.campaigns

    row = next(
        item for item in app.query(GetSurveys(str(ids.EARTH))).items
        if item.cell_id == str(ids.EARTH_CELL_INDUSTRIAL) and item.resource_id == str(ids.WATER)
    )
    assert row.complete is True
    assert row.active is False
    assert row.can_start is False
    assert row.can_pause is False
    assert row.can_resume is False
    assert row.can_set_allocation is False


def test_orbital_survey_stops_at_provider_knowledge_limit_and_reveals_comparison_value():
    app = build_game_application()
    sim = app._simulation
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.WATER)
    target = sim.survey.targets[key]

    assert sim.survey.start_blockers(ids.LUNAR_ORBIT, *key, sim.day) == ()
    assert sim.survey.reachable_knowledge_level(
        ids.LUNAR_ORBIT, key[0], day=sim.day
    ) == 2

    sim.survey.start(ids.LUNAR_ORBIT, *key, allocation_weight=2.0, day=sim.day)
    assert key in sim.survey.campaigns
    assert sim.survey.campaigns[key].target_knowledge_level == 2

    sim.advance_days(8)

    assert sim.survey.progress(*key) == target.thresholds[1]
    assert sim.survey.knowledge_level(*key) == 2
    assert not sim.survey.is_complete(*key)
    assert sim.survey.visible_potential(*key) is not None
    assert key not in sim.survey.campaigns
    assert sim.survey.start_blockers(ids.LUNAR_ORBIT, *key, sim.day) == (
        "survey_provider_limit",
    )

    row = next(
        item for item in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).items
        if item.cell_id == str(ids.MOON_CELL_FARSIDE_HIGHLANDS) and item.resource_id == str(ids.WATER)
    )
    assert row.complete is False
    assert row.active is False
    assert row.can_start is False
    assert row.target_knowledge_level == 2
    assert row.target_threshold == target.thresholds[1]
    assert row.progress_fraction == 1.0
    assert row.blockers == ("survey_provider_limit",)
