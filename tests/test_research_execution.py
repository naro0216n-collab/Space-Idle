from __future__ import annotations

from math import isclose

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    GetResearch,
    PauseFacility,
    PauseResearchProviderAssignment,
    ResumeFacility,
    ResumeResearchProviderAssignment,
    SetFacilityActivityPriority,
    SetResearchPriority,
    SetResearchProviderAssignmentPriority,
    SetResearchProviderFleetQuantity,
    StartResearch,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.knowledge import ExperienceContributionRule
from space_idle.power import PowerSpec
from space_idle.research import (
    ResearchDefinition,
    ResearchOperationalExperienceStageSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
    ResearchProviderSpec,
    ResearchTheoryStageSpec,
)
from space_idle.shared import DefinitionId


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _install_fleet_research_provider(sim, provider_id: DefinitionId) -> None:
    sim.research.providers[provider_id] = ResearchProviderSpec(
        provider_id,
        ResearchProviderSourceKind.FLEET,
        ids.REUSABLE_ORBITAL_CARGO_TUG,
        tier=2,
        levels=(ResearchProviderLevelSpec(1, 3.0, 20.0, 2.0),),
    )


def test_fleet_research_provider_assignment_owns_intent_while_fleet_owns_quantity():
    app = build_game_application()
    sim = app._simulation
    provider_id = DefinitionId("test.research_provider.fleet")
    _install_fleet_research_provider(sim, provider_id)
    sim.transport.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = 1
    initial_free = sim.transport.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO)
    assert initial_free == 1

    option = next(
        row for row in app.query(GetResearch()).provider_fleet
        if row.provider_definition_id == str(provider_id)
        and row.operational_node_id == str(ids.LEO)
    )
    assert option.can_set_quantity
    assert option.committed_units == 0
    assert option.free_units == 1
    assert option.max_units == 1

    with pytest.raises(ApplicationError, match="insufficient free fleet units"):
        app.execute(SetResearchProviderFleetQuantity(
            str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 2
        ))
    assert sim.research.provider_assignments == {}
    assert sim.transport.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == initial_free

    assignment_id = app.execute(SetResearchProviderFleetQuantity(
        str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1
    )).created_id
    assert assignment_id is not None
    assert len(sim.research.provider_assignments) == 1
    repeated_id = app.execute(SetResearchProviderFleetQuantity(
        str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1
    )).created_id
    assert repeated_id == assignment_id
    assert len(sim.research.provider_assignments) == 1
    app.execute(SetResearchProviderAssignmentPriority(assignment_id, 4))
    assignment = sim.research.provider_assignments[next(iter(sim.research.provider_assignments))]
    commitment = sim.transport.fleet_commitment_snapshot(assignment.fleet_commitment_ref)
    assert commitment is not None
    assert commitment.quantity == 1
    assert commitment.owner_activity_ref.activity_type == "research_provider_assignment"
    assert sim.transport.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 0

    row = next(item for item in app.query(GetResearch()).providers if item.id == assignment_id)
    assert row.source_kind == "fleet"
    assert row.committed_units == 1
    assert row.generation_points_per_day == 3.0
    assert row.storage_capacity_points == 20.0
    assert row.research_execution_per_day == 2.0
    assert row.priority == 4

    app.execute(PauseResearchProviderAssignment(assignment_id))
    paused = next(item for item in app.query(GetResearch()).providers if item.id == assignment_id)
    assert paused.generation_points_per_day == 0.0
    assert paused.research_execution_per_day == 0.0
    assert paused.storage_capacity_points == 20.0
    assert sim.transport.fleet_commitment_snapshot(assignment.fleet_commitment_ref) is not None

    app.execute(ResumeResearchProviderAssignment(assignment_id))
    app.execute(SetResearchProviderAssignmentPriority(assignment_id, 5))
    sim.transport.add_fleet_units(ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, day=sim.day)
    resized_id = app.execute(SetResearchProviderFleetQuantity(
        str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 2
    )).created_id
    assert resized_id == assignment_id
    assert len(sim.research.provider_assignments) == 1
    resized = next(item for item in app.query(GetResearch()).providers if item.id == assignment_id)
    assert resized.committed_units == 2
    assert resized.priority == 5
    assert sim.transport.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 0

    app.execute(SetResearchProviderFleetQuantity(
        str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 0
    ))
    assert sim.research.provider_assignments == {}
    assert sim.transport.fleet_free_units(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO) == 2


