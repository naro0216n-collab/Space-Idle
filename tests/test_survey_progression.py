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
    resource = ids.VOLATILE_BEARING_MATERIAL

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
        (str(resource), str(ids.MINERAL_FEEDSTOCK)),
        2,
        None,
        None,
    ))
    campaign = app._simulation.survey.campaigns[campaign_id]
    assert set(campaign.target_cell_ids) == {cell, ids.MOON_CELL_NEARSIDE_MARE}
    assert set(campaign.resource_ids) == {resource, ids.MINERAL_FEEDSTOCK}
    assert campaign.goal_knowledge_level == KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
    assert campaign.provider_constraint is None
    assert campaign.observation_mode_constraint is None

def test_campaign_scope_progression_reallocates_capacity_without_outside_effects_or_overshoot():
    app = build_game_application()
    sim = app._simulation
    cells = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MOON_CELL_NEARSIDE_MARE)
    resources = (ids.MINERAL_FEEDSTOCK, ids.VOLATILE_BEARING_MATERIAL)
    outside = (ids.MOON_CELL_EQUATORIAL_HIGHLANDS, ids.MINERAL_FEEDSTOCK)
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

    remaining = (cells[1], ids.MINERAL_FEEDSTOCK)
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
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MINERAL_FEEDSTOCK)
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
        app, (ids.MOON_CELL_NEARSIDE_MARE,), (ids.MINERAL_FEEDSTOCK,), goal=3
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
            app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.MINERAL_FEEDSTOCK,),
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
        app, (ids.MOON_CELL_FARSIDE_HIGHLANDS,), (ids.MINERAL_FEEDSTOCK,),
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


def test_explicit_provider_constraint_never_falls_back_to_another_provider():
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
        (str(ids.MOON_CELL_FARSIDE_HIGHLANDS),), (str(ids.MINERAL_FEEDSTOCK),), 1,
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
        (str(ids.MOON_CELL_FARSIDE_HIGHLANDS),), (str(ids.MINERAL_FEEDSTOCK),), 1,
        SurveyProviderConstraintInput(str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT)),
        "fleet_remote_mapping",
    )).created_id
    assignment = next(iter(sim.survey.provider_assignments.values()))
    commitment_id = assignment.fleet_commitment_ref
    before = sim.survey.progress(ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MINERAL_FEEDSTOCK)

    app.execute(PauseSurvey(campaign_id))
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MINERAL_FEEDSTOCK) == pytest.approx(before)
    assert sim.transport.fleet_commitment_snapshot(commitment_id) is not None
    assert sim.survey.provider_assignment_quantity(assignment.id) == 1

    app.execute(ResumeSurvey(campaign_id))
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MINERAL_FEEDSTOCK) > before




# Physical targets use the same Survey progress and owner as owned-Cell targets.
def _remote_campaign(*, goal: int) -> StartSurvey:
    return StartSurvey(
        target_cell_ids=(str(ids.MARS_CELL_POLAR_HIGHLANDS),),
        resource_ids=(str(ids.VOLATILE_BEARING_MATERIAL),),
        goal_knowledge_level=goal,
        provider_constraint=SurveyProviderConstraintInput(
            str(ids.LUNAR_RESOURCE_SURVEY_ORBITER), str(ids.LUNAR_ORBIT),
        ),
        observation_mode_constraint="interplanetary_remote_spectrometry",
    )


def test_distant_physical_survey_preserves_fleet_location_and_resource_ownership():
    app = build_game_application()
    sim = app._simulation
    cell, resource = ids.MARS_CELL_POLAR_HIGHLANDS, ids.VOLATILE_BEARING_MATERIAL
    initial_nodes = frozenset(sim.graph.operational_node_ids())
    initial_fleet = dict(sim.transport.fleet_pools)
    mode = sim.survey.observation_mode(
        ids.LUNAR_RESOURCE_SURVEY_ORBITER, "interplanetary_remote_spectrometry"
    )
    sim.technology.completed.update(mode.prerequisite_technologies)

    # One survey owner and knowledge projection, independently scoped by
    # physical body; no remotely observed Cell becomes an owned Location.
    global_view = app.query(GetSurveys())
    mars_view = app.query(GetSurveys(body_id=str(ids.MARS_BODY)))
    moon_view = app.query(GetSurveys(body_id=str(ids.MOON)))
    assert mars_view.items and moon_view.items
    assert {row.body_id for row in mars_view.items} == {str(ids.MARS_BODY)}
    assert {row.body_id for row in moon_view.items} == {str(ids.MOON)}
    assert not {row.cell_id for row in mars_view.items} & {row.cell_id for row in moon_view.items}
    assert len({row.body_id for row in global_view.items}) > 3
    assert all(row.visible_potential is None for row in mars_view.items)

    requirement = KnowledgeRequirement(cell, resource, KnowledgeLevel.PRESENCE_PROBABILITY)
    assert sim.survey.knowledge_requirement_failures(requirement)
    before = next(row for row in app.query(GetSurveys()).items
                  if row.cell_id == str(cell) and row.resource_id == str(resource))
    assert before.location_id is None
    assert before.knowledge_level == int(KnowledgeLevel.UNKNOWN)
    assert before.visible_potential is None

    campaign_id = app.execute(_remote_campaign(goal=1)).created_id
    campaign = sim.survey.campaigns[campaign_id]
    candidate, blockers = sim.survey.resolve_campaign_candidate(campaign, day=sim.day)
    assert blockers == ()
    assert candidate is not None
    assert candidate.max_knowledge_level == KnowledgeLevel.PRESENCE_PROBABILITY
    assert sim.survey.knowledge_requirement_failures(requirement)

    app.execute(AdvanceTime(8))
    assert campaign.control_state is SurveyCampaignControlState.COMPLETED
    assert sim.survey.knowledge_level(cell, resource) == KnowledgeLevel.PRESENCE_PROBABILITY
    assert sim.survey.knowledge_requirement_failures(requirement) == ()
    assert sim.survey.visible_potential(cell, resource) is None
    assert frozenset(sim.graph.operational_node_ids()) == initial_nodes
    assert dict(sim.transport.fleet_pools) == initial_fleet
    assert sim.graph.owner_of_cell(cell) is None

    after = next(row for row in app.query(GetSurveys()).items
                 if row.cell_id == str(cell) and row.resource_id == str(resource))
    assert after.knowledge_level == int(KnowledgeLevel.PRESENCE_PROBABILITY)
    assert after.location_id is None
    assert after.visible_potential is None

    beyond_mode = app.execute(_remote_campaign(goal=2)).created_id
    candidate, blockers = sim.survey.resolve_campaign_candidate(
        sim.survey.campaigns[beyond_mode], day=sim.day,
    )
    assert candidate is None
    assert any("survey_provider_limit" in code for code in blockers)
