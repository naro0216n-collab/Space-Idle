from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    GetSurveys,
    GetSurveyCampaignIntentPreview,
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


def test_campaign_intent_preview_uses_domain_blockers_and_update_excludes_self():
    app = build_game_application()
    completed = app.query(GetSurveyCampaignIntentPreview(
        target_cell_ids=(str(ids.EARTH_CELL_INDUSTRIAL),),
        resource_ids=(str(ids.WATER),),
        goal_knowledge_level=1,
    ))
    assert completed.can_apply is False
    assert any(blocker.code == "knowledge_goal_reached" for blocker in completed.blockers)

    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    resource = ids.WATER

    available = app.query(GetSurveyCampaignIntentPreview(
        target_cell_ids=(str(cell),),
        resource_ids=(str(resource),),
        goal_knowledge_level=1,
    ))
    assert available.can_apply is True
    assert available.blockers == ()

    campaign_id = _start_campaign(app, (cell,), (resource,), constrained=False)

    conflicting_start = app.query(GetSurveyCampaignIntentPreview(
        target_cell_ids=(str(cell),),
        resource_ids=(str(resource),),
        goal_knowledge_level=1,
    ))
    assert conflicting_start.can_apply is False
    assert any(blocker.code.startswith("campaign_scope_conflict:") for blocker in conflicting_start.blockers)

    same_campaign_update = app.query(GetSurveyCampaignIntentPreview(
        target_cell_ids=(str(cell),),
        resource_ids=(str(resource),),
        goal_knowledge_level=1,
        campaign_id=campaign_id,
    ))
    assert same_campaign_update.can_apply is True
    assert same_campaign_update.blockers == ()
    app.execute(UpdateSurvey(
        campaign_id,
        (str(cell), str(ids.MOON_CELL_NEARSIDE_MARE)),
        (str(resource), str(ids.REGOLITH)),
        2,
        None,
        None,
    ))
    campaign = app._simulation.survey.campaigns[campaign_id]
    assert set(campaign.target_cell_ids) == {cell, ids.MOON_CELL_NEARSIDE_MARE}
    assert set(campaign.resource_ids) == {resource, ids.REGOLITH}
    assert campaign.goal_knowledge_level == KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
    assert campaign.provider_constraint is None
    assert campaign.observation_mode_constraint is None

def test_campaign_scope_progression_reallocates_capacity_without_outside_effects_or_overshoot():
    app = build_game_application()
    sim = app._simulation
    cells = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MOON_CELL_NEARSIDE_MARE)
    resources = (ids.REGOLITH, ids.WATER)
    outside = (ids.MOON_CELL_EQUATORIAL_HIGHLANDS, ids.REGOLITH)
    outside_before = sim.survey.progress(*outside)

    campaign_id = _start_campaign(app, cells, resources)
    campaign = sim.survey.campaigns[campaign_id]
    expected_pairs = tuple(
        (cell, resource)
        for cell in sorted(cells, key=str)
        for resource in sorted(resources, key=str)
    )
    assert campaign.target_pairs() == expected_pairs
    bundles = sim.survey.execution_requirement_bundles(sim.day)
    assert {bundle.owner_id for bundle in bundles} == {campaign.id}
    assert len(bundles) == len(expected_pairs) == 4

    app.execute(AdvanceTime(1))
    assert sim.survey.progress(*outside) == pytest.approx(outside_before)
    assert all(sim.survey.progress(cell, resource) > 0 for cell, resource in expected_pairs)

    remaining = (cells[1], ids.REGOLITH)
    remaining_bundle = sim.survey.execution_bundle_id(campaign.id, *remaining)
    for pair in expected_pairs:
        if pair == remaining:
            continue
        target = sim.survey.targets[pair]
        sim.survey.knowledge_progress[pair] = target.thresholds[0]

    active_bundle_ids = {bundle.id for bundle in sim.survey.execution_requirement_bundles(sim.day)}
    assert active_bundle_ids == {remaining_bundle}
    allocation = sim.tick_decision_projection().allocations.execution
    assert allocation.allocated(remaining_bundle) == pytest.approx(1.0)

    threshold = sim.survey.targets[remaining].thresholds[0]
    sim.survey.knowledge_progress[remaining] = threshold - 0.5
    allocation = sim.tick_decision_projection().allocations.execution
    assert allocation.allocated(remaining_bundle) == pytest.approx(0.5 / 8.0)
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(*remaining) == pytest.approx(threshold)
    assert sim.survey.knowledge_level(*remaining) == KnowledgeLevel.PRESENCE_PROBABILITY

