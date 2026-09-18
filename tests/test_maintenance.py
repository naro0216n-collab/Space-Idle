from __future__ import annotations

import pytest

from space_idle import (
    GetFlowReport,
    GetOperationalNode,
    GetLogistics,
    PauseFacility,
    ResumeFacility,
    SetFacilityActivityPriority,
    SetMaintenancePriority,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.execution_requirements import allocate_execution_requirements, resource_constraint
from space_idle.facilities import FacilityDef, ServiceCapacitySupply
from space_idle.shared import DefinitionId, EntityId


def _install_maintenance_facility(
    sim,
    node_id,
    *,
    definition_suffix: str,
    resource_id: DefinitionId,
    service_type: str | None = None,
):
    definition_id = DefinitionId(f"test.facility.maintenance.{definition_suffix}")
    service_supplies = (
        (ServiceCapacitySupply(service_type, 10.0),)
        if service_type is not None
        else ()
    )
    sim.facilities.definitions[definition_id] = FacilityDef(
        definition_id,
        f"Maintenance fixture {definition_suffix}",
        maintenance_fraction_per_year=365.0,
        service_capacity_supplies=service_supplies,
    )
    facility_id = sim.facilities.install(
        definition_id, node_id, invested_resources={resource_id: 1.0}
    )
    return sim.facilities.facilities[facility_id]


def test_facility_maintenance_priority_is_player_visible_and_command_driven():
    app = build_game_application()
    sim = app._simulation
    facility = _install_maintenance_facility(
        sim, ids.EARTH,
        definition_suffix="priority",
        resource_id=DefinitionId("test.resource.maintenance_priority"),
    )

    app.execute(SetMaintenancePriority(str(facility.id), 5))
    app.execute(SetFacilityActivityPriority(str(facility.id), 4))
    app.execute(PauseFacility(str(facility.id)))
    row = next(
        item for item in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if item.id == str(facility.id)
    )

    assert facility.maintenance_priority == 5
    assert facility.activity_priority == 4
    assert facility.paused is True
    assert row.maintenance_priority == 5

    app.execute(ResumeFacility(str(facility.id)))
    assert facility.paused is False
    assert facility.maintenance_priority == 5
    assert facility.activity_priority == 4


def test_maintenance_shortage_can_starve_lower_priority_facility_without_auto_rescue():
    app = build_game_application()
    sim = app._simulation
    common = DefinitionId("test.resource.maintenance_shared")
    high = _install_maintenance_facility(
        sim, ids.EARTH, definition_suffix="shared", resource_id=common
    )
    low_id = sim.facilities.install(
        high.definition_id, ids.EARTH, invested_resources={common: 1.0}
    )
    low = sim.facilities.facilities[low_id]
    sim.facilities.facilities = {high.id: high, low.id: low}
    high.maintenance_priority = 4
    low.maintenance_priority = 1
    sim.inventory.stock[(ids.EARTH, common)] = 1.0

    bundles = sim.maintenance.execution_requirement_bundles(sim.day)
    capacities = {
        resource_constraint(ids.EARTH, common): sim.inventory.available(ids.EARTH, common)
    }
    allocations = allocate_execution_requirements(bundles, capacities)
    satisfaction = sim.maintenance.satisfaction_projection(allocations)
    sim.maintenance.advance_day(allocations, sim.day)

    assert satisfaction[high.id] == pytest.approx(1.0)
    assert satisfaction[low.id] == pytest.approx(0.0)
    assert sim.inventory.amount(ids.EARTH, common) == pytest.approx(0.0)


def test_maintenance_runway_reports_actual_site_stock_not_one_day_planning_amount():
    app = build_game_application()
    sim = app._simulation
    resource_id = DefinitionId("test.resource.maintenance_runway")
    facility = _install_maintenance_facility(
        sim, ids.LEO, definition_suffix="runway", resource_id=resource_id
    )
    sim.facilities.facilities = {facility.id: facility}
    daily = sim.facilities.maintenance_requirements_per_day(facility.id)[resource_id]
    stock_days = sim.maintenance.reorder_point_days + 5.0
    sim.inventory.stock[(ids.LEO, resource_id)] = daily * stock_days

    row = next(
        demand for demand in app.query(GetLogistics()).requirements
        if demand.owner_id == str(facility.id) and demand.resource_id == str(resource_id)
    )

    assert row.requested_t == pytest.approx(daily)
    assert row.local_runway_days == pytest.approx(stock_days)
    assert row.supply_state == "local_covered"


def test_current_tick_maintenance_allocation_controls_power_and_service_capacity():
    app = build_game_application()
    sim = app._simulation
    resource_id = DefinitionId("test.resource.maintenance_service")
    service_type = "test.maintenance_service"
    facility = _install_maintenance_facility(
        sim, ids.EARTH,
        definition_suffix="service",
        resource_id=resource_id,
        service_type=service_type,
    )
    sim.facilities.facilities = {facility.id: facility}
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
    assert service.nominal_rate > 0.0
    assert service.enabled_rate == pytest.approx(0.0)


def test_maintenance_replenishment_plan_is_independent_of_transient_reservations():
    app = build_game_application()
    sim = app._simulation
    resource_id = DefinitionId("test.resource.maintenance_replenishment")
    facility = _install_maintenance_facility(
        sim, ids.EARTH, definition_suffix="replenishment", resource_id=resource_id
    )
    sim.facilities.facilities = {facility.id: facility}
    daily = sim.facilities.maintenance_requirements_per_day(facility.id)[resource_id]
    stock_days = sim.maintenance.reorder_point_days + 5.0
    sim.inventory.stock[(ids.EARTH, resource_id)] = daily * stock_days

    baseline = {
        demand.resource_id: demand.amount_t
        for demand in sim.maintenance.supplys(sim.day)
    }
    sim.inventory.reserve(
        EntityId("test.transient"),
        facility.operational_node_id,
        resource_id,
        daily * (stock_days / 2.0),
    )
    after_reservation = {
        demand.resource_id: demand.amount_t
        for demand in sim.maintenance.supplys(sim.day)
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
