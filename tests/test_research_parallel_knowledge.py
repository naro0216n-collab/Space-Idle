from __future__ import annotations

from dataclasses import replace

from space_idle import GetResearch, SetResearchPriority, StartResearch, build_game_application
from space_idle.content import base_ids as ids
from space_idle.facilities import ServiceCapacitySupply
from space_idle.knowledge import ExperienceContributionRule
from space_idle.research import (
    ResearchDefinition,
    ResearchOperationalExperienceSpec,
    ResearchStage,
)
from space_idle.shared import DefinitionId


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _set_earth_research_execution_capacity(sim, rate: float) -> None:
    lab = next(
        facility for facility in sim.facilities.facilities.values()
        if facility.definition_id == ids.EARTH_RESEARCH_LAB
    )
    definition = sim.facilities.definitions[lab.definition_id]
    supplies = tuple(
        ServiceCapacitySupply(supply.service_type, rate)
        if supply.service_type == "research_execution"
        else supply
        for supply in definition.service_capacity_supplies
    )
    sim.facilities.definitions[lab.definition_id] = replace(
        definition, service_capacity_supplies=supplies
    )


def _parallel_projection(
    start_order: tuple[DefinitionId, DefinitionId],
    *,
    execution_rate: float = 20.0,
    stored_points: float = 1.0,
):
    app = build_game_application()
    sim = app._simulation
    _set_earth_research_execution_capacity(sim, execution_rate)
    for research_id in start_order:
        sim.research.definitions[research_id] = ResearchDefinition(
            research_id,
            str(research_id),
            research_point_cost=10.0,
            stages=(ResearchStage.THEORY,),
        )
    sim.research.stored_points = stored_points
    for research_id in start_order:
        app.execute(StartResearch(str(research_id), priority=3))
    return app


def test_parallel_theory_same_priority_is_fair_and_registration_order_independent_across_constraints():
    for suffix, execution_rate, stored_points, blocker_code in (
        ("rp", 20.0, 1.0, "research_points:allocation"),
        ("execution", 1.0, 100.0, "service:allocation"),
    ):
        a = DefinitionId(f"test.research.parallel.{suffix}.a")
        b = DefinitionId(f"test.research.parallel.{suffix}.b")
        first = _parallel_projection(
            (a, b), execution_rate=execution_rate, stored_points=stored_points
        )
        second = _parallel_projection(
            (b, a), execution_rate=execution_rate, stored_points=stored_points
        )

        first_rows = {rid: _research_row(first, rid) for rid in (a, b)}
        second_rows = {rid: _research_row(second, rid) for rid in (a, b)}
        for rid in (a, b):
            row = first_rows[rid]
            assert row.execution_requested == 10.0
            assert row.execution_allocated == 0.5
            assert row.rp_requested == 10.0
            assert row.rp_allocated == 0.5
            assert second_rows[rid].execution_allocated == row.execution_allocated
            assert second_rows[rid].rp_allocated == row.rp_allocated
            assert any(code == blocker_code for code, _ in row.current_blockers)


def test_research_priority_controls_shared_execution_and_rp_constraints():
    for suffix, execution_rate, stored_points, blocker_code in (
        ("execution", 1.0, 100.0, "service:allocation"),
        ("rp", 20.0, 1.0, "research_points:allocation"),
    ):
        a = DefinitionId(f"test.research.priority.{suffix}.a")
        b = DefinitionId(f"test.research.priority.{suffix}.b")
        app = _parallel_projection(
            (a, b), execution_rate=execution_rate, stored_points=stored_points
        )
        app.execute(SetResearchPriority(str(a), 5))
        app.execute(SetResearchPriority(str(b), 1))

        high = _research_row(app, a)
        low = _research_row(app, b)
        assert high.priority == 5
        assert low.priority == 1
        assert high.execution_allocated == 1.0
        assert low.execution_allocated == 0.0
        assert high.rp_requested == low.rp_requested == 10.0
        assert high.rp_allocated == 1.0
        assert low.rp_allocated == 0.0
        assert any(code == blocker_code for code, _ in low.current_blockers)

def test_operational_experience_is_driven_by_real_activity_not_research_time():
    app = build_game_application()
    sim = app._simulation

    never_emitted = "test.experience.never_emitted"
    sim.research.experience_rules = sim.research.experience_rules + (
        ExperienceContributionRule("never_emitted", never_emitted, 1.0),
    )
    waiting_id = DefinitionId("test.research.operational_experience_wait")
    sim.research.definitions[waiting_id] = ResearchDefinition(
        waiting_id,
        "Experience Wait",
        0.0,
        operational_experience=ResearchOperationalExperienceSpec({never_emitted: 1.0}),
        stages=(ResearchStage.OPERATIONAL_EXPERIENCE,),
    )
    extraction_id = DefinitionId("test.research.extraction_experience")
    sim.research.definitions[extraction_id] = ResearchDefinition(
        extraction_id,
        "Extraction Experience",
        0.0,
        operational_experience=ResearchOperationalExperienceSpec({
            ids.EXPERIENCE_EXTRACTION_OPERATIONS: 0.1,
        }),
        stages=(ResearchStage.OPERATIONAL_EXPERIENCE,),
    )

    sim.research.start(waiting_id, day=sim.day)
    sim.research.start(extraction_id, day=sim.day)
    extraction_before = sim.research.knowledge_state.value(
        ids.EXPERIENCE_EXTRACTION_OPERATIONS
    )
    sim.advance_days(1)

    assert sim.research.knowledge_state.value(never_emitted) == 0.0
    assert waiting_id in sim.research.active
    assert any(
        code == "operational_experience"
        for code, _ in sim.research.operational_experience_blockers(waiting_id)
    )
    assert sim.research.knowledge_state.value(
        ids.EXPERIENCE_EXTRACTION_OPERATIONS
    ) > extraction_before
    assert extraction_id in sim.research.completed
