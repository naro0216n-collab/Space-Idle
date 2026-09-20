from __future__ import annotations

from math import isclose

import pytest

from space_idle import (
    AdvanceTime, ApplicationError, GetResearch, PauseFacility,
    PauseResearchProviderAssignment, ResumeFacility, ResumeResearchProviderAssignment,
    SetResearchProviderFleetQuantity,
    SetFacilityActivityPriority, SetResearchProviderAssignmentPriority, StartResearch,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.research import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
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
            ResearchProviderSourceKind.FACILITY,
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
    app.execute(SetResearchProviderFleetQuantity(
        str(fleet_provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1
    ))
    sim.research.stored_points = 18.0
    admitted = {
        row.source_kind: row.admitted_generation_points_per_day
        for row in app.query(GetResearch()).providers
    }
    return app, facility_definition_id, admitted


def test_research_providers_share_pool_admission_by_priority_independent_of_registration_order():
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
    first.execute(AdvanceTime(1))
    assert first.query(GetResearch()).stored_points == pytest.approx(20.0)

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
