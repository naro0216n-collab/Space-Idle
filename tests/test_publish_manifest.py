from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_manifest.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def run_manifest(repo: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def test_publish_manifest_tracks_only_changes_since_last_published_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    (repo / "b.txt").write_text("keep\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_manifest(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "c.txt").write_text("new\n", encoding="utf-8")
    (repo / "b.txt").unlink()
    commit_all(repo, "change")

    manifest = run_manifest(repo, "prepare")
    by_path = {item["path"]: item for item in manifest["changes"]}
    assert set(by_path) == {"a.txt", "b.txt", "c.txt"}
    assert by_path["a.txt"]["status"] == "M"
    assert by_path["b.txt"]["status"] == "D"
    assert by_path["b.txt"]["blob_sha"] is None
    assert by_path["c.txt"]["status"] == "A"
    assert manifest["base_remote_commit"] == base_commit
    assert manifest["base_remote_tree"] == base_tree
    assert manifest["target_tree"] == git(repo, "rev-parse", "HEAD^{tree}")

    published_commit = "1" * 40
    run_manifest(
        repo,
        "record",
        "--remote-commit",
        published_commit,
        "--remote-tree",
        manifest["target_tree"],
    )

    (repo / "c.txt").write_text("newer\n", encoding="utf-8")
    commit_all(repo, "next")
    next_manifest = run_manifest(repo, "prepare")
    assert next_manifest["base_remote_commit"] == published_commit
    assert {item["path"] for item in next_manifest["changes"]} == {"c.txt"}
