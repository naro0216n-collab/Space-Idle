from __future__ import annotations

from contextlib import contextmanager
import os
import shutil
import time
from collections.abc import Iterator
from typing import Any
import urllib.request


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


class LazyBrowser:
    """Lazily launch one browser process when the first scenario needs a context.

    The suite can share a browser without paying cold-start before a scenario has
    prepared its deterministic runtime and HTTP server. Each scenario still owns
    a fresh BrowserContext, so browser state remains isolated.
    """

    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._playwright_manager: Any | None = None
        self._playwright: Any | None = None
        self._browser: Any | None = None

    def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - developer environment guard
            raise RuntimeError(
                "Playwright is required for browser E2E. Install with: pip install -e '.[e2e]'"
            ) from exc

        manager = sync_playwright()
        playwright = manager.start()
        try:
            browser = getattr(playwright, self.browser_name).launch(
                **browser_launch_kwargs(self.browser_name)
            )
        except Exception:
            playwright.stop()
            raise
        self._playwright_manager = manager
        self._playwright = playwright
        self._browser = browser
        return browser

    def new_context(self, **context_options: Any) -> Any:
        return self._ensure_browser().new_context(**context_options)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright_manager = None
            self._playwright = None


@contextmanager
def managed_lazy_browser(browser_name: str) -> Iterator[LazyBrowser]:
    """Own one suite browser, launching it only at the first context request."""
    browser = LazyBrowser(browser_name)
    try:
        yield browser
    finally:
        browser.close()


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
    browser_name: str,
    *,
    browser: Any | None = None,
    **context_options: Any,
) -> Iterator[Any]:
    """Create a fresh BrowserContext, reusing a suite browser when supplied.

    Scenario state remains isolated at the BrowserContext and HTTP-runtime layers.
    Standalone scenario execution still owns a browser process, while the suite
    runner can avoid paying process startup once per scenario.
    """
    if browser is not None:
        context = browser.new_context(**context_options)
        try:
            yield context
        finally:
            context.close()
        return

    with managed_browser(browser_name) as owned_browser:
        context = owned_browser.new_context(**context_options)
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
