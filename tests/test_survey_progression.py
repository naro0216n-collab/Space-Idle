from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime, ApplicationError, GetSurveys, PauseSurvey, ResumeSurvey, StartSurvey,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.shared import DefinitionId
from space_idle.survey import (
    KnowledgeLevel,
    SurveyCoverage,
    SurveyObservationModeSpec,
    SurveyProviderSourceKind,
    SurveyProviderSpec,
    SurveyTarget,
)


def test_survey_stops_at_selected_provider_mode_knowledge_limit_and_reveals_precision():
    app = build_game_application()
    sim = app._simulation

    provider_source_id = DefinitionId("test.facility.provider_limited_survey")
    provider_id = DefinitionId("test.survey_provider.provider_limited_survey")
    mode_id = "test_estimation_mode"
    sim.facilities.definitions[provider_source_id] = FacilityDef(
        provider_source_id, "Provider-limited survey fixture"
    )
    sim.facilities.install(provider_source_id, ids.LUNAR_ORBIT)
    cell = sim.graph.surface_cells[ids.MOON_CELL_FARSIDE_HIGHLANDS]
    resource_id = ids.REGOLITH
    key = (cell.id, resource_id)
    target = SurveyTarget(cell.id, resource_id, (1.0, 2.0, 3.0), 0.5)
    limit = KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
    mode = SurveyObservationModeSpec(
        mode_id,
        100.0,
        SurveyCoverage.BODY_REMOTE,
        limit,
        estimate_uncertainty_fraction=0.31,
        measurement_precision_fraction=0.07,
    )
    sim.survey.targets[key] = target
    sim.survey.providers = {
        provider_id: SurveyProviderSpec(
            provider_id,
            SurveyProviderSourceKind.FACILITY,
            provider_source_id,
            (mode,),
        )
    }

    assert sim.survey.start_blockers(
        ids.LUNAR_ORBIT, provider_id, mode_id, *key, limit, sim.day
    ) == ()
    assert sim.survey.reachable_knowledge_level(
        ids.LUNAR_ORBIT, provider_id, mode_id, key[0], day=sim.day
    ) == limit

    app.execute(StartSurvey(
        str(ids.LUNAR_ORBIT), str(provider_id), mode_id, str(key[0]), str(key[1]), int(limit), priority=4
    ))
    assert key in sim.survey.campaigns
    assert sim.survey.campaigns[key].target_knowledge_level == limit

    sim.advance_days(1)
    assert key not in sim.survey.campaigns

    target_threshold = target.thresholds[int(limit) - 1]
    assert sim.survey.progress(*key) == target_threshold
    assert sim.survey.knowledge_level(*key) == limit
    assert not sim.survey.is_complete(*key)
    assert sim.survey.visible_potential(*key) is not None
    assert sim.survey.visible_potential_precision_fraction(*key) == 0.31
    assert sim.survey.start_blockers(
        ids.LUNAR_ORBIT,
        provider_id,
        mode_id,
        *key,
        KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL,
        sim.day,
    ) == ("survey_provider_limit",)

    row = next(
        item for item in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).items
        if item.cell_id == str(key[0]) and item.resource_id == str(key[1])
    )
    assert row.complete is False
    assert row.active is False
    assert row.can_start is False
    assert row.target_knowledge_level == int(limit)
    assert row.target_threshold == target_threshold
    assert row.progress_fraction == 1.0
    assert row.start_options == ()


def test_fleet_backed_survey_commitment_releases_on_pause_boundary_and_recommits_on_resume():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT
    provider_id = ids.LUNAR_FLEET_SURVEY_PROVIDER
    mode_id = "fleet_remote_mapping"
    first_key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    second_key = (ids.MOON_CELL_NEARSIDE_MARE, ids.REGOLITH)

    sim.transport.add_fleet_units(vehicle_id, 1, ids.LUNAR_ORBIT, day=sim.day)
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 1

    app.execute(StartSurvey(
        str(ids.LUNAR_ORBIT), str(provider_id), mode_id,
        str(first_key[0]), str(first_key[1]), int(KnowledgeLevel.PRESENCE_PROBABILITY),
    ))
    campaign = sim.survey.campaigns[first_key]
    commitment_id = campaign.fleet_commitment_ref
    assert commitment_id is not None
    commitment = sim.transport.fleet_commitment(commitment_id)
    assert commitment is not None
    assert commitment.quantity == 1
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 0

    with pytest.raises(ApplicationError, match="fleet_units"):
        app.execute(StartSurvey(
            str(ids.LUNAR_ORBIT), str(provider_id), mode_id,
            str(second_key[0]), str(second_key[1]), int(KnowledgeLevel.PRESENCE_PROBABILITY),
        ))

    progress_before_pause = sim.survey.progress(*first_key)
    app.execute(PauseSurvey(str(first_key[0]), str(first_key[1])))
    assert campaign.fleet_commitment_ref == commitment_id
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 0

    app.execute(AdvanceTime(1))
    assert campaign.paused is True
    assert campaign.fleet_commitment_ref is None
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 1
    assert sim.survey.progress(*first_key) == pytest.approx(progress_before_pause)

    app.execute(ResumeSurvey(str(first_key[0]), str(first_key[1])))
    assert campaign.paused is False
    assert campaign.fleet_commitment_ref is not None
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 0


def test_survey_shared_provider_capacity_only_reallocates_among_requested_campaigns():
    app = build_game_application()
    sim = app._simulation
    provider_id = ids.LUNAR_RESOURCE_SURVEY_ORBITER
    mode_id = "remote_orbital_spectrometry"
    requested = (
        (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH),
        (ids.MOON_CELL_NEARSIDE_MARE, ids.REGOLITH),
    )
    for cell_id, resource_id in requested:
        app.execute(StartSurvey(
            str(ids.LUNAR_ORBIT), str(provider_id), mode_id,
            str(cell_id), str(resource_id), int(KnowledgeLevel.PRESENCE_PROBABILITY),
        ))

    assert set(sim.survey.campaigns) == set(requested)
    decision = sim.tick_decision_projection()
    allocations = decision.allocations.execution
    allocated = sum(
        allocations.allocated(sim.survey.execution_bundle_id(*key))
        for key in requested
    )
    capacity = sim.survey.provider_capacity_at(provider_id, ids.LUNAR_ORBIT, day=sim.day)
    assert allocated <= capacity + 1e-12
    assert capacity == pytest.approx(1.0)

    app.execute(AdvanceTime(1))
    assert set(sim.survey.campaigns) == set(requested)
    assert len(sim.survey.campaigns) == 2
