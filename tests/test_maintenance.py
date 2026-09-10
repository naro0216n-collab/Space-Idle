from __future__ import annotations

import pytest

from space_idle import GetLocation, GetLogistics, SetMaintenancePriority, build_game_application
from space_idle.content import base_ids as ids
from space_idle.resource_demand import reserve_local_resource_claims


def _earth_facilities_with_maintenance(sim):
    return [
        facility
        for facility in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id))
        if facility.location_id == ids.EARTH
        and sim.facilities.maintenance_requirements_per_day(facility.id)
    ]


def test_facility_maintenance_priority_is_player_visible_and_command_driven():
    app = build_game_application()
    facility = _earth_facilities_with_maintenance(app._simulation)[0]

    app.execute(SetMaintenancePriority(str(facility.id), 73))
    row = next(
        item for item in app.query(GetLocation(str(ids.EARTH))).facilities
        if item.id == str(facility.id)
    )

    assert facility.maintenance_priority == 73
    assert row.maintenance_priority == 73


def test_maintenance_shortage_can_starve_lower_priority_facility_without_auto_rescue():
    app = build_game_application()
    sim = app._simulation
    high, low = _earth_facilities_with_maintenance(sim)[:2]

    # Keep only two facilities in the maintenance competition so the expected
    # allocation is independent of unrelated initial content.
    sim.facilities.facilities = {high.id: high, low.id: low}
    high.maintenance_priority = 80
    low.maintenance_priority = 20

    high_req = sim.facilities.maintenance_requirements_per_day(high.id)
    low_req = sim.facilities.maintenance_requirements_per_day(low.id)
    common = next(resource for resource in high_req if resource in low_req)

    # All co-inputs are abundant; the common material is deliberately limited
    # to the high-priority facility's one-day need.
    all_resources = set(high_req) | set(low_req)
    for resource_id in all_resources:
        sim.inventory.stock[(ids.EARTH, resource_id)] = 100.0
    sim.inventory.stock[(ids.EARTH, common)] = high_req[common]

    demands = sim.maintenance.resource_demands(sim.day)
    reserve_local_resource_claims(demands, sim.inventory)
    sim.maintenance.advance_day(sim.day)

    assert high.maintenance_satisfaction == pytest.approx(1.0)
    assert low.maintenance_satisfaction == pytest.approx(0.0)
    # The Core exposes the shortage outcome; it does not create material or
    # silently reroute supply to keep every facility operational.
    assert sim.inventory.amount(ids.EARTH, common) == pytest.approx(0.0)


def test_maintenance_runway_reports_actual_site_stock_not_one_day_planning_amount():
    app = build_game_application()
    sim = app._simulation
    facility = next(
        row for row in sim.facilities.facilities.values()
        if row.location_id == ids.LEO
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
