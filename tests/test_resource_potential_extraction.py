from __future__ import annotations

import json
import pytest

from space_idle import GetLocation, GetSurfaceMap, build_game_application
from space_idle.content import base_ids as ids
from space_idle.content.base_facilities import build_facility_definitions
from space_idle.extraction_service import ExtractionService
from space_idle.facilities import FacilityBook
from space_idle.persistence import save_game
from space_idle.power import PowerSnapshot


def _resource_snapshot(sim, resource_id):
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    return next(
        row
        for row in sim.extraction.resource_snapshots(ids.EARTH, sim.facilities, power, sim.day)
        if row.resource_id == resource_id
    )


def test_extraction_does_not_consume_static_resource_potential():
    app = build_game_application()
    sim = app._simulation
    before_potential = {
        cell_id: dict(cell.resource_potential_by_resource)
        for cell_id, cell in sim.graph.surface_cells.items()
    }
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    before_stock = sim.inventory.amount(ids.EARTH, ids.AGGREGATE)
    aggregate = _resource_snapshot(sim, ids.AGGREGATE)
    assert aggregate.output_t_per_day > 0.0

    sim.extraction.advance_day(ids.EARTH, sim.facilities, sim.inventory, power, sim.day)

    assert sim.inventory.amount(ids.EARTH, ids.AGGREGATE) > before_stock
    assert {
        cell_id: dict(cell.resource_potential_by_resource)
        for cell_id, cell in sim.graph.surface_cells.items()
    } == before_potential


def test_soft_saturation_is_monotonic_with_diminishing_marginal_return():
    opportunity = 10.0
    outputs = [ExtractionService.diminishing_response(capacity, opportunity) for capacity in (1.0, 2.0, 3.0)]
    assert outputs[0] < outputs[1] < outputs[2]
    assert outputs[1] - outputs[0] > outputs[2] - outputs[1]
    assert ExtractionService.marginal_response(1.0, opportunity) > ExtractionService.marginal_response(3.0, opportunity)

    # This is soft saturation rather than a finite/hard extraction ceiling.
    assert ExtractionService.diminishing_response(1000.0, opportunity) > opportunity


def test_higher_opportunity_preserves_more_expansion_value_at_same_capacity():
    capacity = 10.0
    low = ExtractionService.diminishing_response(capacity, 5.0)
    high = ExtractionService.diminishing_response(capacity, 50.0)
    assert high > low
    assert ExtractionService.marginal_response(capacity, 50.0) > ExtractionService.marginal_response(capacity, 5.0)


def test_effective_opportunity_uses_surface_infrastructure_for_remote_cells():
    app = build_game_application()
    sim = app._simulation
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    before = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day
    )
    added = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL].resource_potential_by_resource[ids.METAL_ORE]

    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    constrained_power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    constrained = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, constrained_power, sim.day
    )
    assert constrained == pytest.approx(before)

    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    supplied_power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    supplied = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, supplied_power, sim.day
    )
    assert supplied == pytest.approx(before + added)


def test_operational_fulfillment_scales_soft_saturation_output():
    base = build_game_application()._simulation
    facilities = FacilityBook(build_facility_definitions(), base.facilities.environment)
    facility_id = facilities.install(ids.METAL_ORE_MINE, ids.EARTH)
    full_power = PowerSnapshot(0.0, 0.0, 0.0, {facility_id: 1.0}, {facility_id: 1.0})
    half_power = PowerSnapshot(0.0, 0.0, 0.0, {facility_id: 0.5}, {facility_id: 1.0})

    full = next(
        row for row in base.extraction.resource_snapshots(ids.EARTH, facilities, full_power, base.day)
        if row.resource_id == ids.METAL_ORE
    )
    half = next(
        row for row in base.extraction.resource_snapshots(ids.EARTH, facilities, half_power, base.day)
        if row.resource_id == ids.METAL_ORE
    )

    assert full.operational_fulfillment == 1.0
    assert half.operational_fulfillment == 0.5
    assert half.output_t_per_day == pytest.approx(full.output_t_per_day * 0.5)
    assert half.marginal_efficiency == pytest.approx(full.marginal_efficiency * 0.5)


def test_survey_knowledge_and_research_unlocks_do_not_change_physical_throughput():
    app = build_game_application()
    sim = app._simulation
    key = (ids.EARTH_CELL_INDUSTRIAL, ids.METAL_ORE)

    sim.survey.knowledge_progress[key] = 0.0
    unknown = _resource_snapshot(sim, ids.METAL_ORE)
    sim.survey.initialize_known(*key)
    known = _resource_snapshot(sim, ids.METAL_ORE)
    assert known == unknown

    sim.technology.unlock(ids.TECH_REGOLITH_EXCAVATION)
    after_research = _resource_snapshot(sim, ids.METAL_ORE)
    assert after_research == known


def test_new_extraction_capacity_changes_throughput_and_registration_order_does_not():
    base = build_game_application()._simulation
    definitions = build_facility_definitions()
    power = PowerSnapshot(0.0, 0.0, 0.0, {}, {})

    def resource_row(levels):
        facilities = FacilityBook(definitions, base.facilities.environment)
        for level in levels:
            facilities.install(ids.METAL_ORE_MINE, ids.EARTH, level=level)
        return next(
            row
            for row in base.extraction.resource_snapshots(ids.EARTH, facilities, power, base.day)
            if row.resource_id == ids.METAL_ORE
        )

    one = resource_row((1,))
    expanded_a = resource_row((1, 2, 3))
    expanded_b = resource_row((3, 1, 2))

    assert expanded_a.installed_nominal_capacity_t_per_day > one.installed_nominal_capacity_t_per_day
    assert expanded_a.output_t_per_day > one.output_t_per_day
    assert expanded_a == expanded_b


def test_application_queries_expose_surface_knowledge_and_extraction_decision_state():
    app = build_game_application()

    surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    industrial = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_INDUSTRIAL))
    metal = next(row for row in industrial.resources if row.resource_id == str(ids.METAL_ORE))
    assert metal.knowledge_level == 4
    assert metal.visible_potential is not None
    assert metal.visible_potential_precision_fraction == 0.0

    location = app.query(GetLocation(str(ids.EARTH)))
    extraction = next(row for row in location.extraction_resources if row.resource_id == str(ids.METAL_ORE))
    assert extraction.effective_opportunity > 0.0
    assert extraction.installed_nominal_capacity_t_per_day > 0.0
    assert 0.0 <= extraction.operational_fulfillment <= 1.0
    assert extraction.marginal_efficiency > 0.0
    assert extraction.output_t_per_day > 0.0


def test_save_persists_cell_resource_knowledge_without_extraction_deposit_state(tmp_path):
    app = build_game_application()
    path = tmp_path / "resource-potential.json"
    save_game(app, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    state = payload["state"]
    assert "extraction" not in state
    assert "survey" in state
    assert state["survey"]["knowledge_progress"]
    assert all("cell_id" in row and "resource_id" in row for row in state["survey"]["knowledge_progress"])
    assert all("location_id" not in row for row in state["survey"]["knowledge_progress"])

    serialized = json.dumps(payload, sort_keys=True)
    for retired_term in ("reserve_t", "remaining_reserve", "deposit_resource_id", "actual_concentration"):
        assert retired_term not in serialized
