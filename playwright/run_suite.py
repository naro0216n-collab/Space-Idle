from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import sys
import time
from collections.abc import Sequence
from types import ModuleType


_SCENARIO_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLAYWRIGHT_DIR = Path(__file__).resolve().parent


def _load_scenario(name: str) -> ModuleType:
    if not _SCENARIO_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid E2E scenario name: {name!r}")
    path = PLAYWRIGHT_DIR / f"{name}.py"
    if not path.is_file():
        raise ValueError(f"E2E scenario module does not exist: {path.name}")
    module = importlib.import_module(name)
    run = getattr(module, "run", None)
    if not callable(run):
        raise ValueError(f"E2E scenario module {path.name} does not expose callable run()")
    return module


def run_scenarios(names: Sequence[str]) -> None:
    if not names:
        raise ValueError("at least one E2E scenario is required")
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate E2E scenarios are not allowed: {', '.join(names)}")

    bootstrap_started = time.monotonic()
    modules = [_load_scenario(name) for name in names]
    bootstrap_elapsed = time.monotonic() - bootstrap_started
    print(f"E2E suite bootstrap: {bootstrap_elapsed:.3f}s", flush=True)

    import os

    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    print(
        f"E2E suite browser: {browser_name}; each scenario owns a fresh browser process",
        flush=True,
    )

    suite_started = time.monotonic()
    for name, module in zip(names, modules, strict=True):
        scenario_started = time.monotonic()
        print(f"E2E scenario start: {name}", flush=True)
        result = module.run()
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        scenario_elapsed = time.monotonic() - scenario_started
        print(f"E2E scenario complete: {name} ({scenario_elapsed:.3f}s)", flush=True)

    suite_elapsed = time.monotonic() - suite_started
    total_elapsed = time.monotonic() - bootstrap_started
    print(
        f"E2E suite complete: {len(names)} scenario(s), "
        f"scenario_time={suite_elapsed:.3f}s total={total_elapsed:.3f}s",
        flush=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)
    try:
        run_scenarios(names)
    except ValueError as exc:
        print(f"E2E suite configuration error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
