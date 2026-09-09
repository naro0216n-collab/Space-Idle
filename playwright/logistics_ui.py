from __future__ import annotations

import os
from pathlib import Path
from threading import Thread
import tempfile
import time

from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.simulation import OfflineProgressPolicy

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Playwright is required for logistics UI E2E") from exc


EARTH = "base.node.earth_surface"
LEO = "base.node.low_earth_orbit"
SOUTH_POLE = "base.node.south_polar_ridge"
STRUCTURAL_COMPONENTS = "base.resource.structural_components"
OWNED_LAUNCH_VEHICLE = "base.vehicle.reusable_launch_vehicle"
DIRECT_LUNAR_SERVICE = "base.transport_service.commercial_earth_lunar_direct"


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


def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-logistics-ui-")
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=0.35),
    )
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_server(origin)
        with sync_playwright() as p:
            browser = getattr(p, browser_name).launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1194, "height": 834},
                has_touch=True,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
            )
            page = context.new_page()
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            page.get_by_role("button", name="物流ネットワーク").click()

            # Lane is the recurring player-facing logistics configuration. Verify
            # that its resource-agnostic capacity controls are operable before
            # exercising the separate one-off CargoOrder path below.
            page.get_by_role("button", name="Laneを作成").click()
            page.locator("#laneDialog").wait_for(state="visible", timeout=10000)
            page.locator("#laneSource").select_option(EARTH)
            page.locator("#laneDestination").select_option(LEO)
            page.locator("#laneCapacity").fill("1")
            page.get_by_role("button", name="Lane作成").click()
            page.locator("#laneDialog").wait_for(state="hidden", timeout=10000)
            lane_row = page.locator("[data-lane-row]").first
            lane_row.wait_for(timeout=10000)
            lane_text = lane_row.inner_text()
            assert "1" in lane_text and "t/日" in lane_text, "lane UI did not expose configured capacity"
            assert page.get_by_role("heading", name="Resource Demand").count() == 1

            page.get_by_role("button", name="単発資源輸送").click()
            page.locator("#cargoDialog").wait_for(state="visible", timeout=10000)

            # Vehicle choice is part of the transport plan, not an implicit hidden
            # allocator. Earth -> LEO must expose the owned launch vehicle as a
            # selectable mode alongside any purchased service.
            page.locator("#cargoSource").select_option(EARTH)
            page.locator("#cargoDestination").select_option(LEO)
            page.locator('[data-cargo-route-mode]').first.wait_for(timeout=10000)
            launch_mode = page.locator(f'[data-cargo-route-mode] option[value="{OWNED_LAUNCH_VEHICLE}"]')
            assert launch_mode.count() > 0, "cargo UI did not expose the owned launch vehicle"
            assert not launch_mode.first.is_disabled(), "owned launch vehicle was visible but not selectable"

            # Re-plan the reported problematic movement through the same UI. Find
            # the route-plan option that exposes the direct commercial Earth-to-
            # lunar-surface service and select that service explicitly.
            page.locator("#cargoDestination").select_option(SOUTH_POLE)
            page.locator("#cargoAmount").fill("0.1")
            page.locator("#cargoResource").select_option(STRUCTURAL_COMPONENTS)
            page.locator("#cargoPlan").wait_for(timeout=10000)

            direct_found = False
            for value in page.locator("#cargoPlan option").evaluate_all("opts => opts.map(o => o.value)"):
                page.locator("#cargoPlan").select_option(value)
                page.wait_for_timeout(50)
                direct = page.locator(f'[data-cargo-route-mode] option[value="{DIRECT_LUNAR_SERVICE}"]')
                if direct.count() and not direct.first.is_disabled():
                    direct.first.locator("xpath=..").select_option(DIRECT_LUNAR_SERVICE)
                    direct_found = True
                    break
            assert direct_found, "Earth-to-south-pole plan did not expose an executable direct transport service"

            page.get_by_role("button", name="輸送登録").click()
            page.locator("#cargoDialog").wait_for(state="hidden", timeout=10000)

            order_id = page.wait_for_function(
                """async ([dest, mode]) => {
                  const payload = await fetch('/api/v1/logistics/orders').then(r => r.json());
                  const row = payload.data.items.find(o => o.owner_kind === 'player' && o.destination_id === dest && o.route_modes.some(pair => pair[1] === mode));
                  return row?.id || false;
                }""",
                arg=[SOUTH_POLE, DIRECT_LUNAR_SERVICE],
                timeout=10000,
            ).json_value()
            assert order_id, "UI submission did not persist the selected transport mode on CargoOrder"

            page.wait_for_function(
                """async ([orderId, mode]) => {
                  const payload = await fetch('/api/v1/logistics/missions').then(r => r.json());
                  return payload.data.items.some(m => m.order_id === orderId && m.mode_id === mode);
                }""",
                arg=[order_id, DIRECT_LUNAR_SERVICE],
                timeout=10000,
            )
            page.wait_for_function(
                """async orderId => {
                  const payload = await fetch('/api/v1/logistics/orders').then(r => r.json());
                  const row = payload.data.items.find(o => o.id === orderId);
                  return row?.status === 'complete' && row.delivered_t >= row.amount_t;
                }""",
                arg=order_id,
                timeout=15000,
            )

            cargo_text = page.locator("#cargoTable").inner_text()
            assert "手動輸送" in cargo_text, "player resource transport is not identified as resource logistics"
            assert "契約貨物" not in cargo_text, "contract cargo leaked into the resource-transport table"

            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
