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


def test_control_maintenance_uses_content_tree_plan_and_direct_commit_to_ref_sequence(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    prepared = json.loads(run(repo, "prepare").stdout)
    assert prepared["control_paths"] == list(CONTROL_PATHS)
    plan = json.loads(run(repo, "connector-plan", "--publish-head", base).stdout)
    assert plan["base_tree"] == base_tree
    assert plan["strategy"] == "publish-control-tree-content-batches"
    assert plan["normal_pre_ref_helper_round_trips"] == 0
    assert plan["tree_packets"]

    observed: set[str] = set()
    previous_tree = base_tree
    for packet_path in plan["tree_packets"]:
        packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_tree"
        assert packet["action_args"]["base_tree_sha"] == previous_tree
        for element in packet["action_args"]["tree_elements"]:
            assert "content" in element
            assert "sha" not in element
            observed.add(element["path"])
        previous_tree = packet["expected_tree"]
    assert observed == set(CONTROL_PATHS)
    assert previous_tree == plan["expected_tree"]

    commit_packet = json.loads(Path(plan["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["tree_sha"] == plan["expected_tree"]
    assert commit_packet["action_args"]["parent_sha"] == base
    assert plan["post_commit_ref_update"]["force"] is False

    candidate = "a" * 40
    recorded = json.loads(run(repo, "record-update", "--commit-sha", candidate, "--result", "success").stdout)
    assert recorded["normal_publish_base_updated"] is True
    assert recorded["record_verification"] == "manifest-identity-and-successful-ref-update"
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["publish_commit"] == candidate
    assert state["publish_tree"] == plan["expected_tree"]
    assert not transaction(repo).exists()


def test_control_record_rejects_manifest_mutation_after_plan(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    run(repo, "prepare")
    run(repo, "connector-plan", "--publish-head", base)
    manifest = transaction(repo) / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["message"] = "tampered"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    failed = run(repo, "record-update", "--commit-sha", "b" * 40, "--result", "success", check=False)
    assert failed.returncode != 0
    assert "manifest changed" in failed.stderr


def test_control_plan_rejects_moved_publish_head(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    run(repo, "prepare")
    failed = run(repo, "connector-plan", "--publish-head", "e" * 40, check=False)
    assert failed.returncode != 0
    assert "publish HEAD moved" in failed.stderr
