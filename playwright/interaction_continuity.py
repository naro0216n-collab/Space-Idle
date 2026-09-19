from __future__ import annotations

from e2e_support import isolated_browser_context, monitored_page, wait_for_server

import os
from pathlib import Path
from threading import Thread
import tempfile

from space_idle import build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.simulation import OfflineProgressPolicy
from space_idle.version import VERSION



def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-interaction-")
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=0.35),
    )
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        wait_for_server(origin)
        with isolated_browser_context(
            browser_name,
            viewport={"width": 1194, "height": 834},
        ) as context, monitored_page(context) as page:
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            assert page.locator("#appVersion").inner_text() == f"v{VERSION}"

            # Verify research-tree selection and navigation survive automatic
            # snapshots without relying on the removed Theory allocation control.
            page.locator('.primary-nav-button[data-section="research"]').click()
            tree = page.locator("#researchTree")
            tree.wait_for(timeout=10000)
            assert page.locator("#researchTree .research-node").count() > 0
            first_research = page.locator('#researchTree [data-inspect="research"]').first
            first_research.click()
            research_title = page.locator("#inspectorTitle").inner_text()
            scroller = page.locator("#researchTreeScroll")
            scroll_metrics = page.evaluate(
                "el => ({width: el.clientWidth, scrollWidth: el.scrollWidth})", scroller.element_handle()
            )
            assert scroll_metrics["scrollWidth"] > scroll_metrics["width"]
            page.evaluate("el => { el.scrollLeft = 180; el.dispatchEvent(new Event('scroll')); }", scroller.element_handle())
            initial_tree_scroll = page.evaluate("el => el.scrollLeft", scroller.element_handle())
            assert initial_tree_scroll > 0

            start_day = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) >= d + 2",
                arg=start_day,
                timeout=10000,
            )
            assert page.locator(".tab-button.is-active").get_attribute("data-tab") == "research"
            assert page.locator("#inspectorTitle").inner_text() == research_title
            assert page.locator("#researchTree .research-node.is-selected").count() == 1
            tree_scroll_after = page.evaluate("el => el.scrollLeft", page.locator("#researchTreeScroll").element_handle())
            assert tree_scroll_after >= initial_tree_scroll - 2

            # A live editable control must keep its unsaved value and focus while
            # the authoritative clock refreshes the surrounding projection.
            page.locator('.primary-nav-button[data-section="location"]').click()
            page.locator('[data-tab="facilities"]').click()
            first_facility = page.locator('tr[data-inspect="facility"]').first
            first_facility.click()
            inspector_title = page.locator("#inspectorTitle").inner_text()
            priority = page.locator("#facilityPriorityInput")
            priority.wait_for(timeout=10000)
            saved_priority = priority.input_value()
            draft_priority = "4" if saved_priority != "4" else "5"
            priority.select_option(draft_priority)
            priority.focus()
            start_day = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) >= d + 3",
                arg=start_day,
                timeout=10000,
            )
            assert page.locator(".tab-button.is-active").get_attribute("data-tab") == "facilities"
            assert page.locator("#inspectorTitle").inner_text() == inspector_title
            assert priority.is_visible()
            assert priority.input_value() == draft_priority
            assert page.evaluate("() => document.activeElement?.id || ''") == "facilityPriorityInput"

            # Save/Load is a browser wiring contract: the UI action must persist the
            # authoritative state and a later load must replace local/updated state.
            page.locator("#saveButton").click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            page.locator('[data-set-facility-activity-priority]').click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            assert priority.input_value() == draft_priority
            page.locator("#loadButton").click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            priority = page.locator("#facilityPriorityInput")
            priority.wait_for(timeout=10000)
            assert priority.input_value() == saved_priority
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
