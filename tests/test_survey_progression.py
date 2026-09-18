from __future__ import annotations

import pytest

from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError

from space_idle import (
    AdvanceTime, ApplicationError, GetSurveys, PauseSurvey, ResumeSurvey,
    SetSurveyProviderFleetQuantity, StartSurvey,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.content import base_requirements as req
from space_idle.shared import DefinitionId
from space_idle.survey import (
    KnowledgeLevel,
    SurveyObservationModeSpec,
    SurveyReachScope,
    SurveyReachSpec,
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
        SurveyReachSpec(SurveyReachScope.SAME_BODY),
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
    estimated = sim.survey.visible_potential(*key)
    actual = sim.survey.actual_potential(*key)
    assert estimated is not None
    assert estimated != pytest.approx(actual)
    assert abs(estimated - actual) <= actual * 0.31 + 1e-12
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


def test_survey_configuration_rejects_mode_capability_missing_from_provider_source():
    app = build_game_application()
    sim = app._simulation
    provider_id = ids.LUNAR_RESOURCE_SURVEY_ORBITER
    provider = sim.survey.provider(provider_id)
    mode = provider.observation_modes[0]
    invalid_mode = SurveyObservationModeSpec(
        mode.id,
        mode.survey_rate,
        mode.reach,
        mode.max_knowledge_level,
        mode.estimate_uncertainty_fraction,
        mode.measurement_precision_fraction,
        site_requirements=mode.site_requirements,
        required_source_capabilities=frozenset(("capability.not_supplied",)),
        minimum_source_units=mode.minimum_source_units,
    )
    sim.survey.providers[provider_id] = SurveyProviderSpec(
        provider.id,
        provider.source_kind,
        provider.source_definition_id,
        (invalid_mode,),
        capacity_units_per_source_per_day=provider.capacity_units_per_source_per_day,
    )

    with pytest.raises(
        ConfigurationError,
        match="requires capabilities not supplied by its provider source",
    ):
        validate_simulation_configuration(sim)


def test_fleet_backed_survey_provider_assignment_owns_fleet_independently_of_campaign_pause():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT
    provider_id = ids.LUNAR_FLEET_SURVEY_PROVIDER
    mode_id = "fleet_remote_mapping"
    first_key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    second_key = (ids.MOON_CELL_NEARSIDE_MARE, ids.REGOLITH)

    unavailable = next(
        row for row in app.query(GetSurveys(str(ids.LUNAR_ORBIT))).provider_fleet
        if row.provider_definition_id == str(provider_id)
        and row.vehicle_definition_id == str(vehicle_id)
    )
    assert unavailable.committed_units == 0
    assert unavailable.free_units == 0
    assert unavailable.blockers == ("fleet_unavailable",)
    assert unavailable.can_set_quantity is False

    sim.transport.add_fleet_units(vehicle_id, 1, ids.LUNAR_ORBIT, day=sim.day)
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 1

    with pytest.raises(ApplicationError, match="insufficient free fleet units"):
        app.execute(SetSurveyProviderFleetQuantity(
            str(provider_id), str(ids.LUNAR_ORBIT), str(vehicle_id), 2
        ))
    assert sim.survey.provider_assignments == {}
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 1

    result = app.execute(SetSurveyProviderFleetQuantity(
        str(provider_id), str(ids.LUNAR_ORBIT), str(vehicle_id), 1
    ))
    assignment_id = result.created_id
    assert assignment_id is not None
    assert len(sim.survey.provider_assignments) == 1
    repeated_id = app.execute(SetSurveyProviderFleetQuantity(
        str(provider_id), str(ids.LUNAR_ORBIT), str(vehicle_id), 1
    )).created_id
    assert repeated_id == assignment_id
    assert len(sim.survey.provider_assignments) == 1
    assignment = sim.survey.provider_assignments[next(
        key for key in sim.survey.provider_assignments if str(key) == assignment_id
    )]
    commitment = sim.transport.fleet_commitment(assignment.fleet_commitment_ref)
    assert commitment is not None
    assert commitment.quantity == 1
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 0

    for key in (first_key, second_key):
        app.execute(StartSurvey(
            str(ids.LUNAR_ORBIT), str(provider_id), mode_id,
            str(key[0]), str(key[1]), int(KnowledgeLevel.PRESENCE_PROBABILITY),
        ))
    assert set(sim.survey.campaigns) >= {first_key, second_key}
    decision = sim.tick_decision_projection()
    allocated = sum(
        decision.allocations.execution.allocated(sim.survey.execution_bundle_id(*key))
        for key in (first_key, second_key)
    )
    assert allocated <= sim.survey.provider_capacity_at(
        provider_id, ids.LUNAR_ORBIT, day=sim.day
    ) + 1e-12

    with pytest.raises(ApplicationError, match="insufficient free fleet units"):
        app.execute(SetSurveyProviderFleetQuantity(
            str(provider_id), str(ids.LUNAR_ORBIT), str(vehicle_id), 2
        ))
    assert sim.survey.provider_assignment_quantity(assignment.id) == 1

    progress_before_pause = sim.survey.progress(*first_key)
    app.execute(PauseSurvey(str(first_key[0]), str(first_key[1])))
    app.execute(AdvanceTime(1))
    assert sim.survey.campaigns[first_key].paused is True
    assert sim.transport.fleet_commitment(assignment.fleet_commitment_ref) is not None
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 0
    assert sim.survey.progress(*first_key) == pytest.approx(progress_before_pause)
    assert sim.survey.progress(*second_key) > 0.0

    app.execute(ResumeSurvey(str(first_key[0]), str(first_key[1])))
    assert sim.survey.campaigns[first_key].paused is False

    app.execute(SetSurveyProviderFleetQuantity(
        str(provider_id), str(ids.LUNAR_ORBIT), str(vehicle_id), 0
    ))
    assert sim.survey.provider_assignments == {}
    assert sim.transport.fleet_free_units(vehicle_id, ids.LUNAR_ORBIT) == 1
    assert "survey_capacity" in sim.survey.blockers(*first_key, day=sim.day)


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


def test_survey_reach_and_dynamic_site_eligibility_are_domain_authoritative_during_execution():
    app = build_game_application()
    sim = app._simulation
    provider_source_id = DefinitionId("test.facility.cross_body_survey")
    provider_id = DefinitionId("test.survey_provider.cross_body")
    mode_id = "same_system_supported_observation"
    sim.facilities.definitions[provider_source_id] = FacilityDef(
        provider_source_id, "Cross-body survey fixture", installation_requirements=req.ORBIT_SITE,
        operating_requirements=req.ORBIT_SITE,
    )
    sim.facilities.install(provider_source_id, ids.LEO)
    support_id = sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    mode = SurveyObservationModeSpec(
        mode_id,
        2.0,
        SurveyReachSpec(SurveyReachScope.SAME_SYSTEM),
        KnowledgeLevel.PRESENCE_PROBABILITY,
        estimate_uncertainty_fraction=0.2,
        measurement_precision_fraction=0.1,
        site_requirements=req.with_capabilities(req.ORBIT_SITE, "spacecraft_servicing"),
    )
    sim.survey.providers[provider_id] = SurveyProviderSpec(
        provider_id, SurveyProviderSourceKind.FACILITY, provider_source_id, (mode,)
    )
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    sim.survey.knowledge_progress[key] = 0.0

    # SAME_SYSTEM is a Content reach rule, so cross-body observation is not
    # rejected by a hard-coded same-body shortcut.
    assert sim.survey.start_blockers(
        ids.LEO, provider_id, mode_id, *key, KnowledgeLevel.PRESENCE_PROBABILITY, sim.day
    ) == ()
    app.execute(StartSurvey(
        str(ids.LEO), str(provider_id), mode_id, str(key[0]), str(key[1]),
        int(KnowledgeLevel.PRESENCE_PROBABILITY),
    ))
    before = sim.survey.progress(*key)

    # Eligibility is re-evaluated by execution, not just by start/query.
    sim.facilities.pause(support_id)
    blockers = sim.survey.blockers(*key, day=sim.day)
    assert any(row.startswith("survey_eligibility:site:") for row in blockers)
    app.execute(AdvanceTime(1))
    assert sim.survey.progress(*key) == pytest.approx(before)
