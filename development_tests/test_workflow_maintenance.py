from __future__ import annotations

import json
import subprocess
from pathlib import Path

from development_tests.script_harness import load_script, run_script


ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "scripts" / "publish_request.py"
MAINTENANCE = ROOT / "scripts" / "workflow_maintenance.py"
PUBLISH_MODULE = load_script(PUBLISH, "space_idle_test_publish_request_for_maintenance")
MAINTENANCE_MODULE = load_script(MAINTENANCE, "space_idle_test_workflow_maintenance")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


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
    source_snapshot = tmp_path / "source-snapshot"
    source_snapshot.mkdir()
    (source_snapshot / ".source-commit").write_text(base + "\n", encoding="utf-8")
    (source_snapshot / ".source-tree").write_text(tree + "\n", encoding="utf-8")
    (source_snapshot / ".source-branch").write_text("develop\n", encoding="utf-8")
    git(repo, "update-ref", "refs/space-idle/publish-base", base)
    (source_snapshot / ".source-publish-commit").write_text(base + "\n", encoding="utf-8")
    (source_snapshot / ".source-publish-tree").write_text(tree + "\n", encoding="utf-8")
    git(repo, "bundle", "create", str(source_snapshot / "repository.bundle"),
        "refs/heads/develop", "refs/space-idle/publish-base")
    git(repo, "remote", "add", "origin", str((source_snapshot / "repository.bundle").resolve()))
    run(PUBLISH, repo, "init")
    return repo, base, tree


def test_workflow_maintenance_is_separate_and_has_no_target_or_path_selectors() -> None:
    maintenance_help = run(MAINTENANCE, ROOT, "--help").stdout
    publish_help = run(PUBLISH, ROOT, "--help").stdout
    assert ".github/workflows-only" in maintenance_help
    assert "Normal source/game changes belong to publish_request.py" in " ".join(maintenance_help.split())
    assert "workflow-maintenance" not in publish_help
    assert "--repo" not in maintenance_help

    forbidden_by_command = {
        "prepare": ("--repo", "--target-ref", "--output", "--target-branch"),
        "connector-plan": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                           "--output-dir", "--connector-call-budget-bytes", "--target-branch"),
        "record-update": ("--repo", "--manifest", "--plan-dir", "--target-branch", "--force"),
    }
    for command, flags in forbidden_by_command.items():
        help_text = run(MAINTENANCE, ROOT, command, "--help").stdout
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
    assert "source-snapshot" in blocked.stderr

    refreshed_snapshot = tmp_path / "source-snapshot-after-maintenance"
    refreshed_snapshot.mkdir()
    (refreshed_snapshot / ".source-commit").write_text(created_commit + "\n", encoding="utf-8")
    (refreshed_snapshot / ".source-tree").write_text(target_tree + "\n", encoding="utf-8")
    (refreshed_snapshot / ".source-branch").write_text("develop\n", encoding="utf-8")
    publish_base = git(repo, "rev-parse", "refs/space-idle/publish-base")
    publish_tree = git(repo, "rev-parse", f"{publish_base}^{{tree}}")
    (refreshed_snapshot / ".source-publish-commit").write_text(publish_base + "\n", encoding="utf-8")
    (refreshed_snapshot / ".source-publish-tree").write_text(publish_tree + "\n", encoding="utf-8")
    git(repo, "bundle", "create", str(refreshed_snapshot / "repository.bundle"),
        "refs/heads/develop", "refs/space-idle/publish-base")
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


def test_standard_publish_error_names_workflow_maintenance_as_only_entrypoint(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push, workflow_dispatch]\n", encoding="utf-8")
    commit_all(repo, "Update CI workflow")
    result = run(PUBLISH, repo, "prepare", check=False)
    assert result.returncode != 0
    assert "python scripts/workflow_maintenance.py prepare" in result.stderr
