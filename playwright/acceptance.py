from __future__ import annotations

from e2e_support import (
    guard_ci_secondary_entrypoint,
    isolated_browser_context,
    run_ci_suite_or_standalone,
)

if __name__ == "__main__" and guard_ci_secondary_entrypoint(__file__):
    raise SystemExit(0)

import http.client
import json
import os
from pathlib import Path
from threading import Thread
import tempfile
import time
from urllib.parse import urlsplit

from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("SPACE_IDLE_ARTIFACTS", ROOT / "playwright" / "artifacts")).resolve()
FAKE_ORIGIN = "https://space-idle.test"
SUPPORTED_BROWSERS = {"chromium", "webkit"}
SUPPORTED_TRANSPORTS = {"direct", "bridge"}


def _connection(origin: str, timeout: float) -> http.client.HTTPConnection:
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError(f"E2E local server must use http origin, got {origin!r}")
    return http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)


def _wait_for_server(url: str, timeout: float = 12.0) -> None:
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        conn = _connection(origin, 1.0)
        try:
            conn.request("GET", path, headers={"Connection": "close"})
            response = conn.getresponse()
            response.read()
            if response.status == 200:
                return
        except Exception as exc:  # noqa: BLE001 - startup probe
            last_error = exc
        finally:
            conn.close()
        time.sleep(0.1)
    raise RuntimeError(f"development server did not become ready: {last_error}")


def _http_request(
    server_origin: str,
    path: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> dict[str, object]:
    forwarded = {}
    for key, value in (headers or {}).items():
        if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}:
            forwarded[key] = value
    forwarded["Accept-Encoding"] = "identity"
    data = body.encode("utf-8") if body is not None else None
    conn = _connection(server_origin, 15.0)
    try:
        conn.request(method, path, body=data, headers=forwarded)
        response = conn.getresponse()
        raw = response.read()
        status = response.status
        response_headers = response.getheaders()
    finally:
        conn.close()
    allowed = {
        "content-type",
        "cache-control",
        "etag",
        "x-space-idle-revision",
        "access-control-allow-origin",
        "vary",
    }
    return {
        "status": status,
        "headers": {key: value for key, value in response_headers if key.lower() in allowed},
        "body": raw.decode("utf-8"),
    }


def _browser_document(server_origin: str) -> str:
    index = _http_request(server_origin, "/")["body"]
    css = _http_request(server_origin, "/app.css")["body"]
    js = _http_request(server_origin, "/app.js")["body"]
    time_js = _http_request(server_origin, "/time_control.js")["body"]
    bridge = r"""
<script>
window.fetch = async function(input, init = {}) {
  const path = typeof input === 'string' ? input : input.url;
  const headers = Object.fromEntries(new Headers(init.headers || (typeof input === 'object' ? input.headers : undefined)).entries());
  const result = await window.__spaceIdleHttp({path, method: init.method || 'GET', headers, body: init.body == null ? null : String(init.body)});
  return new Response(result.body, {status: result.status, headers: result.headers});
};
</script>
"""
    index = index.replace('<link rel="stylesheet" href="/app.css">', f'<style>{css}</style>')
    index = index.replace('<script src="/app.js" defer></script>', bridge + f'<script>{js}</script>')
    index = index.replace('<script src="/time_control.js" defer></script>', f'<script>{time_js}</script>')
    return index


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _visible_button_min_height(page) -> float:
    return page.evaluate(
        """() => Math.min(...Array.from(document.querySelectorAll('button'))
          .filter(b => { const r=b.getBoundingClientRect(); const s=getComputedStyle(b); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; })
          .map(b => b.getBoundingClientRect().height))"""
    )


