from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
from threading import Thread
import tempfile
import time
from urllib.parse import urlsplit

from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - developer environment guard
    raise SystemExit(
        "Playwright is required for E2E acceptance. Install with: pip install -e '.[e2e]'"
    ) from exc

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
    )
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
        with sync_playwright() as p:
            browser_type = getattr(p, browser_name)
            launch_kwargs: dict[str, object] = {"headless": True}
            if browser_name == "chromium":
                chromium = os.environ.get("SPACE_IDLE_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome")
                if chromium:
                    launch_kwargs["executable_path"] = chromium
                launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
            browser = browser_type.launch(**launch_kwargs)
            context = browser.new_context(
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
            )
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
            day_before = int(page.locator("#dayValue").inner_text().replace(",", ""))
            rev_before = int(page.locator("#revisionValue").inner_text())
            page.get_by_role("button", name="+1日").click()
            page.wait_for_function(
                "([d,r]) => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) > d && Number(document.querySelector('#revisionValue').textContent) > r",
                arg=[day_before, rev_before],
                timeout=15000,
            )
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

            results = {
                "browser": browser_name,
                "transport": transport,
                "server": "in_process_http",
                "device_scale_factor": 2,
                "landscape_viewport": viewport_metrics,
                "standard_ipad_landscape": standard_ipad_metrics,
                "standard_ipad_logistics": standard_logistics_metrics,
                "portrait_scroll_width": portrait["scrollWidth"],
                "portrait_logistics_scroll_width": portrait_logistics["scrollWidth"],
                "route_count": route_buttons.count(),
                "issue_titles_checked": len(issue_titles),
                "day_before": day_before,
                "day_after": int(page.locator("#dayValue").inner_text().replace(",", "")),
                "revision_before": rev_before,
                "revision_after": int(page.locator("#revisionValue").inner_text()),
                "console_errors": list(console_errors),
                "page_errors": list(page_errors),
                "request_failures": list(request_failures),
            }
            browser.close()

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
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
