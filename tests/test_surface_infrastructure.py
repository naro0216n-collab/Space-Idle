from __future__ import annotations

import pytest
import json

from space_idle import (
    AdvanceTime,
    DevelopSurfaceCell,
    GetLogisticsLanes,
    GetOperationalNode,
    GetProjects,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import load_game, save_game
from space_idle.surface_infrastructure import SURFACE_DISTRIBUTION_SERVICE
from space_idle.service_capacity import allocate_service_capacity


def _snapshot(sim, maintenance_factors=None):
    physical = sim.power.physical_snapshot(ids.EARTH, sim.facilities, sim.day)
    power = sim.power.resolve_snapshot(physical, maintenance_factors)
    request = sim.surface_infrastructure.service_request(ids.EARTH)
    key = (ids.EARTH, sim.surface_infrastructure.service_type)
    nominal = sim.facilities.nominal_service_capacity_at(ids.EARTH, key[1], sim.day)
    enabled = sim.surface_infrastructure.provider_available_capacity(
        ids.EARTH, sim.facilities, power, sim.day
    )
    plan = allocate_service_capacity(
        (request,), nominal_supply={key: nominal}, enabled_supply={key: enabled}
    )
    return sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day, allocation_plan=plan
    )


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

    facility_id = sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    supplied = _snapshot(sim)
    assert supplied.nominal_capacity > 0.0
    assert supplied.available_capacity == pytest.approx(supplied.nominal_capacity)
    assert supplied.fulfillment == pytest.approx(
        min(1.0, supplied.available_capacity / supplied.demand)
    )

    degraded = _snapshot(sim, {facility_id: 0.5})
    assert degraded.nominal_capacity == pytest.approx(supplied.nominal_capacity)
    assert degraded.available_capacity == pytest.approx(supplied.available_capacity * 0.5)
    assert degraded.fulfillment == pytest.approx(
        min(1.0, degraded.available_capacity / degraded.demand)
    )
    assert degraded.fulfillment < supplied.fulfillment
    assert degraded.limiting_factors == ("surface_infrastructure",)


def test_remote_resource_opportunity_and_limiting_factor_follow_surface_infrastructure():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]

    core_only = sim.graph.surface_cells[ids.EARTH_CELL_INDUSTRIAL].resource_potential_by_resource[ids.METAL_ORE]
    constrained = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day,
        decision.allocations.services,
    )
    assert constrained == pytest.approx(core_only)
    mine = next(
        row
        for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day,
            decision.allocations.services,
        )
        if row.facility_def_id == ids.METAL_ORE_MINE
    )
    assert "surface_infrastructure" in mine.limiting_factors

    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    supplied = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day,
        decision.allocations.services,
    )
    remote = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL].resource_potential_by_resource[ids.METAL_ORE]
    assert supplied == pytest.approx(core_only + remote)


def test_location_query_exposes_surface_infrastructure_decision_state_and_improvement():
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)

    view = app.query(GetOperationalNode(str(ids.EARTH)))
    row = view.surface_infrastructure
    assert row is not None
    assert row.requested_capacity > 0.0
    assert row.fulfillment == 0.0
    assert row.limiting_factors == ("surface_infrastructure",)
    assert str(ids.SURFACE_DISTRIBUTION_HUB) in row.improvement_facility_definition_ids


def test_surface_infrastructure_does_not_create_cell_inventory_or_logistics_nodes():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    _snapshot(sim)

    assert ids.EARTH_CELL_COASTAL not in sim.graph.operational_node_ids()
    assert all(location_id != ids.EARTH_CELL_COASTAL for location_id, _ in sim.inventory.stock)
    assert SURFACE_DISTRIBUTION_SERVICE in sim.facilities.service_types()


def test_remote_surface_facility_capability_remains_categorical_under_surface_service_shortage():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    station_id = sim.facilities.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_COASTAL,
    )
    assert sim.facilities.installed_capability_at(ids.EARTH, "surface_survey")
    assert sim.facilities.active_capability_at(ids.EARTH, "surface_survey", sim.day)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    assert sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    ).fulfillment == 0.0

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    assert sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    ).fulfillment > 0.0
    assert sim.facilities.active_capability_at(ids.EARTH, "surface_survey", sim.day)
    assert station_id in sim.facilities.facilities


def test_remote_surface_survey_supply_is_enabled_by_shared_surface_dependency_allocation():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    sim.facilities.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_COASTAL,
    )

    expected_rate = sim.survey.providers[ids.ROBOTIC_GEOLOGY_STATION].points_per_day
    constrained = sim.tick_decision_projection().allocations.services.summary(
        ids.EARTH, "survey_observation"
    )
    assert constrained.nominal_rate == pytest.approx(expected_rate)
    assert constrained.enabled_rate == 0.0
    assert constrained.limiting_factors == ("provider_dependency",)

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    supplied = sim.tick_decision_projection().allocations.services.summary(
        ids.EARTH, "survey_observation"
    )
    assert supplied.nominal_rate == pytest.approx(expected_rate)
    assert supplied.enabled_rate == pytest.approx(expected_rate)
    assert supplied.limiting_factors == ()


