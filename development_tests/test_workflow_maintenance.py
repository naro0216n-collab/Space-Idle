from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "scripts" / "publish_request.py"
MAINTENANCE = ROOT / "scripts" / "workflow_maintenance.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def run(script: Path, repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def init_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\non: workflow_dispatch\n", encoding="utf-8")
    (repo / "game.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    run(PUBLISH, repo, "init", "--remote-commit", base, "--remote-tree", tree)
    return repo, base, tree


def test_workflow_maintenance_is_a_separate_clear_entrypoint() -> None:
    maintenance_help = subprocess.run(
        [sys.executable, str(MAINTENANCE), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    publish_help = subprocess.run(
        [sys.executable, str(PUBLISH), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert ".github/workflows-only" in maintenance_help
    assert "Normal source/game changes belong to publish_request.py" in " ".join(maintenance_help.split())
    assert "workflow-maintenance" not in publish_help
    for forbidden in (
        "--github-repository",
        "--output-dir",
        "--connector-call-budget-bytes",
        "--target-branch",
    ):
        assert forbidden not in maintenance_help


def test_workflow_maintenance_prepare_rejects_nonworkflow_and_mixed_changes(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "game.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "game change")
    result = run(
        MAINTENANCE,
        repo,
        "prepare",
        "--output",
        str(tmp_path / "game.json"),
        check=False,
    )
    assert result.returncode != 0
    assert "workflow-only commits" in result.stderr
    assert "game.txt" in result.stderr

    git(repo, "reset", "--hard", "HEAD^")
    (repo / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8"
    )
    (repo / "game.txt").write_text("mixed\n", encoding="utf-8")
    commit_all(repo, "mixed change")
    mixed = run(
        MAINTENANCE,
        repo,
        "prepare",
        "--output",
        str(tmp_path / "mixed.json"),
        check=False,
    )
    assert mixed.returncode != 0
    assert "game.txt" in mixed.stderr


def test_workflow_maintenance_stages_packets_and_requires_rehydration_after_success(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    manifest = tmp_path / "maintenance.json"
    prepared = json.loads(run(MAINTENANCE, repo, "prepare", "--output", str(manifest)).stdout)
    assert prepared["kind"] == "workflow-maintenance"
    assert prepared["target_branch"] == "develop"
    assert prepared["workflow_paths"] == [".github/workflows/ci.yml"]

    plan_dir = Path(f"{manifest}.connector")
    plan = json.loads(
        run(
            MAINTENANCE,
            repo,
            "connector-plan",
            "--manifest",
            str(manifest),
            "--target-remote-head",
            base,
        ).stdout
    )
    assert plan["stage"] == "uploads-planned"
    assert plan["upload_call_count"] == 1
    upload_packet = json.loads(Path(plan["upload_packets"][0]).read_text(encoding="utf-8"))
    assert upload_packet["action_args"]["repository_full_name"] == "naro0216n-collab/Space-Idle"
    assert not (plan_dir / "assemble-workflow-tree.json").exists()
    assert not (plan_dir / "create-workflow-commit.json").exists()
    assert not (plan_dir / "advance-workflow-ref.json").exists()

    tree_meta = json.loads(run(MAINTENANCE, repo, "connector-tree", "--plan-dir", str(plan_dir)).stdout)
    assert tree_meta["stage"] == "tree-packet-ready"
    tree_packet = json.loads((plan_dir / "assemble-workflow-tree.json").read_text(encoding="utf-8"))
    assert tree_packet["expected_tree_git_oid"] == target_tree
    assert tree_packet["action_args"]["base_tree_sha"] == git(repo, "rev-parse", f"{base}^{{tree}}")
    assert not (plan_dir / "create-workflow-commit.json").exists()

    commit_meta = json.loads(
        run(
            MAINTENANCE,
            repo,
            "connector-commit",
            "--plan-dir",
            str(plan_dir),
            "--tree-sha",
            target_tree,
        ).stdout
    )
    assert commit_meta["stage"] == "commit-packet-ready"
    commit_packet = json.loads((plan_dir / "create-workflow-commit.json").read_text(encoding="utf-8"))
    assert commit_packet["action_args"]["parent_sha"] == base
    assert commit_packet["action_args"]["tree_sha"] == target_tree
    assert not (plan_dir / "advance-workflow-ref.json").exists()

    created_commit = "a" * 40
    update_meta = json.loads(
        run(
            MAINTENANCE,
            repo,
            "connector-update",
            "--plan-dir",
            str(plan_dir),
            "--commit-sha",
            created_commit,
        ).stdout
    )
    assert update_meta["stage"] == "update-packet-ready"
    update_packet = json.loads((plan_dir / "advance-workflow-ref.json").read_text(encoding="utf-8"))
    assert update_packet["action_args"]["branch_name"] == "develop"
    assert update_packet["action_args"]["force"] is False

    verified = json.loads(
        run(
            MAINTENANCE,
            repo,
            "verify-remote",
            "--plan-dir",
            str(plan_dir),
            "--remote-head",
            created_commit,
            "--remote-tree",
            target_tree,
        ).stdout
    )
    assert verified["verified"] is True
    assert verified["rehydrate_required"] is True

    blocked = run(PUBLISH, repo, "prepare", "--output", str(tmp_path / "blocked.json"), check=False)
    assert blocked.returncode != 0
    assert "restore the latest source-snapshot" in blocked.stderr

    run(PUBLISH, repo, "init", "--remote-commit", created_commit, "--remote-tree", target_tree)
    marker = repo / ".git" / "space-idle-workflow-maintenance-rehydrate-required"
    assert not marker.exists()


def test_workflow_maintenance_stage_machine_rejects_skips_and_replanning(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push]\n", encoding="utf-8")
    commit_all(repo, "workflow")
    manifest = tmp_path / "maintenance.json"
    run(MAINTENANCE, repo, "prepare", "--output", str(manifest))
    plan_dir = Path(f"{manifest}.connector")
    run(
        MAINTENANCE,
        repo,
        "connector-plan",
        "--manifest",
        str(manifest),
        "--target-remote-head",
        base,
    )

    skipped = run(
        MAINTENANCE,
        repo,
        "connector-commit",
        "--plan-dir",
        str(plan_dir),
        "--tree-sha",
        git(repo, "rev-parse", "HEAD^{tree}"),
        check=False,
    )
    assert skipped.returncode != 0
    assert "requires stage tree-packet-ready" in skipped.stderr

    replanned = run(
        MAINTENANCE,
        repo,
        "connector-plan",
        "--manifest",
        str(manifest),
        "--target-remote-head",
        base,
        check=False,
    )
    assert replanned.returncode != 0
    assert "continue its recorded stage" in replanned.stderr


def test_workflow_maintenance_refuses_moved_develop_before_any_packets(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push]\n", encoding="utf-8")
    commit_all(repo, "workflow")
    manifest = tmp_path / "maintenance.json"
    run(MAINTENANCE, repo, "prepare", "--output", str(manifest))
    plan_dir = Path(f"{manifest}.connector")
    result = run(
        MAINTENANCE,
        repo,
        "connector-plan",
        "--manifest",
        str(manifest),
        "--target-remote-head",
        "f" * 40,
        check=False,
    )
    assert result.returncode != 0
    assert "develop HEAD moved" in result.stderr
    assert not plan_dir.exists()


def test_standard_publish_error_names_the_workflow_maintenance_entrypoint(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push]\n", encoding="utf-8")
    commit_all(repo, "workflow")
    result = run(PUBLISH, repo, "prepare", "--output", str(tmp_path / "request.json"), check=False)
    assert result.returncode != 0
    assert "python scripts/workflow_maintenance.py prepare" in result.stderr