def _mixed_provider_admission_projection(provider_order: tuple[str, str]):
    app = build_game_application()
    sim = app._simulation
    sim.research.providers = {}

    facility_definition_id = DefinitionId("test.facility.rp_provider.mixed")
    facility_provider_id = DefinitionId("test.research_provider.facility.mixed")
    fleet_provider_id = DefinitionId("test.research_provider.fleet.mixed")
    sim.facilities.definitions[facility_definition_id] = FacilityDef(
        facility_definition_id, "Mixed admission facility"
    )
    providers = {
        "facility": ResearchProviderSpec(
            facility_provider_id, ResearchProviderSourceKind.FACILITY,
            facility_definition_id, tier=1,
            levels=(ResearchProviderLevelSpec(1, 4.0, 10.0, 0.0),),
        ),
        "fleet": ResearchProviderSpec(
            fleet_provider_id, ResearchProviderSourceKind.FLEET,
            ids.REUSABLE_ORBITAL_CARGO_TUG, tier=1,
            levels=(ResearchProviderLevelSpec(1, 4.0, 10.0, 0.0),),
        ),
    }
    for key in provider_order:
        provider = providers[key]
        sim.research.providers[provider.id] = provider

    sim.facilities.install(facility_definition_id, ids.EARTH)
    sim.transport.fleet_pool(ids.REUSABLE_ORBITAL_CARGO_TUG, ids.LEO).total_units = 1
    app.execute(SetResearchProviderFleetQuantity(
        str(fleet_provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1
    ))
    sim.research.stored_points = 18.0
    admitted = {
        row.source_kind: row.admitted_generation_points_per_day
        for row in app.query(GetResearch()).providers
    }
    return app, facility_definition_id, admitted


def test_research_point_pool_limits_generation_and_admits_providers_by_priority_independent_of_order():
    first, facility_definition_id, admitted_first = _mixed_provider_admission_projection(
        ("facility", "fleet")
    )
    _second, _definition, admitted_second = _mixed_provider_admission_projection(
        ("fleet", "facility")
    )

    assert admitted_first == admitted_second == {"facility": 1.0, "fleet": 1.0}
    assert sum(admitted_first.values()) == pytest.approx(2.0)

    before = first.query(GetResearch())
    assert before.generation_points_per_day == pytest.approx(8.0)
    assert before.admitted_generation_points_per_day == pytest.approx(2.0)
    assert before.storage_capacity_points == pytest.approx(20.0)
    first.execute(AdvanceTime(1))
    full = first.query(GetResearch())
    assert full.stored_points == pytest.approx(20.0)
    assert full.stored_points <= full.storage_capacity_points + 1e-9

    high_facility = next(
        facility for facility in first._simulation.facilities.facilities.values()
        if facility.definition_id == facility_definition_id
    )
    first._simulation.research.stored_points = 18.0
    first.execute(SetFacilityActivityPriority(str(high_facility.id), 5))
    prioritized = {
        row.source_kind: row.admitted_generation_points_per_day
        for row in first.query(GetResearch()).providers
    }
    assert prioritized == {"facility": 2.0, "fleet": 0.0}

    first._simulation.research.stored_points = full.stored_points
    first.execute(PauseFacility(str(high_facility.id)))
    paused = first.query(GetResearch())
    assert paused.stored_points == full.stored_points
    assert paused.storage_capacity_points == pytest.approx(10.0)
    assert paused.over_capacity
    assert paused.admitted_generation_points_per_day == pytest.approx(0.0)

    first.execute(AdvanceTime(1))
    assert first.query(GetResearch()).stored_points == paused.stored_points

    first.execute(ResumeFacility(str(high_facility.id)))
    resumed = first.query(GetResearch())
    assert resumed.storage_capacity_points == pytest.approx(20.0)
    assert resumed.generation_points_per_day == pytest.approx(8.0)
    assert resumed.stored_points == paused.stored_points


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
        if suffix == "rp":
            research_state = second.query(GetResearch())
            assert research_state.storage_capacity_points == 0.0
            assert research_state.stored_points == stored_points
            assert all(
                row.total_theory_research_point_cost > research_state.storage_capacity_points
                for row in second_rows.values()
            )
        for rid in (a, b):
            row = first_rows[rid]
            assert row.execution_requested == 10.0
            assert row.execution_allocated == 0.5
            assert row.rp_requested == 10.0
            assert row.rp_allocated == 0.5
            assert second_rows[rid].execution_allocated == row.execution_allocated
            assert second_rows[rid].rp_allocated == row.rp_allocated
            assert any(blocker.code == blocker_code for blocker in row.current_blockers)

        if suffix == "rp":
            before_points = second.query(GetResearch()).stored_points
            second.execute(AdvanceTime(1))
            progressed = {rid: _research_row(second, rid) for rid in (a, b)}
            assert all(row.stage_progress == 0.5 for row in progressed.values())
            assert second.query(GetResearch()).stored_points == before_points - 1.0

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
        assert any(blocker.code == blocker_code for blocker in low.current_blockers)


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
    provider_rows = {
        row.provider_definition_id: row
        for row in app.query(GetResearch()).providers
    }
    expected = sum(
        provider_rows[str(provider_id)].research_execution_per_day
        for provider_id in (earth_provider, leo_provider)
    )
    assert isclose(constrained, expected, abs_tol=1e-9)
    assert provider_rows[str(earth_provider)].research_execution_per_day == pytest.approx(1.0)
    assert 0.0 < provider_rows[str(leo_provider)].research_execution_per_day < 1.0

    sim.power.specs[leo_provider] = PowerSpec(None, 0.0)
    unconstrained_view = app.query(GetResearch())
    unconstrained = next(
        row for row in unconstrained_view.items if row.id == str(research_id)
    ).execution_allocated
    unconstrained_provider_rows = {
        row.provider_definition_id: row
        for row in unconstrained_view.providers
    }
    assert isclose(
        unconstrained,
        sum(
            unconstrained_provider_rows[str(provider_id)].research_execution_per_day
            for provider_id in (earth_provider, leo_provider)
        ),
        abs_tol=1e-9,
    )
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
