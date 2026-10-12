"""Local test outcome reports only authoritative pytest exit results."""

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import local_test_run


def test_pytest_exit_codes_are_authoritative_even_if_status_was_polled_early(tmp_path, monkeypatch):
    monkeypatch.setattr(local_test_run, "RUNS", tmp_path)
    run_id = "20261009T000000Z-abcdef01"
    directory = tmp_path / run_id
    directory.mkdir()
    command = [sys.executable, "-m", "pytest", "-q", "tests"]
    (directory / "request.json").write_text(json.dumps({"command": command}))
    (directory / "pid").write_text("1")

    with patch.object(local_test_run, "_alive", return_value=True):
        with patch.object(local_test_run, "print") as output:
            local_test_run._status(run_id)
    pending = json.loads(output.call_args.args[0])
    assert pending["status"] == "running" and pending["result"] is None

    for exit_code, expected in ((0, "passed"), (1, "failed")):
        completed = subprocess.CompletedProcess(command, exit_code)
        with patch.object(local_test_run.subprocess, "run", return_value=completed) as runner:
            local_test_run._worker(run_id)
        assert runner.call_args.args[0] == command
        with patch.object(local_test_run, "print") as output:
            local_test_run._status(run_id)
        status = json.loads(output.call_args.args[0])
        assert status["status"] == expected
        assert status["result"]["exit_code"] == exit_code
        (directory / "result.json").unlink()





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
