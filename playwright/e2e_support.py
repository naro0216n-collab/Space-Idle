from __future__ import annotations

from contextlib import contextmanager
import os
import shutil
import time
from collections.abc import Iterator
from typing import Any
import urllib.request


def priority_group(root: Any, holder_selector: str) -> Any:
    holder = root.locator(holder_selector)
    return holder.locator("xpath=ancestor::*[contains(@class,'priority-segment')][1]")


def choose_priority(root: Any, holder_selector: str, level: int | str) -> Any:
    """Use the same visible priority control contract in every browser scenario."""
    value = str(level)
    holder = root.locator(holder_selector)
    group = priority_group(root, holder_selector)
    button = group.locator(f'[data-priority-choice="{value}"]')
    button.click()
    assert holder.input_value() == value
    return button


def browser_launch_kwargs(browser_name: str) -> dict[str, object]:
    """Return the shared browser launch contract for E2E scenarios."""
    launch_kwargs: dict[str, object] = {"headless": True}
    if browser_name == "chromium":
        executable = (
            os.environ.get("SPACE_IDLE_CHROMIUM")
            or shutil.which("google-chrome")
            or shutil.which("chromium")
        )
        if executable:
            launch_kwargs["executable_path"] = executable
        launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
    return launch_kwargs


def wait_for_server(origin: str, timeout: float = 10.0) -> None:
    """Wait for the real HTTP adapter used by browser scenarios."""
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


@contextmanager
def managed_browser(browser_name: str) -> Iterator[Any]:
    """Launch one real browser process and own its Playwright lifecycle."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - developer environment guard
        raise RuntimeError(
            "Playwright is required for browser E2E. Install with: pip install -e '.[e2e]'"
        ) from exc

    with sync_playwright() as playwright:
        browser = getattr(playwright, browser_name).launch(**browser_launch_kwargs(browser_name))
        try:
            yield browser
        finally:
            browser.close()


@contextmanager
def isolated_browser_context(
    browser: Any,
    **context_options: Any,
) -> Iterator[Any]:
    """Isolate scenario storage and pages using a fresh BrowserContext."""
    context = browser.new_context(**context_options)
    try:
        yield context
    finally:
        context.close()


@contextmanager
def monitored_page(context: Any) -> Iterator[Any]:
    """Create a page and fail a successful scenario on browser/runtime errors.

    Domain assertions remain in their owning test layers. This guard is intentionally
    browser-specific: uncaught JavaScript errors, failed requests, and console errors
    are failures even when the scenario's final DOM assertion still happens to pass.
    """
    console_errors: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    page = context.new_page()
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on(
        "requestfailed",
        lambda req: request_failures.append(f"{req.method} {req.url}: {req.failure}"),
    )
    yield page
    if console_errors or page_errors or request_failures:
        raise AssertionError(
            "browser runtime errors: "
            f"console={console_errors}, page={page_errors}, requests={request_failures}"
        )
