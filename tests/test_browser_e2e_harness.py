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


def test_suite_runner_reuses_one_process_without_dropping_scenarios(monkeypatch, capsys) -> None:
    runner = _load_module("space_idle_e2e_suite_test", PLAYWRIGHT_DIR / "run_suite.py")
    imported: list[str] = []
    executed: list[str] = []

    shared_browser = object()

    def fake_import(name: str):
        imported.append(name)
        return SimpleNamespace(run=lambda *, browser: executed.append((name, browser)))

    class FakeBrowserManager:
        def __enter__(self):
            return shared_browser

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(runner, "managed_browser", lambda _browser_name: FakeBrowserManager())

    monkeypatch.setattr(runner.importlib, "import_module", fake_import)
    selected = ["acceptance", "interaction_continuity", "logistics_ui"]
    runner.run_scenarios(selected)

    assert imported == selected
    assert executed == [(name, shared_browser) for name in selected]
    output = capsys.readouterr().out
    assert "E2E suite bootstrap:" in output
    assert "E2E browser ready: chromium" in output
    assert "E2E suite complete: 3 scenario(s)" in output


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


def test_isolated_browser_context_reuses_browser_but_not_context(monkeypatch) -> None:
    support = _load_module("space_idle_e2e_support_context_test", PLAYWRIGHT_DIR / "e2e_support.py")

    class FakeContext:
        def __init__(self, marker):
            self.marker = marker
            self.closed = False

        def close(self):
            self.closed = True

    class FakeBrowser:
        def __init__(self):
            self.contexts = []

        def new_context(self, **options):
            context = FakeContext((len(self.contexts), options))
            self.contexts.append(context)
            return context

    browser = FakeBrowser()
    with support.isolated_browser_context("chromium", browser=browser, locale="ja-JP") as first:
        assert first.marker == (0, {"locale": "ja-JP"})
    with support.isolated_browser_context("chromium", browser=browser, locale="ja-JP") as second:
        assert second.marker == (1, {"locale": "ja-JP"})

    assert first is not second
    assert first.closed and second.closed
    assert len(browser.contexts) == 2


def test_ci_entrypoint_coalesces_existing_workflow_commands(monkeypatch, tmp_path) -> None:
    support = _load_module("space_idle_e2e_support_ci_test", PLAYWRIGHT_DIR / "e2e_support.py")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Full Validation")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_JOB", "webkit-e2e")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    executed: list[tuple[str, ...]] = []
    fake_runner = SimpleNamespace(run_scenarios=lambda names: executed.append(tuple(names)))
    monkeypatch.setitem(sys.modules, "run_suite", fake_runner)

    support.run_ci_suite_or_standalone("acceptance", lambda: (_ for _ in ()).throw(AssertionError()))

    expected = ("acceptance", "interaction_continuity", "logistics_ui")
    assert executed == [expected]
    assert support.guard_ci_secondary_entrypoint("interaction_continuity") is True
    assert support.guard_ci_secondary_entrypoint("logistics_ui") is True


def test_ci_secondary_entrypoint_refuses_to_skip_without_completed_suite(monkeypatch, tmp_path) -> None:
    support = _load_module("space_idle_e2e_support_ci_guard_test", PLAYWRIGHT_DIR / "e2e_support.py")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Full Validation")
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    monkeypatch.setenv("GITHUB_JOB", "webkit-e2e")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    try:
        support.guard_ci_secondary_entrypoint("interaction_continuity")
    except RuntimeError as exc:
        assert "marker missing or inconsistent" in str(exc)
    else:
        raise AssertionError("secondary entrypoint must not silently skip without a completed suite")


def test_ci_browser_jobs_preserve_scenario_coverage_for_shared_entrypoint() -> None:
    fast = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    full = (ROOT / ".github" / "workflows" / "full-validation.yml").read_text()
    support = _load_module("space_idle_e2e_support_workflow_test", PLAYWRIGHT_DIR / "e2e_support.py")

    assert "python playwright/acceptance.py\n          python playwright/lane_ui.py" in fast
    full_sequence = (
        "python playwright/acceptance.py\n"
        "          python playwright/interaction_continuity.py\n"
        "          python playwright/logistics_ui.py"
    )
    assert full.count(full_sequence) == 2

    # Fast CI deliberately keeps its two scripts independent: on the Linux runner,
    # sharing one browser made the measured smoke step slower.
    assert "Fast CI" not in support.CI_WORKFLOW_SUITES
    assert support.CI_WORKFLOW_SUITES["Full Validation"] == (
        "acceptance",
        "interaction_continuity",
        "logistics_ui",
    )

    # Fast still selects runner Chrome when available; Full's existing unconditional
    # Playwright install remains a workflow-level cost, but scenario launch itself now
    # prefers the same real runner browser through e2e_support.
    selector = 'browser="$(command -v google-chrome || command -v chromium || true)"'
    assert selector in fast
    assert "python -m playwright install --with-deps chromium" in full

    # Full Validation retains independent WebKit coverage and the same scenario set.
    assert "python -m playwright install webkit" in full
    assert "SPACE_IDLE_BROWSER: webkit" in full
