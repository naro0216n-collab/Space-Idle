"""Fast CI: actual browser wiring, not a second execution of full acceptance.

Domain transitions, trade/fleet conservation and long-running gameplay belong to
Python contracts. Full UI journeys and engine-specific rendering remain in Full
Validation's Chromium/WebKit scenarios.
"""
from __future__ import annotations

from pathlib import Path
from threading import Thread
import tempfile

from e2e_support import isolated_browser_context, monitored_page, wait_for_server
from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.bootstrap import build_game_application_for_load


def run(browser) -> None:
    with tempfile.TemporaryDirectory(prefix="space-idle-browser-smoke-") as directory:
        runtime = GameRuntime(
            new_game_factory=build_game_application,
            load_factory=build_game_application_for_load,
            save_dir=Path(directory) / "saves",
        )
        runtime.set_time_control(paused=True)
        server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            wait_for_server(origin)
            with isolated_browser_context(
                browser,
                viewport={"width": 1194, "height": 834},
                has_touch=True,
            ) as context, monitored_page(context) as page:
                page.goto(origin + "/", wait_until="load", timeout=30000)
                page.locator("#connectionState.is-ok").wait_for(timeout=10000)
                assert page.locator("#globalView").is_visible()
                assert page.locator("#systemMapStage [data-system-node-id]").count() > 0

                # An actual touch selection must connect the Map to the Inspector,
                # and the selected context must cross into the Transport canvas.
                node = page.locator("#systemMapStage [data-system-node-id]").first
                node_id = node.get_attribute("data-system-node-id")
                assert node_id
                node.tap()
                assert node.get_attribute("aria-pressed") == "true"
                page.locator('#globalInspectorContent [data-open-node-logistics]').click()
                page.locator("#logisticsView").wait_for(state="visible", timeout=10000)
                assert page.locator(
                    f'#systemMapStage [data-system-node-id="{node_id}"]'
                ).is_visible()
                assert page.locator("#networkDecisionContext").is_visible()

                # Time Control must be a real browser -> HTTP -> rendered-state
                # round trip, not merely a button present in the DOM.
                with page.expect_response(
                    lambda response: response.request.method == "POST"
                    and response.url.endswith("/api/v1/time-control"),
                    timeout=10000,
                ) as time_response:
                    page.locator("#timePauseButton").click()
                assert time_response.value.ok
                page.wait_for_function(
                    "() => document.querySelector('#timePauseButton')?.getAttribute('aria-pressed') === 'false'",
                    timeout=10000,
                )
                page.locator('.primary-nav-button[data-section="research"]').click()
                page.locator("#researchTree .research-node").first.wait_for(timeout=10000)
                page.locator('.primary-nav-button[data-section="location"]').click()
                assert page.locator("#operationsView").is_visible()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
