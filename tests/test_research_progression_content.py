from __future__ import annotations

from space_idle import GetResearch, build_game_application
from space_idle.content import base_ids as ids
from space_idle.content.base_construction import build_construction_recipes
from space_idle.content.base_facilities import build_facility_definitions
from space_idle.content.base_progression import build_survey_providers
from space_idle.content.base_research import build_research_definitions, build_research_providers


def test_initial_research_base_has_ground_and_orbital_assets():
    app = build_game_application()
    view = app.query(GetResearch())
    provider_locations = {
        row.facility_definition_id: row.location_id
        for row in view.providers
    }

    assert provider_locations[str(ids.EARTH_RESEARCH_LAB)] == str(ids.EARTH)
    assert provider_locations[str(ids.EARTH_OBSERVATION_SATELLITE)] == str(ids.LEO)
    assert view.generation_points_per_day > 0
    assert view.storage_capacity_points > 0


def test_research_provider_progression_expands_generation_and_storage_without_gating_total_cost():
    providers = build_research_providers()
    research = build_research_definitions()

    assert all(
        spec.generation_points_per_day >= 0 and spec.storage_capacity_points >= 0
        for provider in providers.values()
        for spec in provider.levels
    )
    assert all(not hasattr(provider, "research_ids") for provider in providers.values())
    assert any(
        definition.research_point_cost > 0
        for definition in research.values()
    )

def test_research_assets_get_more_productive_with_higher_technical_tiers():
    providers = build_research_providers()
    sequence = (
        ids.EARTH_OBSERVATION_SATELLITE,
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
        ids.CREWED_ORBITAL_LABORATORY,
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
    )
    tiers = [providers[facility_id].tier for facility_id in sequence]
    generation = [providers[facility_id].level_spec(1).generation_points_per_day for facility_id in sequence]
    storage = [providers[facility_id].level_spec(1).storage_capacity_points for facility_id in sequence]

    assert tiers == sorted(tiers)
    assert all(later > earlier for earlier, later in zip(generation, generation[1:]))
    assert all(later > earlier for earlier, later in zip(storage, storage[1:]))


def test_robotic_geology_station_contributes_to_both_survey_and_research():
    assert ids.ROBOTIC_GEOLOGY_STATION in build_research_providers()
    assert ids.ROBOTIC_GEOLOGY_STATION in build_survey_providers()


def test_research_facility_construction_is_unlocked_by_concrete_technologies():
    recipes = build_construction_recipes()
    expected_unlocks = {
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM: ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS,
        ids.CREWED_ORBITAL_LABORATORY: ids.TECH_CREWED_ORBITAL_RESEARCH,
        ids.ROBOTIC_GEOLOGY_STATION: ids.TECH_ROBOTIC_FIELD_GEOLOGY,
        ids.SAMPLE_ANALYSIS_LABORATORY: ids.TECH_SAMPLE_ANALYSIS_SYSTEMS,
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY: ids.TECH_VACUUM_REGOLITH_PROCESS_RESEARCH,
    }
    for facility_id, technology_id in expected_unlocks.items():
        assert technology_id in recipes[facility_id].prerequisite_technologies


def test_research_names_describe_technology_and_facility_function_not_abstract_tiers():
    facilities = build_facility_definitions()
    research = build_research_definitions()
    research_facilities = (
        ids.EARTH_RESEARCH_LAB,
        ids.EARTH_OBSERVATION_SATELLITE,
        ids.MICROGRAVITY_EXPERIMENT_PLATFORM,
        ids.CREWED_ORBITAL_LABORATORY,
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.SAMPLE_ANALYSIS_LABORATORY,
        ids.VACUUM_REGOLITH_PROCESS_LABORATORY,
    )
    for facility_id in research_facilities:
        name = facilities[facility_id].display_name.lower()
        assert "tier" not in name
        assert "月面研究所" not in name
    for definition in research.values():
        name = definition.display_name.lower()
        assert "tier" not in name
        assert "月面" not in name
