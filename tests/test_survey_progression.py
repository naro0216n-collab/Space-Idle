from __future__ import annotations

from space_idle import GetSurveys, build_game_application
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.shared import DefinitionId
from space_idle.survey import SurveyCoverage, SurveyProviderSpec, SurveyTarget


def test_survey_stops_at_provider_knowledge_limit_and_reveals_comparison_value():
    app = build_game_application()
    sim = app._simulation

    # Use the real Application/Simulation integration, but make the knowledge
    # ceiling and thresholds explicit test data instead of depending on the
    # current Content balance or on whichever target happens to be limited.
    provider_definition_id = DefinitionId("test.facility.provider_limited_survey")
    sim.facilities.definitions[provider_definition_id] = FacilityDef(
        provider_definition_id, "Provider-limited survey fixture"
    )
    sim.facilities.install(provider_definition_id, ids.EARTH)
    provider_id = ids.EARTH
    cell = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL]
    resource_id = DefinitionId("test.resource.provider_limited_survey")
    key = (cell.id, resource_id)
    target = SurveyTarget(cell.id, resource_id, (1.0, 2.0, 3.0, 4.0), 0.5)
    limit = 2
    sim.survey.targets[key] = target
    sim.survey.providers = {
        provider_definition_id: SurveyProviderSpec(
            provider_definition_id,
            points_per_day=100.0,
            coverage=SurveyCoverage.BODY_REMOTE,
            max_knowledge_level=limit,
        )
    }

    assert sim.survey.start_blockers(provider_id, *key, sim.day) == ()
    assert sim.survey.reachable_knowledge_level(provider_id, key[0], day=sim.day) == limit

    sim.survey.start(provider_id, *key, priority=4, day=sim.day)
    assert key in sim.survey.campaigns
    assert sim.survey.campaigns[key].target_knowledge_level == limit

    sim.advance_days(1)
    assert key not in sim.survey.campaigns

    target_threshold = target.thresholds[limit - 1]
    assert sim.survey.progress(*key) == target_threshold
    assert sim.survey.knowledge_level(*key) == limit
    assert not sim.survey.is_complete(*key)
    assert sim.survey.visible_potential(*key) is not None
    assert sim.survey.start_blockers(provider_id, *key, sim.day) == (
        "survey_provider_limit",
    )

    row = next(
        item for item in app.query(GetSurveys(str(provider_id))).items
        if item.cell_id == str(key[0]) and item.resource_id == str(key[1])
    )
    assert row.complete is False
    assert row.active is False
    assert row.can_start is False
    assert row.target_knowledge_level == limit
    assert row.target_threshold == target_threshold
    assert row.progress_fraction == 1.0
    assert row.blockers == ("survey_provider_limit",)
