from __future__ import annotations

import pytest
import json

from space_idle import GetLocation, build_game_application
from space_idle.content import base_ids as ids
from space_idle.persistence import load_game, save_game
from space_idle.surface_infrastructure import SURFACE_DISTRIBUTION_CAPABILITY


def _snapshot(sim):
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    return sim.surface_infrastructure.snapshot(ids.EARTH, sim.facilities, power, sim.day)


def test_location_expansion_increases_aggregate_surface_infrastructure_load():
    sim = build_game_application()._simulation
    initial = _snapshot(sim)
    assert initial.demand == 0.0
    assert initial.fulfillment == 1.0

    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    one_remote = _snapshot(sim)
    assert one_remote.demand > initial.demand
    assert any(row.code == "territory_area" for row in one_remote.load_sources)

    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_INLAND)
    two_remote = _snapshot(sim)
    assert two_remote.demand > one_remote.demand


def test_surface_distribution_facility_supplies_nominal_and_available_capacity():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    before = _snapshot(sim)
    assert before.nominal_capacity == 0.0
    assert before.available_capacity == 0.0
    assert before.fulfillment == 0.0
    assert before.limiting_factors == ("surface_infrastructure",)

    facility_id = sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    supplied = _snapshot(sim)
    assert supplied.nominal_capacity == pytest.approx(1.0)
    assert supplied.available_capacity == pytest.approx(1.0)
    assert supplied.fulfillment == pytest.approx(1.0)

    sim.facilities.facilities[facility_id].maintenance_satisfaction = 0.5
    degraded = _snapshot(sim)
    assert degraded.nominal_capacity == pytest.approx(1.0)
    assert degraded.available_capacity == pytest.approx(0.5)
    assert degraded.fulfillment == pytest.approx(0.5)
    assert degraded.limiting_factors == ("surface_infrastructure",)


def test_remote_resource_opportunity_and_limiting_factor_follow_surface_infrastructure():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)

    core_only = sim.graph.surface_cells[ids.EARTH_CELL_INDUSTRIAL].resource_potential_by_resource[ids.METAL_ORE]
    constrained = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day
    )
    assert constrained == pytest.approx(core_only)
    mine = next(
        row
        for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day
        )
        if row.facility_def_id == ids.METAL_ORE_MINE
    )
    assert "surface_infrastructure" in mine.limiting_factors

    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    supplied = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day
    )
    remote = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL].resource_potential_by_resource[ids.METAL_ORE]
    assert supplied == pytest.approx(core_only + remote)


def test_location_query_exposes_surface_infrastructure_decision_state_and_improvement():
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)

    view = app.query(GetLocation(str(ids.EARTH)))
    row = view.surface_infrastructure
    assert row is not None
    assert row.demand > 0.0
    assert row.fulfillment == 0.0
    assert row.limiting_factors == ("surface_infrastructure",)
    assert str(ids.SURFACE_DISTRIBUTION_HUB) in row.improvement_facility_definition_ids


def test_surface_infrastructure_does_not_create_cell_inventory_or_logistics_nodes():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    _snapshot(sim)

    assert ids.EARTH_CELL_COASTAL not in sim.graph.operational_node_ids()
    assert all(location_id != ids.EARTH_CELL_COASTAL for location_id, _ in sim.inventory.stock)
    assert SURFACE_DISTRIBUTION_CAPABILITY in sim.facilities.capability_ids()


def test_remote_surface_facility_available_capability_uses_surface_infrastructure():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    station_id = sim.facilities.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_COASTAL,
    )
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    assert sim.facilities.active_capability_capacity_at(
        ids.EARTH, "surface_survey", sim.day
    ) > 0.0
    assert sim.facilities.available_capability_capacity_at(
        ids.EARTH, "surface_survey", power, sim.day
    ) == 0.0

    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    assert sim.facilities.available_capability_capacity_at(
        ids.EARTH, "surface_survey", power, sim.day
    ) > 0.0
    assert station_id in sim.facilities.facilities


def test_surface_map_exposes_projected_infrastructure_limit_for_cell_development():
    app = build_game_application()
    surface = app.query(__import__('space_idle').GetSurfaceMap(str(ids.EARTH_BODY)))
    coastal = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_COASTAL))
    option = next(row for row in coastal.development_options if row.location_id == str(ids.EARTH))
    assert option.blockers == ()
    assert option.projected_surface_infrastructure_demand is not None
    assert option.projected_surface_infrastructure_demand > 0.0
    assert option.projected_surface_infrastructure_fulfillment == 0.0
    assert option.limiting_factors == ("surface_infrastructure",)


def test_surface_infrastructure_is_derived_after_save_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    before = _snapshot(sim)

    path = tmp_path / "surface-infrastructure.json"
    save_game(app, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "surface_infrastructure" not in payload["state"]

    loaded, _ = load_game(path, build_game_application)
    after = _snapshot(loaded._simulation)
    assert after == before


def test_surface_gateway_handling_capability_uses_location_surface_infrastructure():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    assert sim.facilities.active_capability_capacity_at(
        ids.EARTH, "cargo_transfer", sim.day
    ) > 0.0
    assert sim.facilities.available_capability_capacity_at(
        ids.EARTH, "cargo_transfer", power, sim.day
    ) == 0.0

    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH)
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    assert sim.facilities.available_capability_capacity_at(
        ids.EARTH, "cargo_transfer", power, sim.day
    ) > 0.0
