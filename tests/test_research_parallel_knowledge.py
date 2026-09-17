from __future__ import annotations

from math import isclose

from space_idle import GetResearch, SetResearchPriority, StartResearch, build_game_application
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.knowledge import ExperienceContributionRule
from space_idle.power import PowerSpec
from space_idle.research import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchOperationalExperienceStageSpec,
    ResearchProviderLevelSpec, ResearchProviderSourceKind, ResearchProviderSpec,
    ResearchStage,
)
from space_idle.shared import DefinitionId


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _set_earth_research_execution_capacity(sim, rate: float) -> None:
    fixture_id = DefinitionId("test.facility.research_execution_capacity")
    sim.facilities.definitions[fixture_id] = FacilityDef(
        fixture_id, "Research execution capacity fixture"
    )
    sim.research.providers = {fixture_id: ResearchProviderSpec(
        fixture_id, ResearchProviderSourceKind.FACILITY, fixture_id, tier=1,
        levels=(ResearchProviderLevelSpec(1, 0.0, 0.0, rate),),
    )}
    sim.facilities.install(fixture_id, ids.EARTH)


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
        sim.research.definitions[research_id] = ResearchDefinition(research_id, str(research_id), (ResearchTheoryStageSpec("theory", 10.0),), prerequisites=frozenset())
    sim.research.stored_points = stored_points
    for research_id in start_order:
        app.execute(StartResearch(str(research_id), priority=3))
    return app


def test_research_shared_allocation_respects_priority_fairness_and_registration_order():
    for suffix, execution_rate, stored_points, blocker_code in (
        ("rp", 20.0, 1.0, "research_points:allocation"),
        ("execution", 1.0, 100.0, "service_pool:allocation"),
    ):
        a = DefinitionId(f"test.research.shared.{suffix}.a")
        b = DefinitionId(f"test.research.shared.{suffix}.b")
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

        first.execute(SetResearchPriority(str(a), 5))
        first.execute(SetResearchPriority(str(b), 1))
        high = _research_row(first, a)
        low = _research_row(first, b)
        assert high.priority == 5
        assert low.priority == 1
        assert high.execution_allocated == 1.0
        assert low.execution_allocated == 0.0
        assert high.rp_requested == low.rp_requested == 10.0
        assert high.rp_allocated == 1.0
        assert low.rp_allocated == 0.0
        assert any(code == blocker_code for code, _ in low.current_blockers)


def test_organization_research_execution_aggregates_provider_sites_after_local_power():
    app = build_game_application()
    sim = app._simulation
    earth_provider = DefinitionId("test.facility.research_execution.earth")
    leo_provider = DefinitionId("test.facility.research_execution.leo")
    sim.research.providers = {}
    for definition_id in (earth_provider, leo_provider):
        sim.facilities.definitions[definition_id] = FacilityDef(definition_id, str(definition_id))
        sim.research.providers[definition_id] = ResearchProviderSpec(
            definition_id, ResearchProviderSourceKind.FACILITY, definition_id, tier=1,
            levels=(ResearchProviderLevelSpec(1, 0.0, 0.0, 1.0),),
        )
    sim.power.specs[earth_provider] = PowerSpec(None, 0.1)
    sim.power.specs[leo_provider] = PowerSpec(None, 1.0)
    sim.facilities.install(earth_provider, ids.EARTH)
    sim.facilities.install(leo_provider, ids.LEO)

    research_id = DefinitionId("test.research.organization_provider_power")
    sim.research.definitions[research_id] = ResearchDefinition(research_id, "Organization Provider Power", (ResearchTheoryStageSpec("theory", 10.0),), prerequisites=frozenset())
    sim.research.stored_points = 100.0
    app.execute(StartResearch(str(research_id), priority=3))

    constrained = _research_row(app, research_id).execution_allocated
    decision = sim.tick_decision_projection()
    expected = sum(
        sim.research.service_capacity_supply_at(
            node_id, "research_execution", sim.facilities,
            decision.allocations.power_by_location[node_id], sim.day
        )[1]
        for node_id in (ids.EARTH, ids.LEO)
    )
    assert isclose(constrained, expected, abs_tol=1e-9)
    assert 1.0 < constrained < 2.0

    sim.power.specs[leo_provider] = PowerSpec(None, 0.0)
    unconstrained = _research_row(app, research_id).execution_allocated
    assert isclose(unconstrained, 2.0, abs_tol=1e-9)

def test_operational_experience_is_driven_by_real_activity_not_research_time():
    app = build_game_application()
    sim = app._simulation

    never_emitted = "test.experience.never_emitted"
    sim.research.experience_rules = sim.research.experience_rules + (
        ExperienceContributionRule("never_emitted", never_emitted, 1.0),
    )
    waiting_id = DefinitionId("test.research.operational_experience_wait")
    sim.research.definitions[waiting_id] = ResearchDefinition(waiting_id, "Experience Wait", (ResearchOperationalExperienceStageSpec("operational_experience", {never_emitted: 1.0}),), prerequisites=frozenset())
    extraction_id = DefinitionId("test.research.extraction_experience")
    sim.research.definitions[extraction_id] = ResearchDefinition(extraction_id, "Extraction Experience", (ResearchOperationalExperienceStageSpec("operational_experience", {
            ids.EXPERIENCE_EXTRACTION_OPERATIONS: 0.1,
        }),), prerequisites=frozenset())

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
