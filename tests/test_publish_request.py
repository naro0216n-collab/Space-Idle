from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_request.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def run_request(repo: Path, *args: str) -> str:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)


def init_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    return repo, base_commit, base_tree


def prepared(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_receipt(repo: Path, manifest: Path) -> dict[str, object]:
    request = prepared(manifest)
    raw_commit = subprocess.run(
        ["git", "cat-file", "commit", str(request["publish_commit"])],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return {
        "version": 3,
        "request_id": request["request_id"],
        "request_version": 5,
        "target_branch": request["target_branch"],
        "base_commit": request["base_sha"],
        "target_tree": request["target_tree"],
        "published_commit": request["publish_commit"],
        "published_tree": request["target_tree"],
        "published_commit_object_b64": base64.b64encode(raw_commit).decode("ascii"),
    }


def load_module():
    spec = importlib.util.spec_from_file_location("publish_request", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def active_manifest(repo: Path) -> Path:
    return repo / ".git" / "space-idle-publish-active" / "manifest.json"


def gateway_begin(
    repo: Path,
    remote_head: str,
    *,
    target_ref: str = "HEAD",
    target_branch: str = "develop",
) -> dict[str, object]:
    return json.loads(
        run_request(
            repo,
            "gateway-begin",
            "--target-ref",
            target_ref,
            "--target-branch",
            target_branch,
            "--target-remote-head",
            remote_head,
        )
    )


def gateway_submit_expected(repo: Path) -> dict[str, object]:
    session_path = repo / ".git" / "space-idle-publish-active" / "session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    args: list[str] = ["gateway-submit"]
    for packet_name in session["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        args.extend(["--uploaded-blob-sha", packet["expected_blob_git_oid"]])
    return json.loads(run_request(repo, *args))


def test_gateway_begin_recreates_exact_target_and_record_advances_baseline(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    commit_all(repo, "coherent change")
    local_target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    meta = gateway_begin(repo, base_commit)
    manifest = active_manifest(repo)
    request = prepared(manifest)
    assert meta["entrypoint"] == "gateway-begin"
    assert meta["strategy"] == "verified-blobs-then-request-file"
    assert meta["phase"] == "upload-payload-parts"
    assert len(meta["connector_actions"]) >= 1
    assert all(row["action"] == "GitHub.create_blob" for row in meta["connector_actions"])
    assert request["version"] == 5
    assert request["target_branch"] == "develop"
    assert request["base_sha"] == base_commit
    assert request["target_tree"] == target_tree
    assert request["local_target_commit"] == local_target
    payload = base64.b64decode(str(request["payload_b64"]), validate=True)
    assert hashlib.sha256(payload).hexdigest() == request["payload_sha256"]

    publish_commit = str(request["publish_commit"])
    assert git(repo, "rev-parse", f"{publish_commit}^") == base_commit
    assert git(repo, "rev-parse", f"{publish_commit}^{{tree}}") == target_tree

    submitted = gateway_submit_expected(repo)
    assert submitted["connector_action"]["action"] == "GitHub.create_file"
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(make_receipt(repo, manifest)), encoding="utf-8")
    recorded = json.loads(run_request(repo, "gateway-record", "--receipt", str(receipt_path)))
    assert recorded["verified"] is True
    assert recorded["active_session_cleared"] is True
    assert recorded["remote_commit"] == publish_commit
    assert recorded["remote_tree"] == target_tree
    assert not (repo / ".git" / "space-idle-publish-active").exists()

    (repo / "new.txt").write_text("newer\n", encoding="utf-8")
    commit_all(repo, "next")
    next_meta = gateway_begin(repo, publish_commit)
    assert prepared(active_manifest(repo))["base_sha"] == publish_commit
    assert next_meta["verified"] is True


def test_gateway_record_uses_session_target_when_local_head_has_advanced(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    gateway_begin(repo, base_commit, target_ref=checkpoint)
    manifest = active_manifest(repo)

    (repo / "later.txt").write_text("next work\n", encoding="utf-8")
    commit_all(repo, "next local work")
    assert git(repo, "rev-parse", "HEAD") != checkpoint

    gateway_submit_expected(repo)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(make_receipt(repo, manifest)), encoding="utf-8")
    recorded = json.loads(run_request(repo, "gateway-record", "--receipt", str(receipt_path)))
    assert recorded["local_head"] == checkpoint
    assert recorded["remote_tree"] == checkpoint_tree
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["local_head"] == checkpoint
    assert git(repo, "rev-parse", "HEAD") != checkpoint


def test_bundle_payload_is_deterministic_for_same_base_tree_and_message(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("target\n" * 200, encoding="utf-8")
    commit_all(repo, "same checkpoint")
    module = load_module()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    module._prepare_request(
        repo,
        target_branch="develop",
        target_ref="HEAD",
        message_text=None,
        connector_call_budget_bytes=module.DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
        output=first,
    )
    time.sleep(1.05)
    module._prepare_request(
        repo,
        target_branch="develop",
        target_ref="HEAD",
        message_text=None,
        connector_call_budget_bytes=module.DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
        output=second,
    )
    a = prepared(first)
    b = prepared(second)
    assert a["request_id"] != b["request_id"]
    assert a["publish_commit"] == b["publish_commit"]
    assert a["payload_sha256"] == b["payload_sha256"]
    assert a["payload_b64"] == b["payload_b64"]


def test_internal_verify_rejects_corrupted_payload(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    module = load_module()
    manifest = tmp_path / "request.json"
    module._prepare_request(
        repo,
        target_branch="develop",
        target_ref="HEAD",
        message_text=None,
        connector_call_budget_bytes=module.DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
        output=manifest,
    )
    request = prepared(manifest)
    payload = str(request["payload_b64"])
    request["payload_b64"] = ("A" if payload[0] != "A" else "B") + payload[1:]
    manifest.write_text(json.dumps(request), encoding="utf-8")
    try:
        module._verify_prepared_request(repo, manifest)
    except module.PublishStateError as exc:
        assert "sha256 mismatch" in str(exc) or "invalid publish bundle" in str(exc)
    else:
        raise AssertionError("corrupted publish payload was accepted")


def test_plan_reports_combined_and_sequential_bundle_transport(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("first\n" * 300, encoding="utf-8")
    commit_all(repo, "first checkpoint")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "second.txt").write_text("second\n" * 300, encoding="utf-8")
    commit_all(repo, "second checkpoint")
    second = git(repo, "rev-parse", "HEAD")
    plan = json.loads(run_request(repo, "plan"))
    assert plan["transport"] == "git-bundle"
    assert plan["target_ref"] == second
    assert plan["sequential_local_commits_available"] is True
    assert [item["local_commit"] for item in plan["sequential_requests"]] == [first, second]
    assert all(item["payload_bytes"] > 0 for item in plan["sequential_requests"])
    assert plan["combined_request"]["target_tree"] == git(repo, "rev-parse", "HEAD^{tree}")


def test_gateway_begin_uses_verified_blob_before_small_request(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("connector transport\n" * 400, encoding="utf-8")
    commit_all(repo, "connector transport")
    plan = gateway_begin(repo, base_commit)
    assert plan["strategy"] == "verified-blobs-then-request-file"
    assert plan["phase"] == "upload-payload-parts"
    assert plan["initial_connector_action_budget_bytes"] == 96 * 1024
    assert plan["adaptive_split_on_blob_sha_mismatch"] is True
    assert plan["metadata_call_budget_bytes"] == 96 * 1024
    assert plan["connector_action_selection_is_not_a_decision"] is True
    assert plan["execute_packet_action_exactly"] is True
    assert len(plan["connector_actions"]) == 1
    action = plan["connector_actions"][0]
    assert action["action"] == "GitHub.create_blob"
    assert action["connector_namespace"] == "GitHub"
    assert action["connector_function"] == "create_blob"
    packet = json.loads(Path(action["packet"]).read_text(encoding="utf-8"))
    assert packet["action_args"]["repository_full_name"] == "naro0216n-collab/Space-Idle"
    submitted = gateway_submit_expected(repo)
    assert submitted["connector_action"]["action"] == "GitHub.create_file"
    assert submitted["connector_action"]["connector_namespace"] == "GitHub"
    assert submitted["connector_action"]["connector_function"] == "create_file"
    submit_packet = json.loads(
        Path(submitted["connector_action"]["packet"]).read_text(encoding="utf-8")
    )
    transport_request = json.loads(submit_packet["action_args"]["content"])
    assert transport_request["payload_source"]["kind"] == "git-blobs"
    assert transport_request["base_sha"] == base_commit


def test_gateway_begin_starts_at_connector_budget_and_defers_failed_parts_to_sha_handshake(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("\n".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(400)) + "\n", encoding="utf-8")
    commit_all(repo, "adaptive bridge")
    plan = gateway_begin(repo, base_commit)
    assert plan["initial_connector_action_budget_bytes"] == 96 * 1024
    assert plan["adaptive_split_on_blob_sha_mismatch"] is True
    assert len(plan["connector_actions"]) == 1
    module = load_module()
    assert all(
        module._connector_call_bytes(json.loads(Path(action["packet"]).read_text(encoding="utf-8"))) <= 96 * 1024
        for action in plan["connector_actions"]
    )


def test_gateway_submit_resplits_only_mismatched_payload_part(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("adaptive split\n" * 40, encoding="utf-8")
    commit_all(repo, "adaptive split")
    plan = gateway_begin(repo, base_commit)
    assert len(plan["connector_actions"]) == 1
    result = json.loads(run_request(repo, "gateway-submit", "--uploaded-blob-sha", "0" * 40))
    assert result["phase"] == "upload-payload-parts"
    assert result["request_action_generated"] is False
    assert result["resplit_mismatched_parts"] == 1
    assert len(result["connector_actions"]) == 2
    submitted = gateway_submit_expected(repo)
    assert submitted["phase"] == "submit-request"
    assert submitted["connector_action"]["action"] == "GitHub.create_file"


def test_overflow_begin_emits_only_blob_actions_and_submit_is_separate(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    content = "\n".join(
        f"{index:06d}:{hashlib.sha256(str(index).encode()).hexdigest()}" for index in range(3000)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large connector transport")
    module = load_module()
    active_dir = repo / ".git" / "space-idle-publish-active"
    active_dir.mkdir(parents=True)
    manifest = active_dir / "manifest.json"
    module._prepare_request(
        repo,
        target_branch="develop",
        target_ref="HEAD",
        message_text=None,
        connector_call_budget_bytes=20_000,
        output=manifest,
    )
    connector_dir = active_dir / "connector"
    plan = module._build_connector_plan(
        repo,
        manifest=manifest,
        github_repository=module.GITHUB_REPOSITORY,
        target_remote_head=base_commit,
        publish_branch=module.PUBLISH_BRANCH,
        output_dir=connector_dir,
        connector_call_budget_bytes=20_000,
        defer_submit_for_split=True,
        always_blob=True,
    )
    assert plan["strategy"] == "verified-blobs-then-request-file"
    assert plan["submit_request_packet"] is None
    assert plan["submit_deferred_until_upload_phase_complete"] is True
    assert not (connector_dir / "submit-request.json").exists()
    assert len(plan["upload_packets"]) >= 2
    for packet_name in plan["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_blob"

    prepared_request = prepared(manifest)
    session = {
        "version": 2,
        "request_id": prepared_request["request_id"],
        "manifest": str(manifest),
        "connector_dir": str(connector_dir),
        "strategy": plan["strategy"],
        "phase": "upload-payload-parts",
        "target_branch": prepared_request["target_branch"],
        "base_sha": prepared_request["base_sha"],
        "target_tree": prepared_request["target_tree"],
        "publish_commit": prepared_request["publish_commit"],
        "local_target_commit": prepared_request["local_target_commit"],
        "remote_request_path": plan["remote_request_path"],
        "remote_receipt_path": plan["remote_receipt_path"],
        "upload_packets": list(plan["upload_packets"]),
        "payload_parts": [
            {
                "packet": packet_name,
                "oid": json.loads(Path(packet_name).read_text(encoding="utf-8"))["expected_blob_git_oid"],
                "chars": len(json.loads(Path(packet_name).read_text(encoding="utf-8"))["action_args"]["content"]),
                "confirmed_sha": None,
            }
            for packet_name in plan["upload_packets"]
        ],
        "next_packet_index": len(plan["upload_packets"]),
        "submit_request_packet": None,
    }
    (active_dir / "session.json").write_text(json.dumps(session), encoding="utf-8")
    submit_args = ["gateway-submit"]
    for packet_name in session["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        submit_args.extend(["--uploaded-blob-sha", packet["expected_blob_git_oid"]])
    submitted = json.loads(run_request(repo, *submit_args))
    assert submitted["connector_action"]["action"] == "GitHub.create_file"
    assert (connector_dir / "submit-request.json").exists()
    updated_session = json.loads((active_dir / "session.json").read_text(encoding="utf-8"))
    assert updated_session["phase"] == "submit-request"


def test_gateway_begin_rejects_target_head_mismatch_before_transport(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "gateway-begin",
            "--target-ref",
            "HEAD",
            "--target-remote-head",
            "3" * 40,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "develop HEAD moved" in result.stderr
    assert not (repo / ".git" / "space-idle-publish-active").exists()


def test_gateway_begin_rejects_second_active_session(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    first = gateway_begin(repo, base_commit)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "gateway-begin",
            "--target-ref",
            "HEAD",
            "--target-remote-head",
            base_commit,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert first["request_id"] in result.stderr
    assert "active Gateway publish session" in result.stderr


def test_standard_cli_has_one_gateway_entry_and_no_low_level_connector_knobs() -> None:
    top_help = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert "gateway-begin" in top_help
    assert "gateway-submit" in top_help
    assert "gateway-record" in top_help
    assert "gateway-complete" in top_help
    assert "gateway-reconcile" in top_help
    command_set = top_help.split("{", 1)[1].split("}", 1)[0].split(",")
    assert "prepare" not in command_set
    assert "connector-plan" not in command_set
    assert "verify" not in command_set
    assert "record" not in command_set
    assert "connector-publish-step" not in top_help
    assert "patch" not in top_help.lower()

    begin_help = subprocess.run(
        [sys.executable, str(SCRIPT), "gateway-begin", "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert "--target-ref" in begin_help
    assert "--target-remote-head" in begin_help
    assert "--connector-call-budget-bytes" not in begin_help
    assert "--github-repository" not in begin_help
    assert "--publish-branch" not in begin_help
    assert "--output" not in begin_help


def test_gateway_begin_defaults_to_develop_and_temp_is_explicit_only(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    standard = gateway_begin(repo, base_commit)
    assert prepared(active_manifest(repo))["target_branch"] == "develop"
    request_id = standard["request_id"]
    run_request(repo, "gateway-abort", "--request-id", request_id)
    isolated = gateway_begin(repo, base_commit, target_branch="temp")
    assert prepared(active_manifest(repo))["target_branch"] == "temp"
    assert isolated["target_branch"] == "temp"


def test_gateway_begin_temp_uses_observed_temp_head_not_develop_publish_state(tmp_path: Path) -> None:
    repo, develop_base, develop_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("temp base\n", encoding="utf-8")
    commit_all(repo, "temp base")
    temp_base = git(repo, "rev-parse", "HEAD")
    (repo / "payload.txt").write_text("temp target\n", encoding="utf-8")
    commit_all(repo, "temp target")
    target = git(repo, "rev-parse", "HEAD")

    begun = gateway_begin(repo, temp_base, target_ref=target, target_branch="temp")
    request = prepared(active_manifest(repo))
    assert begun["target_remote_head"] == temp_base
    assert request["base_sha"] == temp_base
    assert git(repo, "rev-parse", f"{request['publish_commit']}^") == temp_base

    gateway_submit_expected(repo)
    completed = json.loads(
        run_request(
            repo,
            "gateway-complete",
            "--target-remote-head",
            str(request["publish_commit"]),
        )
    )
    assert completed["develop_publish_state_unchanged"] is True
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state == {
        "local_head": develop_base,
        "remote_commit": develop_base,
        "remote_tree": develop_tree,
    }


def test_gateway_record_temp_verifies_without_advancing_develop_state(tmp_path: Path) -> None:
    repo, base_commit, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("isolated temp validation\n", encoding="utf-8")
    commit_all(repo, "temp validation")
    gateway_begin(repo, base_commit, target_branch="temp")
    manifest = active_manifest(repo)
    gateway_submit_expected(repo)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(make_receipt(repo, manifest)), encoding="utf-8")

    recorded = json.loads(run_request(repo, "gateway-record", "--receipt", str(receipt_path)))
    assert recorded["verified"] is True
    assert recorded["publish_state_updated"] is False
    assert recorded["develop_publish_state_unchanged"] is True
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state == {
        "local_head": base_commit,
        "remote_commit": base_commit,
        "remote_tree": base_tree,
    }


def test_gateway_submit_refines_wrong_returned_blob_sha_without_request(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    gateway_begin(repo, base_commit)
    result = json.loads(
        run_request(
            repo,
            "gateway-submit",
            "--uploaded-blob-sha",
            "1" * 40,
        )
    )
    assert result["phase"] == "upload-payload-parts"
    assert result["request_action_generated"] is False
    assert result["resplit_mismatched_parts"] == 1
    assert len(result["connector_actions"]) == 2
    session = json.loads(
        (repo / ".git" / "space-idle-publish-active" / "session.json").read_text(encoding="utf-8")
    )
    assert session["phase"] == "upload-payload-parts"
    assert session["submit_request_packet"] is None


def test_gateway_complete_advances_develop_without_receipt_copy(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")
    gateway_begin(repo, base_commit)
    gateway_submit_expected(repo)
    manifest = prepared(active_manifest(repo))
    completed = json.loads(
        run_request(
            repo,
            "gateway-complete",
            "--target-remote-head",
            str(manifest["publish_commit"]),
        )
    )
    assert completed["verified"] is True
    assert completed["publish_state_updated"] is True
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["remote_commit"] == manifest["publish_commit"]
    assert state["remote_tree"] == target_tree
    assert state["local_head"] == target
    assert not (repo / ".git" / "space-idle-publish-active").exists()


def test_gateway_complete_temp_uses_observed_temp_base_without_mutating_develop_state(tmp_path: Path) -> None:
    repo, base_commit, base_tree = init_repo(tmp_path)
    (repo / "temp-base.txt").write_text("temp base\n", encoding="utf-8")
    commit_all(repo, "temp base")
    temp_base = git(repo, "rev-parse", "HEAD")
    (repo / "payload.txt").write_text("temp target\n", encoding="utf-8")
    commit_all(repo, "temp target")

    started = gateway_begin(repo, temp_base, target_branch="temp")
    manifest = prepared(active_manifest(repo))
    assert started["target_remote_head"] == temp_base
    assert manifest["base_sha"] == temp_base
    assert git(repo, "rev-parse", f"{manifest['publish_commit']}^") == temp_base

    gateway_submit_expected(repo)
    completed = json.loads(
        run_request(
            repo,
            "gateway-complete",
            "--target-remote-head",
            str(manifest["publish_commit"]),
        )
    )
    assert completed["develop_publish_state_unchanged"] is True
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state == {
        "local_head": base_commit,
        "remote_commit": base_commit,
        "remote_tree": base_tree,
    }


def test_gateway_record_temp_accepts_temp_base_distinct_from_develop_state(tmp_path: Path) -> None:
    repo, base_commit, base_tree = init_repo(tmp_path)
    (repo / "temp-base.txt").write_text("temp base\n", encoding="utf-8")
    commit_all(repo, "temp base")
    temp_base = git(repo, "rev-parse", "HEAD")
    (repo / "payload.txt").write_text("temp target\n", encoding="utf-8")
    commit_all(repo, "temp target")

    gateway_begin(repo, temp_base, target_branch="temp")
    manifest_path = active_manifest(repo)
    gateway_submit_expected(repo)
    receipt_path = tmp_path / "temp-receipt.json"
    receipt_path.write_text(json.dumps(make_receipt(repo, manifest_path)), encoding="utf-8")
    recorded = json.loads(run_request(repo, "gateway-record", "--receipt", str(receipt_path)))

    assert recorded["verified"] is True
    assert recorded["develop_publish_state_unchanged"] is True
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state == {
        "local_head": base_commit,
        "remote_commit": base_commit,
        "remote_tree": base_tree,
    }


def test_gateway_reconcile_repairs_missed_state_handoff_only_for_expected_commit(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("published already\n", encoding="utf-8")
    commit_all(repo, "published already")
    target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")
    module = load_module()
    state = module._read_state(repo)
    expected = module._create_publish_commit(
        repo,
        state["remote_commit"],
        target_tree,
        module._message_bytes(module._default_message(repo, state, target)),
    )
    reconciled = json.loads(
        run_request(
            repo,
            "gateway-reconcile",
            "--target-ref",
            target,
            "--target-remote-head",
            expected,
        )
    )
    assert reconciled["verified"] is True
    state_after = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state_after["remote_commit"] == expected
    assert state_after["remote_tree"] == target_tree
    assert state_after["local_head"] == target


def test_gateway_accepts_only_v5_request_files_and_completes_publish_after_verification() -> None:
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "'.publish/requests/*.json'" in workflow
    assert ".publish/request.patch" not in workflow
    assert "request['version'] != 5" in workflow
    assert "payload_source" in workflow
    assert "git-blobs" in workflow
    assert "git hash-object" not in workflow  # command is expressed as argv in Python, not shell text
    assert "['git', 'hash-object', '--stdin']" in workflow
    assert "GitHub blob Git OID mismatch" in workflow
    assert "bundle sha256 mismatch" in workflow
    assert "git bundle verify" in workflow
    assert 'actual_parent="$(git rev-parse "${PUBLISH_COMMIT}^")"' in workflow
    assert 'actual_tree="$(git rev-parse "${PUBLISH_COMMIT}^{tree}")"' in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "'version': 3" in workflow
    assert "'request_version': 5" in workflow
    assert "Dispatch Fast CI for published branch" in workflow


def make_commit_tree(repo: Path, tree: str, parent: str, message: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Gateway",
            "-c",
            "user.email=gateway@example.com",
            "commit-tree",
            tree,
            "-p",
            parent,
        ],
        cwd=repo,
        check=True,
        text=True,
        input=message.rstrip() + "\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def test_native_publish_uses_remote_head_as_parent_without_rewriting_local_history(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    git(repo, "init")
    git(tmp_path, "init", "--bare", str(remote))
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    git(repo, "push", str(remote), f"{base_commit}:refs/heads/develop")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    commit_all(repo, "local checkpoint")
    local_commit = git(repo, "rev-parse", "HEAD")
    local_tree = git(repo, "rev-parse", "HEAD^{tree}")
    result = json.loads(
        run_request(
            repo,
            "native-publish",
            "--remote",
            str(remote),
            "--target-branch",
            "develop",
        )
    )
    published = result["published_commit"]
    assert git(repo, "rev-parse", f"{published}^") == base_commit
    assert git(repo, "rev-parse", f"{published}^{{tree}}") == local_tree
    assert git(repo, "rev-parse", "HEAD") == local_commit
    assert git(repo, "ls-remote", "--heads", str(remote), "refs/heads/develop").split()[0] == published
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["remote_commit"] == published
    assert state["remote_tree"] == local_tree
    assert state["local_head"] == local_commit


def test_native_publish_rejects_remote_head_move_before_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    git(repo, "init")
    git(tmp_path, "init", "--bare", str(remote))
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    recorded_remote = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    git(repo, "push", str(remote), f"{recorded_remote}:refs/heads/develop")
    run_request(repo, "init", "--remote-commit", recorded_remote, "--remote-tree", base_tree)

    moved_remote = make_commit_tree(repo, base_tree, recorded_remote, "remote moved")
    git(repo, "push", str(remote), f"{moved_remote}:refs/heads/develop")
    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    commit_all(repo, "local checkpoint")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "native-publish",
            "--remote",
            str(remote),
            "--target-branch",
            "develop",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "remote target moved before native publish" in result.stderr
    assert git(repo, "ls-remote", "--heads", str(remote), "refs/heads/develop").split()[0] == moved_remote


def test_gateway_begin_excludes_newer_uncommitted_work(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "payload.txt").write_text("uncommitted follow-up\n", encoding="utf-8")
    (repo / "later.txt").write_text("not published yet\n", encoding="utf-8")

    result = gateway_begin(repo, base_commit, target_ref=checkpoint)
    assert result["target_tree"] == checkpoint_tree
    assert result["local_target_commit"] == checkpoint
    assert result["prepared"]["working_tree_clean"] is False
    assert result["prepared"]["uncommitted_changes_excluded"] is True
    assert (repo / "payload.txt").read_text(encoding="utf-8") == "uncommitted follow-up\n"
    assert (repo / "later.txt").read_text(encoding="utf-8") == "not published yet\n"


def test_plan_excludes_uncommitted_work(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "payload.txt").write_text("later\n", encoding="utf-8")
    result = json.loads(run_request(repo, "plan", "--target-ref", checkpoint))
    assert result["target_ref"] == checkpoint
    assert result["combined_request"]["target_tree"] == checkpoint_tree
    assert result["working_tree_clean"] is False
    assert result["uncommitted_changes_excluded"] is True
