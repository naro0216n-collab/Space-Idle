from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from development_tests.script_harness import load_script, run_script


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_request.py"
PUBLISH_REQUEST = load_script(SCRIPT, "space_idle_test_publish_request")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def run_request(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_script(PUBLISH_REQUEST, SCRIPT, repo, *args, check=check)


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def manifest_path(repo: Path) -> Path:
    return repo / ".git" / "space-idle-publish-transaction" / "manifest.json"


def plan_dir(repo: Path) -> Path:
    return repo / ".git" / "space-idle-publish-transaction" / "connector"


def write_source_snapshot(repo: Path, destination: Path) -> Path:
    destination.mkdir()
    commit = git(repo, "rev-parse", "HEAD^{commit}")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    (destination / ".source-commit").write_text(commit + "\n", encoding="utf-8")
    (destination / ".source-tree").write_text(tree + "\n", encoding="utf-8")
    (destination / ".source-branch").write_text("develop\n", encoding="utf-8")
    git(repo, "bundle", "create", str(destination / "repository.bundle"), "refs/heads/develop")
    return destination


def init_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    source_snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((source_snapshot / "repository.bundle").resolve()))
    run_request(repo, "init")
    return repo, base_commit, base_tree


def prepared(repo: Path) -> dict[str, object]:
    return json.loads(manifest_path(repo).read_text(encoding="utf-8"))


