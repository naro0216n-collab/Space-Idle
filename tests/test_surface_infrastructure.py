from __future__ import annotations

import pytest

from space_idle import (
    AdvanceTime,
    DevelopSurfaceCell,
    GetLogistics,
    GetSurfaceMap,
    GetOperationalNode,
    GetProjects,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.surface_infrastructure import SURFACE_DISTRIBUTION_SERVICE
from space_idle.service_capacity import allocate_service_capacity


def _ensure_project_materials_on_hand(sim, *project_ids: str) -> None:
    required = {}
    for project_id in project_ids:
        project = next(
            row for row in sim.projects.projects.values()
            if str(row.id) == project_id
        )
        recipe = sim.projects.recipe_for_project(project)
        for requirement in recipe.resources:
            key = (project.operational_node_id, requirement.resource_id)
            required[key] = required.get(key, 0.0) + requirement.amount_t
    for (node_id, resource_id), amount_t in required.items():
        sim.inventory.stock[(node_id, resource_id)] = max(
            sim.inventory.amount(node_id, resource_id), amount_t
        )


def _snapshot(sim, maintenance_factors=None):
    physical = sim.power.physical_snapshot(ids.EARTH, sim.facilities, sim.day)
    power = sim.power.resolve_snapshot(physical, maintenance_factors)
    request = sim.surface_infrastructure.service_request(ids.EARTH)
    key = (ids.EARTH, sim.surface_infrastructure.service_type)
    nominal, enabled = sim.service_capacity_registry.supply_at(
        ids.EARTH, key[1], sim.facilities, power, sim.day
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
    assert ids.EARTH_CELL_COASTAL not in sim.graph.operational_node_ids()
    assert all(
        location_id != ids.EARTH_CELL_COASTAL
        for location_id, _resource_id in sim.inventory.stock
    )
    assert SURFACE_DISTRIBUTION_SERVICE in sim.facilities.service_types()

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


def test_cell_physical_opportunity_is_independent_of_surface_infrastructure_and_execution_is_limited_once():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]

    core = sim.graph.surface_cells[ids.EARTH_CELL_INDUSTRIAL].resource_potential_by_resource[ids.METAL_ORE]
    remote = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL].resource_potential_by_resource[ids.METAL_ORE]
    opportunity = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day,
        decision.allocations.services,
    )
    core_access = sim.graph.surface_cells[ids.EARTH_CELL_INDUSTRIAL].terrain.bearing_capacity_factor
    remote_access = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL].terrain.bearing_capacity_factor
    physical_opportunity = core * core_access + remote * remote_access
    assert opportunity == pytest.approx(physical_opportunity)
    constrained = next(
        row for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day,
            decision.allocations.execution,
        )
        if row.facility_def_id == ids.METAL_ORE_MINE
    )
    assert constrained.scale == 0.0
    assert constrained.effective_opportunity == pytest.approx(physical_opportunity)
    assert "service_capacity" in constrained.limiting_factors

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    supplied = next(
        row for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day,
            decision.allocations.execution,
        )
        if row.facility_def_id == ids.METAL_ORE_MINE
    )
    assert supplied.effective_opportunity == pytest.approx(physical_opportunity)
    assert supplied.scale == pytest.approx(1.0)
    assert supplied.limiting_factors == ()


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

    spatial = view.surface_location
    assert spatial is not None
    assert spatial.core_cell_id == str(ids.EARTH_CELL_INDUSTRIAL)
    assert spatial.developed_cell_ids == (
        str(ids.EARTH_CELL_COASTAL),
        str(ids.EARTH_CELL_INDUSTRIAL),
    )
    assert any(anchor.cell_id == str(ids.EARTH_CELL_INDUSTRIAL) for anchor in spatial.active_access_anchors)
    illumination = next(summary for summary in spatial.environment_summary if summary.key == "illumination")
    assert illumination.location_values == ()
    assert {cell_id for cell_id, _values in illumination.cell_values} == {
        str(ids.EARTH_CELL_COASTAL),
        str(ids.EARTH_CELL_INDUSTRIAL),
    }


def test_surface_infrastructure_limits_remote_service_execution_without_disabling_capability():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    station_id = sim.facilities.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_COASTAL,
    )

    provider = sim.survey.providers[ids.ROBOTIC_GEOLOGY_STATION]
    service_type = sim.survey.service_type_for_provider(provider.id)
    expected_rate = provider.capacity_units_per_source_per_day
    assert sim.facilities.installed_capability_at(ids.EARTH, "surface_survey")
    assert sim.facilities.active_capability_at(ids.EARTH, "surface_survey", sim.day)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    assert sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    ).fulfillment == 0.0
    constrained = decision.allocations.services.summary(ids.EARTH, service_type)
    cargo_constrained = decision.allocations.services.summary(ids.EARTH, "cargo_transfer")
    assert constrained.nominal_rate == pytest.approx(expected_rate)
    assert constrained.enabled_rate == 0.0
    assert constrained.limiting_factors == ("provider_dependency",)
    assert cargo_constrained.nominal_rate > 0.0
    assert cargo_constrained.enabled_rate == 0.0
    assert sim.facilities.active_capability_at(ids.EARTH, "cargo_transfer", sim.day)

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
    supplied = decision.allocations.services.summary(ids.EARTH, service_type)
    cargo_supplied = decision.allocations.services.summary(ids.EARTH, "cargo_transfer")
    assert supplied.nominal_rate == pytest.approx(expected_rate)
    assert supplied.enabled_rate == pytest.approx(expected_rate)
    assert supplied.limiting_factors == ()
    assert cargo_supplied.enabled_rate > 0.0
    assert sim.facilities.active_capability_at(ids.EARTH, "surface_survey", sim.day)
    assert sim.facilities.active_capability_at(ids.EARTH, "cargo_transfer", sim.day)
    assert station_id in sim.facilities.facilities

