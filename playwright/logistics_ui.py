from __future__ import annotations

from e2e_support import (
    guard_ci_secondary_entrypoint,
    isolated_browser_context,
    run_ci_suite_or_standalone,
)

if __name__ == "__main__" and guard_ci_secondary_entrypoint("logistics_ui"):
    raise SystemExit(0)

import os
from pathlib import Path
from threading import Thread
import tempfile
import time

from space_idle import AdvanceTime, PlanBuild, build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy



EARTH = str(ids.EARTH)
LEO = str(ids.LEO)
OWNED_LAUNCH_VEHICLE = str(ids.REUSABLE_LAUNCH_VEHICLE)


def _wait_for_server(origin: str, timeout: float = 10.0) -> None:
    import urllib.request

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{origin}/api/v1/health", timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"server did not become ready: {last_error}")


def _build_logistics_test_application():
    app = build_game_application()
    app._simulation.technology.completed.update(  # noqa: SLF001 - deterministic E2E fixture setup
        {ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS}
    )
    return app


def run(*, browser=None) -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-logistics-ui-")
    runtime = GameRuntime(
        factory=_build_logistics_test_application,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
    )
    runtime.set_time_control(paused=True)
    project_id = runtime.execute(
        PlanBuild(
            LEO,
            str(ids.ORBITAL_LOGISTICS_NODE),
            priority=100,
            sourcing_policy="import_now",
            import_source_id=EARTH,
        )
    ).data.created_id
    assert project_id is not None
    # Establish source-constrained Resource Demand before the UI configures the
    # Fleet Allocation and Lane that will satisfy it.
    runtime.execute(AdvanceTime(1))

    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_server(origin)
        with isolated_browser_context(
            browser_name,
            browser=browser,
                viewport={"width": 1194, "height": 834},
                has_touch=True,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
            ) as context:
            page = context.new_page()
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            page.get_by_role("button", name="物流ネットワーク").click()

            demand_row = page.locator("#demandTable tbody tr", has_text=project_id).first
            demand_row.wait_for(timeout=10000)
            assert "Lane未設定" in demand_row.inner_text(), (
                "project demand must remain visible before a Lane is configured"
            )

            # Player Fleet investment is explicit: create an authoritative UNITS
            # allocation and verify target, fulfillment, and sustained capacity.
            page.get_by_role("button", name="Transport Allocationを作成").click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
            page.locator("#allocationVehicle").select_option(OWNED_LAUNCH_VEHICLE)
            page.locator("#allocationSource").select_option(EARTH)
            page.locator("#allocationDestination").select_option(LEO)
            page.locator("#allocationMode").select_option("units")
            page.locator("#allocationUnits").fill("1")
            page.locator("#allocationPriority").fill("100")
            page.get_by_role("button", name="Allocation作成").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)

            allocation_row = page.locator("#allocationTable [data-allocation-row]").first
            allocation_row.wait_for(timeout=10000)
            allocation_text = allocation_row.inner_text()
            assert "UNITS" in allocation_text and "1 unit" in allocation_text
            assert "1 / 1" in allocation_text and "unfilled 0" in allocation_text
            nominal_text = allocation_row.locator("td").nth(3).inner_text()
            available_text = allocation_row.locator("td").nth(4).inner_text()
            assert "t/日" in nominal_text and not nominal_text.startswith("0 / 0"), (
                "Fleet allocation must expose positive derived nominal sustained capacity"
            )
            assert "t/日" in available_text and not available_text.startswith("0 / 0"), (
                "operable Fleet allocation must expose available sustained capacity"
            )

            # Lane is only the capacity consumer. Creating it must not change the
            # Fleet target; the existing project demand becomes serviceable.
            page.get_by_role("button", name="Laneを作成").click()
            page.locator("#laneDialog").wait_for(state="visible", timeout=10000)
            page.locator("#laneSource").select_option(EARTH)
            page.locator("#laneDestination").select_option(LEO)
            page.locator("#laneCapacity").fill("20")
            page.locator("#lanePriority").fill("100")
            page.get_by_role("button", name="Lane作成").click()
            page.locator("#laneDialog").wait_for(state="hidden", timeout=10000)
            lane_row = page.locator("#laneTable tbody tr", has_text="地球地表").first
            lane_row.wait_for(timeout=10000)
            assert "20 t/日" in lane_row.inner_text()
            assert "稼働" in lane_row.inner_text()
            assert "1 unit" in allocation_row.inner_text(), (
                "Lane demand must not resize the authoritative Fleet allocation"
            )

            page.wait_for_function(
                """projectId => {
                  const row=[...document.querySelectorAll('#demandTable tbody tr')]
                    .find(row=>row.innerText.includes(projectId));
                  return row?.innerText.includes('Lane 1/1');
                }""",
                arg=project_id,
                timeout=10000,
            )

            # Advance the authoritative application one tick. The browser must
            # then expose Cargo Flow using owned Fleet-derived capacity, rather
            # than any individual-vehicle mission path.
            runtime.execute(AdvanceTime(1))
            page.wait_for_function(
                """projectId => [...document.querySelectorAll('#cargoTable tbody tr')]
                  .some(row => row.innerText.includes(projectId)
                    && row.innerText.includes('allocation:transport.allocation.'))""",
                arg=project_id,
                timeout=10000,
            )
            cargo_text = page.locator("#cargoTable").inner_text()
            assert "in_transit" in cargo_text
            assert "allocation:transport.allocation." in cargo_text

            page.wait_for_function(
                """() => {
                  const row=document.querySelector('#allocationTable [data-allocation-row]');
                  if(!row)return false;
                  const cells=row.querySelectorAll('td');
                  return cells.length >= 6 && !cells[5].innerText.startsWith('0 / 0');
                }""",
                timeout=10000,
            )
            page.wait_for_function(
                """() => {
                  const row=[...document.querySelectorAll('#laneTable tbody tr')]
                    .find(row=>row.innerText.includes('地球地表'));
                  if(!row)return false;
                  const cells=row.querySelectorAll('td');
                  return cells.length >= 5 && parseFloat(cells[4].innerText) > 0;
                }""",
                timeout=10000,
            )

            # Preserve transport latency: flows remain in transit until their
            # arrival tick, then leave the Cargo Flow table after inventory
            # admission while the Fleet allocation itself remains configured.
            runtime.execute(AdvanceTime(2))
            page.wait_for_function(
                """projectId => ![...document.querySelectorAll('#cargoTable tbody tr')]
                  .some(row => row.innerText.includes(projectId))""",
                arg=project_id,
                timeout=10000,
            )
            assert "1 unit" in allocation_row.inner_text()

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run_ci_suite_or_standalone("logistics_ui", run)
