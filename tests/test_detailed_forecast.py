from __future__ import annotations

import pytest

from space_idle import GetDetailedForecast, build_game_application
from space_idle.application_commands import ApplicationError
from space_idle.content import base_ids as ids


def test_detailed_forecast_advances_isolated_snapshot_and_projects_future_inventory():
    app = build_game_application()
    sim = app._simulation
    base_day = sim.day
    base_stock = dict(sim.inventory.stock)

    view = app.query(GetDetailedForecast(
        "operational_nodes",
        node_ids=(str(ids.EARTH),),
        horizon="SHORT_TERM",
        period_days=5,
    ))

    assert view.base_day == base_day
    assert view.projected_day == base_day + 5
    assert view.period_days == 5
    assert view.horizon == "SHORT_TERM"
    assert view.node_ids == (str(ids.EARTH),)
    assert view.inventory
    assert sim.day == base_day
    assert sim.inventory.stock == base_stock
    assert all(
        row.steady_state in {"stable", "accumulating", "depleting"}
        for row in view.inventory
    )

    with pytest.raises(ApplicationError, match="unsupported detailed forecast horizon"):
        app.query(GetDetailedForecast(horizon="UNKNOWN", period_days=1))
    with pytest.raises(ApplicationError, match="period_days"):
        app.query(GetDetailedForecast(period_days=0))
