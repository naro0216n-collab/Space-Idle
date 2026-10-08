from __future__ import annotations

import json
import subprocess
from pathlib import Path

from development_tests.script_harness import (
    commit_all, git, load_script, run_script, write_source_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "scripts" / "publish_request.py"
MAINTENANCE = ROOT / "scripts" / "workflow_maintenance.py"
PUBLISH_MODULE = load_script(PUBLISH, "space_idle_test_publish_request_for_maintenance")
MAINTENANCE_MODULE = load_script(MAINTENANCE, "space_idle_test_workflow_maintenance")


def run(script: Path, repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    module = MAINTENANCE_MODULE if script == MAINTENANCE else PUBLISH_MODULE
    return run_script(module, script, repo, *args, check=check)


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
    git(repo, "branch", "-M", "develop")
    base = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    source_snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((source_snapshot / "repository.bundle").resolve()))
    run(PUBLISH, repo, "init")
    return repo, base, tree


def test_prepare_rejects_nonworkflow_mixed_and_second_active_transaction(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "game.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "game change")
    result = run(MAINTENANCE, repo, "prepare", check=False)
    assert result.returncode != 0
    assert not maintenance_manifest(repo).exists()

    git(repo, "reset", "--hard", "HEAD^")
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    (repo / "game.txt").write_text("mixed\n", encoding="utf-8")
    commit_all(repo, "mixed change")
    mixed = run(MAINTENANCE, repo, "prepare", check=False)
    assert mixed.returncode != 0
    assert not maintenance_manifest(repo).exists()

    git(repo, "reset", "--hard", "HEAD^")
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "workflow only")
    # Workflow-only maintenance cannot be redirected to another branch.
    redirected = run(MAINTENANCE, repo, "prepare", "--target-branch", "main", check=False)
    assert redirected.returncode != 0
    assert not maintenance_manifest(repo).exists()
    run(MAINTENANCE, repo, "prepare")
    second = run(MAINTENANCE, repo, "prepare", check=False)
    assert second.returncode != 0
    assert maintenance_manifest(repo).exists()


def test_workflow_maintenance_generates_complete_content_tree_plan_and_requires_rehydration(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    prepared = json.loads(run(MAINTENANCE, repo, "prepare").stdout)
    assert prepared["workflow_paths"] == [".github/workflows/ci.yml"]
    assert maintenance_manifest(repo).exists()

    plan = json.loads(run(
        MAINTENANCE, repo, "connector-plan", "--develop-head", base
    ).stdout)
    plan_path = maintenance_plan(repo)
    assert plan["stage"] == "execution-plan-ready"
    assert plan["strategy"] == "workflow-maintenance-tree-content-batches"
    assert plan["normal_pre_ref_helper_round_trips"] == 0
    assert plan["tree_packets"]

    previous_tree = plan["base_tree"]
    for packet_path in plan["tree_packets"]:
        packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_tree"
        assert packet["action_args"]["base_tree_sha"] == previous_tree
        for element in packet["action_args"]["tree_elements"]:
            if element.get("sha") is not None:
                assert "content" in element
        previous_tree = packet["expected_tree"]
    assert previous_tree == target_tree

    commit_packet = json.loads(Path(plan["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["parent_sha"] == base
    assert commit_packet["action_args"]["tree_sha"] == target_tree
    assert plan["post_commit_ref_update"]["branch_name"] == "develop"
    assert plan["post_commit_ref_update"]["force"] is False

    created_commit = git(repo, "rev-parse", "HEAD")
    recorded = json.loads(run(
        MAINTENANCE, repo, "record-update", "--commit-sha", created_commit, "--result", "success"
    ).stdout)
    assert recorded["verified"] is True
    assert recorded["rehydrate_required"] is True
    assert recorded["record_verification"] == "manifest-identity-and-successful-ref-update"

    blocked = run(PUBLISH, repo, "prepare", check=False)
    assert blocked.returncode != 0

    refreshed_snapshot = write_source_snapshot(
        repo, tmp_path / "source-snapshot-after-maintenance",
        publish_commit=git(repo, "rev-parse", "refs/space-idle/publish-base"),
    )
    git(repo, "remote", "set-url", "origin", str((refreshed_snapshot / "repository.bundle").resolve()))
    run(PUBLISH, repo, "init")
    marker = repo / ".git" / "space-idle-workflow-maintenance-rehydrate-required"
    assert not marker.exists()
    assert not plan_path.exists()


def test_workflow_plan_rejects_replan_moved_develop_and_manifest_mutation(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    run(MAINTENANCE, repo, "prepare")

    moved = run(MAINTENANCE, repo, "connector-plan", "--develop-head", "3" * 40, check=False)
    assert moved.returncode != 0
    assert "develop HEAD moved" in moved.stderr
    assert not maintenance_plan(repo).exists()

    run(MAINTENANCE, repo, "connector-plan", "--develop-head", base)
    replan = run(MAINTENANCE, repo, "connector-plan", "--develop-head", base, check=False)
    assert replan.returncode != 0
    assert "already exists" in replan.stderr

    manifest = maintenance_manifest(repo)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["message"] = "tampered"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    rejected = run(
        MAINTENANCE, repo, "record-update", "--commit-sha", "4" * 40, "--result", "success", check=False
    )
    assert rejected.returncode != 0
    assert "manifest changed" in rejected.stderr
