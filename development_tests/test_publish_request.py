from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

from development_tests.script_harness import load_script, run_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_request.py"
PUBLISH_REQUEST = load_script(SCRIPT, "space_idle_test_publish_request")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


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


def write_source_snapshot(repo: Path, directory: Path, *, publish_commit: str | None = None) -> Path:
    directory.mkdir()
    develop = git(repo, "rev-parse", "refs/heads/develop")
    develop_tree = git(repo, "rev-parse", f"{develop}^{{tree}}")
    publish = publish_commit or develop
    publish_tree = git(repo, "rev-parse", f"{publish}^{{tree}}")
    git(repo, "update-ref", "refs/space-idle/publish-base", publish)
    (directory / ".source-commit").write_text(develop + "\n", encoding="utf-8")
    (directory / ".source-tree").write_text(develop_tree + "\n", encoding="utf-8")
    (directory / ".source-branch").write_text("develop\n", encoding="utf-8")
    (directory / ".source-publish-commit").write_text(publish + "\n", encoding="utf-8")
    (directory / ".source-publish-tree").write_text(publish_tree + "\n", encoding="utf-8")
    git(
        repo, "bundle", "create", str(directory / "repository.bundle"),
        "refs/heads/develop", "refs/space-idle/publish-base",
    )
    return directory


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
        "--target-remote-head", develop_head,
        "--publish-remote-head", publish_head,
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

    (snapshot / ".source-publish-tree").write_text("f" * 40 + "\n", encoding="utf-8")
    broken = run_request(repo, "init", check=False)
    assert broken.returncode != 0
    assert "publish base" in broken.stderr


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
    raw = subprocess.run(
        ["git", "cat-file", "commit", str(request["publish_commit"])], cwd=repo,
        check=True, stdout=subprocess.PIPE,
    ).stdout
    assert raw.partition(b"\n\n")[2] == b"checkpoint\n"


