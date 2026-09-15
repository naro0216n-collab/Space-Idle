from __future__ import annotations

from e2e_support import guard_ci_secondary_entrypoint, run_ci_suite_or_standalone
from logistics_ui import run


if __name__ == "__main__" and guard_ci_secondary_entrypoint(__file__):
    raise SystemExit(0)


if __name__ == "__main__":
    run_ci_suite_or_standalone(__file__, run)
