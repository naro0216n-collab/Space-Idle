from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_DIR = ROOT / "playwright"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _write_workflow(path: Path, *, workflow_name: str, job: str, scenarios: list[str]) -> None:
    commands = "\n".join(f"          python playwright/{name}.py" for name in scenarios)
    path.write_text(
        f"""name: {workflow_name}

jobs:
  {job}:
    runs-on: ubuntu-latest
    steps:
      - name: Browser scenarios
        run: |
{commands}
""",
        encoding="utf-8",
    )


def _configure_ci(monkeypatch, tmp_path: Path, workflow: Path, *, name: str, job: str) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", name)
    monkeypatch.setenv("GITHUB_JOB", job)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("SPACE_IDLE_CI_WORKFLOW_FILE", str(workflow))


def test_suite_runner_accepts_new_scenario_modules_without_registry_changes(
    monkeypatch, tmp_path, capsys
) -> None:
    runner = _load_module("space_idle_e2e_suite_test", PLAYWRIGHT_DIR / "run_suite.py")
    runner.PLAYWRIGHT_DIR = tmp_path
    imported: list[str] = []
    executed: list[str] = []

    for name in ("acceptance", "future_browser_contract"):
        (tmp_path / f"{name}.py").write_text("def run(): pass\n", encoding="utf-8")

    def fake_import(name: str):
        imported.append(name)
        return SimpleNamespace(run=lambda: executed.append(name))

    monkeypatch.setattr(runner.importlib, "import_module", fake_import)
    selected = ["acceptance", "future_browser_contract"]
    runner.run_scenarios(selected)

    assert imported == selected
    assert executed == selected
    output = capsys.readouterr().out
    assert "E2E suite bootstrap:" in output
    assert "each scenario owns a fresh browser process" in output
    assert "E2E suite complete: 2 scenario(s)" in output


