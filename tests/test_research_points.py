from __future__ import annotations

from math import isclose

from space_idle import AdvanceTime, GetResearch, PauseFacility, ResumeFacility, StartResearch, build_game_application
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef, ServiceCapacitySupply
from space_idle.service_capacity import ServiceCapacityScope
from space_idle.research import (
    ResearchDefinition,
    ResearchProviderLevelSpec,
    ResearchProviderSpec,
    ResearchStage,
)
from space_idle.shared import DefinitionId


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def test_research_point_storage_limits_generation_without_discarding_overcapacity():
    app = build_game_application()
    sim = app._simulation
    provider_definition_id = DefinitionId("test.facility.research_storage_provider")
    sim.facilities.definitions[provider_definition_id] = FacilityDef(
        provider_definition_id, "Research storage provider fixture"
    )
    sim.research.providers = {
        provider_definition_id: ResearchProviderSpec(
            provider_definition_id,
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 2.0, 10.0),),
        )
    }
    provider_id = sim.facilities.install(provider_definition_id, ids.EARTH)
    initial = app.query(GetResearch())
    assert initial.generation_points_per_day == 2.0
    assert initial.storage_capacity_points == 10.0

    sim.research.stored_points = initial.storage_capacity_points
    full = app.query(GetResearch())
    app.execute(AdvanceTime(1))
    clipped = app.query(GetResearch())
    assert isclose(clipped.stored_points, full.stored_points, abs_tol=1e-9)
    assert clipped.stored_points <= clipped.storage_capacity_points + 1e-9

    provider_ids = tuple(row.facility_id for row in clipped.providers)
    assert provider_ids == (str(provider_id),)
    assert clipped.stored_points > 0
    for facility_id in provider_ids:
        app.execute(PauseFacility(facility_id))

    paused = app.query(GetResearch())
    assert paused.stored_points == clipped.stored_points
    assert paused.storage_capacity_points < clipped.storage_capacity_points
    assert paused.over_capacity
    assert paused.generation_points_per_day == 0

    app.execute(AdvanceTime(1))
    still_paused = app.query(GetResearch())
    assert still_paused.stored_points == paused.stored_points

    for facility_id in provider_ids:
        app.execute(ResumeFacility(facility_id))
    resumed = app.query(GetResearch())
    assert resumed.storage_capacity_points > paused.storage_capacity_points
    assert resumed.generation_points_per_day > 0
    assert resumed.stored_points == paused.stored_points

def test_global_research_points_are_progressively_allocated_without_upfront_or_storage_cap_requirement():
    app = build_game_application()
    sim = app._simulation
    provider_definition_id = DefinitionId("test.facility.research_execution_provider")
    sim.facilities.definitions[provider_definition_id] = FacilityDef(
        provider_definition_id,
        "Research execution provider fixture",
        service_capacity_supplies=(
            ServiceCapacitySupply(
                "research_execution", 1.0, ServiceCapacityScope.ORGANIZATION
            ),
        ),
    )
    sim.research.providers = {
        provider_definition_id: ResearchProviderSpec(
            provider_definition_id,
            tier=1,
            levels=(ResearchProviderLevelSpec(1, 0.0, 10.0),),
        )
    }
    sim.facilities.install(provider_definition_id, ids.EARTH)
    capacity = app.query(GetResearch()).storage_capacity_points
    assert capacity == 10.0

    research_id = DefinitionId("test.research.progressive_global_points")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Progressive global RP fixture",
        research_point_cost=capacity * 2.0,
        stages=(ResearchStage.THEORY,),
    )
    sim.research.stored_points = capacity

    available = _research_row(app, research_id)
    assert available.can_start
    assert not any(
        code in {"research_points", "rp_storage_capacity"}
        for code, _detail in available.start_blockers
    )
    before = app.query(GetResearch()).stored_points
    app.execute(StartResearch(str(research_id), priority=4))

    started = _research_row(app, research_id)
    assert app.query(GetResearch()).stored_points == before
    assert started.status == "theory"
    assert started.priority == 4
    assert started.rp_remaining == started.research_point_cost
    assert started.research_point_cost > capacity
    assert started.execution_allocated > 0.0
    assert started.rp_allocated > 0.0

    expected_consumption = started.rp_allocated
    app.execute(AdvanceTime(1))
    progressed = _research_row(app, research_id)
    after = app.query(GetResearch())
    assert progressed.stage_progress == expected_consumption
    assert progressed.rp_remaining == progressed.research_point_cost - expected_consumption
    assert isclose(after.stored_points, before - expected_consumption, abs_tol=1e-9)
