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
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def run(script: Path, repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=repo, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def maintenance_manifest(repo: Path) -> Path:
    return repo / ".git" / "space-idle-workflow-maintenance-transaction" / "manifest.json"


def maintenance_plan(repo: Path) -> Path:
    return repo / ".git" / "space-idle-workflow-maintenance-transaction" / "connector"


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


def test_workflow_maintenance_is_separate_and_has_no_target_or_path_selectors() -> None:
    maintenance_help = subprocess.run(
        [sys.executable, str(MAINTENANCE), "--help"], check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout
    publish_help = subprocess.run(
        [sys.executable, str(PUBLISH), "--help"], check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert ".github/workflows-only" in maintenance_help
    assert "Normal source/game changes belong to publish_request.py" in " ".join(maintenance_help.split())
    assert "workflow-maintenance" not in publish_help
    assert "--repo" not in maintenance_help

    forbidden_by_command = {
        "prepare": ("--repo", "--target-ref", "--output", "--target-branch"),
        "connector-plan": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                           "--output-dir", "--connector-call-budget-bytes", "--target-branch"),
        "connector-tree": ("--repo", "--manifest", "--plan-dir"),
        "connector-commit": ("--repo", "--manifest", "--plan-dir"),
        "connector-update": ("--repo", "--manifest", "--plan-dir", "--force"),
        "verify-remote": ("--repo", "--manifest", "--plan-dir", "--target-branch"),
    }
    for command, flags in forbidden_by_command.items():
        help_text = subprocess.run([sys.executable, str(MAINTENANCE), command, "--help"], check=True,
                                   text=True, stdout=subprocess.PIPE).stdout
        for flag in flags:
            assert flag not in help_text


def test_prepare_rejects_nonworkflow_mixed_and_second_active_transaction(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "game.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "game change")
    result = run(MAINTENANCE, repo, "prepare", check=False)
    assert result.returncode != 0
    assert "workflow-only commits" in result.stderr

    git(repo, "reset", "--hard", "HEAD^")
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    (repo / "game.txt").write_text("mixed\n", encoding="utf-8")
    commit_all(repo, "mixed change")
    mixed = run(MAINTENANCE, repo, "prepare", check=False)
    assert mixed.returncode != 0
    assert "game.txt" in mixed.stderr

    git(repo, "reset", "--hard", "HEAD^")
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "workflow only")
    run(MAINTENANCE, repo, "prepare")
    second = run(MAINTENANCE, repo, "prepare", check=False)
    assert second.returncode != 0
    assert "active workflow maintenance transaction" in second.stderr


def test_workflow_maintenance_stages_exact_git_data_and_requires_rehydration(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    prepared = json.loads(run(MAINTENANCE, repo, "prepare").stdout)
    assert prepared["workflow_paths"] == [".github/workflows/ci.yml"]
    assert maintenance_manifest(repo).exists()

    plan = json.loads(run(
        MAINTENANCE, repo, "connector-plan", "--target-remote-head", base
    ).stdout)
    plan_path = maintenance_plan(repo)
    assert plan["stage"] == "uploads-planned"
    assert plan["upload_call_count"] == 1
    upload = json.loads(Path(plan["upload_packets"][0]).read_text(encoding="utf-8"))
    assert upload["action"] == "GitHub.create_blob"
    assert upload["action_args"]["repository_full_name"] == "naro0216n-collab/Space-Idle"

    tree_meta = json.loads(run(MAINTENANCE, repo, "connector-tree").stdout)
    tree_packet = json.loads(Path(tree_meta["tree_packet"]).read_text(encoding="utf-8"))
    assert tree_packet["action"] == "GitHub.create_tree"
    assert tree_packet["expected_tree_git_oid"] == target_tree

    commit_meta = json.loads(run(
        MAINTENANCE, repo, "connector-commit", "--tree-sha", target_tree
    ).stdout)
    commit_packet = json.loads(Path(commit_meta["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["parent_sha"] == base

    created_commit = git(repo, "rev-parse", "HEAD")
    update_meta = json.loads(run(
        MAINTENANCE, repo, "connector-update", "--commit-sha", created_commit
    ).stdout)
    update_packet = json.loads(Path(update_meta["update_packet"]).read_text(encoding="utf-8"))
    assert update_packet["action"] == "GitHub.update_ref"
    assert update_packet["action_args"]["branch_name"] == "develop"
    assert update_packet["action_args"]["force"] is False

    verified = json.loads(run(
        MAINTENANCE, repo, "verify-remote", "--remote-head", created_commit,
        "--remote-tree", target_tree,
    ).stdout)
    assert verified["verified"] is True
    assert verified["rehydrate_required"] is True

    blocked = run(PUBLISH, repo, "prepare", check=False)
    assert blocked.returncode != 0
    assert "source-snapshot" in blocked.stderr

    # A verified source-snapshot init is the only route back to normal publish.
    run(PUBLISH, repo, "init", "--remote-commit", created_commit, "--remote-tree", target_tree)
    marker = repo / ".git" / "space-idle-workflow-maintenance-rehydrate-required"
    assert not marker.exists()
    assert not plan_path.exists()


def test_workflow_stage_machine_rejects_skips_replanning_and_wrong_sha(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    run(MAINTENANCE, repo, "prepare")

    skipped = run(MAINTENANCE, repo, "connector-tree", check=False)
    assert skipped.returncode != 0
    assert "uploads-planned" in skipped.stderr or "state" in skipped.stderr

    run(MAINTENANCE, repo, "connector-plan", "--target-remote-head", base)
    replan = run(MAINTENANCE, repo, "connector-plan", "--target-remote-head", base, check=False)
    assert replan.returncode != 0
    assert "already exists" in replan.stderr

    run(MAINTENANCE, repo, "connector-tree")
    wrong_tree = run(MAINTENANCE, repo, "connector-commit", "--tree-sha", "3" * 40, check=False)
    assert wrong_tree.returncode != 0
    assert "does not match expected target tree" in wrong_tree.stderr


def test_workflow_plan_refuses_moved_develop_before_any_packets(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    run(MAINTENANCE, repo, "prepare")
    result = run(
        MAINTENANCE, repo, "connector-plan", "--target-remote-head", "3" * 40, check=False
    )
    assert result.returncode != 0
    assert "develop HEAD moved" in result.stderr
    assert not maintenance_plan(repo).exists()


def test_standard_publish_error_names_workflow_maintenance_as_only_entrypoint(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    result = run(PUBLISH, repo, "prepare", check=False)
    assert result.returncode != 0
    assert "python scripts/workflow_maintenance.py prepare" in result.stderr
