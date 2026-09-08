from __future__ import annotations

from dataclasses import replace
from math import isclose

from space_idle import AdvanceTime, GetResearch, PauseFacility, ResumeFacility, StartResearch, build_game_application
from space_idle.content.base_game import TECH_ORBITAL_OPERATIONS
from space_idle.research import ResearchDefinition
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
    app.execute(AdvanceTime(2))
    before = app.query(GetResearch())
    provider = before.providers[0]
    assert before.stored_points > 0

    app.execute(PauseFacility(provider.facility_id))
    paused = app.query(GetResearch())
    assert paused.stored_points == before.stored_points
    assert paused.storage_capacity_points < before.storage_capacity_points
    assert paused.over_capacity
    assert paused.generation_points_per_day == 0

    app.execute(AdvanceTime(5))
    still_paused = app.query(GetResearch())
    assert still_paused.stored_points == paused.stored_points

    app.execute(ResumeFacility(provider.facility_id))
    app.execute(AdvanceTime(1))
    resumed = app.query(GetResearch())
    assert resumed.storage_capacity_points > paused.storage_capacity_points
    assert resumed.stored_points > paused.stored_points


def test_research_start_consumes_full_cost_atomically_and_skips_theory_phase():
    app = build_game_application()
    row = _advance_until_startable(app, TECH_ORBITAL_OPERATIONS)
    before = app.query(GetResearch()).stored_points

    app.execute(StartResearch(str(TECH_ORBITAL_OPERATIONS)))

    after = app.query(GetResearch())
    started = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert isclose(after.stored_points, before - row.research_point_cost, abs_tol=1e-9)
    assert started.status in {"prototype", "demonstration", "complete"}
    assert started.status != "theory"


def test_insufficient_points_and_insufficient_capacity_are_distinct_start_blockers():
    app = build_game_application()
    initial = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert any(code == "research_points" for code, _detail in initial.start_blockers)

    sim = app._simulation
    definition = sim.research.definitions[TECH_ORBITAL_OPERATIONS]
    current_capacity = app.query(GetResearch()).storage_capacity_points
    unreachable_cost = max(definition.research_point_cost, current_capacity) + max(1.0, current_capacity)
    sim.research.definitions[TECH_ORBITAL_OPERATIONS] = replace(
        definition,
        research_point_cost=unreachable_cost,
    )
    sim.research.stored_points = unreachable_cost

    blocked = _research_row(app, TECH_ORBITAL_OPERATIONS)
    assert not blocked.can_start
    assert not any(code == "research_points" for code, _detail in blocked.start_blockers)
    assert any(code == "rp_storage_capacity" for code, _detail in blocked.start_blockers)


def test_global_research_points_do_not_use_provider_research_allowlists():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.unscoped")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Unscoped Research",
        research_point_cost=1.0,
    )
    sim.research.stored_points = 1.0

    sim.research.start(research_id, day=sim.day)

    assert research_id in sim.research.completed
    assert sim.research.stored_points == 0.0
    assert all(not hasattr(provider, "research_ids") for provider in sim.research.providers.values())


def test_research_provider_level_behavior_comes_from_provider_content():
    app = build_game_application()
    sim = app._simulation
    view = app.query(GetResearch())
    row = view.providers[0]
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
