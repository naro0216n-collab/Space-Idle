from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
from collections.abc import Iterator
from typing import Any, Callable


# Process coalescing is a runner-specific optimization policy, not a list of tests.
# The scenario set itself is derived from the current workflow job so additions or
# reordering cannot silently diverge from what CI declares it will execute.
COALESCED_CI_WORKFLOWS = frozenset({"Full Validation"})
_WORKFLOW_SCENARIO_RE = re.compile(
    r"^\s*python(?:3)?\s+playwright/([A-Za-z_][A-Za-z0-9_]*)\.py(?:\s.*)?$"
)


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


def _workflow_path() -> Path | None:
    explicit = os.environ.get("SPACE_IDLE_CI_WORKFLOW_FILE")
    if explicit:
        return Path(explicit)

    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    marker = "/.github/workflows/"
    if marker in workflow_ref:
        relative = ".github/workflows/" + workflow_ref.split(marker, 1)[1].split("@", 1)[0]
        return Path(__file__).resolve().parents[1] / relative

    workflow_name = os.environ.get("GITHUB_WORKFLOW", "")
    workflow_root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    if workflow_root.is_dir():
        for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
            try:
                first_lines = path.read_text(encoding="utf-8").splitlines()[:20]
            except OSError:
                continue
            if any(line.strip() == f"name: {workflow_name}" for line in first_lines):
                return path
    return None


def _job_block(workflow_text: str, job_name: str) -> tuple[str, ...]:
    """Return the raw YAML lines belonging to one top-level workflow job.

    This intentionally reads only the stable `jobs.<job>` indentation contract and
    does not attempt to implement YAML. Browser scenario commands are then extracted
    from `python playwright/<scenario>.py` lines in that job.
    """
    lines = workflow_text.splitlines()
    jobs_index = next((i for i, line in enumerate(lines) if line == "jobs:"), None)
    if jobs_index is None:
        return ()

    job_header = f"  {job_name}:"
    start = next((i for i in range(jobs_index + 1, len(lines)) if lines[i] == job_header), None)
    if start is None:
        return ()

    block: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            break
        block.append(line)
    return tuple(block)


def _declared_job_scenarios(path: Path, job_name: str) -> tuple[str, ...]:
    try:
        block = _job_block(path.read_text(encoding="utf-8"), job_name)
    except OSError as exc:
        raise RuntimeError(f"cannot read CI workflow {path}: {exc}") from exc

    scenarios = tuple(
        match.group(1)
        for line in block
        if (match := _WORKFLOW_SCENARIO_RE.match(line)) is not None
    )
    if len(scenarios) != len(set(scenarios)):
        raise RuntimeError(
            f"CI E2E job {job_name!r} declares duplicate browser scenario commands: {scenarios}"
        )
    return scenarios


def ci_suite() -> tuple[str, ...] | None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return None
    workflow_name = os.environ.get("GITHUB_WORKFLOW", "")
    if workflow_name not in COALESCED_CI_WORKFLOWS:
        return None

    job_name = os.environ.get("GITHUB_JOB", "")
    workflow = _workflow_path()
    if not job_name or workflow is None:
        raise RuntimeError(
            "coalesced CI E2E could not resolve its workflow job; "
            "GITHUB_JOB and workflow file are required"
        )
    scenarios = _declared_job_scenarios(workflow, job_name)
    if not scenarios:
        raise RuntimeError(
            f"coalesced CI E2E found no browser scenario commands in {workflow}:{job_name}"
        )
    return scenarios


def scenario_name(entrypoint: str | os.PathLike[str]) -> str:
    return Path(entrypoint).stem


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


def guard_ci_secondary_entrypoint(entrypoint: str | os.PathLike[str]) -> bool:
    """Skip a later CI command only after the declared job suite completed.

    The current workflow job is the source of truth for scenario membership and
    ordering. If a new scenario is inserted before the coalescing entrypoint but does
    not participate in this harness, the marker is absent and CI fails closed rather
    than silently omitting or duplicating coverage.
    """
    name = scenario_name(entrypoint)
    suite = ci_suite()
    if suite is None or name not in suite or name == suite[0]:
        return False
    completed = _read_completed_ci_suite()
    if completed != suite:
        raise RuntimeError(
            f"CI E2E suite marker missing or inconsistent before {name}: "
            f"expected {suite}, got {completed}"
        )
    print(f"E2E scenario already completed by shared CI suite: {name}", flush=True)
    return True


def run_ci_suite_or_standalone(
    entrypoint: str | os.PathLike[str], standalone: Callable[[], Any]
) -> Any:
    name = scenario_name(entrypoint)
    suite = ci_suite()
    if suite is None or name not in suite:
        return standalone()
    if name != suite[0]:
        raise RuntimeError(f"secondary CI E2E entrypoint {name} reached execution without guard")

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
def isolated_browser_context(browser_name: str, **context_options: Any) -> Iterator[Any]:
    """Create a fresh browser process and BrowserContext for one E2E scenario."""
    with managed_browser(browser_name) as browser:
        context = browser.new_context(**context_options)
        try:
            yield context
        finally:
            context.close()
