from __future__ import annotations

import json
import subprocess
from pathlib import Path

from development_tests.script_harness import load_script, run_script


ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "scripts" / "publish_control_maintenance.py"
CONTROL_MODULE = load_script(CONTROL, "space_idle_test_publish_control_maintenance")
CONTROL_PATHS = (
    ".github/workflows/publish-gateway.yml",
    "scripts/publish_gateway_payload.py",
    "scripts/publish_gateway_validate.py",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_script(CONTROL_MODULE, CONTROL, repo, *args, check=check)


def transaction(repo: Path) -> Path:
    return repo / ".git" / "space-idle-publish-control-maintenance-transaction"


def init_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    for path in CONTROL_PATHS:
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"base {path}\n", encoding="utf-8")
        if path.startswith("scripts/"):
            file.chmod(0o755)
    commit_all(repo, "base control plane")
    base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    for path in CONTROL_PATHS:
        file = repo / path
        file.write_text(f"updated {path}\n", encoding="utf-8")
    commit_all(repo, "updated control plane")
    return repo, base, base_tree


def expected_oids(repo: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in CONTROL_PATHS:
        result[path] = git(repo, "rev-parse", f"HEAD:{path}")
    return result


def test_control_maintenance_uses_fixed_publish_scope_and_staged_git_data(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    prepared = json.loads(run(repo, "prepare").stdout)
    assert prepared["target_branch"] == "publish"
    assert prepared["control_paths"] == list(CONTROL_PATHS)

    plan = json.loads(run(
        repo,
        "connector-plan",
        "--target-remote-head", base,
        "--target-remote-tree", base_tree,
    ).stdout)
    assert plan["stage"] == "uploads-planned"
    assert len(plan["upload_packets"]) == len(CONTROL_PATHS)
    assert "copy/paste" in plan["next"]

    oids = expected_oids(repo)
    for packet_path in plan["upload_packets"]:
        packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_blob"
        assert packet["action_args"]["repository_full_name"] == "naro0216n-collab/Space-Idle"
        assert packet["action_args"]["encoding"] == "utf-8"
        assert packet["expected_blob_git_oid"] == oids[packet["control_path"]]

    blob_args: list[str] = []
    for path, oid in oids.items():
        blob_args.extend(["--blob", f"{path}={oid}"])
    tree = json.loads(run(repo, "connector-tree", *blob_args).stdout)
    tree_packet = json.loads(Path(tree["tree_packet"]).read_text(encoding="utf-8"))
    assert tree_packet["action"] == "GitHub.create_tree"
    assert tree_packet["action_args"]["base_tree_sha"] == base_tree
    assert {entry["path"] for entry in tree_packet["action_args"]["tree_elements"]} == set(CONTROL_PATHS)

    created_tree = "a" * 40
    commit = json.loads(run(repo, "connector-commit", "--tree-sha", created_tree).stdout)
    commit_packet = json.loads(Path(commit["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["parent_sha"] == base
    assert commit_packet["action_args"]["tree_sha"] == created_tree

    created_commit = "b" * 40
    update = json.loads(run(
        repo,
        "connector-update",
        "--commit-sha", created_commit,
        "--commit-tree-sha", created_tree,
        "--commit-parent-sha", base,
    ).stdout)
    update_packet = json.loads(Path(update["update_packet"]).read_text(encoding="utf-8"))
    assert update_packet["action"] == "GitHub.update_ref"
    assert update_packet["action_args"]["branch_name"] == "publish"
    assert update_packet["action_args"]["force"] is False

    verified = json.loads(run(
        repo,
        "verify-remote",
        "--remote-head", created_commit,
        "--remote-tree", created_tree,
    ).stdout)
    assert verified["verified"] is True
    assert not transaction(repo).exists()


def test_control_tree_rejects_any_blob_oid_mismatch(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    run(repo, "prepare")
    run(repo, "connector-plan", "--target-remote-head", base, "--target-remote-tree", base_tree)
    oids = expected_oids(repo)
    blob_args: list[str] = []
    for index, (path, oid) in enumerate(oids.items()):
        blob_args.extend(["--blob", f"{path}={'f' * 40 if index == 1 else oid}"])
    result = run(repo, "connector-tree", *blob_args, check=False)
    assert result.returncode != 0
    assert "control blob OID mismatch" in result.stderr
    assert not (transaction(repo) / "connector" / "assemble-control-tree.json").exists()


def test_control_maintenance_rejects_dirty_or_duplicate_transaction(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "scratch.txt").write_text("dirty\n", encoding="utf-8")
    dirty = run(repo, "prepare", check=False)
    assert dirty.returncode != 0
    assert "clean worktree" in dirty.stderr
    (repo / "scratch.txt").unlink()
    run(repo, "prepare")
    duplicate = run(repo, "prepare", check=False)
    assert duplicate.returncode != 0
    assert "active publish control maintenance transaction" in duplicate.stderr


def test_gateway_control_files_remain_small_independent_handoff_units() -> None:
    sizes = {path: (ROOT / path).stat().st_size for path in CONTROL_PATHS}
    assert max(sizes.values()) < 12 * 1024
