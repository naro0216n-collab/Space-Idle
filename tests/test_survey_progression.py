from __future__ import annotations

from space_idle import GetSurveys, build_game_application


def test_survey_stops_at_provider_knowledge_limit_and_reveals_comparison_value():
    app = build_game_application()
    sim = app._simulation

    candidate = None
    for provider_id in sorted(sim.graph.operational_node_ids(), key=str):
        for key, target in sorted(
            sim.survey.targets.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            limit = sim.survey.reachable_knowledge_level(provider_id, key[0], day=sim.day)
            if (
                sim.survey.start_blockers(provider_id, *key, sim.day) == ()
                and 0 < limit < len(target.thresholds)
            ):
                candidate = (provider_id, key, target, limit)
                break
        if candidate is not None:
            break

    assert candidate is not None, "base content must expose a provider-limited survey target"
    provider_id, key, target, limit = candidate

    sim.survey.start(provider_id, *key, priority=80, day=sim.day)
    assert key in sim.survey.campaigns
    assert sim.survey.campaigns[key].target_knowledge_level == limit

    for _ in range(200):
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