def run() -> dict[str, object]:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    transport = os.environ.get("SPACE_IDLE_E2E_TRANSPORT", "direct").strip().lower()
    if browser_name not in SUPPORTED_BROWSERS:
        raise ValueError(f"unsupported browser {browser_name!r}; expected one of {sorted(SUPPORTED_BROWSERS)}")
    if transport not in SUPPORTED_TRANSPORTS:
        raise ValueError(f"unsupported transport {transport!r}; expected one of {sorted(SUPPORTED_TRANSPORTS)}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-e2e-")
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=0.5),
    )
    # The browser test is about the upgrade decision surface and command path,
    # not about replaying the research progression. Prepare whichever initial
    # facility currently has a content-defined next upgrade by satisfying that
    # recipe's prerequisite technologies. No balance value or technology ID is
    # hard-coded into the acceptance fixture.
    fixture_sim = runtime._app._simulation
    upgrade_fixture = next(
        (
            (facility, recipe)
            for facility in sorted(fixture_sim.facilities.facilities.values(), key=lambda row: str(row.id))
            if (recipe := fixture_sim.projects.next_upgrade_recipe(facility.id)) is not None
        ),
        None,
    )
    if upgrade_fixture is None:
        raise AssertionError("base game must expose at least one facility upgrade for browser acceptance")
    _fixture_facility, fixture_recipe = upgrade_fixture
    fixture_sim.technology.completed.update(fixture_recipe.prerequisite_technologies)

    server = create_server(
        runtime,
        ApiServerConfig(host="127.0.0.1", port=0),
    )
    port = int(server.server_address[1])
    server_origin = f"http://127.0.0.1:{port}"
    server_thread = Thread(target=server.serve_forever, name="space-idle-e2e-http", daemon=True)
    server_thread.start()

    console_errors: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    results: dict[str, object] = {}
    try:
        _wait_for_server(f"{server_origin}/api/v1/health")
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with isolated_browser_context(
            browser_name,
                viewport={"width": 1194, "height": 834},
                screen={"width": 1194, "height": 834},
                has_touch=True,
                device_scale_factor=2,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                user_agent=(
                    "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            ) as context:
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("requestfailed", lambda req: request_failures.append(f"{req.method} {req.url}: {req.failure}"))
            if transport == "bridge":
                page.expose_function(
                    "__spaceIdleHttp",
                    lambda request: _http_request(
                        server_origin,
                        request.get("path", "/"),
                        request.get("method", "GET"),
                        request.get("headers") or {},
                        request.get("body"),
                    ),
                )
                page.set_content(_browser_document(server_origin), wait_until="load", timeout=30000)
            else:
                page.goto(server_origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)

            _assert(page.locator("#operationsView").is_visible(), "operations view should be visible by default")
            _assert(not page.locator("#logisticsView").is_visible(), "logistics view must not coexist with operations")
            _assert(page.locator(".location-button").count() > 0, "at least one spatial node must be rendered")
            viewport_metrics = page.evaluate("() => ({w: innerWidth, scroll: document.documentElement.scrollWidth})")
            _assert(viewport_metrics["scroll"] <= viewport_metrics["w"], "1194px landscape must not horizontally overflow")
            _assert(_visible_button_min_height(page) >= 44, "visible touch controls must be at least 44 CSS px high")

            _assert(page.locator("#timePauseButton").is_visible(), "automatic clock must expose pause control")
            _assert(page.locator('[data-time-speed="1"]').is_visible(), "1x speed control must be visible")
            _assert(page.locator('[data-time-speed="4"]').is_visible(), "4x speed control must be visible")
            _assert(page.locator('[data-time-speed="16"]').is_visible(), "16x speed control must be visible")
            _assert(page.get_by_role("button", name="+1日").count() == 0, "manual day-jump control must be removed")

            day_before = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) > d",
                arg=day_before,
                timeout=10000,
            )
            running_day = int(page.locator("#dayValue").inner_text().replace(",", ""))

            page.locator("#timePauseButton").click()
            page.wait_for_function(
                "() => document.querySelector('#timeState').textContent.includes('停止中')",
                timeout=10000,
            )
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            paused_day = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_timeout(1200)
            _assert(
                int(page.locator("#dayValue").inner_text().replace(",", "")) == paused_day,
                "paused automatic clock must not advance",
            )

            # Facility upgrades are ordinary construction projects. Verify the
            # decision surface and command path while the clock is paused so the
            # project cannot consume materials before we inspect it.
            page.locator('[data-tab="facilities"]').click()
            production_row = page.locator('tr[data-inspect="facility"]', has_text="基礎構造材工場")
            _assert(production_row.count() == 1, "opening production facility must be visible")
            production_row.click()
            production_text = page.locator("#inspectorContent").inner_text()
            _assert("生産物/日" in production_text, "facility inspector must expose configured production outputs")
            _assert("高性能構造部材" in production_text, "facility inspector must name the produced resource")
            _assert("投入/日" in production_text, "facility inspector must expose configured production inputs")
            facility_rows = page.locator('tr[data-inspect="facility"]')
            upgrade_button = None
            for index in range(facility_rows.count()):
                facility_rows.nth(index).click()
                candidate = page.locator('#inspectorContent [data-upgrade]')
                if candidate.count():
                    upgrade_button = candidate.first
                    break
            _assert(upgrade_button is not None, "at least one initial facility must expose a defined next upgrade")
            _assert(upgrade_button.is_visible(), "facility inspector must show the upgrade action")
            _assert(upgrade_button.is_enabled(), "unblocked facility upgrade action must be enabled")
            _assert("必要工数" in page.locator("#inspectorContent").inner_text(), "upgrade inspector must expose construction work")
            _assert("必要資源" in page.locator("#inspectorContent").inner_text(), "upgrade inspector must expose physical resource requirements")
            _assert(page.locator("#upgradePlanPriorityInput").is_visible(), "upgrade planning must expose priority before project creation")
            _assert(page.locator("#upgradePlanSourcingPolicy").is_visible(), "upgrade planning must expose sourcing policy before project creation")
            _assert(page.locator("#upgradePlanImportSource").is_visible(), "upgrade planning must expose preferred import source before project creation")
            page.locator("#upgradePlanPriorityInput").fill("73")
            # The form is a multi-field draft. Moving focus to another control
            # must not let periodic synchronization overwrite the first edit.
            page.locator("#upgradePlanSourcingPolicy").focus()
            page.wait_for_timeout(1200)
            _assert(
                page.locator("#upgradePlanPriorityInput").input_value() == "73",
                "non-focused construction planning drafts must survive periodic refresh",
            )
            page.locator("#upgradePlanSourcingPolicy").select_option("import_now")
            source_select = page.locator("#upgradePlanImportSource")
            source_values = source_select.locator("option").evaluate_all("opts => opts.map(o => o.value).filter(Boolean)")
            selected_source = source_values[0] if source_values else None
            if selected_source is not None:
                source_select.select_option(selected_source)
            # Unsaved planning values are client-owned drafts. A refresh with no
            # authoritative change must not silently reset them before submission.
            page.evaluate("async () => { await window.SpaceIdleApp.loadUiSnapshot(); }")
            _assert(page.locator("#upgradePlanPriorityInput").input_value() == "73", "upgrade planning priority must survive refresh")
            _assert(page.locator("#upgradePlanSourcingPolicy").input_value() == "import_now", "upgrade sourcing policy must survive refresh")
            if selected_source is not None:
                _assert(page.locator("#upgradePlanImportSource").input_value() == selected_source, "upgrade import source must survive refresh")
            upgrade_button = page.locator('#inspectorContent [data-upgrade]').first
            upgrade_button.click()
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            page.locator('[data-tab="construction"]').click()
            upgrade_rows = page.locator('tr[data-inspect="project"]', has_text="Upgrade")
            _assert(upgrade_rows.count() > 0, "upgrade command must create a construction project visible in the project list")
            upgrade_rows.first.click()
            inspector_text = page.locator("#inspectorContent").inner_text()
            _assert("Facility Upgrade" in inspector_text, "project inspector must retain typed upgrade target information")
            _assert("73" in page.locator("#projectPriorityInput").input_value(), "project inspector must retain the planned priority")
            _assert(page.locator("#projectSourcingPolicy").input_value() == "import_now", "project inspector must retain the planned sourcing policy")
            if selected_source is not None:
                _assert(page.locator("#projectImportSource").input_value() == selected_source, "project inspector must retain the planned preferred source")
            _assert(page.locator("#projectPriorityInput").is_enabled(), "mutable project priority must stay visible and enabled")
            _assert(page.locator("#projectWeightInput").is_enabled(), "mutable construction allocation must stay visible and enabled")
            _assert(page.locator("#projectSourcingPolicy").is_enabled(), "mutable sourcing policy must stay visible and enabled")
            page.locator("#projectPriorityInput").fill("82")
            page.locator('[data-set-project-priority]').click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            page.locator("#projectWeightInput").fill("2.5")
            page.locator('[data-set-project-weight]').click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            _assert(page.locator("#projectPriorityInput").input_value() == "82", "project priority command must round-trip through the UI")
            _assert(float(page.locator("#projectWeightInput").input_value()) == 2.5, "construction allocation command must round-trip through the UI")
            cancel_upgrade = page.locator('#inspectorContent [data-command="CancelBuild"]')
            _assert(cancel_upgrade.is_enabled(), "planned upgrade project must use ordinary construction cancellation")
            cancel_upgrade.click()
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            page.locator('[data-tab="overview"]').click()

            page.locator('[data-tab="research"]').click()
            research_rows = page.locator('#researchTree [data-inspect="research"]')
            _assert(research_rows.count() > 0, "research tree must expose research decisions")
            research_rows.first.click()
            _assert(page.locator('#inspectorContent [data-lifecycle-control="research"]').count() == 1, "research must expose one stable lifecycle control")
            page.locator('[data-tab="overview"]').click()

            page.locator('[data-tab="scientific-exploration"]').click()
            exploration_rows = page.locator('tr[data-inspect="scientific-exploration"]')
            _assert(exploration_rows.count() > 0, "scientific exploration campaign must be visible")
            exploration_rows.first.click()
            exploration_text = page.locator("#inspectorContent").inner_text()
            _assert("Mission Duration要件" in exploration_text, "exploration inspector must expose mission duration without redefining it as transit time")
            _assert("Minimum Payload" in exploration_text, "exploration inspector must expose minimum payload requirement")
            _assert("Vehicle Capability" in exploration_text, "exploration inspector must expose generic vehicle capability requirements")
            _assert("RP/日" in exploration_text, "exploration inspector must expose application-projected RP rate")
            _assert("軌道環境が必要" in exploration_text, "exploration inspector must expose site environment requirements")
            _assert("Operation:" in exploration_text, "exploration inspector must expose required operations")
            _assert("消耗資源:" in exploration_text, "exploration inspector must expose consumable resources")
            exploration_assign_buttons = page.locator('#inspectorContent [data-exploration-assign]')
            _assert(exploration_assign_buttons.count() > 0, "exploration inspector must keep vehicle assignment controls visible before campaign start")
            _assert(all(not exploration_assign_buttons.nth(i).is_enabled() for i in range(exploration_assign_buttons.count())), "vehicle assignment must remain disabled until the campaign exists")
            exploration_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="exploration"]')
            _assert(exploration_lifecycle.count() == 1, "exploration must expose one lifecycle control")
            _assert(exploration_lifecycle.get_attribute('data-exploration-action') == 'start' and exploration_lifecycle.is_enabled(), "campaign lifecycle control must expose start when startable")
            page.locator('[data-tab="overview"]').click()

            page.locator(f'[data-location-id="{ids.EARTH}"]').click()
            page.locator('[data-tab="survey"]').click()
            known_survey = page.locator(f'tr[data-inspect="survey"][data-id="{ids.WATER}"]')
            known_survey.wait_for(timeout=10000)
            _assert("完了" in known_survey.inner_text(), "initial knowledge must not appear as an active survey campaign")
            known_survey.click()
            known_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="survey"]')
            _assert(known_lifecycle.count() == 1, "survey must expose one stable lifecycle control")
            _assert(known_lifecycle.is_disabled() and "完了" in known_lifecycle.inner_text(), "completed initial knowledge must expose a disabled completed lifecycle state")

            page.locator(f'[data-location-id="{ids.SOUTH_POLAR_RIDGE}"]').click()
            page.locator('[data-tab="survey"]').click()
            survey_row = page.locator(f'tr[data-inspect="survey"][data-id="{ids.WATER}"]')
            survey_row.wait_for(timeout=10000)
            survey_row.click()
            _assert(page.locator('#surveyWeightInput').is_enabled(), "startable survey must expose initial allocation")
            _assert(float(page.locator('#surveyWeightInput').input_value()) == 1.0, "survey initial allocation must come from the application contract")
            page.locator('#surveyWeightInput').fill("0.5")
            survey_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="survey"]')
            _assert(survey_lifecycle.get_attribute('data-survey-action') == 'start', "unstarted survey lifecycle control must expose start")
            survey_lifecycle.click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            survey_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="survey"]')
            _assert(survey_lifecycle.get_attribute('data-survey-action') == 'pause' and survey_lifecycle.is_enabled(), "active survey lifecycle control must transition to pause")
            _assert(page.locator('#inspectorContent [data-set-survey-weight]').is_enabled(), "active survey must expose allocation command")
            _assert(float(page.locator('#surveyWeightInput').input_value()) == 0.5, "survey start allocation must round-trip through the UI")
            page.locator('[data-tab="overview"]').click()

            page.locator('[data-time-speed="4"]').click()
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            page.locator("#timePauseButton").click()
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) > d",
                arg=paused_day,
                timeout=10000,
            )
            rev_after = int(page.locator("#revisionValue").inner_text())
            page.screenshot(path=ARTIFACTS / "operations_landscape_1194x834.png", full_page=True)

            page.set_viewport_size({"width": 1180, "height": 820})
            page.wait_for_timeout(100)
            standard_ipad_metrics = page.evaluate("() => ({w: innerWidth, scroll: document.documentElement.scrollWidth})")
            _assert(
                standard_ipad_metrics["scroll"] <= standard_ipad_metrics["w"],
                "1180px full-size iPad landscape must not horizontally overflow",
            )

            page.get_by_role("button", name="物流ネットワーク").click()
            standard_logistics_metrics = page.evaluate("() => ({w: innerWidth, scroll: document.documentElement.scrollWidth})")
            _assert(
                standard_logistics_metrics["scroll"] <= standard_logistics_metrics["w"],
                "1180px full-size iPad logistics must not horizontally overflow",
            )
            page.set_viewport_size({"width": 1194, "height": 834})
            page.wait_for_timeout(100)
            _assert(page.locator("#logisticsView").is_visible(), "logistics view should be visible after switch")
            _assert(not page.locator("#operationsView").is_visible(), "operations view must be hidden after switch")
            route_buttons = page.locator(".route-button")
            _assert(route_buttons.count() > 0, "at least one route must be rendered")
            blocked = page.locator(".route-button", has=page.locator(".badge", has_text="未解禁"))
            (blocked.first if blocked.count() else route_buttons.first).click()
            page.locator("#routeInspectorContent .route-mode-card").first.wait_for(timeout=10000)
            _assert(
                page.locator("#routeInspectorTitle").inner_text() != "輸送路を選択",
                "route inspector should show selected route",
            )
            _assert(
                page.locator("#routeInspectorContent .route-mode-card").count() > 0,
                "selected route should expose transport modes",
            )
            issue_titles = page.locator("#routeInspectorContent .issue-title").all_inner_texts()
            _assert(all("base.tech." not in text for text in issue_titles), "technology IDs must not leak into blocker titles")
            _assert(all("technology:" not in text for text in issue_titles), "raw blocker prefixes must not leak into blocker titles")
            page.screenshot(path=ARTIFACTS / "logistics_landscape_1194x834.png", full_page=True)

            page.get_by_role("button", name="拠点運用").click()
            page.set_viewport_size({"width": 834, "height": 1194})
            page.wait_for_timeout(100)
            portrait = page.evaluate(
                """() => {
                  const view=document.querySelector('#operationsView');
                  const children=Array.from(view.children).map(x=>x.getBoundingClientRect());
                  return {
                    innerWidth,
                    scrollWidth: document.documentElement.scrollWidth,
                    display: getComputedStyle(view).display,
                    left0: children[0]?.left,
                    left1: children[1]?.left,
                    left2: children[2]?.left,
                    bodyText: document.body.innerText,
                  };
                }"""
            )
            _assert(portrait["scrollWidth"] >= 1180, "portrait must retain the landscape design width")
            _assert(portrait["display"] == "grid", "portrait must not switch to a stacked alternate layout")
            _assert(
                portrait["left0"] < portrait["left1"] < portrait["left2"],
                "portrait must preserve left/workspace/inspector order",
            )
            _assert("非対応" not in portrait["bodyText"], "portrait must not replace the UI with an unsupported notice")
            page.screenshot(path=ARTIFACTS / "operations_portrait_landscape_layout_834x1194.png", full_page=True)

            page.get_by_role("button", name="物流ネットワーク").click()
            portrait_logistics = page.evaluate(
                """() => {
                  const view=document.querySelector('#logisticsView');
                  const children=Array.from(view.children).map(x=>x.getBoundingClientRect());
                  return {
                    scrollWidth: document.documentElement.scrollWidth,
                    display: getComputedStyle(view).display,
                    left0: children[0]?.left, left1: children[1]?.left, left2: children[2]?.left
                  };
                }"""
            )
            _assert(
                portrait_logistics["scrollWidth"] >= 1180,
                "portrait logistics must retain the landscape design width",
            )
            _assert(
                portrait_logistics["display"] == "grid",
                "portrait logistics must not switch to a stacked layout",
            )
            _assert(
                portrait_logistics["left0"] < portrait_logistics["left1"] < portrait_logistics["left2"],
                "portrait logistics must preserve route/network/inspector order",
            )
            network_locations = page.locator("#networkNodes [data-network-location]")
            expected_network_locations = page.locator("#routeOriginFilter option").count() - 1
            _assert(
                network_locations.count() == expected_network_locations,
                "network must render every location exposed by the Application view",
            )
            network_positions = network_locations.evaluate_all(
                "rows => rows.map(row => { const node=row.closest('.network-node'); return `${node.style.left}:${node.style.top}`; })"
            )
            _assert(
                len(set(network_positions)) == len(network_positions),
                "network layout must give each rendered location a distinct position",
            )

            results = {
                "browser": browser_name,
                "transport": transport,
                "server": "in_process_http",
                "device_scale_factor": 2,
                "facility_upgrade_ui": True,
                "landscape_viewport": viewport_metrics,
                "standard_ipad_landscape": standard_ipad_metrics,
                "standard_ipad_logistics": standard_logistics_metrics,
                "portrait_scroll_width": portrait["scrollWidth"],
                "portrait_logistics_scroll_width": portrait_logistics["scrollWidth"],
                "route_count": route_buttons.count(),
                "issue_titles_checked": len(issue_titles),
                "day_before": day_before,
                "day_running": running_day,
                "day_after": int(page.locator("#dayValue").inner_text().replace(",", "")),
                "revision_after": rev_after,
                "console_errors": list(console_errors),
                "page_errors": list(page_errors),
                "request_failures": list(request_failures),
            }

        _assert(not console_errors, f"browser console errors: {console_errors}")
        _assert(not page_errors, f"page errors: {page_errors}")
        _assert(not request_failures, f"request failures: {request_failures}")
        (ARTIFACTS / "acceptance.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return results
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    result = run_ci_suite_or_standalone(__file__, run)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
