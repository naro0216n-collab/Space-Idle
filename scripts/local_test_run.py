"""Run long local validation commands beyond a caller's response deadline.

The command's process, log and final exit code live under the local Git directory.
This is a tool-facing launcher, not a replacement for pytest or CI.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import traceback


REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / ".git" / "local-test-runs"


def _write_json(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _start(command: list[str]) -> None:
    if not command:
        raise ValueError("provide the validation command after --")
    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    directory = RUNS / run_id
    directory.mkdir()
    _write_json(directory / "request.json", {"command": command, "started_at": _now()})
    detached = ({"start_new_session": True} if os.name != "nt" else
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS})
    worker = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_worker", run_id],
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **detached,
    )
    (directory / "pid").write_text(str(worker.pid) + "\n", encoding="ascii")
    (RUNS / "latest").write_text(run_id + "\n", encoding="ascii")
    print(json.dumps({"run_id": run_id, "pid": worker.pid,
                      "log": str(directory / "output.log"), "status": "running"}))


def _worker(run_id: str) -> None:
    directory = RUNS / run_id
    command = _read_json(directory / "request.json")["command"]
    assert isinstance(command, list)
    start = time.monotonic()
    exit_code = 127
    with (directory / "output.log").open("w", encoding="utf-8") as output:
        try:
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            exit_code = subprocess.run(command, cwd=REPO, stdout=output,
                                       stderr=subprocess.STDOUT, env=env, check=False).returncode
        except Exception:
            traceback.print_exc(file=output)
        finally:
            output.flush()
            _write_json(directory / "result.json", {
                "exit_code": exit_code,
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "finished_at": _now(),
            })


def _alive(pid: int) -> bool:
    if os.name == "nt":
        # On Windows os.kill(pid, 0) is not a portable existence probe.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
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
    directory = RUNS / run_id
    request = _read_json(directory / "request.json")
    result_path = directory / "result.json"
    pid = int((directory / "pid").read_text(encoding="ascii"))
    if result_path.exists():
        result = _read_json(result_path)
        state = "passed" if result["exit_code"] == 0 else "failed"
    else:
        result = None
        state = "running" if _alive(pid) else "interrupted"
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
    start.add_argument("command", nargs=argparse.REMAINDER)
    status = commands.add_parser("status")
    status.add_argument("run_id", nargs="?")
    worker = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("run_id")
    args = parser.parse_args()
    if args.action == "start":
        command = args.command[1:] if args.command and args.command[0] == "--" else args.command
        _start(command)
    elif args.action == "status":
        _status(args.run_id)
    else:
        _worker(args.run_id)


if __name__ == "__main__":
    main()
