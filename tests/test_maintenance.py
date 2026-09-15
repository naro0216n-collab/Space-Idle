from __future__ import annotations

import pytest

from space_idle import GetFlowReport, GetOperationalNode, GetLogistics, SetMaintenancePriority, build_game_application
from space_idle.content import base_ids as ids
from space_idle.execution_requirements import allocate_execution_requirements, resource_constraint
from space_idle.shared import EntityId


def _earth_facilities_with_maintenance(sim):
    return [
        facility
        for facility in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id))
        if facility.operational_node_id == ids.EARTH
        and sim.facilities.maintenance_requirements_per_day(facility.id)
    ]


def test_facility_maintenance_priority_is_player_visible_and_command_driven():
    app = build_game_application()
    facility = _earth_facilities_with_maintenance(app._simulation)[0]

    app.execute(SetMaintenancePriority(str(facility.id), 5))
    row = next(
        item for item in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if item.id == str(facility.id)
    )

    assert facility.maintenance_priority == 5
    assert row.maintenance_priority == 5


def test_maintenance_shortage_can_starve_lower_priority_facility_without_auto_rescue():
    app = build_game_application()
    sim = app._simulation
    high, low = _earth_facilities_with_maintenance(sim)[:2]

    # Keep only two facilities in the maintenance competition so the expected
    # allocation is independent of unrelated initial content.
    sim.facilities.facilities = {high.id: high, low.id: low}
    high.maintenance_priority = 4
    low.maintenance_priority = 1

    high_req = sim.facilities.maintenance_requirements_per_day(high.id)
    low_req = sim.facilities.maintenance_requirements_per_day(low.id)
    common = next(resource for resource in high_req if resource in low_req)

    # All co-inputs are abundant; the common material is deliberately limited
    # to the high-priority facility's one-day need.
    all_resources = set(high_req) | set(low_req)
    for resource_id in all_resources:
        sim.inventory.stock[(ids.EARTH, resource_id)] = 100.0
    sim.inventory.stock[(ids.EARTH, common)] = high_req[common]

    bundles = sim.maintenance.execution_requirement_bundles(sim.day)
    capacities = {
        resource_constraint(ids.EARTH, resource_id): sim.inventory.available(ids.EARTH, resource_id)
        for resource_id in all_resources
    }
    allocations = allocate_execution_requirements(bundles, capacities)
    satisfaction = sim.maintenance.satisfaction_projection(allocations)
    sim.maintenance.advance_day(allocations, sim.day)

    assert satisfaction[high.id] == pytest.approx(1.0)
    assert satisfaction[low.id] == pytest.approx(0.0)
    # The Core exposes the shortage outcome; it does not create material or
    # silently reroute supply to keep every facility operational.
    assert sim.inventory.amount(ids.EARTH, common) == pytest.approx(0.0)


def test_maintenance_runway_reports_actual_site_stock_not_one_day_planning_amount():
    app = build_game_application()
    sim = app._simulation
    facility = next(
        row for row in sim.facilities.facilities.values()
        if row.operational_node_id == ids.LEO
        and sim.facilities.maintenance_requirements_per_day(row.id)
    )
    sim.facilities.facilities = {facility.id: facility}
    requirements = sim.facilities.maintenance_requirements_per_day(facility.id)
    resource_id, daily = next(iter(requirements.items()))
    for rid, rate in requirements.items():
        sim.inventory.stock[(ids.LEO, rid)] = rate * 20.0

    row = next(
        demand for demand in app.query(GetLogistics()).demands
        if demand.owner_id == str(facility.id) and demand.resource_id == str(resource_id)
    )

    assert row.requested_t == pytest.approx(daily)  # above the 15-day reorder point
    assert row.local_runway_days == pytest.approx(20.0)
    assert row.supply_state == "local_covered"


def test_current_tick_maintenance_allocation_controls_power_and_service_capacity():
    app = build_game_application()
    sim = app._simulation
    facility = next(
        row for row in sim.facilities.facilities.values()
        if row.operational_node_id == ids.EARTH
        and sim.facilities.maintenance_requirements_per_day(row.id)
        and sim.facilities.definitions[row.definition_id].service_capacity_supplies
    )
    service_type = sim.facilities.definitions[facility.definition_id].service_capacity_supplies[0].service_type
    requirements = sim.facilities.maintenance_requirements_per_day(facility.id)
    for resource_id in requirements:
        sim.inventory.stock[(ids.EARTH, resource_id)] = 0.0

    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    factor = power.maintenance_factor_by_facility[facility.id]
    service = decision.allocations.services.summary(ids.EARTH, service_type)
    row = next(
        item for item in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if item.id == str(facility.id)
    )

    assert factor == pytest.approx(0.0)
    assert row.maintenance_satisfaction == pytest.approx(0.0)
    assert service.enabled_rate < service.nominal_rate


def test_maintenance_replenishment_plan_is_independent_of_transient_reservations():
    app = build_game_application()
    sim = app._simulation
    facility = _earth_facilities_with_maintenance(sim)[0]
    sim.facilities.facilities = {facility.id: facility}
    requirements = sim.facilities.maintenance_requirements_per_day(facility.id)
    resource_id, daily = next(iter(requirements.items()))

    for rid, rate in requirements.items():
        sim.inventory.stock[(facility.operational_node_id, rid)] = rate * 20.0

    baseline = {
        demand.resource_id: demand.amount_t
        for demand in sim.maintenance.resource_demands(sim.day)
    }
    sim.inventory.reserve(
        EntityId('test.transient'),
        facility.operational_node_id,
        resource_id,
        daily * 10.0,
    )
    after_reservation = {
        demand.resource_id: demand.amount_t
        for demand in sim.maintenance.resource_demands(sim.day)
    }

    assert baseline == after_reservation
    assert baseline[resource_id] == pytest.approx(daily)


def test_flow_report_includes_current_facility_maintenance_consumption():
    app = build_game_application()
    sim = app._simulation
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]

    expected = {}
    allocations = decision.allocations.execution
    for snap in sim.industry.snapshots(
        ids.EARTH, sim.facilities, sim.inventory, sim.day, allocations
    ):
        for resource_id, amount in snap.input_rates_per_day.items():
            expected[resource_id] = expected.get(resource_id, 0.0) + amount
    for node_id, resource_id, amount in sim.maintenance.resource_consumption_projection(allocations):
        if node_id == ids.EARTH:
            expected[resource_id] = expected.get(resource_id, 0.0) + amount

    flow = app.query(GetFlowReport(str(ids.EARTH)))
    rows = {row.resource_id: row for row in flow.resources}
    maintained = [resource_id for resource_id, amount in expected.items() if amount > 1e-12]
    assert maintained
    for resource_id in maintained:
        assert rows[str(resource_id)].local_consumption_per_day == pytest.approx(
            expected[resource_id]
        )
        assert rows[str(resource_id)].local_net_per_day == pytest.approx(
            rows[str(resource_id)].local_production_per_day - expected[resource_id]
        )
