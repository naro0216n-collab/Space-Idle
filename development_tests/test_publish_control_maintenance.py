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
    "scripts/publish_gateway_validate.py",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


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
    commit_all(repo, "base control plane")
    base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    state = {
        "remote_commit": base, "remote_tree": base_tree, "local_head": base,
        "publish_commit": base, "publish_tree": base_tree,
    }
    (repo / ".git" / "space-idle-publish-state.json").write_text(json.dumps(state), encoding="utf-8")
    for path in CONTROL_PATHS:
        (repo / path).write_text(f"updated {path}\n", encoding="utf-8")
    commit_all(repo, "updated control plane")
    return repo, base, base_tree


def expected_oids(repo: Path) -> dict[str, str]:
    return {path: git(repo, "rev-parse", f"HEAD:{path}") for path in CONTROL_PATHS}


def test_control_maintenance_uses_recorded_publish_base_and_exact_current_paths(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    prepared = json.loads(run(repo, "prepare").stdout)
    assert prepared["control_paths"] == list(CONTROL_PATHS)
    plan = json.loads(run(repo, "connector-plan", "--target-remote-head", base).stdout)
    assert plan["base_tree"] == base_tree
    assert len(plan["upload_packets"]) == 2
    assert "expected_tree" in plan

    oids = expected_oids(repo)
    blob_args: list[str] = []
    for path, oid in oids.items():
        blob_args.extend(["--blob", f"{path}={oid}"])
    tree = json.loads(run(repo, "connector-tree", *blob_args).stdout)
    packet = json.loads(Path(tree["tree_packet"]).read_text(encoding="utf-8"))
    assert packet["action"] == "GitHub.create_tree"
    assert packet["action_args"]["base_tree_sha"] == base_tree
    elements = packet["action_args"]["tree_elements"]
    assert {e["path"] for e in elements} == set(CONTROL_PATHS)

    wrong = run(repo, "connector-commit", "--tree-sha", "f" * 40, check=False)
    assert wrong.returncode != 0
    commit = json.loads(run(repo, "connector-commit", "--tree-sha", plan["expected_tree"]).stdout)
    commit_packet = json.loads(Path(commit["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action_args"]["parent_sha"] == base

    candidate = "a" * 40
    update = json.loads(run(repo, "connector-update", "--commit-sha", candidate).stdout)
    update_packet = json.loads(Path(update["update_packet"]).read_text(encoding="utf-8"))
    assert update_packet["action_args"]["force"] is False
    recorded = json.loads(run(repo, "record-update", "--commit-sha", candidate, "--result", "success").stdout)
    assert recorded["normal_publish_base_updated"] is True
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["publish_commit"] == candidate
    assert state["publish_tree"] == plan["expected_tree"]
    assert not transaction(repo).exists()


def test_control_tree_rejects_blob_transfer_mismatch_before_tree_creation(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    run(repo, "prepare")
    run(repo, "connector-plan", "--target-remote-head", base)
    oids = expected_oids(repo)
    args: list[str] = []
    for index, (path, oid) in enumerate(oids.items()):
        args.extend(["--blob", f"{path}={'f' * 40 if index == 0 else oid}"])
    failed = run(repo, "connector-tree", *args, check=False)
    assert failed.returncode != 0
    assert "control blob OID mismatch" in failed.stderr


def test_control_plan_rejects_moved_publish_head(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    run(repo, "prepare")
    failed = run(repo, "connector-plan", "--target-remote-head", "e" * 40, check=False)
    assert failed.returncode != 0
    assert "publish HEAD moved" in failed.stderr
