from __future__ import annotations

import os
from pathlib import Path
import shutil
from threading import Thread
import tempfile
import time
import urllib.request

from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.simulation import OfflineProgressPolicy

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Playwright is required for lane UI E2E") from exc


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


def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-lane-ui-")
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
    )
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_server(origin)
        with sync_playwright() as p:
            browser_type = getattr(p, browser_name)
            launch_kwargs: dict[str, object] = {"headless": True}
            if browser_name == "chromium":
                executable = os.environ.get("SPACE_IDLE_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
                if executable:
                    launch_kwargs["executable_path"] = executable
                launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
            browser = browser_type.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": 1194, "height": 834})
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            page.get_by_role("button", name="物流ネットワーク").click()

            assert page.locator("#laneTable").is_visible()
            lane_headers = page.locator("#laneTable th").all_inner_texts()
            for required in ("要求容量", "実効容量", "本日使用", "待ち需要", "状態"):
                assert required in lane_headers, f"lane decision surface lacks {required}"
            demand_headers = page.locator("#demandTable th").all_inner_texts()
            for required in ("発生元", "資源", "要求", "輸送系内", "未充足"):
                assert required in demand_headers, f"demand decision surface lacks {required}"

            page.get_by_role("button", name="Laneを作成").click()
            page.locator("#laneDialog").wait_for(state="visible", timeout=10000)
            assert page.locator("#laneDialog #cargoResource").count() == 0
            options = page.locator("#laneSource option").evaluate_all("rows => rows.map(x => x.value)")
            assert len(options) >= 2
            page.locator("#laneSource").select_option(options[0])
            page.locator("#laneDestination").select_option(options[1])
            page.locator("#laneCapacity").fill("2")
            page.locator("#lanePriority").fill("70")
            page.get_by_role("button", name="Lane作成").click()
            page.locator("#laneDialog").wait_for(state="hidden", timeout=10000)
            page.locator("#laneTable tbody tr[data-lane-row]").first.wait_for(timeout=10000)
            row = page.locator("#laneTable tbody tr[data-lane-row]").first
            text = row.inner_text()
            assert "2 t/日" in text

            row.get_by_role("button", name="停止").click()
            page.wait_for_function(
                "() => document.querySelector('#laneTable tbody tr[data-lane-row]')?.innerText.includes('停止')",
                timeout=10000,
            )
            row = page.locator("#laneTable tbody tr[data-lane-row]").first
            row.get_by_role("button", name="再開").click()
            page.wait_for_function(
                "() => document.querySelector('#laneTable tbody tr[data-lane-row]') && !document.querySelector('#laneTable tbody tr[data-lane-row]').innerText.includes('手動停止')",
                timeout=10000,
            )

            page.locator("#laneTable tbody tr[data-lane-row]").first.get_by_role("button", name="削除").click()
            page.wait_for_function(
                "() => document.querySelectorAll('#laneTable tbody tr[data-lane-row]').length === 0",
                timeout=10000,
            )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