def test_connector_plan_uses_fixed_slot_without_index_trigger_or_verification_read(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    result = plan(repo, base, publish_head)
    assert result["strategy"] == "fixed-slot-expected-tree"
    assert result["index_files"] == 0
    assert result["trigger_files"] == 0
    assert result["normal_pre_ref_verification_reads"] == 0
    assert result["tree_call_count"] == 1
    assert result["payload_part_count"] == 1
    packet = json.loads(Path(result["tree_packet"]).read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in packet["action_args"]["tree_elements"] if "content" in entry]
    assert paths == [".publish/transport/develop/0000.b64"]
    assert not any("index" in path or "requests" in path or "retries" in path for path in paths)
    assert packet["action_args"]["base_tree_sha"] == connector_state(repo)["publish_base_tree"]


def test_returned_tree_sha_is_the_pre_ref_integrity_boundary(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    first = plan(repo, base, publish_head)
    expected = first["expected_tree_sha"]

    retry = json.loads(run_request(repo, "connector-tree", "--tree-sha", "f" * 40).stdout)
    assert retry["stage"] == "transport-retry-tree-ready"
    assert retry["transport_attempt"] == 1
    assert retry["adaptive_handoff"] is False
    assert connector_state(repo)["stage"] == "tree-ready"
    assert not (transaction(repo) / "connector" / "create-transport-commit.json").exists()

    succeeded = json.loads(run_request(repo, "connector-tree", "--tree-sha", expected).stdout)
    assert succeeded["stage"] == "commit-packet-ready"
    commit_packet = json.loads(Path(succeeded["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["tree_sha"] == expected


def test_second_tree_mismatch_adapts_transfer_and_third_exhausts_without_ref_packet(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    # Force multiple large inline fields so adaptive repartitioning is observable.
    (repo / "large.bin").write_bytes(os.urandom(180_000))
    commit_all(repo, "large checkpoint")
    run_request(repo, "prepare")
    initial = plan(repo, base, publish_head)
    initial_cap = initial["max_inline_content_chars"]

    run_request(repo, "connector-tree", "--tree-sha", "a" * 40)
    second = json.loads(run_request(repo, "connector-tree", "--tree-sha", "b" * 40).stdout)
    assert second["adaptive_handoff"] is True
    state = connector_state(repo)
    assert state["transport_attempt"] == 2
    assert state["plan"]["max_inline_content_chars"] < initial_cap
    exhausted = run_request(repo, "connector-tree", "--tree-sha", "c" * 40, check=False)
    assert exhausted.returncode != 0
    assert "publish ref was not updated" in exhausted.stderr
    assert connector_state(repo)["stage"] == "transport-failed"
    assert not (transaction(repo) / "connector" / "advance-publish-ref.json").exists()


def test_dynamic_packing_has_no_fixed_6kib_handoff(tmp_path: Path) -> None:
    repo, _, base_tree, publish_head, publish_tree = init_repo(tmp_path)
    prepared_request = {
        "target_branch": "develop",
        "payload_b64": "A" * 300_000,
    }
    plan_data = PUBLISH_REQUEST._build_transport_plan(
        repo, prepared_request, publish_head=publish_head, publish_tree=publish_tree
    )
    assert plan_data["max_inline_content_chars"] > 100_000
    assert plan_data["payload_part_count"] == 3
    assert plan_data["tree_call_count"] == 3
    for batch in plan_data["batches"]:
        packet = PUBLISH_REQUEST._tree_packet(batch["base_tree"], batch["elements"], batch["batch_index"])
        assert PUBLISH_REQUEST._connector_call_bytes(packet) <= 144 * 1024


def test_fixed_slot_plan_removes_legacy_publish_transport_state_generically(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    legacy = repo / ".publish" / "requests" / "old.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}\n", encoding="utf-8")
    temp_slot = repo / ".publish" / "transport" / "temp" / "0000.b64"
    temp_slot.parent.mkdir(parents=True)
    temp_slot.write_text("QQ==", encoding="utf-8")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    prepared_request = {"target_branch": "develop", "payload_b64": "Qg=="}
    elements, _, stale = PUBLISH_REQUEST._desired_transport_elements(
        repo, prepared_request, base_tree=tree
    )
    assert ".publish/requests/old.json" in stale
    assert ".publish/transport/temp/0000.b64" not in stale
    request_delete = next(e for e in elements if e.get("sha") is None and e["path"] == ".publish/requests")
    assert request_delete["type"] == "tree"
    assert request_delete["mode"] == "040000"



def test_legacy_subtree_deletion_compacts_connector_packet_without_changing_expected_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    for index in range(120):
        path = repo / ".publish" / "requests" / f"{index:04d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    temp_slot = repo / ".publish" / "transport" / "temp" / "0000.b64"
    temp_slot.parent.mkdir(parents=True)
    temp_slot.write_text("QQ==", encoding="utf-8")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    prepared_request = {"target_branch": "develop", "payload_b64": "Qg=="}

    plan_data = PUBLISH_REQUEST._build_transport_plan(
        repo, prepared_request, publish_head=git(repo, "rev-parse", "HEAD"), publish_tree=tree
    )
    elements = plan_data["batches"][0]["elements"]
    deletes = [element for element in elements if "content" not in element and element.get("sha") is None]
    assert [element["path"] for element in deletes] == [".publish/requests"]
    assert deletes[0]["type"] == "tree"
    assert plan_data["stale_transport_path_count"] == 120
    assert plan_data["tree_call_count"] == 1

    expected_repo = tmp_path / "expected"
    subprocess.run(["git", "clone", "--quiet", str(repo), str(expected_repo)], check=True)
    subprocess.run(["git", "rm", "-qr", ".publish/requests"], cwd=expected_repo, check=True)
    desired = expected_repo / ".publish" / "transport" / "develop" / "0000.b64"
    desired.parent.mkdir(parents=True, exist_ok=True)
    desired.write_text("Qg==", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=expected_repo, check=True)
    expected_tree = git(expected_repo, "write-tree")
    assert plan_data["final_tree"] == expected_tree

def test_commit_then_ref_is_only_remaining_normal_write_sequence_and_record_uses_gateway_run(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    result = prepare_change(repo)
    tree = plan(repo, base, publish_head)
    commit = json.loads(run_request(repo, "connector-tree", "--tree-sha", tree["expected_tree_sha"]).stdout)
    fake_transport_commit = "a" * 40
    update = json.loads(run_request(repo, "connector-commit", "--commit-sha", fake_transport_commit).stdout)
    update_packet = json.loads(Path(update["update_packet"]).read_text(encoding="utf-8"))
    assert update_packet["action"] == "GitHub.update_ref"
    assert update_packet["action_args"]["branch_name"] == "publish"
    assert update_packet["action_args"]["force"] is False
    assert not any((transaction(repo) / "connector").glob("*verify*"))

    recorded = json.loads(run_request(
        repo, "record",
        "--gateway-transport-commit", fake_transport_commit,
        "--gateway-run-id", "12345",
        "--gateway-conclusion", "success",
    ).stdout)
    assert recorded["verified"] is True
    assert recorded["remote_commit"] == result["publish_commit"]
    assert recorded["publish_commit"] == fake_transport_commit
    assert not transaction(repo).exists()


def test_record_stays_bound_to_prepared_target_if_local_head_advances(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    first = prepare_change(repo, "first\n")
    tree = plan(repo, base, publish_head)
    run_request(repo, "connector-tree", "--tree-sha", tree["expected_tree_sha"])
    candidate = "b" * 40
    run_request(repo, "connector-commit", "--commit-sha", candidate)
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "later local work")
    recorded = json.loads(run_request(
        repo, "record",
        "--gateway-transport-commit", candidate,
        "--gateway-run-id", "42",
        "--gateway-conclusion", "success",
    ).stdout)
    assert recorded["local_head"] == first["local_target_commit"]
    assert recorded["local_head"] != git(repo, "rev-parse", "HEAD")


def test_combined_preflight_rejects_moved_develop_or_publish(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    moved_target = run_request(
        repo, "connector-plan", "--target-remote-head", "c" * 40,
        "--publish-remote-head", publish_head, check=False,
    )
    assert moved_target.returncode != 0
    moved_publish = run_request(
        repo, "connector-plan", "--target-remote-head", base,
        "--publish-remote-head", "d" * 40, check=False,
    )
    assert moved_publish.returncode != 0


def test_cancel_uses_heads_only_and_never_needs_publish_tree_read(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    plan(repo, base, publish_head)
    cancelled = json.loads(run_request(
        repo, "cancel",
        "--target-remote-head", base,
        "--publish-remote-head", publish_head,
    ).stdout)
    assert cancelled["cancelled"] is True
    assert not transaction(repo).exists()


def test_standard_cli_exposes_no_generation_verification_or_repair_commands() -> None:
    top = run_request(ROOT, "--help").stdout
    assert "{init,prepare,connector-plan,connector-tree,connector-commit,cancel,record}" in top
    for forbidden in ("connector-verify", "connector-repair", "--repo", "native-publish"):
        assert forbidden not in top
    assert "--publish-remote-tree" not in run_request(ROOT, "connector-plan", "--help").stdout
    assert "--publish-remote-tree" not in run_request(ROOT, "cancel", "--help").stdout


def test_standard_prepare_rejects_untrusted_workflow_changes(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    commit_all(repo, "change workflow")
    result = run_request(repo, "prepare", check=False)
    assert result.returncode != 0
    assert "workflow_maintenance.py prepare" in result.stderr


def test_standard_prepare_allows_trusted_gateway_workflow_change(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "publish-gateway.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: Publish Gateway\n", encoding="utf-8")
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


def test_gateway_contract_is_fixed_slot_local_validation_without_receipt_or_status_api() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "publish_gateway_validate.py").read_text(encoding="utf-8")
    assert "'.publish/transport/**'" in workflow
    assert ".publish/requests" not in workflow
    assert ".publish/retries" not in workflow
    assert "Record verified publish receipt" not in workflow
    assert "Mark Fast CI pending" not in workflow
    assert "statuses: write" not in workflow
    assert "git ls-remote" not in workflow
    assert "git fetch --quiet --no-tags origin" not in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "Dispatch Fast CI for published branch" in workflow
    assert "load_indexed_payload" not in validator
    assert "gh api" not in validator
    assert "_transport_parts" in validator
    assert "git bundle" not in workflow  # bundle verification/fetch is consolidated in the validator
    assert not (ROOT / "scripts" / "publish_gateway_payload.py").exists()
