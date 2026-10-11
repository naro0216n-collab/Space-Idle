"""Local test outcome reports only authoritative pytest exit results."""

import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from scripts import local_test_run


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


def test_pytest_entrypoint_preserves_success_and_failure(tmp_path):
    test_file = tmp_path / "test_outcome.py"
    test_file.write_text("def test_success():\n    assert True\n", encoding="utf-8")
    success = _invoke("start", "--", "-q", str(test_file))
    completed = _wait_for(success["run_id"])
    assert completed["status"] == "passed"
    assert completed["result"]["exit_code"] == 0
    assert completed["command"][:3] == [sys.executable, "-m", "pytest"]
    assert "1 passed" in "\n".join(completed["output_tail"])

    test_file.write_text("def test_failure():\n    assert False\n", encoding="utf-8")
    failed = _wait_for(_invoke("start", "--", "-q", str(test_file))["run_id"])
    assert failed["status"] == "failed"
    assert failed["result"]["exit_code"] == 1
    assert "1 failed" in "\n".join(failed["output_tail"])



def test_tool_response_is_not_a_pytest_result(tmp_path):
    test_file = tmp_path / "test_slow.py"
    test_file.write_text("import time\ndef test_slow():\n    time.sleep(1.5)\n", encoding="utf-8")
    started = _invoke("start", "--", "-q", str(test_file))
    current = _invoke("status", started["run_id"])
    assert current["status"] == "running"
    assert current["result"] is None
    assert _wait_for(started["run_id"])["status"] == "passed"


def test_runner_launch_errors_do_not_fabricate_pytest_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(local_test_run, "RUNS", tmp_path)
    run_id = "20261009T000000Z-abcdef01"
    directory = tmp_path / run_id
    directory.mkdir()
    (directory / "request.json").write_text(json.dumps({"command": [sys.executable, "-m", "pytest"]}))
    with patch.object(local_test_run.subprocess, "run", side_effect=OSError("cannot launch")):
        local_test_run._worker(run_id)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert "exit_code" not in result

    (directory / "result.json").unlink()
    (directory / "pid").write_text("99999999")
    with patch.object(local_test_run, "_alive", return_value=False):
        with patch.object(local_test_run, "print") as output:
            local_test_run._status(run_id)
    assert json.loads(output.call_args[0][0])["status"] == "interrupted"

def test_entrypoint_rejects_nested_commands_and_bad_run_ids():
    with pytest.raises(ValueError, match="pytest arguments only"):
        local_test_run._start(["python", "-m", "pytest", "-q"])
    with pytest.raises(ValueError, match="invalid local test run ID"):
        local_test_run._directory("../../test")
