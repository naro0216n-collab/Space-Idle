from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    ClearPopulationTarget, GetOperationalNode, PauseFacility, SetPopulationTarget,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.site import evaluate_physical_site_requirements


def test_population_life_support_and_resource_allocation_share_the_normal_day():
    app = build_game_application()
    sim = app._simulation
    initial_food = sim.inventory.amount(ids.EARTH, ids.FOOD)
    initial_water = sim.inventory.amount(ids.EARTH, ids.WATER)
    before = app.query(GetOperationalNode(str(ids.EARTH))).population
    assert before.current_count > 0
    assert before.life_support_required == before.current_count
    assert before.life_support_allocated == before.life_support_required
    assert before.housing_usable >= before.current_count
    assert sum(source.remaining_people for source in before.external_sources) > 0
    assert before.resource_demand_per_day

    sim.advance_days(1)
    after = app.query(GetOperationalNode(str(ids.EARTH))).population
    assert after.current_count == before.current_count
    assert after.deprivation_person_days == 0
    # Food is a normal Industry output, while inhabited Life Support consumes
    # an allocated Resource requirement exactly once.
    assert sim.inventory.amount(ids.EARTH, ids.FOOD) > initial_food
    empty_app = build_game_application()
    empty_app._simulation.population.groups.clear()
    empty_app._simulation.advance_days(1)
    assert sim.inventory.amount(ids.EARTH, ids.WATER) == pytest.approx(
        empty_app._simulation.inventory.amount(ids.EARTH, ids.WATER) - 0.06
    )

    farm = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == ids.FOOD_FARM)
    app.execute(PauseFacility(str(farm.id)))
    sim.inventory.stock[(ids.EARTH, ids.FOOD)] = 0.0
    population = sim.population
    sim.advance_days(1)
    group = population.groups_at(ids.EARTH)[0]
    assert group.deprivation == pytest.approx(1.0)
    assert population.crew_factor(group) < 1.0
    assert population.count_at(ids.EARTH) == before.current_count
    sim.advance_days(4)
    assert population.count_at(ids.EARTH) < before.current_count
    assert population.external_remaining == {source.id: source.remaining_people for source in before.external_sources}


def test_housing_is_physical_and_facility_removal_cannot_evict_people():
    app = build_game_application()
    sim = app._simulation
    housing = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == ids.EARTH_LIFE_SUPPORT)
    blockers = sim.projects.facility_lifecycle_registry.decommission_blockers(housing.id)
    assert any(row.code == 'population_housing' for row in blockers)
    before = sim.population.count_at(ids.EARTH)
    app.execute(PauseFacility(str(housing.id)))
    view = app.query(GetOperationalNode(str(ids.EARTH))).population
    assert view.housing_physical >= before
    assert view.housing_usable == 0
    assert view.life_support_allocated == 0
    sim.advance_days(1)
    assert sim.population.count_at(ids.EARTH) == before
    assert sim.population.groups_at(ids.EARTH)[0].deprivation > 0

    # An ambient oxygen provider is eligible by the physical atmosphere, not
    # by a planet ID; an artificial pressurized habitat supplies the alternative.
    ambient = sim.facilities.definitions[ids.EARTH_LIFE_SUPPORT]
    assert not evaluate_physical_site_requirements(
        ambient.operating_requirements, ids.EARTH, sim.day, sim.environment,
    )
    assert evaluate_physical_site_requirements(
        ambient.operating_requirements, ids.MOON_CELL_NEARSIDE_MARE, sim.day, sim.environment,
    )
    assert sim.facilities.definitions[ids.HABITAT].life_support is not None


def test_population_targets_sources_and_deprivation_are_single_save_state(tmp_path):
    app = build_game_application()
    sim = app._simulation
    node = str(ids.EARTH)
    original = sim.population.count_at(ids.EARTH)
    app.execute(SetPopulationTarget(node, original + 5))
    assert sim.population.count_at(ids.EARTH) == original
    housing = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == ids.EARTH_LIFE_SUPPORT)
    app.execute(PauseFacility(str(housing.id)))
    sim.advance_days(1)
    path = tmp_path / 'population.json'
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert loaded.query(GetOperationalNode(node)).population.desired_count == original + 5
    assert loaded._simulation.population.external_remaining == sim.population.external_remaining
    sim.advance_days(3)
    loaded._simulation.advance_days(3)
    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded.execute(ClearPopulationTarget(node))
    assert loaded.query(GetOperationalNode(node)).population.desired_count is None
    assert loaded._simulation.population.count_at(ids.EARTH) <= original
