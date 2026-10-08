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


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def write_source_snapshot(
    repo: Path, directory: Path, *, publish_commit: str | None = None,
) -> Path:
    """Construct the actual publish-base metadata and bundle for a test repository."""
    directory.mkdir()
    develop = git(repo, "rev-parse", "refs/heads/develop")
    develop_tree = git(repo, "rev-parse", f"{develop}^{{tree}}")
    publish = publish_commit or develop
    publish_tree = git(repo, "rev-parse", f"{publish}^{{tree}}")
    git(repo, "update-ref", "refs/space-idle/publish-base", publish)
    for name, value in (
        (".source-commit", develop),
        (".source-tree", develop_tree),
        (".source-branch", "develop"),
        (".source-publish-commit", publish),
        (".source-publish-tree", publish_tree),
    ):
        (directory / name).write_text(value + "\n", encoding="utf-8")
    git(
        repo, "bundle", "create", str(directory / "repository.bundle"),
        "refs/heads/develop", "refs/space-idle/publish-base",
    )
    return directory
