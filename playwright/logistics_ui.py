from __future__ import annotations

from e2e_support import (
    guard_ci_secondary_entrypoint,
    isolated_browser_context,
    run_ci_suite_or_standalone,
)

if __name__ == "__main__" and guard_ci_secondary_entrypoint(__file__):
    raise SystemExit(0)

import os
from pathlib import Path
from threading import Thread
import tempfile
import time
import urllib.request

from space_idle import AdvanceTime, PlanBuild, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy


EARTH = str(ids.EARTH)
LEO = str(ids.LEO)
MACHINERY = str(ids.MACHINERY)
PROPELLANT = str(ids.PROPELLANT)
OWNED_LAUNCH_VEHICLE = str(ids.REUSABLE_LAUNCH_VEHICLE)


def _wait_for_server(origin: str, timeout: float = 10.0) -> None:
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


def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-logistics-ui-")
    runtime = GameRuntime(
        new_game_factory=_build_logistics_test_application,
        load_factory=build_game_application_for_load,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
    )
    runtime.set_time_control(paused=True)
    project_id = runtime.execute(
        PlanBuild(
            LEO,
            str(ids.ORBITAL_LOGISTICS_NODE),
            priority=5,
            procurement_policy="immediate",
        )
    ).data.created_id
    assert project_id is not None
    # Establish Supply Requirements before Fleet capacity exists. Auto-routing stays
    # within the player-built network; the browser flow below adds a sparse project
    # hard source constraint without mutating Fleet provisioning.
    runtime.execute(AdvanceTime(1))
    allocation_capacity = runtime._app._simulation.transport.transport_capacity_for_units(  # noqa: SLF001 - deterministic E2E fixture setup
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 1,
        day=runtime._app._simulation.day,  # noqa: SLF001
    )

    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_server(origin)
        with isolated_browser_context(
            browser_name,
            viewport={"width": 1194, "height": 834},
            has_touch=True,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        ) as context:
            page = context.new_page()
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            page.get_by_role("button", name="物流ネットワーク").click()

            requirement_row = page.locator("#requirementTable tbody tr", has_text=project_id).first
            requirement_row.wait_for(timeout=10000)
            assert "輸送能力阻害" in requirement_row.inner_text(), (
                "Supply Requirement must remain visible while Transport Capacity is unavailable"
            )
            # A project-scoped Supply Routing Constraint is sparse hard intent.
            # Setting it must not create strategic transport capacity or Fleet.
            requirement_row.locator("[data-requirement-constraint]").click()
            page.locator("#routingConstraintDialog").wait_for(state="visible", timeout=10000)
            assert page.locator("#routingConstraintOwnerId").input_value() == project_id
            assert page.locator("#routingConstraintDestination").input_value() == LEO
            page.locator("#routingConstraintSource").select_option(EARTH)
            page.get_by_role("button", name="Constraintを保存").click()
            page.locator("#routingConstraintDialog").wait_for(state="hidden", timeout=10000)
            page.wait_for_function(
                """projectId => [...document.querySelectorAll('#requirementTable tbody tr')]
                  .some(row => row.innerText.includes(projectId) && row.innerText.includes('hard: source'))""",
                arg=project_id,
                timeout=10000,
            )
            requirement_row = page.locator("#requirementTable tbody tr", has_text=project_id).first
            assert "地球" in requirement_row.inner_text(), "hard source constraint must be projected on the requirement"
            assert page.locator("#allocationTable [data-allocation-row]").count() == 0, (
                "Supply Routing Constraint must not create or resize Transport Allocation"
            )

            # Player Fleet provisioning is explicit and remains a separate decision.
            page.get_by_role("button", name="Transport Allocationを作成").click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
            page.locator("#allocationVehicle").select_option(OWNED_LAUNCH_VEHICLE)
            page.locator("#allocationSource").select_option(EARTH)
            page.locator("#allocationDestination").select_option(LEO)
            page.locator("#allocationForward").fill(str(allocation_capacity.forward_t_per_day))
            page.locator("#allocationReverse").fill(str(allocation_capacity.reverse_t_per_day))
            page.locator("#allocationPriority").select_option("5")
            page.get_by_role("button", name="Allocation作成").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)

            allocation_row = page.locator("#allocationTable [data-allocation-row]").first
            allocation_row.wait_for(timeout=10000)
            allocation_text = allocation_row.inner_text()
            assert "方向別Capacity target" in allocation_text
            assert "1 / 1" in allocation_text and "unfilled 0" in allocation_text
            nominal_text = allocation_row.locator("td").nth(3).inner_text()
            available_text = allocation_row.locator("td").nth(4).inner_text()
            assert "t/日" in nominal_text and not nominal_text.startswith("0 / 0")
            assert "t/日" in available_text and not available_text.startswith("0 / 0")
            assert "1 / 1" in allocation_row.inner_text(), (
                "Supply Routing Constraint must not resize derived Fleet provisioning"
            )

            # A canonical day lets Supply Planning consume the now-available capacity.
            runtime.execute(AdvanceTime(1))
            page.wait_for_function(
                """projectId => [...document.querySelectorAll('#cargoTable tbody tr')]
                  .some(row => row.innerText.includes(projectId))""",
                arg=project_id,
                timeout=10000,
            )
            cargo_text = page.locator("#cargoTable").inner_text()
            assert "in_transit" in cargo_text
            assert "1 / 1" in allocation_row.inner_text()

            # Target Stock is a persistent Supply Planning intent with Activity Priority.
            page.get_by_role("button", name="Target Stockを設定").click()
            page.locator("#targetStockDialog").wait_for(state="visible", timeout=10000)
            page.locator("#targetStockDestination").select_option(LEO)
            page.locator("#targetStockResource").select_option(PROPELLANT)
            page.locator("#targetStockQuantity").fill("2")
            page.locator("#targetStockPriority").select_option("4")
            page.get_by_role("button", name="Target Stockを保存").click()
            page.locator("#targetStockDialog").wait_for(state="hidden", timeout=10000)
            target_delete = page.locator(
                f'[data-target-stock-delete="{LEO}"][data-resource-id="{PROPELLANT}"]'
            )
            target_delete.wait_for(timeout=10000)
            target_row = target_delete.locator("xpath=ancestor::tr")
            target_text = target_row.inner_text()
            assert "2" in target_text and "高" in target_text
            assert "1 / 1" in allocation_row.inner_text(), (
                "Target Stock must not mutate Transport Allocation target"
            )

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run_ci_suite_or_standalone(__file__, run)
