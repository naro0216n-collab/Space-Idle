from __future__ import annotations

import base64
import gzip
import hashlib
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_request.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def run_request(repo: Path, *args: str) -> str:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def parse_request(manifest: str, chunk_dir: Path) -> tuple[dict[str, str], str]:
    headers: dict[str, str] = {}
    for line in manifest.splitlines():
        if line.startswith("# "):
            key, sep, value = line[2:].partition(": ")
            if sep:
                headers[key] = value
    chunk_count = int(headers["chunk-count"])
    payload_parts = []
    for index in range(chunk_count):
        chunk = (chunk_dir / f"{index:04d}.txt").read_text(encoding="ascii").strip()
        assert hashlib.sha256(chunk.encode("ascii")).hexdigest() == headers[f"chunk-{index:04d}-sha256"]
        payload_parts.append(chunk)
    patch = gzip.decompress(base64.b64decode("".join(payload_parts), validate=True)).decode("utf-8")
    return headers, patch


def test_publish_request_recreates_exact_target_tree_and_tracks_next_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    (repo / "b.txt").write_text("keep\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "c.txt").write_text("new\n", encoding="utf-8")
    (repo / "b.txt").unlink()
    commit_all(repo, "coherent change")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    published_local_ref = git(repo, "rev-parse", "HEAD")
    request_path = tmp_path / "publish-request.patch"
    run_request(
        repo, "prepare", "--target-branch", "temp", "--target-ref", published_local_ref,
        "--output", str(request_path),
    )
    headers, patch = parse_request(request_path.read_text(encoding="utf-8"), Path(f"{request_path}.chunks"))
    assert headers["version"] == "3"
    assert headers["patch-encoding"] == "gzip-base64-chunks"
    assert headers["target-branch"] == "temp"
    assert headers["base-sha"] == base_commit
    assert headers["target-tree"] == target_tree
    assert headers["patch-sha256"] == hashlib.sha256(patch.encode("utf-8")).hexdigest()
    assert base64.b64decode(headers["message-b64"]).decode("utf-8") == "coherent change\n"

    apply_repo = tmp_path / "apply"
    git(tmp_path, "clone", str(repo), str(apply_repo))
    git(apply_repo, "checkout", "--detach", base_commit)
    patch_path = tmp_path / "request.patch"
    patch_path.write_text(patch, encoding="utf-8", newline="")
    git(apply_repo, "apply", "--index", "--binary", str(patch_path))
    assert git(apply_repo, "write-tree") == target_tree

    published_commit = "1" * 40
    run_request(
        repo,
        "record",
        "--remote-commit",
        published_commit,
        "--remote-tree",
        target_tree,
        "--local-ref",
        published_local_ref,
    )

    (repo / "c.txt").write_text("newer\n", encoding="utf-8")
    commit_all(repo, "next")
    next_path = tmp_path / "next-request.patch"
    run_request(repo, "prepare", "--output", str(next_path))
    next_headers, next_patch = parse_request(next_path.read_text(encoding="utf-8"), Path(f"{next_path}.chunks"))
    assert next_headers["base-sha"] == published_commit
    assert "a/a.txt" not in next_patch
    assert "b/b.txt" not in next_patch
    assert "a/c.txt" in next_patch
