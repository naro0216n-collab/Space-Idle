from __future__ import annotations

import os
from pathlib import Path
from threading import Thread
import tempfile
import time

from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.simulation import OfflineProgressPolicy
from space_idle.version import VERSION

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Playwright is required for interaction-continuity E2E") from exc


def _wait_for_server(origin: str, timeout: float = 10.0) -> None:
    import urllib.request

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{origin}/api/v1/health", timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - startup probe
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"server did not become ready: {last_error}")


def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-interaction-")
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
            assert page.locator("#appVersion").inner_text() == f"v{VERSION}", "UI version diverged from declared package version"

            page.locator('[data-tab="research"]').click()
            first_research = page.locator('#operationsTabContent [data-inspect="research"]').first
            first_research.wait_for(timeout=10000)
            first_research.click()
            inspector_title = page.locator("#inspectorTitle").inner_text()

            weight = page.locator("#researchWeightInput")
            weight.wait_for(timeout=10000)
            weight.fill("3.7")
            weight.focus()

            start_day = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) >= d + 3",
                arg=start_day,
                timeout=10000,
            )

            active_tab = page.locator(".tab-button.is-active")
            assert active_tab.get_attribute("data-tab") == "research", "automatic progress changed the active tab"
            assert page.locator("#inspectorTitle").inner_text() == inspector_title, "automatic progress cleared inspector selection"
            assert weight.is_visible(), "automatic progress removed the active inspector form"
            assert weight.input_value() == "3.7", "automatic progress overwrote an in-progress input"
            active_id = page.evaluate("() => document.activeElement?.id || ''")
            assert active_id == "researchWeightInput", "automatic progress stole input focus"

            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
