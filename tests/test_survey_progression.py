from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    GetSurveys,
    PauseSurvey,
    ResumeSurvey,
    SetSurveyProviderFleetQuantity,
    StartSurvey,
    SurveyProviderConstraintInput,
    UpdateSurvey,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.exploration_models import SurveyCampaignControlState, SurveyProviderConstraint
from space_idle.shared import DefinitionId
from space_idle.survey import (
    KnowledgeLevel,
    KnowledgeRequirement,
    SurveyObservationModeSpec,
    SurveyProviderSourceKind,
    SurveyProviderSpec,
    SurveyReachScope,
    SurveyReachSpec,
)


def _orbiter_constraint() -> SurveyProviderConstraintInput:
    return SurveyProviderConstraintInput(
        str(ids.LUNAR_RESOURCE_SURVEY_ORBITER), str(ids.LUNAR_ORBIT)
    )


def _start_campaign(app, cells, resources, goal=1, *, constrained=True, priority=3):
    return app.execute(StartSurvey(
        target_cell_ids=tuple(map(str, cells)),
        resource_ids=tuple(map(str, resources)),
        goal_knowledge_level=goal,
        provider_constraint=_orbiter_constraint() if constrained else None,
        observation_mode_constraint="remote_orbital_spectrometry" if constrained else None,
        priority=priority,
    )).created_id


def test_campaign_scope_is_multi_cell_multi_resource_and_never_changes_outside_scope():
    app = build_game_application()
    sim = app._simulation
    cells = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MOON_CELL_NEARSIDE_MARE)
    resources = (ids.REGOLITH, ids.WATER)
    outside = (ids.MOON_CELL_EQUATORIAL_HIGHLANDS, ids.REGOLITH)
    outside_before = sim.survey.progress(*outside)

    campaign_id = _start_campaign(app, cells, resources)
    campaign = sim.survey.campaigns[campaign_id]
    assert campaign.target_pairs() == tuple(
        (cell, resource) for cell in sorted(cells, key=str) for resource in sorted(resources, key=str)
    )
    bundles = sim.survey.execution_requirement_bundles(sim.day)
    assert {bundle.owner_id for bundle in bundles} == {campaign.id}
    assert len(bundles) == 4

    app.execute(AdvanceTime(1))
    assert sim.survey.progress(*outside) == pytest.approx(outside_before)
    assert all(sim.survey.progress(cell, resource) > 0 for cell in cells for resource in resources)


def test_completed_targets_leave_demand_and_capacity_reallocates_without_overshoot():
    app = build_game_application()
    sim = app._simulation
    first = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    second = (ids.MOON_CELL_NEARSIDE_MARE, ids.REGOLITH)
    campaign_id = _start_campaign(app, (first[0], second[0]), (ids.REGOLITH,))
    campaign = sim.survey.campaigns[campaign_id]
    threshold = sim.survey.targets[first].thresholds[0]
    first_bundle = sim.survey.execution_bundle_id(campaign.id, *first)
    second_bundle = sim.survey.execution_bundle_id(campaign.id, *second)

    # A target that has already reached the campaign goal contributes no demand,
    # so the shared Survey capacity is immediately available to the remainder.
    sim.survey.knowledge_progress[first] = threshold
    bundles = {bundle.id for bundle in sim.survey.execution_requirement_bundles(sim.day)}
    assert first_bundle not in bundles
    assert second_bundle in bundles
    allocation = sim.tick_decision_projection().allocations.execution
    assert allocation.allocated(second_bundle) == pytest.approx(1.0)

    # The final partial day is capped at the goal threshold rather than overshooting.
    sim.survey.knowledge_progress[second] = threshold - 0.5
    allocation = sim.tick_decision_projection().allocations.execution
    assert allocation.allocated(second_bundle) == pytest.approx(0.5 / 8.0)
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(*second) == pytest.approx(threshold)
    assert sim.survey.knowledge_level(*second) == KnowledgeLevel.PRESENCE_PROBABILITY


def test_campaign_completes_only_when_all_targets_reach_goal_and_retains_identity():
    app = build_game_application()
    sim = app._simulation
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    campaign_id = _start_campaign(app, (key[0],), (key[1],))
    app.execute(AdvanceTime(3))
    campaign = sim.survey.campaigns[campaign_id]
    assert campaign.control_state is SurveyCampaignControlState.COMPLETED
    assert sim.survey.unfinished_targets(campaign) == ()
    assert sim.survey.execution_requirement_bundles(sim.day) == ()


