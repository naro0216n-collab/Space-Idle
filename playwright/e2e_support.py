from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
from collections.abc import Iterator, Sequence
from typing import Any, Callable

CI_WORKFLOW_SUITES: dict[str, tuple[str, ...]] = {
    "Fast CI": ("acceptance", "lane_ui"),
    "Full Validation": ("acceptance", "interaction_continuity", "logistics_ui"),
}


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


def ci_suite() -> tuple[str, ...] | None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return None
    return CI_WORKFLOW_SUITES.get(os.environ.get("GITHUB_WORKFLOW", ""))


def _ci_marker_path() -> Path:
    root = Path(os.environ.get("RUNNER_TEMP") or os.environ.get("TMPDIR") or "/tmp")
    run_id = os.environ.get("GITHUB_RUN_ID", "run")
    job = os.environ.get("GITHUB_JOB", "job")
    return root / f"space-idle-e2e-{run_id}-{job}.json"


def _read_completed_ci_suite() -> tuple[str, ...] | None:
    path = _ci_marker_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("completed") is not True:
        return None
    suite = payload.get("suite")
    if not isinstance(suite, list) or not all(isinstance(name, str) for name in suite):
        return None
    return tuple(suite)


def guard_ci_secondary_entrypoint(scenario_name: str) -> bool:
    """Skip a later CI command only after the first command completed the suite.

    Existing workflow files invoke scenarios as separate Python commands. The first
    scenario coalesces the job into one process/browser; later commands reach this
    guard before importing the game and verify the completion marker instead of
    paying the cold-start cost again.
    """
    suite = ci_suite()
    if suite is None or scenario_name not in suite or scenario_name == suite[0]:
        return False
    completed = _read_completed_ci_suite()
    if completed != suite:
        raise RuntimeError(
            f"CI E2E suite marker missing or inconsistent before {scenario_name}: "
            f"expected {suite}, got {completed}"
        )
    print(f"E2E scenario already completed by shared CI suite: {scenario_name}", flush=True)
    return True


def run_ci_suite_or_standalone(scenario_name: str, standalone: Callable[[], Any]) -> Any:
    suite = ci_suite()
    if suite is None or scenario_name not in suite:
        return standalone()
    if scenario_name != suite[0]:
        raise RuntimeError(
            f"secondary CI E2E entrypoint {scenario_name} reached execution without guard"
        )

    from run_suite import run_scenarios

    result = run_scenarios(suite)
    marker = _ci_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(marker.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"completed": True, "suite": list(suite)}, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(marker)
    return result


@contextmanager
def managed_browser(browser_name: str) -> Iterator[Any]:
    """Launch one browser process and own its Playwright lifecycle."""
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
    """Create a fresh BrowserContext while optionally reusing a suite browser."""
    if browser is None:
        with managed_browser(browser_name) as owned_browser:
            context = owned_browser.new_context(**context_options)
            try:
                yield context
            finally:
                context.close()
        return

    context = browser.new_context(**context_options)
    try:
        yield context
    finally:
        context.close()
