from __future__ import annotations

from space_idle import AdvanceTime, GetCatalog, GetContracts, GetWorld, SubmitCargo, build_game_application
from space_idle.content.base_game import (
    EARTH,
    EARTH_LEO_LAUNCH_SERVICE,
    LEO,
    REUSABLE_LAUNCH_VEHICLE,
    WATER,
)


EARTH_LEO_ROUTE = "base.route.earth_leo"


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
    owned = build_game_application()
    owned_before = owned.query(GetWorld()).funds_musd
    owned.execute(SubmitCargo(
        str(EARTH), str(LEO), str(WATER), 1.0, 100,
        (EARTH_LEO_ROUTE,), ((EARTH_LEO_ROUTE, str(REUSABLE_LAUNCH_VEHICLE)),),
    ))
    owned.execute(AdvanceTime(1))
    assert owned.query(GetWorld()).funds_musd == owned_before

    commercial = build_game_application()
    commercial_before = commercial.query(GetWorld()).funds_musd
    commercial.execute(SubmitCargo(
        str(EARTH), str(LEO), str(WATER), 1.0, 100,
        (EARTH_LEO_ROUTE,), ((EARTH_LEO_ROUTE, str(EARTH_LEO_LAUNCH_SERVICE)),),
    ))
    commercial.execute(AdvanceTime(1))
    assert commercial.query(GetWorld()).funds_musd < commercial_before


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