def test_goal_cap_and_precision_are_provider_mode_authoritative():
    app = build_game_application()
    sim = app._simulation
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    campaign_id = _start_campaign(app, (key[0],), (key[1],), goal=2)
    app.execute(AdvanceTime(8))
    assert sim.survey.knowledge_level(*key) == KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
    assert sim.survey.visible_potential_precision_fraction(*key) == pytest.approx(0.35)
    assert sim.survey.campaigns[campaign_id].control_state is SurveyCampaignControlState.COMPLETED

    blocked_id = _start_campaign(app, (ids.MOON_CELL_NEARSIDE_MARE,), (ids.REGOLITH,), goal=3)
    blocked = sim.survey.campaigns[blocked_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(blocked, day=sim.day)
    assert candidate is None
    assert "survey_candidate_unavailable" in blockers
    assert any("survey_provider_limit" in blocker for blocker in blockers)


def test_equivalent_candidates_auto_resolve_by_stable_key_independent_of_registration_order():
    def selected(reverse: bool):
        app = build_game_application()
        sim = app._simulation
        source = ids.LUNAR_RESOURCE_SURVEY_ORBITER
        mode = sim.survey.provider(source).observation_modes[0]
        rows = [
            (DefinitionId("test.provider.a"), SurveyProviderSpec(DefinitionId("test.provider.a"), SurveyProviderSourceKind.FACILITY, source, (mode,))),
            (DefinitionId("test.provider.b"), SurveyProviderSpec(DefinitionId("test.provider.b"), SurveyProviderSourceKind.FACILITY, source, (mode,))),
        ]
        if reverse:
            rows.reverse()
        sim.survey.providers = dict(rows)
        cid = _start_campaign(app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.REGOLITH,), constrained=False)
        candidate, blockers = sim.survey.resolve_campaign_candidate(sim.survey.campaigns[cid], day=sim.day)
        assert blockers == ()
        assert candidate is not None
        return candidate.provider_definition_id

    assert selected(False) == selected(True) == DefinitionId("test.provider.a")


def test_strategically_distinct_candidates_require_decision_and_do_not_arbitrarily_execute():
    app = build_game_application()
    sim = app._simulation
    sim.transport.add_fleet_units(
        ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT, 1, ids.LUNAR_ORBIT, day=sim.day
    )
    app.execute(SetSurveyProviderFleetQuantity(
        str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT),
        str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 1,
    ))
    campaign_id = _start_campaign(
        app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.REGOLITH,), constrained=False
    )
    campaign = sim.survey.campaigns[campaign_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(campaign, day=sim.day)
    assert candidate is None
    assert blockers == ("survey_decision_required",)
    assert sim.survey.execution_requirement_bundles(sim.day) == ()

    row = next(c for c in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).campaigns if c.id == campaign_id)
    assert "survey_decision_required" in row.blockers
    assert len([candidate for candidate in row.candidates if candidate.viable]) >= 2
    assert {candidate.provider_source_kind for candidate in row.candidates if candidate.viable} >= {"facility", "fleet"}


