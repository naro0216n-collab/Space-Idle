"""Single local pytest entry point with durable process results.

A tool response deadline never determines the outcome of pytest.  Start a run,
then inspect its durable status by run ID.  CI owns its own process lifecycle.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import traceback


REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / ".git" / "local-test-runs"
_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}\Z")


def _write_json(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _directory(run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("invalid local test run ID")
    return RUNS / run_id


def _start(pytest_args: list[str]) -> None:
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    if pytest_args and pytest_args[0] in ("python", "python3", "pytest", sys.executable):
        raise ValueError("pass pytest arguments only; this entry point owns the pytest command")
    command = [sys.executable, "-m", "pytest", *pytest_args]
    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    directory = _directory(run_id)
    directory.mkdir()
    _write_json(directory / "request.json", {"command": command, "started_at": _now()})
    detached = ({"start_new_session": True} if os.name != "nt" else
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS})
    try:
        worker = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_worker", run_id],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **detached,
        )
    except OSError as exc:
        _write_json(directory / "result.json", {
            "status": "error", "reason": f"worker launch: {exc}", "finished_at": _now(),
        })
        raise
    (directory / "pid").write_text(str(worker.pid) + "\n", encoding="ascii")
    (RUNS / "latest").write_text(run_id + "\n", encoding="ascii")
    print(json.dumps({"run_id": run_id, "pid": worker.pid,
                      "log": str(directory / "output.log"), "status": "running"}))


def _worker(run_id: str) -> None:
    directory = _directory(run_id)
    command = _read_json(directory / "request.json")["command"]
    start = time.monotonic()
    with (directory / "output.log").open("w", encoding="utf-8") as output:
        try:
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            completed = subprocess.run(command, cwd=REPO, stdout=output,
                                       stderr=subprocess.STDOUT, env=env, check=False)
        except Exception as exc:
            traceback.print_exc(file=output)
            result = {"status": "error", "reason": f"pytest launch: {exc}"}
        else:
            result = {
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
            }
        finally:
            output.flush()
            _write_json(directory / "result.json", {
                **result,
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "finished_at": _now(),
            })


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _status(run_id: str | None) -> None:
    if run_id is None:
        run_id = (RUNS / "latest").read_text(encoding="ascii").strip()
    directory = _directory(run_id)
    request = _read_json(directory / "request.json")
    result_path = directory / "result.json"
    result = _read_json(result_path) if result_path.exists() else None
    pid_path = directory / "pid"
    pid = int(pid_path.read_text(encoding="ascii")) if pid_path.exists() else None
    state = result["status"] if result is not None else (
        "running" if pid is None or _alive(pid) else "interrupted"
    )
    log_path = directory / "output.log"
    if log_path.exists():
        with log_path.open(encoding="utf-8", errors="replace") as log_file:
            tail = [line.rstrip("\n") for line in deque(log_file, maxlen=8)]
    else:
        tail = []
    print(json.dumps({"run_id": run_id, "status": state, "pid": pid,
                      "command": request["command"], "result": result,
                      "log": str(log_path), "output_tail": tail}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start")
    start.add_argument("pytest_args", nargs=argparse.REMAINDER)
    status = commands.add_parser("status")
    status.add_argument("run_id", nargs="?")
    worker = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("run_id")
    args = parser.parse_args()
    if args.action == "start":
        _start(args.pytest_args)
    elif args.action == "status":
        _status(args.run_id)
    else:
        _worker(args.run_id)


if __name__ == "__main__":
    main()
