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
    run_request(repo, "init", str(source_snapshot))
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

    (repo / "payload.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "later")

    result = run_request(repo, "init", str(source_snapshot), check=False)
    assert result.returncode != 0
    assert not (repo / ".git" / "space-idle-publish-state.json").exists()


def make_receipt(repo: Path) -> dict[str, object]:
    request = prepared(repo)
    raw_commit = subprocess.run(
        ["git", "cat-file", "commit", str(request["publish_commit"])],
        cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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


def test_connector_transport_is_one_way_and_root_gated(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("connector\n" * 400, encoding="utf-8")
    commit_all(repo, "connector transport")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, "connector-plan", "--target-remote-head", base).stdout)
    transaction_plan = plan_dir(repo)
    assert plan["stage"] == "uploads-planned"
    assert plan["upload_call_count"] == 1
    assert plan["payload_root_packet"] is None
    assert plan["submit_request_packet"] is None
    assert not (transaction_plan / "submit-request.json").exists()

    upload = json.loads(Path(plan["upload_packets"][0]).read_text(encoding="utf-8"))
    assert upload["action"] == "GitHub.create_blob"
    assert upload["action_args"]["repository_full_name"] == "naro0216n-collab/Space-Idle"

    replan = run_request(repo, "connector-plan", "--target-remote-head", base, check=False)
    assert replan.returncode != 0
    assert "already initialized" in replan.stderr

    root_meta = json.loads(run_request(repo, "connector-root").stdout)
    root = json.loads(Path(root_meta["payload_root_packet"]).read_text(encoding="utf-8"))
    assert root["action"] == "GitHub.create_tree"
    assert not (transaction_plan / "submit-request.json").exists()

    wrong = run_request(repo, "connector-submit", "--root-tree-sha", "3" * 40, check=False)
    assert wrong.returncode != 0
    assert "does not match the precomputed root" in wrong.stderr

    submit_meta = json.loads(
        run_request(repo, "connector-submit", "--root-tree-sha", root["expected_tree_git_oid"]).stdout
    )
    packet = json.loads(Path(submit_meta["submit_request_packet"]).read_text(encoding="utf-8"))
    transport = json.loads(packet["action_args"]["content"])
    assert transport["payload_source"] == {
        "kind": "git-tree", "oid": root["expected_tree_git_oid"], "part_count": 1
    }


def test_fixed_connector_profile_keeps_fleet_sized_payload_in_one_blob(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, _, _ = init_repo(tmp_path)
    parts = module._split_payload_for_blob_calls(
        repo, "naro0216n-collab/Space-Idle", "A" * 81_780, module.CONNECTOR_CALL_BUDGET_BYTES
    )
    assert len(parts) == 1
    assert module._connector_call_bytes(parts[0]["packet"]) < 96 * 1024


def test_fixed_connector_profile_splits_only_when_actual_call_exceeds_limit(tmp_path: Path) -> None:
    repo, base, _ = init_repo(tmp_path)
    content = "\n".join(
        f"{i:06d}:{hashlib.sha256(str(i).encode()).hexdigest()}" for i in range(7000)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large connector transport")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, "connector-plan", "--target-remote-head", base).stdout)
    assert plan["upload_call_count"] >= 2
    assert plan["connector_call_budget_bytes"] == 96 * 1024
    for packet_name in plan["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        size = len(json.dumps(packet["action_args"], separators=(",", ":")).encode("utf-8"))
        assert size <= 96 * 1024


def test_payload_root_oid_matches_git_tree_object_format(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    module = PUBLISH_REQUEST
    contents = [b"alpha", b"beta", b"gamma"]
    oids = [
        subprocess.run(["git", "hash-object", "--stdin"], cwd=repo, input=x, check=True,
                       stdout=subprocess.PIPE).stdout.decode().strip()
        for x in contents
    ]
    expected = subprocess.run(
        ["git", "mktree", "--missing"], cwd=repo,
        input="".join(f"100644 blob {oid}\t{i:04d}.b64\n" for i, oid in enumerate(oids)),
        text=True, check=True, stdout=subprocess.PIPE,
    ).stdout.strip()
    assert module._git_tree_oid(repo, oids) == expected


def test_standard_cli_has_no_alternative_repository_target_or_transaction_selectors() -> None:
    top = run_request(SCRIPT.parents[1], "--help").stdout
    assert "{init,prepare,connector-plan,connector-root,connector-submit,record}" in top
    for forbidden in ("native-publish", " plan ", "--repo"):
        assert forbidden not in f" {top.replace(chr(10), ' ')} "
    command_forbidden = {
        "init": ("--repo", "--local-ref", "--remote-commit", "--remote-tree"),
        "prepare": ("--repo", "--target-ref", "--output", "--target-branch", "--message"),
        "connector-plan": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                           "--publish-branch", "--output-dir", "--connector-call-budget-bytes"),
        "connector-root": ("--repo", "--manifest", "--plan-dir"),
        "connector-submit": ("--repo", "--manifest", "--plan-dir"),
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


def test_standard_prepare_rejects_workflow_changes_and_names_only_entrypoint(tmp_path: Path) -> None:
    repo, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    commit_all(repo, "change workflow")
    result = run_request(repo, "prepare", check=False)
    assert result.returncode != 0
    assert "standard Publish Gateway cannot publish .github/workflows changes" in result.stderr
    assert "python scripts/workflow_maintenance.py prepare" in result.stderr
    assert not manifest_path(repo).exists()


def test_gateway_contract_is_v6_git_tree_and_exact_commit_verification() -> None:
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "'.publish/requests/*.json'" in workflow
    assert ".publish/request.patch" not in workflow
    assert "request['version'] != 6" in workflow
    assert "git-tree" in workflow
    assert "git-blobs" not in workflow
    assert "['git', 'hash-object', '--stdin']" in workflow
    assert "GitHub payload blob Git OID mismatch" in workflow
    assert "GitHub payload tree Git OID mismatch" in workflow
    assert "bundle sha256 mismatch" in workflow
    assert "git bundle verify" in workflow
    assert 'actual_parent="$(git rev-parse "${PUBLISH_COMMIT}^")"' in workflow
    assert 'actual_tree="$(git rev-parse "${PUBLISH_COMMIT}^{tree}")"' in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "Dispatch Fast CI for published branch" in workflow
