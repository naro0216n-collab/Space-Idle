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
        app.execute(StartResearch(str(research_id), priority=50))
    return app


def test_parallel_theory_same_priority_is_proportional_and_registration_order_independent():
    a = DefinitionId("test.research.parallel.a")
    b = DefinitionId("test.research.parallel.b")
    first = _parallel_projection((a, b))
    second = _parallel_projection((b, a))

    first_rows = {rid: _research_row(first, rid) for rid in (a, b)}
    second_rows = {rid: _research_row(second, rid) for rid in (a, b)}
    for rid in (a, b):
        assert first_rows[rid].execution_allocated == 10.0
        assert first_rows[rid].rp_requested == 10.0
        assert first_rows[rid].rp_allocated == 0.5
        assert second_rows[rid].rp_allocated == first_rows[rid].rp_allocated


def test_parallel_theory_execution_capacity_is_shared_independently_of_start_order():
    a = DefinitionId("test.research.execution.parallel.a")
    b = DefinitionId("test.research.execution.parallel.b")
    first = _parallel_projection((a, b), execution_rate=1.0, stored_points=100.0)
    second = _parallel_projection((b, a), execution_rate=1.0, stored_points=100.0)

    first_rows = {rid: _research_row(first, rid) for rid in (a, b)}
    second_rows = {rid: _research_row(second, rid) for rid in (a, b)}
    for rid in (a, b):
        assert first_rows[rid].execution_requested == 10.0
        assert first_rows[rid].execution_allocated == 0.5
        assert second_rows[rid].execution_allocated == first_rows[rid].execution_allocated
        assert first_rows[rid].rp_requested == 0.5
        assert first_rows[rid].rp_allocated == 0.5


def test_research_priority_controls_shared_execution_capacity_before_rp_consumption():
    a = DefinitionId("test.research.execution.priority.a")
    b = DefinitionId("test.research.execution.priority.b")
    app = _parallel_projection((a, b), execution_rate=1.0, stored_points=100.0)

    app.execute(SetResearchPriority(str(a), 100))
    app.execute(SetResearchPriority(str(b), 10))

    high = _research_row(app, a)
    low = _research_row(app, b)
    assert high.execution_allocated == 1.0
    assert low.execution_allocated == 0.0
    assert high.rp_requested == 1.0
    assert low.rp_requested == 0.0


def test_research_priority_controls_shared_rp_allocation_without_project_order():
    a = DefinitionId("test.research.priority.a")
    b = DefinitionId("test.research.priority.b")
    app = _parallel_projection((a, b))

    app.execute(SetResearchPriority(str(a), 100))
    app.execute(SetResearchPriority(str(b), 10))

    high = _research_row(app, a)
    low = _research_row(app, b)
    assert high.priority == 100
    assert low.priority == 10
    assert high.rp_requested == 10.0
    assert low.rp_requested == 10.0
    assert high.rp_allocated == 1.0
    assert low.rp_allocated == 0.0
    assert any(code == "research_points:allocation" for code, _ in low.current_blockers)


def test_operational_experience_does_not_accumulate_from_research_time_itself():
    app = build_game_application()
    sim = app._simulation
    category = "test.experience.never_emitted"
    sim.research.experience_rules = sim.research.experience_rules + (
        ExperienceContributionRule("never_emitted", category, 1.0),
    )
    research_id = DefinitionId("test.research.operational_experience_wait")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Experience Wait",
        0.0,
        operational_experience=ResearchOperationalExperienceSpec({category: 1.0}),
        stages=(ResearchStage.OPERATIONAL_EXPERIENCE,),
    )

    sim.research.start(research_id, day=sim.day)
    assert sim.research.active[research_id].stage is ResearchStage.OPERATIONAL_EXPERIENCE
    sim.advance_days(3)

    assert sim.research.knowledge_state.value(category) == 0.0
    assert research_id in sim.research.active
    assert any(
        code == "operational_experience"
        for code, _ in sim.research.operational_experience_blockers(research_id)
    )


def test_actual_extraction_activity_contributes_to_knowledge_and_unblocks_research():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.extraction_experience")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Extraction Experience",
        0.0,
        operational_experience=ResearchOperationalExperienceSpec({
            ids.EXPERIENCE_EXTRACTION_OPERATIONS: 0.1,
        }),
        stages=(ResearchStage.OPERATIONAL_EXPERIENCE,),
    )

    sim.research.start(research_id, day=sim.day)
    before = sim.research.knowledge_state.value(ids.EXPERIENCE_EXTRACTION_OPERATIONS)
    sim.advance_days(1)

    after = sim.research.knowledge_state.value(ids.EXPERIENCE_EXTRACTION_OPERATIONS)
    assert after > before
    assert research_id in sim.research.completed
