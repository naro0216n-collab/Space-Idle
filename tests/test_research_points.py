from __future__ import annotations

from dataclasses import replace
from math import isclose

from space_idle import AdvanceTime, GetResearch, PauseFacility, ResumeFacility, StartResearch, build_game_application
from space_idle.content.base_game import TECH_ORBITAL_OPERATIONS
from space_idle.research import ResearchDefinition, ResearchStage
from space_idle.shared import DefinitionId


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _advance_until_startable(app, research_id, max_days=2000):
    for _ in range(max_days + 1):
        row = _research_row(app, research_id)
        if row.can_start:
            return row
        app.execute(AdvanceTime(1))
    raise AssertionError(f"research never became startable: {research_id}")


def test_research_points_generate_and_clip_at_current_storage_capacity():
    app = build_game_application()
    initial = app.query(GetResearch())
    assert initial.generation_points_per_day > 0
    assert initial.storage_capacity_points > 0

    app.execute(AdvanceTime(1))
    after_one_day = app.query(GetResearch())
    assert after_one_day.stored_points > initial.stored_points
    assert after_one_day.stored_points <= after_one_day.storage_capacity_points + 1e-9

    for _ in range(5000):
        current = app.query(GetResearch())
        if current.storage_capacity_points - current.stored_points <= 1e-9:
            break
        app.execute(AdvanceTime(1))
    else:
        raise AssertionError("research storage never filled")

    full = app.query(GetResearch())
    app.execute(AdvanceTime(10))
    later = app.query(GetResearch())
    assert isclose(later.stored_points, full.stored_points, abs_tol=1e-9)
    assert later.stored_points <= later.storage_capacity_points + 1e-9


def test_capacity_drop_preserves_stored_points_and_overcap_blocks_generation():
    app = build_game_application()

    # Fill whatever aggregate capacity the current provider set supplies. The
    # invariant must hold regardless of how many research assets contribute.
    for _ in range(5000):
        current = app.query(GetResearch())
        if current.storage_capacity_points - current.stored_points <= 1e-9:
            break
        app.execute(AdvanceTime(1))
    else:
        raise AssertionError("research storage never filled")

    before = app.query(GetResearch())
    provider_ids = tuple(row.facility_id for row in before.providers)
    assert provider_ids and before.stored_points > 0

    for facility_id in provider_ids:
        app.execute(PauseFacility(facility_id))
    paused = app.query(GetResearch())
    assert paused.stored_points == before.stored_points
    assert paused.storage_capacity_points < before.storage_capacity_points
    assert paused.over_capacity
    assert paused.generation_points_per_day == 0

    app.execute(AdvanceTime(5))
    still_paused = app.query(GetResearch())
    assert still_paused.stored_points == paused.stored_points

    for facility_id in provider_ids:
        app.execute(ResumeFacility(facility_id))
    resumed = app.query(GetResearch())
    assert resumed.storage_capacity_points > paused.storage_capacity_points
    assert resumed.generation_points_per_day > 0
    assert resumed.stored_points == paused.stored_points


def test_research_start_creates_theory_project_without_upfront_rp_payment():
    app = build_game_application()
    sim = app._simulation
    sim.research.stored_points = 10.0
    before = app.query(GetResearch()).stored_points

    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS), priority=80))

    started = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert app.query(GetResearch()).stored_points == before
    assert started.status == "theory"
    assert started.priority == 80
    assert started.rp_remaining == started.research_point_cost
    assert started.execution_requested > 0
    assert started.execution_allocated > 0

    expected_consumption = started.rp_allocated
    expected_generation = app.query(GetResearch()).generation_points_per_day
    app.execute(AdvanceTime(1))
    after = app.query(GetResearch())
    progressed = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert progressed.stage_progress == expected_consumption
    assert isclose(
        after.stored_points,
        min(after.storage_capacity_points, before - expected_consumption + expected_generation),
        abs_tol=1e-9,
    )


def test_research_total_cost_may_exceed_rp_storage_capacity():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.more_than_storage")
    capacity = app.query(GetResearch()).storage_capacity_points
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Long Theory",
        research_point_cost=capacity + 10.0,
        stages=(ResearchStage.THEORY,),
    )

    row = _research_row(app, research_id)
    assert row.can_start
    assert not any(code in {"research_points", "rp_storage_capacity"} for code, _ in row.start_blockers)
    app.execute(StartResearch(str(research_id)))
    assert _research_row(app, research_id).status == "theory"

    for _ in range(20):
        app.execute(AdvanceTime(1))
    progressed = _research_row(app, research_id)
    assert progressed.stage_progress > 0
    assert progressed.rp_remaining < progressed.research_point_cost


def test_global_research_points_do_not_use_provider_research_allowlists():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.unscoped")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Unscoped Research",
        research_point_cost=1.0,
        stages=(ResearchStage.THEORY,),
    )
    sim.research.stored_points = 1.0

    sim.research.start(research_id, day=sim.day)
    assert research_id in sim.research.active
    assert sim.research.active[research_id].stage.value == "theory"
    assert sim.research.stored_points == 1.0

    sim.advance_days(1)
    assert research_id in sim.research.completed
    assert all(not hasattr(provider, "research_ids") for provider in sim.research.providers.values())

def test_research_provider_level_behavior_comes_from_provider_content():
    app = build_game_application()
    sim = app._simulation
    view = app.query(GetResearch())
    row = next(
        item
        for item in view.providers
        if len(sim.research.providers[DefinitionId(item.facility_definition_id)].levels) > 1
    )
    facility_id = next(fid for fid in sim.facilities.facilities if str(fid) == row.facility_id)
    facility = sim.facilities.facilities[facility_id]
    provider = sim.research.providers[facility.definition_id]
    current_spec = provider.level_spec(facility.level)
    alternative = next(
        spec
        for spec in provider.levels
        if spec.level != facility.level
        and (
            spec.generation_points_per_day,
            spec.storage_capacity_points,
        )
        != (
            current_spec.generation_points_per_day,
            current_spec.storage_capacity_points,
        )
    )

    facility.level = alternative.level
    changed = next(item for item in app.query(GetResearch()).providers if item.facility_id == row.facility_id)

    assert changed.level == alternative.level
    assert (
        changed.generation_points_per_day,
        changed.storage_capacity_points,
    ) != (
        row.generation_points_per_day,
        row.storage_capacity_points,
    )
