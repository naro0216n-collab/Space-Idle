"""Cross-domain remote observation contract on an unoperated physical world."""

from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    GetSurveys,
    StartSurvey,
    SurveyProviderConstraintInput,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.exploration_models import KnowledgeLevel, SurveyCampaignControlState
from space_idle.spatial import AtmosphereField, GravityField, IlluminationField, ThermalField


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

    app.execute(AdvanceTime(8))
    assert campaign.control_state is SurveyCampaignControlState.COMPLETED
    assert sim.survey.knowledge_level(cell, resource) == KnowledgeLevel.PRESENCE_PROBABILITY
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


def test_martian_geography_resolves_local_illumination_and_own_atmosphere():
    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    environment = sim.facilities.environment

    assert graph.owner_of_cell(ids.MARS_CELL_EQUATORIAL_PLAIN) is None
    assert set(graph.surface_cells[ids.MARS_CELL_EQUATORIAL_PLAIN].neighbor_ids) == {
        ids.MARS_CELL_NORTHERN_BASIN, ids.MARS_CELL_POLAR_HIGHLANDS,
    }
    atmosphere = environment.require(ids.MARS_CELL_EQUATORIAL_PLAIN, AtmosphereField)
    assert atmosphere.pressure_pa == pytest.approx(610.0)
    assert environment.require(ids.MARS_CELL_EQUATORIAL_PLAIN, GravityField).local_acceleration_m_s2 == pytest.approx(3.71)
    equatorial = environment.require(ids.MARS_CELL_EQUATORIAL_PLAIN, IlluminationField)
    polar = environment.require(ids.MARS_CELL_POLAR_HIGHLANDS, IlluminationField)
    assert equatorial.solar_flux_w_m2 == pytest.approx(polar.solar_flux_w_m2)
    assert equatorial.availability > polar.availability
    assert environment.require(ids.MARS_CELL_POLAR_HIGHLANDS, ThermalField).nominal_temperature_k < environment.require(
        ids.MARS_CELL_EQUATORIAL_PLAIN, ThermalField,
    ).nominal_temperature_k
    assert environment.require(ids.MARS_ORBIT, AtmosphereField).pressure_pa == pytest.approx(0)