def test_surface_cell_development_progress_is_limited_by_surface_infrastructure():
    app = build_game_application()
    sim = app._simulation
    project_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    )).created_id
    assert project_id is not None

    app.execute(AdvanceTime(12))
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project.construction_done == 0.0
    assert project.construction_fulfillment == 0.0
    assert project.limiting_factors == ("surface_infrastructure",)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    app.execute(AdvanceTime(12))
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project.construction_done > 0.0
    assert project.construction_fulfillment == 1.0
    assert project.limiting_factors == ()


def test_surface_map_exposes_projected_infrastructure_limit_for_cell_development():
    app = build_game_application()
    surface = app.query(__import__('space_idle').GetSurfaceMap(str(ids.EARTH_BODY)))
    coastal = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_COASTAL))
    option = next(row for row in coastal.development_options if row.location_id == str(ids.EARTH))
    assert option.blockers == ()
    assert option.can_plan
    assert option.projected_surface_infrastructure_demand is not None
    assert option.projected_surface_infrastructure_demand > 0.0
    assert option.projected_surface_infrastructure_fulfillment == 0.0
    assert option.limiting_factors == ("surface_infrastructure",)



def test_concurrent_surface_development_projects_share_surface_infrastructure_capacity():
    app = build_game_application()
    sim = app._simulation
    coastal_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    )).created_id
    inland_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_INLAND), sourcing_policy="import_now"
    )).created_id
    assert coastal_id is not None
    assert inland_id is not None

    app.execute(AdvanceTime(12))
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    requests = {
        str(request.owner_id): request
        for request in sim.projects.surface_infrastructure_service_requests(sim.day)
    }
    coastal_request = requests[coastal_id]
    inland_request = requests[inland_id]
    coastal_allocated = decision.allocations.services.allocated(coastal_request.id)
    inland_allocated = decision.allocations.services.allocated(inland_request.id)

    assert coastal_request.requested_rate == pytest.approx(1.0)
    assert inland_request.requested_rate == pytest.approx(1.0)
    assert coastal_allocated == pytest.approx(0.5)
    assert inland_allocated == pytest.approx(0.5)
    assert coastal_allocated + inland_allocated == pytest.approx(1.0)

    rows = {row.id: row for row in app.query(GetProjects()).items}
    assert rows[coastal_id].construction_fulfillment == pytest.approx(0.5)
    assert rows[inland_id].construction_fulfillment == pytest.approx(0.5)

def test_surface_infrastructure_is_derived_after_save_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH, site_cell_id=ids.EARTH_CELL_INDUSTRIAL)
    before = _snapshot(sim)

    path = tmp_path / "surface-infrastructure.json"
    save_game(app, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "surface_infrastructure" not in payload["state"]

    loaded, _ = load_game(path, build_game_application)
    after = _snapshot(loaded._simulation)
    assert after == before


def test_surface_gateway_handling_service_uses_location_surface_infrastructure():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    assert sim.facilities.active_capability_at(ids.EARTH, "cargo_transfer", sim.day)
    decision = sim.tick_decision_projection()
    assert decision.allocations.services.summary(
        ids.EARTH, "cargo_transfer"
    ).enabled_rate == 0.0

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    assert decision.allocations.services.summary(
        ids.EARTH, "cargo_transfer"
    ).enabled_rate > 0.0


def test_remote_surface_route_available_capacity_uses_location_surface_infrastructure():
    from space_idle.shared import SpatialNodeId
    app = build_game_application()
    sim = app._simulation
    a = SpatialNodeId("test.location.infrastructure.a")
    b = SpatialNodeId("test.location.infrastructure.b")
    sim.graph.found_location(a, "A", ids.MOON, ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    sim.graph.found_location(b, "B", ids.MOON, ids.MOON_CELL_NEARSIDE_MARE)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, a)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, b)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, a, site_cell_id=ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, b, site_cell_id=ids.MOON_CELL_NEARSIDE_MARE)
    sim.transport.add_fleet_units(ids.SURFACE_CARGO_HAULER, 1, a)
    sim.transport.synchronize_surface_access_routes()
    allocation_id = sim.transport.create_transport_allocation(
        ids.SURFACE_CARGO_HAULER, a, b, target_units=1, day=sim.day
    )
    initial = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert initial.nominal.forward_t_per_day > 0.0
    assert initial.available.forward_t_per_day == pytest.approx(initial.nominal.forward_t_per_day)

    sim.graph.develop_surface_cell(a, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(a, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)
    sim.transport.synchronize_surface_access_routes()
    physical = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert physical.available.forward_t_per_day == pytest.approx(physical.nominal.forward_t_per_day)
    decision = sim.tick_decision_projection()
    constrained = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=sim.day,
        execution_allocation=decision.allocations.transport,
    )
    assert 0.0 < constrained.available.forward_t_per_day < constrained.nominal.forward_t_per_day
    assert any(factor.startswith("surface_infrastructure:") for factor in constrained.limiting_factors)

    lane_id = sim.logistics.create_lane(a, b, 1.0, 100)
    lane = next(
        row for row in app.query(GetLogisticsLanes()).items if row.id == str(lane_id)
    )
    assert lane.effective_capacity_t_per_day == pytest.approx(
        constrained.available.forward_t_per_day
    )