def test_remote_campaign_completion_respects_provider_goal_cap_and_precision():
    app = build_game_application()
    sim = app._simulation
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    assert sim.graph.owner_of_cell(key[0]) is None

    campaign_id = _start_campaign(app, (key[0],), (key[1],), goal=2)
    campaign = sim.survey.campaigns[campaign_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(campaign, day=sim.day)
    assert blockers == ()
    assert candidate is not None

    app.execute(AdvanceTime(8))
    assert campaign.control_state is SurveyCampaignControlState.COMPLETED
    assert sim.survey.unfinished_targets(campaign) == ()
    assert sim.survey.execution_requirement_bundles(sim.day) == ()
    assert sim.survey.knowledge_level(*key) == KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
    assert sim.survey.visible_potential_precision_fraction(*key) == pytest.approx(0.35)

    blocked_id = _start_campaign(
        app, (ids.MOON_CELL_NEARSIDE_MARE,), (ids.REGOLITH,), goal=3
    )
    blocked = sim.survey.campaigns[blocked_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(blocked, day=sim.day)
    assert candidate is None
    assert "survey_candidate_unavailable" in blockers
    assert any("survey_provider_limit" in blocker for blocker in blockers)

def test_candidate_arbitration_auto_resolves_only_equivalent_options_and_requires_strategic_choice():
    def selected_equivalent(reverse: bool):
        app = build_game_application()
        sim = app._simulation
        source = ids.LUNAR_RESOURCE_SURVEY_ORBITER
        mode = sim.survey.provider(source).observation_modes[0]
        rows = [
            (
                DefinitionId("test.provider.a"),
                SurveyProviderSpec(
                    DefinitionId("test.provider.a"),
                    SurveyProviderSourceKind.FACILITY, source, (mode,),
                ),
            ),
            (
                DefinitionId("test.provider.b"),
                SurveyProviderSpec(
                    DefinitionId("test.provider.b"),
                    SurveyProviderSourceKind.FACILITY, source, (mode,),
                ),
            ),
        ]
        if reverse:
            rows.reverse()
        sim.survey.providers = dict(rows)
        campaign_id = _start_campaign(
            app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.REGOLITH,),
            constrained=False,
        )
        candidate, blockers = sim.survey.resolve_campaign_candidate(
            sim.survey.campaigns[campaign_id], day=sim.day
        )
        assert blockers == ()
        assert candidate is not None
        projected = next(
            campaign for campaign in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).campaigns
            if campaign.id == campaign_id
        )
        assert len(projected.candidates) == 2
        assert projected.comparison_axes == ()
        return candidate.provider_definition_id

    assert selected_equivalent(False) == selected_equivalent(True) == DefinitionId(
        "test.provider.a"
    )

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
        app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.REGOLITH,),
        constrained=False,
    )
    campaign = sim.survey.campaigns[campaign_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(campaign, day=sim.day)
    assert candidate is None
    assert blockers == ("survey_decision_required",)
    assert sim.survey.execution_requirement_bundles(sim.day) == ()

    row = next(
        campaign for campaign in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).campaigns
        if campaign.id == campaign_id
    )
    assert any(blocker.code == "survey_decision_required" for blocker in row.blockers)
    viable = [candidate for candidate in row.candidates if candidate.viable]
    assert len(viable) >= 2
    assert {candidate.provider_source_kind for candidate in viable} >= {"facility", "fleet"}
    assert len({candidate.comparison_key for candidate in viable}) == len(viable)
    assert row.comparison_axes
    assert any(axis.differs for axis in row.comparison_axes)
    assert {axis.key for axis in row.comparison_axes} == {
        "survey_rate",
        "max_knowledge_level",
        "estimate_uncertainty_fraction",
        "measurement_precision_fraction",
        "minimum_source_units",
        "capacity_units_per_day",
    }
    for candidate in viable:
        assert candidate.observation_mode_display_name
        assert not candidate.observation_mode_display_name.startswith("base.")
        assert {value.axis_key for value in candidate.comparison_values} == {
            axis.key for axis in row.comparison_axes
        }

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