def test_explicit_constraint_failure_never_falls_back_to_other_provider():
    app = build_game_application()
    sim = app._simulation
    source_id = DefinitionId("test.facility.earth_only_survey")
    provider_id = DefinitionId("test.provider.earth_only_survey")
    sim.facilities.definitions[source_id] = FacilityDef(source_id, "Earth survey")
    sim.facilities.install(source_id, ids.LEO)
    mode = SurveyObservationModeSpec(
        "same_body_only", 5.0, SurveyReachSpec(SurveyReachScope.SAME_BODY),
        KnowledgeLevel.PRESENCE_PROBABILITY, 0.2, 0.1,
    )
    sim.survey.providers[provider_id] = SurveyProviderSpec(
        provider_id, SurveyProviderSourceKind.FACILITY, source_id, (mode,)
    )
    campaign_id = app.execute(StartSurvey(
        (str(ids.MOON_CELL_FARSIDE_HIGHLANDS),), (str(ids.REGOLITH),), 1,
        SurveyProviderConstraintInput(str(provider_id), str(ids.LEO)), "same_body_only",
    )).created_id
    campaign = sim.survey.campaigns[campaign_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(campaign, day=sim.day)
    assert candidate is None
    assert any("reach:body" in blocker for blocker in blockers)
    assert sim.survey.execution_requirement_bundles(sim.day) == ()


def test_pause_suspends_campaign_demand_without_releasing_provider_fleet_commitment():
    app = build_game_application()
    sim = app._simulation
    sim.transport.add_fleet_units(
        ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT, 1, ids.LUNAR_ORBIT, day=sim.day
    )
    assignment_id = app.execute(SetSurveyProviderFleetQuantity(
        str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT),
        str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 1,
    )).created_id
    assert assignment_id is not None
    campaign_id = app.execute(StartSurvey(
        (str(ids.MOON_CELL_FARSIDE_HIGHLANDS),), (str(ids.REGOLITH),), 1,
        SurveyProviderConstraintInput(str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT)),
        "fleet_remote_mapping",
    )).created_id
    assignment = next(iter(sim.survey.provider_assignments.values()))
    commitment_id = assignment.fleet_commitment_ref
    before = sim.survey.progress(ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)

    app.execute(PauseSurvey(campaign_id))
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH) == pytest.approx(before)
    assert sim.transport.fleet_commitment_snapshot(commitment_id) is not None
    assert sim.survey.provider_assignment_quantity(assignment.id) == 1

    app.execute(ResumeSurvey(campaign_id))
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH) > before


def test_remote_survey_does_not_require_surface_location():
    app = build_game_application()
    sim = app._simulation
    cell_id = ids.MOON_CELL_FARSIDE_HIGHLANDS
    assert sim.graph.owner_of_cell(cell_id) is None
    campaign_id = _start_campaign(app, (cell_id,), (ids.REGOLITH,))
    candidate, blockers = sim.survey.resolve_campaign_candidate(sim.survey.campaigns[campaign_id], day=sim.day)
    assert blockers == ()
    assert candidate is not None
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(cell_id, ids.REGOLITH) > 0


def test_campaign_update_replaces_scope_goal_and_constraints():
    app = build_game_application()
    sim = app._simulation
    campaign_id = _start_campaign(app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.REGOLITH,))
    app.execute(UpdateSurvey(
        campaign_id,
        (str(ids.MOON_CELL_FARSIDE_HIGHLANDS), str(ids.MOON_CELL_NEARSIDE_MARE)),
        (str(ids.REGOLITH), str(ids.WATER)),
        2,
        None,
        None,
    ))
    campaign = sim.survey.campaigns[campaign_id]
    assert set(campaign.target_cell_ids) == {ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MOON_CELL_NEARSIDE_MARE}
    assert set(campaign.resource_ids) == {ids.REGOLITH, ids.WATER}
    assert campaign.goal_knowledge_level == KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
    assert campaign.provider_constraint is None
    assert campaign.observation_mode_constraint is None


def test_knowledge_consumers_depend_on_typed_requirement_not_campaign_internal_state():
    app = build_game_application()
    sim = app._simulation
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    requirement = KnowledgeRequirement(key[0], key[1], KnowledgeLevel.PRESENCE_PROBABILITY)
    assert sim.survey.knowledge_requirement_failures(requirement)
    campaign_id = _start_campaign(app, (key[0],), (key[1],))
    assert campaign_id in sim.survey.campaigns
    assert sim.survey.knowledge_requirement_failures(requirement)
    sim.survey.knowledge_progress[key] = sim.survey.targets[key].thresholds[0]
    assert sim.survey.knowledge_requirement_failures(requirement) == ()


def test_campaign_projection_is_reused_within_query_and_canonical_day(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    campaign_id = _start_campaign(
        app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.REGOLITH,)
    )
    seen = []
    original = sim.survey.campaign_projection

    def tracked(campaign, *, day=0):
        projection = original(campaign, day=day)
        if campaign.id == campaign_id:
            seen.append(projection)
        return projection

    monkeypatch.setattr(sim.survey, "campaign_projection", tracked)

    app.query(GetSurveys(str(ids.LUNAR_ORBIT)))
    assert seen
    assert len({id(projection) for projection in seen}) == 1

    seen.clear()
    app.execute(AdvanceTime(1))
    assert seen
    assert len({id(projection) for projection in seen}) == 1
