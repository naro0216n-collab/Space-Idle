from __future__ import annotations

import importlib
import json
import os
import sys
import time
from collections.abc import Sequence


AVAILABLE_SCENARIOS = {
    "acceptance": "acceptance",
    "interaction_continuity": "interaction_continuity",
    "lane_ui": "lane_ui",
    "logistics_ui": "logistics_ui",
}


def run_scenarios(names: Sequence[str]) -> None:
    if not names:
        raise ValueError("at least one E2E scenario is required")

    unknown = [name for name in names if name not in AVAILABLE_SCENARIOS]
    if unknown:
        raise ValueError(
            f"unknown E2E scenario(s): {', '.join(unknown)}; "
            f"available: {', '.join(AVAILABLE_SCENARIOS)}"
        )

    bootstrap_started = time.monotonic()
    modules = [importlib.import_module(AVAILABLE_SCENARIOS[name]) for name in names]
    bootstrap_elapsed = time.monotonic() - bootstrap_started
    print(f"E2E suite bootstrap: {bootstrap_elapsed:.3f}s", flush=True)

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
