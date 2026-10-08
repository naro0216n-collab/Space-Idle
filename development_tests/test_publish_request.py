from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from development_tests.script_harness import (
    commit_all, git, load_script, run_script, write_source_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_request.py"
PUBLISH_REQUEST = load_script(SCRIPT, "space_idle_test_publish_request")


def run_request(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_script(PUBLISH_REQUEST, SCRIPT, repo, *args, check=check)


def transaction(repo: Path) -> Path:
    return repo / ".git" / "space-idle-publish-transaction"


def manifest_path(repo: Path) -> Path:
    return transaction(repo) / "manifest.json"


def connector_state(repo: Path) -> dict[str, object]:
    return json.loads((transaction(repo) / "connector" / "connector-state.json").read_text(encoding="utf-8"))


def prepared(repo: Path) -> dict[str, object]:
    return json.loads(manifest_path(repo).read_text(encoding="utf-8"))


def init_repo(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((snapshot / "repository.bundle").resolve()))
    result = json.loads(run_request(repo, "init").stdout)
    assert result["publish_commit"] == base
    assert result["publish_tree"] == base_tree
    return repo, base, base_tree, base, base_tree


def prepare_change(repo: Path, text: str = "changed\n") -> dict[str, object]:
    (repo / "payload.txt").write_text(text, encoding="utf-8")
    commit_all(repo, "checkpoint")
    return json.loads(run_request(repo, "prepare").stdout)


def plan(repo: Path, develop_head: str, publish_head: str) -> dict[str, object]:
    return json.loads(run_request(
        repo, "connector-plan",
        "--develop-head", develop_head,
        "--publish-head", publish_head,
    ).stdout)


def test_init_requires_exact_develop_and_publish_base_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "x").write_text("x\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((snapshot / "repository.bundle").resolve()))
    ok = json.loads(run_request(repo, "init").stdout)
    assert ok["remote_commit"] == git(repo, "rev-parse", "HEAD")
    assert ok["publish_commit"] == git(repo, "rev-parse", "refs/space-idle/publish-base")
    assert git(repo, "config", "--local", "--get", "user.name") == PUBLISH_REQUEST.PUBLISH_IDENTITY_NAME
    assert git(repo, "config", "--local", "--get", "user.email") == PUBLISH_REQUEST.PUBLISH_IDENTITY_EMAIL

    (snapshot / ".source-publish-tree").write_text("f" * 40 + "\n", encoding="utf-8")
    broken = run_request(repo, "init", check=False)
    assert broken.returncode != 0
    assert "publish base" in broken.stderr



def test_init_restores_publish_base_after_clone_from_snapshot_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    (source / "x").write_text("x\n", encoding="utf-8")
    commit_all(source, "base")
    git(source, "branch", "-M", "develop")
    snapshot = write_source_snapshot(source, tmp_path / "source-snapshot")

    restored = tmp_path / "restored"
    subprocess.run(
        ["git", "clone", "-b", "develop", str(snapshot / "repository.bundle"), str(restored)],
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/space-idle/publish-base"],
        cwd=restored, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).returncode != 0

    result = json.loads(run_request(restored, "init").stdout)
    assert result["publish_commit"] == git(restored, "rev-parse", "refs/space-idle/publish-base")
    assert result["publish_commit"] == (snapshot / ".source-publish-commit").read_text(encoding="utf-8").strip()


def test_prepare_uses_head_only_and_excludes_uncommitted_work(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "payload.txt").write_text("uncommitted\n", encoding="utf-8")
    result = json.loads(run_request(repo, "prepare").stdout)
    request = prepared(repo)
    assert result["local_target_commit"] == checkpoint
    assert result["target_tree"] == checkpoint_tree
    assert result["working_tree_clean"] is False
    assert request["version"] == 8
    # The published identity and timestamp must belong to the committed target,
    # not to later working-tree edits.
    assert git(repo, "show", "-s", "--format=%cI", str(result["publish_commit"])) == git(
        repo, "show", "-s", "--format=%cI", checkpoint
    )
    raw = subprocess.run(
        ["git", "cat-file", "commit", str(request["publish_commit"])], cwd=repo,
        check=True, stdout=subprocess.PIPE,
    ).stdout
    assert raw.partition(b"\n\n")[2] == b"checkpoint\n"


def test_connector_plan_uses_tree_content_batches_and_scales_past_single_call_budget(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    (repo / "large.bin").write_bytes(os.urandom(420_000))
    commit_all(repo, "large checkpoint")
    run_request(repo, "prepare")
    summary = plan(repo, base, publish_head)

    assert summary["strategy"] == "fixed-slot-16kib-tree-content-batches"
    assert summary["transport_chunk_bytes"] == 16 * 1024
    assert summary["payload_part_count"] > 8
    assert summary["tree_call_count"] > 1
    assert summary["normal_pre_ref_helper_round_trips"] == 0

    state = connector_state(repo)
    assert state["stage"] == "execution-plan-ready"
    plan_data = state["plan"]
    assert isinstance(plan_data, dict)
    chunks = plan_data["chunks"]
    assert isinstance(chunks, list) and len(chunks) == summary["payload_part_count"]
    assert all(len(str(chunk["content"]).encode("utf-8")) <= 16 * 1024 for chunk in chunks)

    expected_paths = {str(chunk["path"]) for chunk in chunks}
    observed_paths: set[str] = set()
    previous_tree = state["publish_base_tree"]
    tree_packets = [Path(path) for path in summary["tree_packets"]]
    assert len(tree_packets) == summary["tree_call_count"]
    for index, packet_path in enumerate(tree_packets):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_tree"
        assert packet["tree_batch_index"] == index
        assert packet["action_args"]["base_tree_sha"] == previous_tree
        encoded_args = json.dumps(
            packet["action_args"], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        assert len(encoded_args) <= 144 * 1024
        for entry in packet["action_args"]["tree_elements"]:
            if str(entry["path"]).endswith(".b64"):
                assert "content" in entry
                assert "sha" not in entry
                observed_paths.add(str(entry["path"]))
        previous_tree = packet["expected_tree"]

    assert observed_paths == expected_paths
    assert previous_tree == plan_data["final_tree"]

    commit_packet = json.loads(Path(str(summary["commit_packet"])).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["tree_sha"] == plan_data["final_tree"]
    assert commit_packet["action_args"]["parent_sha"] == publish_head
    assert summary["post_commit_ref_update"] == {
        "action": "GitHub.update_ref",
        "repository_full_name": PUBLISH_REQUEST.GITHUB_REPOSITORY,
        "branch_name": "publish",
        "sha": "<GitHub.create_commit returned SHA>",
        "force": False,
    }


def test_record_uses_prepared_identity_without_reverifying_bundle_and_tracks_gateway_run(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    result = prepare_change(repo)
    summary = plan(repo, base, publish_head)
    candidate = "a" * 40
    # Work on the next checkpoint must not change the prepared transaction.
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "later local work")

    recorded = json.loads(run_request(
        repo, "record",
        "--gateway-transport-commit", candidate,
        "--gateway-run-id", "12345",
        "--gateway-conclusion", "success",
    ).stdout)
    assert recorded["verified"] is True
    assert recorded["record_verification"] == "manifest-identity-and-gateway-run"
    assert recorded["remote_commit"] == result["publish_commit"]
    assert recorded["local_head"] == result["local_target_commit"]
    assert recorded["local_head"] != git(repo, "rev-parse", "HEAD")
    assert recorded["publish_commit"] == candidate
    assert recorded["publish_tree"] == connector_state_from_summary_tree(summary)
    assert not transaction(repo).exists()


def connector_state_from_summary_tree(summary: dict[str, object]) -> str:
    expected = summary["tree_expected_shas"]
    assert isinstance(expected, list) and expected
    return str(expected[-1])


def test_preflight_and_record_reject_moved_heads_or_modified_manifest(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    for develop_head, gateway_head in (("c" * 40, publish_head), (base, "d" * 40)):
        rejected = run_request(
            repo, "connector-plan", "--develop-head", develop_head,
            "--publish-head", gateway_head, check=False,
        )
        assert rejected.returncode != 0

    plan(repo, base, publish_head)
    manifest = prepared(repo)
    manifest["request_id"] = "0" * 32
    manifest_path(repo).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    rejected = run_request(
        repo, "record", "--gateway-transport-commit", "c" * 40,
        "--gateway-run-id", "77", "--gateway-conclusion", "success", check=False,
    )
    assert rejected.returncode != 0
    assert "manifest changed" in rejected.stderr


def test_cancel_uses_heads_only_and_never_needs_publish_tree_read(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    plan(repo, base, publish_head)
    cancelled = json.loads(run_request(
        repo, "cancel",
        "--develop-head", base,
        "--publish-head", publish_head,
    ).stdout)
    assert cancelled["cancelled"] is True
    assert not transaction(repo).exists()


def test_standard_prepare_accepts_only_the_trusted_gateway_workflow_change(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    commit_all(repo, "change workflow")
    blocked = run_request(repo, "prepare", check=False)
    assert blocked.returncode != 0
    assert "workflow_maintenance.py prepare" in blocked.stderr

    git(repo, "reset", "--hard", "HEAD^")
    gateway = repo / ".github" / "workflows" / "publish-gateway.yml"
    gateway.parent.mkdir(parents=True, exist_ok=True)
    gateway.write_text("name: Publish Gateway\n", encoding="utf-8")
    commit_all(repo, "change trusted gateway workflow")
    assert json.loads(run_request(repo, "prepare").stdout)["verified"] is True

def test_gateway_trusted_workflow_guard_requires_publish_control_blob_identity(tmp_path: Path) -> None:
    validator = ROOT / "scripts" / "publish_gateway_validate.py"
    repo = tmp_path / "guard-repo"
    repo.mkdir()
    git(repo, "init")
    gateway = repo / ".github" / "workflows" / "publish-gateway.yml"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("name: old\n", encoding="utf-8")
    commit_all(repo, "base")
    base = git(repo, "rev-parse", "HEAD")
    gateway.write_text("name: trusted\n", encoding="utf-8")
    commit_all(repo, "publish control")
    control = git(repo, "rev-parse", "HEAD")
    (repo / "payload.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "target")
    target = git(repo, "rev-parse", "HEAD")
    env = {**os.environ, "BASE_SHA": base, "PUBLISH_COMMIT": target, "GITHUB_SHA": control}
    ok = subprocess.run(["python", str(validator), "--verify-trusted-workflow"], cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert ok.returncode == 0, ok.stderr
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text("name: untrusted\n", encoding="utf-8")
    commit_all(repo, "untrusted workflow")
    blocked = subprocess.run(
        ["python", str(validator), "--verify-trusted-workflow"], cwd=repo,
        env={**env, "PUBLISH_COMMIT": git(repo, "rev-parse", "HEAD")},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert blocked.returncode != 0
    assert "untrusted workflow change" in blocked.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="Gateway's bash execution contract is verified on Linux CI")
def test_gateway_workflow_accepts_only_transport_slot_mutations(tmp_path: Path) -> None:
    """Execute the actual Gateway path filter, rather than assert source fragments."""
    workflow = (ROOT / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Resolve fixed transport slot\n", 1)[1]
    script = step.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
    script = "\n".join(line.removeprefix("          ") for line in script.splitlines())

    repo = tmp_path / "gateway"
    repo.mkdir()
    git(repo, "init")
    (repo / "base.txt").write_text("baseline", encoding="utf-8")
    commit_all(repo, "base")

    def run_filter(path: str) -> subprocess.CompletedProcess[str]:
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("payload", encoding="utf-8")
        commit_all(repo, "candidate transport")
        env_file = tmp_path / "gateway.env"
        env_file.write_text("", encoding="utf-8")
        return subprocess.run(
            ["bash", "-c", script], cwd=repo,
            env={**os.environ, "GITHUB_SHA": git(repo, "rev-parse", "HEAD"),
                 "GITHUB_ENV": str(env_file)},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    accepted = run_filter(".publish/transport/develop/0000.b64")
    assert accepted.returncode == 0, accepted.stderr
    assert "TARGET_BRANCH=develop" in (tmp_path / "gateway.env").read_text(encoding="utf-8")

    for unexpected_path in ("src/unrelated.py", ".publish/transport/publish/0000.b64"):
        rejected = run_filter(unexpected_path)
        assert rejected.returncode != 0


def test_gateway_contract_validates_fixed_slot_then_publishes_exact_commit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "'.publish/transport/**'" in workflow
    assert "TRANSPORT_DIR=.publish/transport/${branches[0]}" in workflow
    assert "python scripts/publish_gateway_validate.py" in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "actions/workflows/ci.yml/dispatches" in workflow
    assert '-f ref="${TARGET_BRANCH}"' in workflow
