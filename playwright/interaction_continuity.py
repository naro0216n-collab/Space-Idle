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


def _priority_group(page, holder_selector: str):
    holder = page.locator(holder_selector)
    return holder.locator("xpath=ancestor::*[contains(@class,'priority-segment')][1]")


def _choose_priority(page, holder_selector: str, level: int | str):
    value = str(level)
    group = _priority_group(page, holder_selector)
    button = group.locator(f'[data-priority-choice="{value}"]')
    button.click()
    assert page.locator(holder_selector).input_value() == value
    return button



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

            # Top-level navigation is a view change, not a reset of the current
            # decision. Returning to research must restore its selected subject.
            page.locator('.primary-nav-button[data-section="location"]').click()
            page.locator('.primary-nav-button[data-section="research"]').click()
            assert page.locator("#inspectorTitle").inner_text() == research_title
            assert page.locator("#researchTree .research-node.is-selected").count() == 1

            # A structured-decision draft must keep its unsaved priority and focus
            # while the authoritative clock refreshes the surrounding projection.
            page.locator('.primary-nav-button[data-section="location"]').click()
            page.locator('[data-section-tab="location"][data-tab="construction"]').click()
            build_option = page.locator('[data-inspect="build-option"]').first
            build_option.wait_for(timeout=10000)
            build_option.click()
            inspector_title = page.locator("#inspectorTitle").inner_text()
            priority = page.locator("#buildPlanPriorityInput")
            priority.wait_for(timeout=10000, state="attached")
            saved_priority = priority.input_value()
            draft_priority = "4" if saved_priority != "4" else "5"
            priority_button = _choose_priority(page, "#buildPlanPriorityInput", draft_priority)
            priority_button.focus()
            start_day = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) >= d + 3",
                arg=start_day,
                timeout=10000,
            )
            assert page.locator(".tab-button.is-active").get_attribute("data-tab") == "construction"
            assert page.locator("#inspectorTitle").inner_text() == inspector_title
            assert _priority_group(page, "#buildPlanPriorityInput").is_visible()
            assert priority.input_value() == draft_priority
            assert page.evaluate("el => document.activeElement === el", priority_button.element_handle())

            # Structured Draft ownership is UI state, not DOM state. It must survive
            # leaving the decision surface entirely and returning later.
            assert page.locator("#activeDraftBar").is_visible()
            page.locator('[data-section-tab="location"][data-tab="inventory"]').click()
            assert page.locator("#activeDraftBar").is_visible()
            page.locator('[data-section-tab="location"][data-tab="construction"]').click()
            page.locator('[data-inspect="build-option"]').first.click()
            priority = page.locator("#buildPlanPriorityInput")
            priority.wait_for(timeout=10000, state="attached")
            assert priority.input_value() == draft_priority
            page.locator("#activeDraftDiscard").click()
            assert page.locator("#activeDraftBar").is_hidden()
            priority = page.locator("#buildPlanPriorityInput")
            priority.wait_for(timeout=10000, state="attached")
            assert priority.input_value() == saved_priority

            # Save/Load must restore authoritative state after a direct priority action.
            page.locator('[data-section-tab="location"][data-tab="facilities"]').click()
            first_facility = page.locator('[data-inspect="facility"]').first
            first_facility.click()
            facility_priority = page.locator("#facilityPriorityInput")
            facility_priority.wait_for(timeout=10000, state="attached")
            authoritative_priority = facility_priority.input_value()
            changed_priority = "4" if authoritative_priority != "4" else "5"
            page.locator("#saveButton").click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            _choose_priority(page, "#facilityPriorityInput", changed_priority)
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            assert page.locator("#facilityPriorityInput").input_value() == changed_priority
            page.locator("#loadButton").click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            facility_priority = page.locator("#facilityPriorityInput")
            facility_priority.wait_for(timeout=10000, state="attached")
            assert facility_priority.input_value() == authoritative_priority
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
