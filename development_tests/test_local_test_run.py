"""The local test launcher must preserve actual process results across invocations."""

import json
from pathlib import Path
import subprocess
import sys
import time


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local_test_run.py"


def _invoke(*args):
    output = subprocess.check_output([sys.executable, str(SCRIPT), *args], text=True)
    return json.loads(output)


def _wait_for(run_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = _invoke("status", run_id)
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("launcher did not return a completed test result")


def test_detached_test_run_preserves_success_and_failure_with_actual_exit_codes():
    success = _invoke("start", "--", sys.executable, "-c", "print('complete')")
    complete = _wait_for(success["run_id"])
    assert complete["status"] == "passed"
    assert complete["result"]["exit_code"] == 0
    assert "complete" in "\n".join(complete["output_tail"])

    failed = _invoke("start", "--", sys.executable, "-c", "import sys; sys.exit(7)")
    complete = _wait_for(failed["run_id"])
    assert complete["status"] == "failed"
    assert complete["result"]["exit_code"] == 7


def test_detached_test_run_remains_pending_after_launcher_returns():
    # The tool returns immediately while a test is still executing.
    started = _invoke("start", "--", sys.executable, "-c", "import time; time.sleep(1.5)")
    current = _invoke("status", started["run_id"])
    assert current["status"] == "running"
    assert _wait_for(started["run_id"])["status"] == "passed"