def test_suite_runner_rejects_missing_or_non_runnable_modules(monkeypatch, tmp_path) -> None:
    runner = _load_module("space_idle_e2e_suite_validation_test", PLAYWRIGHT_DIR / "run_suite.py")
    runner.PLAYWRIGHT_DIR = tmp_path

    try:
        runner.run_scenarios(["missing_future_scenario"])
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing scenarios must fail instead of being silently skipped")

    (tmp_path / "future_scenario.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(runner.importlib, "import_module", lambda _name: SimpleNamespace(VALUE=1))
    try:
        runner.run_scenarios(["future_scenario"])
    except ValueError as exc:
        assert "callable run()" in str(exc)
    else:
        raise AssertionError("scenario modules without run() must fail closed")


def test_shared_chromium_launch_contract_prefers_explicit_runner_browser(monkeypatch) -> None:
    support = _load_module("space_idle_e2e_support_test", PLAYWRIGHT_DIR / "e2e_support.py")
    monkeypatch.setenv("SPACE_IDLE_CHROMIUM", "/ci/google-chrome")
    monkeypatch.setattr(support.shutil, "which", lambda _name: None)

    assert support.browser_launch_kwargs("chromium") == {
        "headless": True,
        "executable_path": "/ci/google-chrome",
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    assert support.browser_launch_kwargs("webkit") == {"headless": True}


def test_isolated_browser_context_always_owns_a_fresh_browser(monkeypatch) -> None:
    support = _load_module("space_idle_e2e_support_context_test", PLAYWRIGHT_DIR / "e2e_support.py")
    opened: list[object] = []

    class FakeContext:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeBrowser:
        def __init__(self):
            self.context = FakeContext()

        def new_context(self, **_options):
            return self.context

    from contextlib import contextmanager

    @contextmanager
    def fake_managed_browser(_browser_name):
        browser = FakeBrowser()
        opened.append(browser)
        yield browser

    monkeypatch.setattr(support, "managed_browser", fake_managed_browser)

    with support.isolated_browser_context("chromium", locale="ja-JP") as first:
        pass
    with support.isolated_browser_context("chromium", locale="ja-JP") as second:
        pass

    assert first is not second
    assert len(opened) == 2
    assert first.closed and second.closed


def test_ci_suite_is_derived_from_current_job_commands_including_future_additions(
    monkeypatch, tmp_path
) -> None:
    support = _load_module("space_idle_e2e_support_ci_test", PLAYWRIGHT_DIR / "e2e_support.py")
    workflow = tmp_path / "full-validation.yml"
    declared = ["acceptance", "interaction_continuity", "future_browser_contract"]
    _write_workflow(workflow, workflow_name="Full Validation", job="webkit-e2e", scenarios=declared)
    _configure_ci(
        monkeypatch,
        tmp_path,
        workflow,
        name="Full Validation",
        job="webkit-e2e",
    )

    executed: list[tuple[str, ...]] = []
    fake_runner = SimpleNamespace(run_scenarios=lambda names: executed.append(tuple(names)))
    monkeypatch.setitem(sys.modules, "run_suite", fake_runner)

    support.run_ci_suite_or_standalone("/repo/playwright/acceptance.py", lambda: None)

    assert executed == [tuple(declared)]
    assert support.guard_ci_secondary_entrypoint("interaction_continuity.py") is True
    assert support.guard_ci_secondary_entrypoint("future_browser_contract.py") is True


def test_ci_fails_closed_when_new_first_scenario_does_not_create_suite_marker(
    monkeypatch, tmp_path
) -> None:
    support = _load_module("space_idle_e2e_support_ci_guard_test", PLAYWRIGHT_DIR / "e2e_support.py")
    workflow = tmp_path / "full-validation.yml"
    _write_workflow(
        workflow,
        workflow_name="Full Validation",
        job="webkit-e2e",
        scenarios=["future_first", "acceptance", "logistics_ui"],
    )
    _configure_ci(
        monkeypatch,
        tmp_path,
        workflow,
        name="Full Validation",
        job="webkit-e2e",
    )

    try:
        support.guard_ci_secondary_entrypoint("acceptance.py")
    except RuntimeError as exc:
        assert "marker missing or inconsistent" in str(exc)
    else:
        raise AssertionError("a new unintegrated first scenario must fail instead of hiding coverage")


def test_fast_ci_remains_independent_even_as_its_scenario_list_changes(monkeypatch, tmp_path) -> None:
    support = _load_module("space_idle_e2e_support_fast_test", PLAYWRIGHT_DIR / "e2e_support.py")
    workflow = tmp_path / "ci.yml"
    _write_workflow(
        workflow,
        workflow_name="Fast CI",
        job="chromium-smoke",
        scenarios=["acceptance", "future_fast_smoke"],
    )
    _configure_ci(monkeypatch, tmp_path, workflow, name="Fast CI", job="chromium-smoke")

    assert support.ci_suite() is None
    assert support.guard_ci_secondary_entrypoint("future_fast_smoke.py") is False


def test_full_browser_jobs_derive_each_declared_suite_and_harness_contract() -> None:
    support = _load_module("space_idle_e2e_support_workflow_test", PLAYWRIGHT_DIR / "e2e_support.py")
    workflow = ROOT / ".github" / "workflows" / "full-validation.yml"

    suites = [
        support._declared_job_scenarios(workflow, "chromium-e2e"),
        support._declared_job_scenarios(workflow, "webkit-e2e"),
    ]
    assert all(suites)
    assert "full-validation.yml" in support.COALESCED_CI_WORKFLOW_FILES
    assert "ci.yml" not in support.COALESCED_CI_WORKFLOW_FILES

    # Every scenario declared in any coalesced browser job must adopt the generic
    # entrypoint contract. Browser-specific additions are allowed; an unintegrated
    # addition fails locally instead of silently restoring duplicate cold starts.
    for name in {name for suite in suites for name in suite}:
        scenario = (PLAYWRIGHT_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert "guard_ci_secondary_entrypoint(__file__)" in scenario
        assert "run_ci_suite_or_standalone(__file__, run)" in scenario
