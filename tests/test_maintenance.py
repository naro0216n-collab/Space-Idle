from __future__ import annotations

import pytest

from space_idle import (
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


def test_maintenance_priority_is_player_controlled_and_drives_resource_allocation():
    app = build_game_application()
    sim = app._simulation
    common = DefinitionId("test.resource.maintenance_shared")
    high = _install_maintenance_facility(
        sim, ids.EARTH, definition_suffix="priority", resource_id=common
    )
    low_id = sim.facilities.install(
        high.definition_id, ids.EARTH, invested_resources={common: 1.0}
    )
    low = sim.facilities.facilities[low_id]
    sim.facilities.facilities = {high.id: high, low.id: low}

    app.execute(SetMaintenancePriority(str(high.id), 5))
    app.execute(SetMaintenancePriority(str(low.id), 1))
    app.execute(SetFacilityActivityPriority(str(high.id), 4))
    app.execute(PauseFacility(str(high.id)))
    row = next(
        item for item in app.query(GetOperationalNode(str(ids.EARTH))).facilities
        if item.id == str(high.id)
    )
    assert high.maintenance_priority == 5
    assert low.maintenance_priority == 1
    assert high.activity_priority == 4
    assert high.paused is True
    assert row.maintenance_priority == 5

    app.execute(ResumeFacility(str(high.id)))
    assert high.paused is False
    assert high.maintenance_priority == 5
    assert high.activity_priority == 4

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


def test_maintenance_replenishment_uses_actual_stock_and_ignores_transient_reservations():
    app = build_game_application()
    sim = app._simulation
    resource_id = DefinitionId("test.resource.maintenance_replenishment")
    facility = _install_maintenance_facility(
        sim, ids.LEO, definition_suffix="replenishment", resource_id=resource_id
    )
    sim.facilities.facilities = {facility.id: facility}
    daily = sim.facilities.maintenance_requirements_per_day(facility.id)[resource_id]
    stock_days = sim.maintenance.reorder_point_days + 5.0
    sim.inventory.stock[(ids.LEO, resource_id)] = daily * stock_days

    row = next(
        demand for demand in app.query(GetLogistics()).requirements
        if demand.owner_id == str(facility.id) and demand.resource_id == str(resource_id)
    )
    baseline = {
        demand.resource_id: demand.amount_t
        for demand in sim.maintenance.supplys(sim.day)
    }
    assert row.requested_t == pytest.approx(daily)
    assert row.local_runway_days == pytest.approx(stock_days)
    assert row.supply_state == "local_covered"
    assert baseline[resource_id] == pytest.approx(daily)

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


def test_current_tick_maintenance_fulfillment_controls_power_and_service_capacity():
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