def test_init_rejects_a_snapshot_that_is_not_the_exact_restored_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    source_snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((source_snapshot / "repository.bundle").resolve()))

    (repo / "payload.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "later")

    result = run_request(repo, "init", check=False)
    assert result.returncode != 0
    assert not (repo / ".git" / "space-idle-publish-state.json").exists()


def test_init_derives_snapshot_from_origin_and_rejects_manual_source_selector(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    source_snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")

    missing_origin = run_request(repo, "init", check=False)
    assert missing_origin.returncode != 0
    assert "origin" in missing_origin.stderr

    git(repo, "remote", "add", "origin", str((source_snapshot / "repository.bundle").resolve()))
    run_request(repo, "init")

    manual = run_request(repo, "init", str(source_snapshot), check=False)
    assert manual.returncode != 0
    assert "unrecognized arguments" in manual.stderr


def make_receipt(repo: Path) -> dict[str, object]:
    request = prepared(repo)
    raw_commit = subprocess.run(
        ["git", "cat-file", "commit", str(request["publish_commit"])],
        cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    return {
        "version": 3,
        "request_id": request["request_id"],
        "request_version": 7,
        "target_branch": request["target_branch"],
        "base_commit": request["base_sha"],
        "target_tree": request["target_tree"],
        "published_commit": request["publish_commit"],
        "published_tree": request["target_tree"],
        "published_commit_object_b64": base64.b64encode(raw_commit).decode("ascii"),
    }


def test_prepare_and_record_use_one_fixed_transaction(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    commit_all(repo, "coherent change")
    local_target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    meta = json.loads(run_request(repo, "prepare").stdout)
    request = prepared(repo)
    assert meta["manifest"] == str(manifest_path(repo))
    assert request["base_sha"] == base_commit
    assert request["target_branch"] == "develop"
    assert request["target_tree"] == target_tree
    assert request["local_target_commit"] == local_target
    payload = base64.b64decode(str(request["payload_b64"]), validate=True)
    assert hashlib.sha256(payload).hexdigest() == request["payload_sha256"]

    second = run_request(repo, "prepare", check=False)
    assert second.returncode != 0
    assert "active publish transaction" in second.stderr

    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(make_receipt(repo)), encoding="utf-8")
    recorded = json.loads(run_request(repo, "record", "--receipt", str(receipt)).stdout)
    assert recorded["verified"] is True
    assert recorded["remote_tree"] == target_tree
    assert not manifest_path(repo).exists()

    (repo / "payload.txt").write_text("next\n", encoding="utf-8")
    commit_all(repo, "next")
    run_request(repo, "prepare")
    assert prepared(repo)["base_sha"] == request["publish_commit"]


def test_record_is_bound_to_prepared_head_even_after_local_head_advances(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "prepare")

    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "later local work")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(make_receipt(repo)), encoding="utf-8")
    recorded = json.loads(run_request(repo, "record", "--receipt", str(receipt)).stdout)
    assert recorded["local_head"] == checkpoint
    assert recorded["remote_tree"] == checkpoint_tree
    assert git(repo, "rev-parse", "HEAD") != checkpoint


def test_connector_plan_revalidates_manifest_and_remote_base(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    run_request(repo, "prepare")

    wrong_head = run_request(repo, "connector-plan", "--target-remote-head", "3" * 40, check=False)
    assert wrong_head.returncode != 0
    assert "target branch HEAD moved since prepare" in wrong_head.stderr

    request = prepared(repo)
    payload = str(request["payload_b64"])
    request["payload_b64"] = ("A" if payload[0] != "A" else "B") + payload[1:]
    manifest_path(repo).write_text(json.dumps(request), encoding="utf-8")
    corrupt = run_request(repo, "connector-plan", "--target-remote-head", base, check=False)
    assert corrupt.returncode != 0
    assert "sha256 mismatch" in corrupt.stderr or "invalid publish bundle" in corrupt.stderr


def test_connector_plan_generates_indexed_payload_generation_and_submit_packet(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("connector\n" * 400, encoding="utf-8")
    commit_all(repo, "connector transport")
    run_request(repo, "prepare")
    request = prepared(repo)
    request_id = str(request["request_id"])
    plan = json.loads(run_request(repo, "connector-plan", "--target-remote-head", base).stdout)
    assert plan["stage"] == "packets-ready"
    assert plan["strategy"] == "append-only-payload-generations-then-request"
    assert plan["current_generation"] == 0
    assert plan["upload_call_count"] == 1
    assert plan["response_sha_handoff_required"] is False
    assert "copy/paste" in plan["next"]

    upload = json.loads(Path(plan["upload_packets"][0]).read_text(encoding="utf-8"))
    assert upload["action"] == "GitHub.create_file"
    assert upload["generation"] == 0
    assert upload["action_args"]["repository_full_name"] == "naro0216n-collab/Space-Idle"
    assert upload["action_args"]["branch"] == "publish"
    assert upload["action_args"]["path"] == f".publish/payloads/{request_id}/g0000/0000.b64"
    assert plan["remote_payload_paths"] == [upload["action_args"]["path"]]
    assert plan["remote_payload_dir"] == f".publish/payloads/{request_id}"
    assert plan["expected_blob_git_oids"] == [upload["expected_blob_git_oid"]]

    index_packet = json.loads(Path(plan["payload_index_packet"]).read_text(encoding="utf-8"))
    assert index_packet["action"] == "GitHub.create_file"
    assert index_packet["generation"] == 0
    assert index_packet["action_args"]["path"] == f".publish/payloads/{request_id}/index-0000.json"
    index = json.loads(index_packet["action_args"]["content"])
    assert index["version"] == 1
    assert index["request_id"] == request_id
    assert index["generation"] == 0
    assert index["payload_chars"] == len(str(request["payload_b64"]))
    assert index["payload_sha256"] == request["payload_sha256"]
    assert index["parts"] == [{
        "index": 0,
        "path": "g0000/0000.b64",
        "chars": len(upload["action_args"]["content"]),
        "blob_git_oid": upload["expected_blob_git_oid"],
    }]

    packet = json.loads(Path(plan["submit_request_packet"]).read_text(encoding="utf-8"))
    transport = json.loads(packet["action_args"]["content"])
    assert transport["version"] == 7
    assert transport["payload_source"] == {
        "kind": "indexed-files",
        "directory": f".publish/payloads/{request_id}",
        "minimum_generation": 0,
    }

    replan = run_request(repo, "connector-plan", "--target-remote-head", base, check=False)
    assert replan.returncode != 0
    assert "already initialized" in replan.stderr


def test_initial_generation_keeps_fleet_sized_payload_in_one_file(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, _, _ = init_repo(tmp_path)
    parts = module._split_payload_for_file_calls(
        repo, "naro0216n-collab/Space-Idle", "publish", "a" * 32, 0,
        "A" * 81_780, module.CONNECTOR_CALL_BUDGET_BYTES
    )
    assert len(parts) == 1
    assert module._connector_call_bytes(parts[0]["packet"]) < 144 * 1024


def test_connector_profile_uses_144_kib_as_initial_actual_call_upper_bound(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, _, _ = init_repo(tmp_path)
    request_id = "a" * 32
    empty = module._connector_payload_file_packet(
        repo, "naro0216n-collab/Space-Idle", "publish", request_id, 0, "", 0
    )
    max_chars = module.CONNECTOR_CALL_BUDGET_BYTES - module._connector_call_bytes(empty)

    single = module._split_payload_for_file_calls(
        repo, "naro0216n-collab/Space-Idle", "publish", request_id, 0,
        "A" * max_chars, module.CONNECTOR_CALL_BUDGET_BYTES
    )
    assert len(single) == 1
    assert module._connector_call_bytes(single[0]["packet"]) == 144 * 1024

    split = module._split_payload_for_file_calls(
        repo, "naro0216n-collab/Space-Idle", "publish", request_id, 0,
        "A" * (max_chars + 1), module.CONNECTOR_CALL_BUDGET_BYTES
    )
    assert len(split) == 2
    assert all(module._connector_call_bytes(part["packet"]) <= 144 * 1024 for part in split)


def test_initial_generation_splits_only_when_actual_call_exceeds_limit(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    content = "\n".join(
        f"{i:06d}:{hashlib.sha256(str(i).encode()).hexdigest()}" for i in range(7000)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large connector transport")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, "connector-plan", "--target-remote-head", base).stdout)
    assert plan["upload_call_count"] >= 2
    assert plan["connector_call_budget_bytes"] == 144 * 1024
    assert plan["generation_call_budget_bytes"] == 144 * 1024
    for packet_name in plan["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_file"
        size = len(json.dumps(packet["action_args"], separators=(",", ":")).encode("utf-8"))
        assert size <= 144 * 1024


def test_connector_repair_creates_append_only_smaller_generation(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    content = "\n".join(
        f"{i:05d}:{hashlib.sha256(str(i).encode()).hexdigest()}" for i in range(900)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "repair target")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, "connector-plan", "--target-remote-head", base).stdout)
    initial_max = max(plan["upload_call_bytes"])

    repair = json.loads(run_request(repo, "connector-repair").stdout)
    assert repair["stage"] == "repair-generation-ready"
    assert repair["previous_generation"] == 0
    assert repair["generation"] == 1
    assert repair["previous_max_upload_call_bytes"] == initial_max
    assert repair["max_upload_call_bytes"] < initial_max
    assert repair["upload_call_count"] >= plan["upload_call_count"]
    assert "remote_blob_sha" not in json.dumps(repair)

    for packet_name in repair["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_file"
        assert packet["generation"] == 1
        assert "/g0001/" in packet["action_args"]["path"]
        assert "sha" not in packet["action_args"]

    index_packet = json.loads(Path(repair["payload_index_packet"]).read_text(encoding="utf-8"))
    assert index_packet["action"] == "GitHub.create_file"
    assert index_packet["action_args"]["path"].endswith("/index-0001.json")
    index = json.loads(index_packet["action_args"]["content"])
    assert index["generation"] == 1
    assert index["part_count"] == repair["upload_call_count"]

    retry_packet = json.loads(Path(repair["retry_request_packet"]).read_text(encoding="utf-8"))
    assert retry_packet["action"] == "GitHub.create_file"
    assert retry_packet["action_args"]["path"].endswith("/g0001.json")
    retry_request = json.loads(retry_packet["action_args"]["content"])
    assert retry_request["version"] == 7
    assert retry_request["request_id"] == prepared(repo)["request_id"]
    assert retry_request["payload_source"]["minimum_generation"] == 1

    repair2 = json.loads(run_request(repo, "connector-repair").stdout)
    assert repair2["generation"] == 2
    assert repair2["max_upload_call_bytes"] < repair["max_upload_call_bytes"]
    assert all("/g0002/" in json.loads(Path(name).read_text())["action_args"]["path"]
               for name in repair2["upload_packets"])


def test_payload_index_is_self_consistent_and_uses_precomputed_blob_oids(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    module = PUBLISH_REQUEST
    request_id = "f" * 32
    payload = "alphabetagamma"
    prepared_request = {
        "request_id": request_id,
        "payload_b64": payload,
        "payload_sha256": hashlib.sha256(base64.b64decode("YWJjZA==")).hexdigest(),
    }
    parts = module._split_payload_for_file_calls(
        repo, "naro0216n-collab/Space-Idle", "publish", request_id, 3, payload, 1024
    )
    index = module._payload_index_document(prepared_request, request_id, 3, parts)
    assert index["generation"] == 3
    assert index["part_count"] == len(parts)
    assert [part["index"] for part in index["parts"]] == list(range(len(parts)))
    assert [part["blob_git_oid"] for part in index["parts"]] == [part["oid"] for part in parts]
    assert [part["path"] for part in index["parts"]] == [
        f"g0003/{i:04d}.b64" for i in range(len(parts))
    ]



def test_connector_repair_migrates_active_v6_transport_without_reprepare(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    content = "\n".join(
        f"{i:05d}:{hashlib.sha256(str(i).encode()).hexdigest()}" for i in range(900)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "legacy repair target")
    run_request(repo, "prepare")
    request = prepared(repo)
    request["version"] = 6
    manifest_path(repo).write_text(json.dumps(request, indent=2), encoding="utf-8")

    # Build a representative v6 connector state and upload packet from the same canonical payload.
    output = plan_dir(repo)
    output.mkdir(parents=True)
    old_parts = PUBLISH_REQUEST._split_payload_for_file_calls(
        repo, "naro0216n-collab/Space-Idle", "publish", str(request["request_id"]), 0,
        str(request["payload_b64"]), PUBLISH_REQUEST.CONNECTOR_CALL_BUDGET_BYTES,
    )
    old_packet = old_parts[0]["packet"]
    # Rewrite the generated v7 path into the legacy unversioned path shape.
    old_packet["action_args"]["path"] = f".publish/payloads/{request['request_id']}/0000.b64"
    old_packet.pop("generation", None)
    old_path = output / "upload-part-000.json"
    old_path.write_text(json.dumps(old_packet), encoding="utf-8")
    submit_path = output / "submit-request.json"
    submit_path.write_text("{}", encoding="utf-8")
    legacy_state = {
        "version": 4,
        "stage": "packets-ready",
        "manifest": str(manifest_path(repo)),
        "request_id": request["request_id"],
        "github_repository": "naro0216n-collab/Space-Idle",
        "publish_branch": "publish",
        "target_branch": "develop",
        "target_remote_head": base,
        "expected_blob_git_oids": [old_packet["expected_blob_git_oid"]],
        "expected_payload_tree_git_oid": "1" * 40,
        "upload_packets": [str(old_path)],
        "remote_payload_paths": [old_packet["action_args"]["path"]],
        "remote_payload_dir": f".publish/payloads/{request['request_id']}",
        "submit_request_packet": str(submit_path),
    }
    (output / "connector-state.json").write_text(json.dumps(legacy_state), encoding="utf-8")

    migrated = json.loads(run_request(repo, "connector-repair").stdout)
    assert migrated["stage"] == "legacy-v6-repair-migrated"
    assert migrated["generation"] == 0
    assert prepared(repo)["version"] == 7
    assert migrated["max_upload_call_bytes"] < PUBLISH_REQUEST._connector_call_bytes(old_packet)
    assert all("/g0000/" in json.loads(Path(name).read_text())["action_args"]["path"]
               for name in migrated["upload_packets"])
    retry_packet = json.loads(Path(migrated["retry_request_packet"]).read_text())
    retry_request = json.loads(retry_packet["action_args"]["content"])
    assert retry_request["version"] == 7
    assert retry_request["request_id"] == request["request_id"]
    assert retry_request["base_sha"] == request["base_sha"]
    assert retry_request["target_tree"] == request["target_tree"]
    assert retry_request["publish_commit"] == request["publish_commit"]
    assert retry_request["payload_source"]["minimum_generation"] == 0


def test_record_can_close_an_already_prepared_v6_transaction(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("legacy checkpoint\n", encoding="utf-8")
    commit_all(repo, "legacy checkpoint")
    run_request(repo, "prepare")
    request = prepared(repo)
    request["version"] = 6
    manifest_path(repo).write_text(json.dumps(request), encoding="utf-8")

    receipt_data = make_receipt(repo)
    receipt_data["request_version"] = 6
    receipt = tmp_path / "receipt-v6.json"
    receipt.write_text(json.dumps(receipt_data), encoding="utf-8")
    recorded = json.loads(run_request(repo, "record", "--receipt", str(receipt)).stdout)
    assert recorded["verified"] is True
    assert not manifest_path(repo).exists()


def test_adaptive_repair_converges_from_observed_33k_class_packet_without_fixed_chunk_size(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, _, _ = init_repo(tmp_path)
    request_id = "e" * 32
    payload = "A" * 33_752
    prepared_request = {
        "request_id": request_id,
        "payload_b64": payload,
        "payload_sha256": "0" * 64,
    }
    parts0 = module._split_payload_for_file_calls(
        repo, "naro0216n-collab/Space-Idle", "publish", request_id, 0,
        payload, module.CONNECTOR_CALL_BUDGET_BYTES,
    )
    assert len(parts0) == 1
    current = {
        "generation": 0,
        "upload_call_bytes": [module._connector_call_bytes(parts0[0]["packet"])],
    }
    previous_max = current["upload_call_bytes"][0]
    assert 33_000 < previous_max < 40_000

    for generation in range(1, 4):
        budget = module._next_repair_call_budget(repo, prepared_request, current)
        parts = module._split_payload_for_file_calls(
            repo, "naro0216n-collab/Space-Idle", "publish", request_id, generation,
            payload, budget,
        )
        next_max = max(module._connector_call_bytes(part["packet"]) for part in parts)
        assert next_max < previous_max
        current = {
            "generation": generation,
            "upload_call_bytes": [module._connector_call_bytes(part["packet"]) for part in parts],
        }
        previous_max = next_max
    assert previous_max < 10_000
    assert len(parts) > 1

def test_standard_cli_has_no_alternative_repository_target_or_transaction_selectors() -> None:
    top = run_request(SCRIPT.parents[1], "--help").stdout
    assert "{init,prepare,connector-plan,connector-repair,record}" in top
    for forbidden in ("native-publish", " plan ", "--repo"):
        assert forbidden not in f" {top.replace(chr(10), ' ')} "
    command_forbidden = {
        "init": ("--repo", "--local-ref", "--remote-commit", "--remote-tree", "source_snapshot"),
        "prepare": ("--repo", "--target-ref", "--output", "--target-branch", "--message"),
        "connector-plan": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                           "--publish-branch", "--output-dir", "--connector-call-budget-bytes"),
        "connector-repair": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                             "--publish-branch", "--path", "--content", "--request-id",
                             "--part-index", "--remote-blob-sha"),
        "record": ("--repo", "--manifest", "--remote-commit", "--remote-tree", "--local-ref"),
    }
    for command, forbidden_flags in command_forbidden.items():
        help_text = run_request(SCRIPT.parents[1], command, "--help").stdout
        for flag in forbidden_flags:
            assert flag not in help_text


def test_prepare_is_head_only_develop_and_excludes_uncommitted_work(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "payload.txt").write_text("uncommitted\n", encoding="utf-8")
    (repo / "later.txt").write_text("not published\n", encoding="utf-8")
    result = json.loads(run_request(repo, "prepare").stdout)
    request = prepared(repo)
    assert request["target_branch"] == "develop"
    assert result["local_target_commit"] == checkpoint
    assert result["target_tree"] == checkpoint_tree
    assert result["working_tree_clean"] is False
    assert result["uncommitted_changes_excluded"] is True
    raw = subprocess.run(["git", "cat-file", "commit", str(request["publish_commit"])], cwd=repo,
                         check=True, stdout=subprocess.PIPE).stdout
    assert raw.partition(b"\n\n")[2] == b"checkpoint\n"


def test_standard_prepare_rejects_untrusted_workflow_changes(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    commit_all(repo, "change workflow")
    result = run_request(repo, "prepare", check=False)
    assert result.returncode != 0
    assert "standard Publish Gateway cannot publish untrusted .github/workflows changes" in result.stderr
    assert "python scripts/workflow_maintenance.py prepare" in result.stderr
    assert not manifest_path(repo).exists()


def test_standard_prepare_allows_trusted_publish_gateway_control_workflow(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "publish-gateway.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: Publish Gateway\n", encoding="utf-8")
    commit_all(repo, "change trusted gateway workflow")
    result = json.loads(run_request(repo, "prepare").stdout)
    assert result["verified"] is True
    assert prepared(repo)["target_tree"] == git(repo, "rev-parse", "HEAD^{tree}")


def test_gateway_trusted_workflow_guard_requires_publish_control_blob_identity(tmp_path: Path) -> None:
    validator = SCRIPT.parents[1] / "scripts" / "publish_gateway_validate.py"
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

    (repo / "payload.txt").write_text("mixed source change\n", encoding="utf-8")
    commit_all(repo, "mixed target")
    target = git(repo, "rev-parse", "HEAD")
    env = {**__import__("os").environ, "BASE_SHA": base, "PUBLISH_COMMIT": target, "GITHUB_SHA": control}
    ok = subprocess.run(
        ["python", str(validator), "--verify-trusted-workflow"],
        cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert ok.returncode == 0, ok.stderr

    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text("name: untrusted\n", encoding="utf-8")
    commit_all(repo, "untrusted workflow")
    blocked = subprocess.run(
        ["python", str(validator), "--verify-trusted-workflow"],
        cwd=repo,
        env={**env, "PUBLISH_COMMIT": git(repo, "rev-parse", "HEAD")},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert blocked.returncode != 0
    assert "untrusted workflow change" in blocked.stderr


def test_gateway_contract_is_v7_indexed_generation_and_exact_commit_verification() -> None:
    root = SCRIPT.parents[1]
    workflow = (root / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    request_validator = (root / "scripts" / "publish_gateway_validate.py").read_text(encoding="utf-8")
    payload_validator = (root / "scripts" / "publish_gateway_payload.py").read_text(encoding="utf-8")
    assert "'.publish/requests/*.json'" in workflow
    assert "'.publish/retries/*/*.json'" in workflow
    assert ".publish/request.patch" not in workflow
    assert "python scripts/publish_gateway_validate.py" in workflow
    assert "python scripts/publish_gateway_validate.py --verify-trusted-workflow" in workflow
    assert "TRUSTED_CONTROL_WORKFLOW" in request_validator
    assert "trusted control workflow blob mismatch" in request_validator
    assert 'request["version"] != 7' in request_validator
    assert "indexed-files" in payload_validator
    assert "git-tree" not in payload_validator
    assert r'index-(\d{4})\.json' in payload_validator
    assert "Using payload generation" in payload_validator
    assert "minimum_generation" in payload_validator
    assert "trigger_generation" in request_validator
    assert "payload part path blob mismatch generation" in payload_validator
    assert "_git_blob_oid" in payload_validator
    assert "GitHub payload blob Git OID mismatch" in payload_validator
    assert "bundle sha256 mismatch" in payload_validator
    assert "git bundle verify" in workflow
    assert 'actual_parent="$(git rev-parse "${PUBLISH_COMMIT}^")"' in workflow
    assert 'actual_tree="$(git rev-parse "${PUBLISH_COMMIT}^{tree}")"' in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "'request_version': 7" in workflow
    assert "Dispatch Fast CI for published branch" in workflow
