from __future__ import annotations

from space_idle import GetSurveys, build_game_application
from space_idle.content import base_ids as ids


def test_orbital_survey_stops_at_provider_knowledge_limit_and_reveals_comparison_value():
    app = build_game_application()
    sim = app._simulation
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.WATER)
    target = sim.survey.targets[key]
    limit = sim.survey.reachable_knowledge_level(
        ids.LUNAR_ORBIT, key[0], day=sim.day
    )

    assert sim.survey.start_blockers(ids.LUNAR_ORBIT, *key, sim.day) == ()
    assert 0 < limit < len(target.thresholds)

    sim.survey.start(ids.LUNAR_ORBIT, *key, priority=80, day=sim.day)
    assert key in sim.survey.campaigns
    assert sim.survey.campaigns[key].target_knowledge_level == limit

    for _ in range(100):
        if key not in sim.survey.campaigns:
            break
        sim.advance_days(1)
    else:
        raise AssertionError("survey did not reach provider knowledge limit")

    target_threshold = target.thresholds[limit - 1]
    assert sim.survey.progress(*key) == target_threshold
    assert sim.survey.knowledge_level(*key) == limit
    assert not sim.survey.is_complete(*key)
    assert sim.survey.visible_potential(*key) is not None
    assert sim.survey.start_blockers(ids.LUNAR_ORBIT, *key, sim.day) == (
        "survey_provider_limit",
    )

    row = next(
        item for item in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).items
        if item.cell_id == str(ids.MOON_CELL_FARSIDE_HIGHLANDS) and item.resource_id == str(ids.WATER)
    )
    assert row.complete is False
    assert row.active is False
    assert row.can_start is False
    assert row.target_knowledge_level == limit
    assert row.target_threshold == target_threshold
    assert row.progress_fraction == 1.0
    assert row.blockers == ("survey_provider_limit",)
