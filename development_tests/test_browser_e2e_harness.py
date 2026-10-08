from __future__ import annotations

import ast
from contextlib import contextmanager
import importlib.util
import re
import shlex
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


def test_suite_runner_accepts_scenario_modules_without_registry_changes(
    monkeypatch, tmp_path, capsys
) -> None:
    runner = _load_module("space_idle_e2e_suite_test", PLAYWRIGHT_DIR / "run_suite.py")
    runner.PLAYWRIGHT_DIR = tmp_path
    imported: list[str] = []
    executed: list[tuple[str, object]] = []
    opened: list[object] = []

    for name in ("acceptance", "future_browser_contract"):
        (tmp_path / f"{name}.py").write_text("def run(*, browser=None): pass\n", encoding="utf-8")

    def fake_import(name: str):
        imported.append(name)
        return SimpleNamespace(run=lambda *, browser=None: executed.append((name, browser)))

    @contextmanager
    def fake_managed_lazy_browser(_browser_name):
        browser = object()
        opened.append(browser)
        yield browser

    monkeypatch.setattr(runner.importlib, "import_module", fake_import)
    monkeypatch.setattr(runner, "managed_lazy_browser", fake_managed_lazy_browser)
    selected = ["acceptance", "future_browser_contract"]
    runner.run_scenarios(selected)

    assert imported == selected
    assert len(opened) == 1
    assert executed == [(name, opened[0]) for name in selected]
    output = capsys.readouterr().out
    assert "E2E suite bootstrap:" in output
    assert "one lazily launched browser process with a fresh context per scenario" in output
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


def test_isolated_browser_context_standalone_owns_a_fresh_browser(monkeypatch) -> None:
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


def test_isolated_browser_context_reuses_suite_browser_without_relaunch(monkeypatch) -> None:
    support = _load_module("space_idle_e2e_support_reuse_test", PLAYWRIGHT_DIR / "e2e_support.py")

    class FakeContext:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeBrowser:
        def __init__(self):
            self.contexts: list[FakeContext] = []

        def new_context(self, **_options):
            context = FakeContext()
            self.contexts.append(context)
            return context

    @contextmanager
    def forbidden_managed_browser(_browser_name):
        raise AssertionError("suite-owned browser must not relaunch per scenario")
        yield

    monkeypatch.setattr(support, "managed_browser", forbidden_managed_browser)
    browser = FakeBrowser()

    with support.isolated_browser_context("chromium", browser=browser, locale="ja-JP") as first:
        pass
    with support.isolated_browser_context("chromium", browser=browser, locale="ja-JP") as second:
        pass

    assert first is not second
    assert browser.contexts == [first, second]
    assert first.closed and second.closed


def test_lazy_suite_browser_defers_launch_until_first_context(monkeypatch) -> None:
    support = _load_module("space_idle_e2e_support_lazy_test", PLAYWRIGHT_DIR / "e2e_support.py")
    events: list[str] = []

    class FakeContext:
        def close(self):
            events.append("context-close")

    class FakeBrowser:
        def new_context(self, **_options):
            events.append("context-open")
            return FakeContext()

        def close(self):
            events.append("browser-close")

    class FakeBrowserType:
        def launch(self, **_options):
            events.append("browser-launch")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeBrowserType()

        def stop(self):
            events.append("playwright-stop")

    class FakeManager:
        def start(self):
            events.append("playwright-start")
            return FakePlaywright()

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: FakeManager()),
    )

    with support.managed_lazy_browser("chromium") as browser:
        assert events == []
        with support.isolated_browser_context("chromium", browser=browser):
            assert events[:3] == ["playwright-start", "browser-launch", "context-open"]
        with support.isolated_browser_context("chromium", browser=browser):
            pass

    assert events.count("browser-launch") == 1
    assert events.count("context-open") == 2
    assert events[-2:] == ["browser-close", "playwright-stop"]


def test_monitored_page_fails_on_browser_specific_runtime_errors() -> None:
    support = _load_module("space_idle_e2e_support_monitor_test", PLAYWRIGHT_DIR / "e2e_support.py")

    class FakePage:
        def __init__(self):
            self.handlers = {}

        def on(self, event, handler):
            self.handlers[event] = handler

    page = FakePage()
    context = SimpleNamespace(new_page=lambda: page)

    try:
        with support.monitored_page(context):
            page.handlers["pageerror"](RuntimeError("broken browser handler"))
    except AssertionError as exc:
        assert "broken browser handler" in str(exc)
    else:
        raise AssertionError("browser runtime errors must fail the scenario")


def _runnable_browser_scenarios() -> set[str]:
    """The actual scenario entrypoints, not an old hand-maintained test list."""
    result = set()
    for path in PLAYWRIGHT_DIR.glob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
            for node in module.body
        ):
            result.add(path.stem)
    return result


def _workflow_browser_scenarios(workflow: Path, job: str, browser_name: str) -> set[str]:
    """Check the invocation actually wired to a CI job, not a comment/string."""
    source = workflow.read_text(encoding="utf-8")
    section = re.search(
        rf"(?ms)^  {re.escape(job)}:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)",
        source,
    )
    assert section is not None, f"Missing CI browser job: {job}"
    assert re.search(
        rf"(?m)^\s+SPACE_IDLE_BROWSER:\s*{re.escape(browser_name)}\s*$",
        section.group(1),
    ), f"{job} must select the intended browser engine"
    invocations = []
    for line in section.group(1).splitlines():
        if match := re.match(r"^\s+run:\s*(.*?)\s*$", line):
            args = shlex.split(match.group(1))
            if len(args) >= 2 and args[1] == "playwright/run_suite.py":
                assert args[0] in {"python", "python3"}
                invocations.append(args[2:])
    assert len(invocations) == 1, f"{job} must execute exactly one browser suite"
    scenarios = invocations[0]
    assert scenarios and len(scenarios) == len(set(scenarios))
    return set(scenarios)


def test_ci_browser_jobs_execute_the_runnable_scenarios_without_gaps() -> None:
    """No supported browser surface silently drops scenarios after suite changes."""
    workflows = ROOT / ".github" / "workflows"
    runnable = _runnable_browser_scenarios()
    assert runnable
    fast = _workflow_browser_scenarios(workflows / "ci.yml", "chromium-smoke", "chromium")
    full_chromium = _workflow_browser_scenarios(
        workflows / "full-validation.yml", "chromium-e2e", "chromium"
    )
    full_webkit = _workflow_browser_scenarios(
        workflows / "full-validation.yml", "webkit-e2e", "webkit"
    )
    assert fast and fast <= runnable
    assert full_chromium == full_webkit == runnable
    assert fast <= full_chromium