def test_surface_cell_development_projection_execution_and_completion_share_one_infrastructure_contract():
    app = build_game_application()
    sim = app._simulation

    surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    coastal = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_COASTAL))
    option = next(row for row in coastal.development_options if row.location_id == str(ids.EARTH))
    assert option.blockers == ()
    assert option.can_plan
    assert option.projected_surface_infrastructure_demand is not None
    assert option.projected_surface_infrastructure_demand > 0.0
    assert option.projected_surface_infrastructure_fulfillment == 0.0
    assert option.limiting_factors == ("surface_infrastructure",)

    project_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), procurement_policy="extended_wait"
    )).created_id
    assert project_id is not None
    _ensure_project_materials_on_hand(sim, project_id)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    app.execute(AdvanceTime(1))
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project.construction_done == 0.0
    assert project.construction_fulfillment == 0.0
    assert project.limiting_factors == ("surface_infrastructure",)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    bundle_id = sim.projects.construction_execution_bundle_id(project_id)
    projected = decision.allocations.execution.fulfillment(bundle_id)
    assert projected > 0.0

    app.execute(AdvanceTime(1))
    project_view = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project_view.construction_done > 0.0
    assert project_view.construction_fulfillment > 0.0
    assert "surface_infrastructure" not in project_view.limiting_factors
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    project_state = next(row for row in sim.projects.projects.values() if str(row.id) == project_id)
    while project_state.status.value != "complete":
        before = (
            project_state.status,
            project_state.construction_done,
            project_state.materials_committed,
        )
        app.execute(AdvanceTime(1))
        after = (
            project_state.status,
            project_state.construction_done,
            project_state.materials_committed,
        )
        assert after != before, "ready surface development made no canonical-tick progress"

    assert ids.EARTH_CELL_COASTAL in sim.graph.locations[ids.EARTH].developed_cell_ids


def test_concurrent_surface_development_projects_share_the_common_execution_allocator():
    app = build_game_application()
    sim = app._simulation
    coastal_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), procurement_policy="extended_wait"
    )).created_id
    inland_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_INLAND), procurement_policy="extended_wait"
    )).created_id
    assert coastal_id is not None and inland_id is not None
    _ensure_project_materials_on_hand(sim, coastal_id, inland_id)

    app.execute(AdvanceTime(1))
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    execution = decision.allocations.execution
    bundles = {
        str(bundle.owner_id): bundle
        for bundle in execution.bundles
        if bundle.owner_kind == "construction"
    }
    coastal = bundles[coastal_id]
    inland = bundles[inland_id]
    surface_type = sim.surface_infrastructure.service_type
    assert any(key.kind == "service" and key.name == surface_type for key, _ in coastal.coefficients())
    assert any(key.kind == "service" and key.name == surface_type for key, _ in inland.coefficients())
    assert execution.allocated(coastal.id) == pytest.approx(execution.allocated(inland.id))

    rows = {row.id: row for row in app.query(GetProjects()).items}
    assert rows[coastal_id].construction_fulfillment == pytest.approx(execution.fulfillment(coastal.id))
    assert rows[inland_id].construction_fulfillment == pytest.approx(execution.fulfillment(inland.id))


def test_remote_surface_movement_capacity_uses_location_surface_infrastructure():
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
    sim.transport.invalidate_movement_plans()
    allocation_id = sim.transport.create_transport_allocation(
        ids.SURFACE_CARGO_HAULER, a, b,
        target_capacity=sim.transport.transport_capacity_for_units(
            ids.SURFACE_CARGO_HAULER, a, b, 1, day=sim.day
        ),
        day=sim.day,
    )
    initial = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert initial.nominal.forward_t_per_day > 0.0
    assert initial.available.forward_t_per_day == pytest.approx(initial.nominal.forward_t_per_day)

    sim.graph.develop_surface_cell(a, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    sim.graph.develop_surface_cell(a, ids.MOON_CELL_EQUATORIAL_HIGHLANDS)
    sim.transport.invalidate_movement_plans()
    physical = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert physical.available.forward_t_per_day == pytest.approx(physical.nominal.forward_t_per_day)
    decision = sim.tick_decision_projection()
    constrained = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=sim.day,
        execution_allocation=decision.allocations.transport,
    )
    assert 0.0 < constrained.available.forward_t_per_day < constrained.nominal.forward_t_per_day
    assert any(factor.startswith("surface_infrastructure:") for factor in constrained.limiting_factors)

    allocation = next(
        row for row in app.query(GetLogistics()).allocations if row.id == str(allocation_id)
    )
    assert allocation.available.forward_t_per_day == pytest.approx(
        constrained.available.forward_t_per_day
    )
