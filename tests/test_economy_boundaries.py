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
