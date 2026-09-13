from __future__ import annotations

from space_idle import AdvanceTime, GetCatalog, GetContracts, GetWorld, build_game_application
from space_idle.content.base_game import (
    EARTH,
    LEO,
    REUSABLE_LAUNCH_VEHICLE,
    WATER,
)


from space_idle.resource_demand import ResourceDemand
from space_idle.shared import EntityId



def test_time_progression_has_no_automatic_income_and_world_exposes_no_passive_rate():
    app = build_game_application()
    before = app.query(GetWorld())

    app.execute(AdvanceTime(30))
    after = app.query(GetWorld())

    assert after.funds_musd == before.funds_musd
    assert not hasattr(after, "passive_income_musd_per_day")


def test_base_game_starts_without_contract_offers_or_contract_only_resources():
    app = build_game_application()

    assert app.query(GetContracts()).items == ()
    resource_ids = {row.id for row in app.query(GetCatalog()).resources}
    assert "base.resource.contract_payload" not in resource_ids


def test_owned_transport_is_physical_while_commercial_transport_uses_money():
    def demand():
        return ResourceDemand(
            EntityId("demand.economy"), "test", EntityId("owner.economy"),
            LEO, WATER, 1.0, 100, EARTH, 0.0,
        )

    owned = build_game_application()
    owned_sim = owned._simulation
    owned_sim.logistics.external_services.clear()
    owned_sim.logistics.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=owned_sim.day
    )
    owned_sim.logistics.create_lane(EARTH, LEO, 1.0, 100)
    owned_sim.inventory.add(EARTH, WATER, 1.0)
    owned_before = owned.query(GetWorld()).funds_musd
    owned_sim.logistics.advance_capacity_logistics(owned_sim.day, (demand(),))
    assert owned.query(GetWorld()).funds_musd == owned_before
    assert owned_sim.logistics.cargo_flows

    commercial = build_game_application()
    commercial_sim = commercial._simulation
    commercial_sim.logistics.transport_allocations.clear()
    commercial_sim.logistics.create_lane(EARTH, LEO, 1.0, 100)
    commercial_sim.inventory.add(EARTH, WATER, 1.0)
    commercial_before = commercial.query(GetWorld()).funds_musd
    commercial_sim.logistics.advance_capacity_logistics(commercial_sim.day, (demand(),))
    assert commercial.query(GetWorld()).funds_musd < commercial_before
    assert commercial_sim.logistics.cargo_flows


def test_extraction_stops_when_output_storage_service_is_full():
    app = build_game_application()
    sim = app._simulation
    power = sim.power.snapshot(EARTH, sim.facilities, sim.day)
    initial = next(
        row
        for row in sim.extraction.snapshots(EARTH, sim.facilities, sim.inventory, power, sim.day)
        if row.output_t_per_day > 0
    )
    spec = sim.extraction.specs[initial.facility_def_id]
    free = sim.inventory.free_capacity(EARTH, spec.output_resource_id)
    assert free is not None and free > 0

    sim.inventory.add(EARTH, spec.output_resource_id, free)
    before = sim.inventory.amount(EARTH, spec.output_resource_id)
    blocked = next(
        row
        for row in sim.extraction.snapshots(EARTH, sim.facilities, sim.inventory, power, sim.day)
        if row.facility_id == initial.facility_id
    )
    assert blocked.output_t_per_day == 0.0
    assert any(reason.startswith("storage:") for reason in blocked.limiting_factors)

    sim.extraction.advance_day(EARTH, sim.facilities, sim.inventory, power, sim.day)
    assert sim.inventory.amount(EARTH, spec.output_resource_id) == before
