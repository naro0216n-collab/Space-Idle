from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType


def load_script(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(
    module: ModuleType,
    script: Path,
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    argv = [str(script), *args]
    stdout = StringIO()
    stderr = StringIO()
    previous_argv = sys.argv
    previous_cwd = Path.cwd()
    sys.argv = argv
    os.chdir(repo)
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                result = module.main()
                returncode = 0 if result is None else int(result)
            except SystemExit as exc:
                returncode = 0 if exc.code is None else int(exc.code)
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)

    completed = subprocess.CompletedProcess(
        args=argv,
        returncode=returncode,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )
    if check and returncode != 0:
        raise subprocess.CalledProcessError(
            returncode,
            argv,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed
