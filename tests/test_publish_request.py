from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_request.py"

pytestmark = pytest.mark.development


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
        "request_version": 6,
        "target_branch": request["target_branch"],
        "base_commit": request["base_sha"],
        "target_tree": request["target_tree"],
        "published_commit": request["publish_commit"],
        "published_tree": request["target_tree"],
        "published_commit_object_b64": base64.b64encode(raw_commit).decode("ascii"),
    }


def test_prepare_bundle_recreates_exact_target_and_record_advances_baseline(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    commit_all(repo, "coherent change")
    local_target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    manifest = tmp_path / "request.json"
    meta = json.loads(run_request(repo, "prepare", "--output", str(manifest)))
    request = prepared(manifest)
    assert request["version"] == 6
    assert request["target_branch"] == "develop"
    assert request["base_sha"] == base_commit
    assert request["target_tree"] == target_tree
    assert request["local_target_commit"] == local_target
    assert request["payload_encoding"] == "git-bundle-base64"
    payload = base64.b64decode(str(request["payload_b64"]), validate=True)
    assert hashlib.sha256(payload).hexdigest() == request["payload_sha256"]
    assert meta["verified"] is True
    assert json.loads(run_request(repo, "verify", "--manifest", str(manifest)))["verified"] is True

    publish_commit = str(request["publish_commit"])
    assert git(repo, "rev-parse", f"{publish_commit}^") == base_commit
    assert git(repo, "rev-parse", f"{publish_commit}^{{tree}}") == target_tree

    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(make_receipt(repo, manifest)), encoding="utf-8")
    recorded = json.loads(
        run_request(
            repo,
            "record",
            "--manifest",
            str(manifest),
            "--receipt",
            str(receipt_path),
        )
    )
    assert recorded["verified"] is True
    assert recorded["remote_commit"] == publish_commit
    assert recorded["remote_tree"] == target_tree

    (repo / "new.txt").write_text("newer\n", encoding="utf-8")
    commit_all(repo, "next")
    next_manifest = tmp_path / "next.json"
    run_request(repo, "prepare", "--output", str(next_manifest))
    assert prepared(next_manifest)["base_sha"] == publish_commit


def test_record_uses_manifest_target_when_local_head_has_advanced(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    manifest = tmp_path / "request.json"
    run_request(repo, "prepare", "--output", str(manifest))
    request = prepared(manifest)

    (repo / "later.txt").write_text("next work\n", encoding="utf-8")
    commit_all(repo, "next local work")
    assert git(repo, "rev-parse", "HEAD") != checkpoint

    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(make_receipt(repo, manifest)), encoding="utf-8")
    recorded = json.loads(
        run_request(repo, "record", "--manifest", str(manifest), "--receipt", str(receipt_path))
    )
    assert recorded["verified"] is True
    assert recorded["local_head"] == checkpoint
    assert recorded["remote_tree"] == checkpoint_tree
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["local_head"] == checkpoint
    assert git(repo, "rev-parse", "HEAD") != checkpoint


def test_bundle_payload_is_deterministic_for_same_base_tree_and_message(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("target\n" * 200, encoding="utf-8")
    commit_all(repo, "same checkpoint")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    run_request(repo, "prepare", "--output", str(first))
    time.sleep(1.05)
    run_request(repo, "prepare", "--output", str(second))
    a = prepared(first)
    b = prepared(second)
    assert a["request_id"] != b["request_id"]
    assert a["publish_commit"] == b["publish_commit"]
    assert a["payload_sha256"] == b["payload_sha256"]
    assert a["payload_b64"] == b["payload_b64"]


def test_verify_rejects_corrupted_payload(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    manifest = tmp_path / "request.json"
    run_request(repo, "prepare", "--output", str(manifest))
    request = prepared(manifest)
    payload = str(request["payload_b64"])
    request["payload_b64"] = ("A" if payload[0] != "A" else "B") + payload[1:]
    manifest.write_text(json.dumps(request), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "verify", "--manifest", str(manifest)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr or "invalid publish bundle" in result.stderr


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


def test_connector_plan_keeps_materialization_separate_from_root_binding(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("connector transport\n" * 400, encoding="utf-8")
    commit_all(repo, "connector transport")
    manifest = tmp_path / "request.json"
    run_request(repo, "prepare", "--output", str(manifest))
    plan_dir = tmp_path / "connector"
    plan = json.loads(
        run_request(
            repo,
            "connector-plan",
            "--manifest",
            str(manifest),
            "--github-repository",
            "owner/repo",
            "--target-remote-head",
            base_commit,
            "--output-dir",
            str(plan_dir),
        )
    )
    assert plan["strategy"] == "blobs-root-tree-then-request-file"
    assert plan["upload_call_count"] == 1
    assert plan["normal_remote_target_probe_calls"] == 1
    assert plan["normal_publish_transport_probe_calls"] == 0
    assert plan["normal_github_mutation_calls"] == 3
    assert plan["normal_github_calls_before_gateway"] == 4
    assert plan["normal_sha_handoffs"] == 0
    assert plan["normal_per_upload_verification_calls"] == 0
    assert plan["returned_upload_blob_shas_are_not_required"] is True
    assert plan["returned_root_tree_sha_is_required"] is False
    assert plan["submit_deferred_until_root_verified"] is False
    assert plan["submit_request_packet"] is not None
    assert plan["gateway_completes_target_publish"] is True

    upload = json.loads(Path(plan["upload_packets"][0]).read_text(encoding="utf-8"))
    assert upload["action"] == "GitHub.create_blob"
    root = json.loads(Path(plan["payload_root_packet"]).read_text(encoding="utf-8"))
    assert root["action"] == "GitHub.create_tree"
    assert root["action_args"]["tree_elements"] == [
        {
            "mode": "100644",
            "path": "0000.b64",
            "sha": upload["expected_blob_git_oid"],
            "type": "blob",
        }
    ]

    packet = json.loads(Path(plan["submit_request_packet"]).read_text(encoding="utf-8"))
    transport_request = json.loads(packet["action_args"]["content"])
    assert transport_request["version"] == 6
    assert transport_request["payload_source"] == {
        "kind": "git-tree",
        "oid": root["expected_tree_git_oid"],
        "part_count": 1,
    }
    assert transport_request["base_sha"] == base_commit


def test_fleet_sized_payload_uses_one_blob_plus_root_not_inline_request(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("publish_request", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    repo, _, _ = init_repo(tmp_path)
    payload = "A" * 81_780
    parts = module._split_payload_for_blob_calls(
        repo, "naro0216n-collab/Space-Idle", payload, 96 * 1024
    )
    assert len(parts) == 1
    assert module._connector_call_bytes(parts[0]["packet"]) < 96 * 1024
    root = module._connector_payload_root_packet(
        repo, "naro0216n-collab/Space-Idle", [parts[0]["oid"]]
    )
    assert module._connector_call_bytes(root) < 96 * 1024


def test_connector_plan_splits_overflow_into_blobs_then_precomputed_root_tree(tmp_path: Path) -> None:
    repo, base_commit, _ = init_repo(tmp_path)
    content = "\n".join(
        f"{index:06d}:{hashlib.sha256(str(index).encode()).hexdigest()}" for index in range(3000)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large connector transport")
    manifest = tmp_path / "request.json"
    run_request(
        repo,
        "prepare",
        "--output",
        str(manifest),
        "--connector-call-budget-bytes",
        "20000",
    )
    plan_dir = tmp_path / "connector"
    plan = json.loads(
        run_request(
            repo,
            "connector-plan",
            "--manifest",
            str(manifest),
            "--github-repository",
            "owner/repo",
            "--target-remote-head",
            base_commit,
            "--output-dir",
            str(plan_dir),
        )
    )
    assert plan["strategy"] == "blobs-root-tree-then-request-file"
    assert plan["upload_call_count"] >= 2
    assert plan["connector_uploads_may_run_in_parallel"] is True
    assert plan["returned_upload_blob_shas_are_not_required"] is True
    assert plan["returned_root_tree_sha_is_required"] is False
    assert plan["submit_deferred_until_root_verified"] is False
    assert plan["submit_request_packet"] is not None
    assert plan["normal_github_mutation_calls"] == plan["upload_call_count"] + 2
    assert plan["normal_github_calls_before_gateway"] == plan["upload_call_count"] + 3
    assert plan["normal_sha_handoffs"] == 0

    oids = []
    for packet_name in plan["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        assert packet["action"] == "GitHub.create_blob"
        compact_size = len(json.dumps(packet["action_args"], separators=(",", ":")).encode("utf-8"))
        assert compact_size <= 20_000
        raw = packet["action_args"]["content"].encode("ascii")
        actual = subprocess.run(
            ["git", "hash-object", "--stdin"],
            cwd=repo,
            input=raw,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode().strip()
        assert actual == packet["expected_blob_git_oid"]
        oids.append(actual)

    root = json.loads(Path(plan["payload_root_packet"]).read_text(encoding="utf-8"))
    assert root["action"] == "GitHub.create_tree"
    assert len(json.dumps(root["action_args"], separators=(",", ":")).encode("utf-8")) <= 20_000
    assert [entry["sha"] for entry in root["action_args"]["tree_elements"]] == oids
    assert [entry["path"] for entry in root["action_args"]["tree_elements"]] == [
        f"{index:04d}.b64" for index in range(len(oids))
    ]
    assert root["expected_tree_git_oid"] == plan["expected_payload_tree_git_oid"]

    spec = importlib.util.spec_from_file_location("publish_request", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert root["expected_tree_git_oid"] == module._git_tree_oid(repo, oids)

    submit = json.loads(Path(plan["submit_request_packet"]).read_text(encoding="utf-8"))
    assert submit["action"] == "GitHub.create_file"
    assert len(json.dumps(submit["action_args"], separators=(",", ":")).encode("utf-8")) <= 20_000
    transport = json.loads(submit["action_args"]["content"])
    assert transport["payload_source"] == {
        "kind": "git-tree",
        "oid": root["expected_tree_git_oid"],
        "part_count": len(oids),
    }


def test_payload_tree_oid_matches_git_tree_object_format(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    spec = importlib.util.spec_from_file_location("publish_request", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    contents = [b"alpha", b"beta", b"gamma"]
    oids = [
        subprocess.run(
            ["git", "hash-object", "--stdin"],
            cwd=repo,
            input=content,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode().strip()
        for content in contents
    ]
    expected = subprocess.run(
        ["git", "mktree", "--missing"],
        cwd=repo,
        input="".join(
            f"100644 blob {oid}\t{index:04d}.b64\n" for index, oid in enumerate(oids)
        ),
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    assert module._git_tree_oid(repo, oids) == expected


def test_connector_plan_rejects_target_head_mismatch_before_transport(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    manifest = tmp_path / "request.json"
    run_request(repo, "prepare", "--output", str(manifest))
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "connector-plan",
            "--manifest",
            str(manifest),
            "--github-repository",
            "owner/repo",
            "--target-remote-head",
            "3" * 40,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "target branch HEAD moved since prepare" in result.stderr


def test_standard_cli_has_no_patch_or_manual_connector_fallbacks() -> None:
    top_help = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert "connector-publish-step" not in top_help
    assert "connector-finalize" not in top_help
    assert "verify-transport" not in top_help
    assert "patch" not in top_help.lower()

    plan_help = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert "--transport" not in plan_help
    record_help = subprocess.run(
        [sys.executable, str(SCRIPT), "record", "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    assert "--remote-commit" not in record_help
    assert "--remote-tree" not in record_help
    assert "--local-ref" not in record_help


def test_prepare_defaults_to_develop_and_temp_is_explicit_only(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    standard = tmp_path / "develop.json"
    isolated = tmp_path / "temp.json"
    run_request(repo, "prepare", "--output", str(standard))
    run_request(repo, "prepare", "--target-branch", "temp", "--output", str(isolated))
    assert prepared(standard)["target_branch"] == "develop"
    assert prepared(isolated)["target_branch"] == "temp"


def test_gateway_accepts_only_v6_request_files_and_completes_publish_after_verification() -> None:
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "'.publish/requests/*.json'" in workflow
    assert ".publish/request.patch" not in workflow
    assert "request['version'] != 6" in workflow
    assert "payload_source" in workflow
    assert "git-tree" in workflow
    assert "git-blobs" not in workflow
    assert "git hash-object" not in workflow  # command is expressed as argv in Python, not shell text
    assert "['git', 'hash-object', '--stdin']" in workflow
    assert "GitHub payload blob Git OID mismatch" in workflow
    assert "GitHub payload tree Git OID mismatch" in workflow
    assert "bundle sha256 mismatch" in workflow
    assert "git bundle verify" in workflow
    assert 'actual_parent="$(git rev-parse "${PUBLISH_COMMIT}^")"' in workflow
    assert 'actual_tree="$(git rev-parse "${PUBLISH_COMMIT}^{tree}")"' in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "'version': 3" in workflow
    assert "'request_version': 6" in workflow
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


def test_prepare_excludes_newer_uncommitted_work(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "payload.txt").write_text("uncommitted follow-up\n", encoding="utf-8")
    (repo / "later.txt").write_text("not published yet\n", encoding="utf-8")

    manifest = tmp_path / "request.json"
    result = json.loads(
        run_request(
            repo,
            "prepare",
            "--target-ref",
            checkpoint,
            "--output",
            str(manifest),
        )
    )
    assert result["target_tree"] == checkpoint_tree
    assert result["local_target_commit"] == checkpoint
    assert result["working_tree_clean"] is False
    assert result["uncommitted_changes_excluded"] is True
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
