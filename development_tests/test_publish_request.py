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


def expected_remote_part_args(repo: Path, *, sha_override: str | None = None, size_delta: int = 0) -> list[str]:
    state = json.loads((plan_dir(repo) / "connector-state.json").read_text(encoding="utf-8"))
    generation = state["generations"][-1]
    args: list[str] = []
    for path, oid, size in zip(
        generation["remote_payload_paths"],
        generation["expected_payload_blob_git_oids"],
        generation["expected_payload_chars"],
        strict=True,
    ):
        sha = sha_override or oid
        args.extend(["--remote-part", f"{Path(path).name}={sha}:{int(size) + size_delta}"])
    return args


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


def _plan_args(base: str, tree: str) -> tuple[str, ...]:
    return (
        "connector-plan",
        "--target-remote-head", base,
        "--publish-remote-head", base,
        "--publish-remote-tree", tree,
    )


def test_connector_plan_revalidates_manifest_and_remote_base(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    run_request(repo, "prepare")

    wrong_head = run_request(
        repo,
        "connector-plan",
        "--target-remote-head", "3" * 40,
        "--publish-remote-head", base,
        "--publish-remote-tree", base_tree,
        check=False,
    )
    assert wrong_head.returncode != 0
    assert "target branch HEAD moved since prepare" in wrong_head.stderr

    request = prepared(repo)
    payload = str(request["payload_b64"])
    request["payload_b64"] = ("A" if payload[0] != "A" else "B") + payload[1:]
    manifest_path(repo).write_text(json.dumps(request), encoding="utf-8")
    corrupt = run_request(repo, *_plan_args(base, base_tree), check=False)
    assert corrupt.returncode != 0
    assert "sha256 mismatch" in corrupt.stderr or "invalid publish bundle" in corrupt.stderr


def test_connector_plan_builds_one_atomic_publish_generation(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("connector\n" * 400, encoding="utf-8")
    commit_all(repo, "connector transport")
    run_request(repo, "prepare")
    request = prepared(repo)
    request_id = str(request["request_id"])
    plan = json.loads(run_request(repo, *_plan_args(base, base_tree)).stdout)

    assert plan["stage"] == "tree-ready"
    assert plan["strategy"] == "atomic-inline-tree-generation"
    assert plan["current_generation"] == 0
    assert plan["tree_call_count"] == 1
    assert plan["payload_handoff_field_count"] >= 1
    assert plan["blob_response_sha_handoff_required"] is False
    assert plan["branch_updates_per_generation"] == 1
    assert "GitHub.create_tree" in plan["next"]

    tree_packet = json.loads(Path(plan["tree_packet"]).read_text(encoding="utf-8"))
    assert tree_packet["action"] == "GitHub.create_tree"
    assert tree_packet["action_args"]["base_tree_sha"] == base_tree
    elements = tree_packet["action_args"]["tree_elements"]
    assert all("content" in element and "sha" not in element for element in elements)
    payload_elements = [
        element for element in elements
        if f".publish/payloads/{request_id}/g0000/" in element["path"]
    ]
    assert len(payload_elements) == plan["payload_handoff_field_count"]
    index_element = next(
        element for element in elements
        if element["path"] == f".publish/payloads/{request_id}/index-0000.json"
    )
    trigger_element = next(
        element for element in elements
        if element["path"] == f".publish/requests/{request_id}.json"
    )
    index = json.loads(index_element["content"])
    assert index["generation"] == 0
    assert index["payload_chars"] == len(str(request["payload_b64"]))
    assert index["part_count"] == len(payload_elements)
    assert [part["chars"] for part in index["parts"]] == [len(e["content"]) for e in payload_elements]
    assert [part["blob_git_oid"] for part in index["parts"]] == [
        PUBLISH_REQUEST._git_object_oid(repo, "blob", e["content"].encode("utf-8"))
        for e in payload_elements
    ]

    transport = json.loads(trigger_element["content"])
    assert transport["version"] == 7
    assert transport["payload_source"] == {
        "kind": "indexed-files",
        "directory": f".publish/payloads/{request_id}",
        "minimum_generation": 0,
    }

    handoff_elements = [json.loads(Path(name).read_text(encoding="utf-8")) for name in plan["tree_element_files"]]
    assert handoff_elements == elements

    commit = json.loads(run_request(repo, "connector-tree", "--tree-sha", "4" * 40).stdout)
    assert commit["stage"] == "commit-packet-ready"
    commit_packet = json.loads(Path(commit["commit_packet"]).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["tree_sha"] == "4" * 40
    assert commit_packet["action_args"]["parent_sha"] == base

    verify = json.loads(run_request(repo, "connector-commit", "--commit-sha", "5" * 40).stdout)
    assert verify["stage"] == "verification-packet-ready"
    verification_packet = json.loads(Path(verify["verification_packet"]).read_text(encoding="utf-8"))
    assert verification_packet["action"] == "GitHub.fetch"
    assert f"/.publish/payloads/{request_id}/g0000?ref={'5' * 40}" in verification_packet["action_args"]["url"]

    update = json.loads(run_request(repo, "connector-verify", *expected_remote_part_args(repo)).stdout)
    update_packet = json.loads(Path(update["update_packet"]).read_text(encoding="utf-8"))
    assert update["payload_transport_verified"] is True
    assert update_packet["action"] == "GitHub.update_ref"
    assert update_packet["action_args"] == {
        "repository_full_name": "naro0216n-collab/Space-Idle",
        "branch_name": "publish",
        "sha": "5" * 40,
        "force": False,
    }

    replan = run_request(repo, *_plan_args(base, base_tree), check=False)
    assert replan.returncode != 0
    assert "already initialized" in replan.stderr

def test_handoff_fields_fit_in_one_tree_call_when_total_capacity_allows(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, base, base_tree = init_repo(tmp_path)
    prepared_request = {
        "request_id": "a" * 32,
        "target_branch": "develop",
        "base_sha": base,
        "target_tree": base_tree,
        "publish_commit": base,
        "payload_b64": "A" * 81_780,
        "payload_sha256": "b" * 64,
    }
    generation = module._generation_plan(
        repo,
        prepared_request,
        0,
        base_publish_head=base,
        base_publish_tree=base_tree,
        retry=False,
    )
    assert generation["payload_part_count"] > 1
    assert generation["tree_batch_call_count"] == 1
    assert all(
        len(element["content"]) <= module.CONNECTOR_HANDOFF_ELEMENT_CHARS
        for element in generation["tree_batches"][0]
        if "/g0000/" in element["path"]
    )

def test_connector_profile_uses_144_kib_as_tree_call_ceiling(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, base, base_tree = init_repo(tmp_path)
    prepared_request = {
        "request_id": "a" * 32,
        "target_branch": "develop",
        "base_sha": base,
        "target_tree": base_tree,
        "publish_commit": base,
        "payload_b64": "A" * 220_000,
        "payload_sha256": "b" * 64,
    }
    generation = module._generation_plan(
        repo,
        prepared_request,
        0,
        base_publish_head=base,
        base_publish_tree=base_tree,
        retry=False,
    )
    batches = generation["tree_batches"]
    assert len(batches) >= 2
    for index, batch in enumerate(batches):
        packet = module._generation_tree_packet(
            base_tree="0" * 40,
            elements=batch,
            generation=0,
            batch_index=index,
        )
        assert module._connector_call_bytes(packet) <= 144 * 1024
    for left, right in zip(batches, batches[1:]):
        combined = module._generation_tree_packet(
            base_tree="0" * 40,
            elements=[*left, *right],
            generation=0,
            batch_index=0,
        )
        assert module._connector_call_bytes(combined) > 144 * 1024

def test_large_handoff_uses_minimum_tree_calls_and_one_branch_update(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    content = "\n".join(
        f"{i:06d}:{hashlib.sha256(str(i).encode()).hexdigest()}" for i in range(7000)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large connector transport")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, *_plan_args(base, base_tree)).stdout)
    assert plan["payload_handoff_field_count"] >= 2
    assert plan["connector_call_budget_bytes"] == 144 * 1024
    assert plan["branch_updates_per_generation"] == 1
    assert plan["tree_call_count"] >= 1
    assert plan["tree_call_bytes"] <= 144 * 1024
    tree_packet = json.loads(Path(plan["tree_packet"]).read_text(encoding="utf-8"))
    assert tree_packet["action"] == "GitHub.create_tree"
    assert all("content" in element for element in tree_packet["action_args"]["tree_elements"])
    assert "GitHub.create_blob" not in Path(plan["tree_packet"]).read_text(encoding="utf-8")

def _advance_to_verification(repo: Path, *, tree_sha: str, commit_sha: str) -> dict[str, object]:
    result = json.loads(run_request(repo, "connector-tree", "--tree-sha", tree_sha).stdout)
    while result["stage"] == "tree-ready":
        result = json.loads(run_request(repo, "connector-tree", "--tree-sha", tree_sha).stdout)
    assert result["stage"] == "commit-packet-ready"
    return json.loads(run_request(repo, "connector-commit", "--commit-sha", commit_sha).stdout)


def test_payload_mismatch_retries_same_generation_before_ref_update(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("transport retry\n" * 500, encoding="utf-8")
    commit_all(repo, "transport retry")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, *_plan_args(base, base_tree)).stdout)
    initial_chars = plan["payload_handoff_field_chars"]

    _advance_to_verification(repo, tree_sha="4" * 40, commit_sha="5" * 40)
    retry1 = json.loads(run_request(
        repo,
        "connector-verify",
        *expected_remote_part_args(repo, sha_override="a" * 40),
    ).stdout)
    assert retry1["stage"] == "transport-retry-tree-ready"
    assert retry1["generation"] == 0
    assert retry1["transport_attempt"] == 1
    assert retry1["attempt_number"] == 2
    assert retry1["payload_handoff_element_chars"] == initial_chars
    assert retry1["adaptive_handoff"] is False
    state1 = json.loads((plan_dir(repo) / "connector-state.json").read_text(encoding="utf-8"))
    assert state1["current_generation"] == 0
    assert state1["transport_attempt"] == 1
    assert "update_packet" not in state1

    _advance_to_verification(repo, tree_sha="6" * 40, commit_sha="7" * 40)
    retry2 = json.loads(run_request(
        repo,
        "connector-verify",
        *expected_remote_part_args(repo, sha_override="b" * 40),
    ).stdout)
    assert retry2["generation"] == 0
    assert retry2["transport_attempt"] == 2
    assert retry2["attempt_number"] == 3
    assert retry2["payload_handoff_element_chars"] == initial_chars // 2
    assert retry2["adaptive_handoff"] is True
    state2 = json.loads((plan_dir(repo) / "connector-state.json").read_text(encoding="utf-8"))
    assert state2["current_generation"] == 0
    assert state2["generations"][-1]["payload_handoff_element_chars"] == initial_chars // 2


def test_payload_transport_retry_exhaustion_never_generates_ref_update(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("retry exhaustion\n" * 450, encoding="utf-8")
    commit_all(repo, "retry exhaustion")
    run_request(repo, "prepare")
    run_request(repo, *_plan_args(base, base_tree))

    for tree_sha, commit_sha, bad_sha in (
        ("4" * 40, "5" * 40, "a" * 40),
        ("6" * 40, "7" * 40, "b" * 40),
    ):
        _advance_to_verification(repo, tree_sha=tree_sha, commit_sha=commit_sha)
        result = run_request(
            repo,
            "connector-verify",
            *expected_remote_part_args(repo, sha_override=bad_sha),
        )
        parsed = json.loads(result.stdout)
        assert parsed["stage"] == "transport-retry-tree-ready"

    _advance_to_verification(repo, tree_sha="8" * 40, commit_sha="9" * 40)
    exhausted = run_request(
        repo,
        "connector-verify",
        *expected_remote_part_args(repo, sha_override="c" * 40),
        check=False,
    )
    assert exhausted.returncode != 0
    assert "failed after 3 attempts" in exhausted.stderr
    state = json.loads((plan_dir(repo) / "connector-state.json").read_text(encoding="utf-8"))
    assert state["stage"] == "transport-failed"
    assert state["current_generation"] == 0
    assert state["transport_attempt"] == 2
    assert "update_packet" not in state


def test_payload_transport_retry_can_succeed_without_generation_change(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("retry success\n" * 350, encoding="utf-8")
    commit_all(repo, "retry success")
    run_request(repo, "prepare")
    run_request(repo, *_plan_args(base, base_tree))

    _advance_to_verification(repo, tree_sha="4" * 40, commit_sha="5" * 40)
    run_request(repo, "connector-verify", *expected_remote_part_args(repo, sha_override="a" * 40))
    _advance_to_verification(repo, tree_sha="6" * 40, commit_sha="7" * 40)
    success = json.loads(run_request(repo, "connector-verify", *expected_remote_part_args(repo)).stdout)
    assert success["stage"] == "update-packet-ready"
    assert success["generation"] == 0
    assert success["transport_attempt"] == 1
    packet = json.loads(Path(success["update_packet"]).read_text(encoding="utf-8"))
    assert packet["action_args"]["sha"] == "7" * 40


def test_connector_repair_rebuilds_one_atomic_tree_generation(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    content = "\n".join(
        f"{i:05d}:{hashlib.sha256(str(i).encode()).hexdigest()}" for i in range(900)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "repair target")
    run_request(repo, "prepare")
    plan = json.loads(run_request(repo, *_plan_args(base, base_tree)).stdout)
    initial_count = plan["payload_handoff_field_count"]

    repair = json.loads(run_request(
        repo,
        "connector-repair",
        "--publish-remote-head", base,
        "--publish-remote-tree", base_tree,
    ).stdout)
    assert repair["stage"] == "tree-ready"
    assert repair["previous_generation"] == 0
    assert repair["generation"] == 1
    assert repair["previous_payload_handoff_field_count"] == initial_count
    assert repair["payload_handoff_field_count"] == initial_count
    assert repair["connector_call_budget_bytes"] == 144 * 1024
    assert repair["branch_updates_per_generation"] == 1

    tree_packet = json.loads(Path(repair["tree_packet"]).read_text())
    assert tree_packet["action"] == "GitHub.create_tree"
    assert tree_packet["action_args"]["base_tree_sha"] == base_tree
    assert all("content" in element and "sha" not in element for element in tree_packet["action_args"]["tree_elements"])
    retry_element = next(
        element for element in tree_packet["action_args"]["tree_elements"]
        if element["path"].endswith("/g0001.json")
    )
    retry_request = json.loads(retry_element["content"])
    assert retry_request["version"] == 7
    assert retry_request["request_id"] == prepared(repo)["request_id"]
    assert retry_request["payload_source"]["minimum_generation"] == 1

    repair2 = json.loads(run_request(
        repo,
        "connector-repair",
        "--publish-remote-head", base,
        "--publish-remote-tree", base_tree,
    ).stdout)
    assert repair2["generation"] == 2
    assert repair2["payload_handoff_field_count"] == initial_count

def test_repair_accepts_previous_atomic_generation_as_new_base(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("repair after ref update\n" * 300, encoding="utf-8")
    commit_all(repo, "repair after atomic update")
    run_request(repo, "prepare")
    run_request(repo, *_plan_args(base, base_tree))
    created_tree = "6" * 40
    created_commit = "7" * 40
    result = json.loads(run_request(repo, "connector-tree", "--tree-sha", created_tree).stdout)
    while result["stage"] == "tree-ready":
        result = json.loads(run_request(repo, "connector-tree", "--tree-sha", created_tree).stdout)
    assert result["stage"] == "commit-packet-ready"
    run_request(repo, "connector-commit", "--commit-sha", created_commit)
    run_request(repo, "connector-verify", *expected_remote_part_args(repo))

    repair = json.loads(run_request(
        repo,
        "connector-repair",
        "--publish-remote-head", created_commit,
        "--publish-remote-tree", created_tree,
    ).stdout)
    assert repair["generation"] == 1
    assert repair["base_publish_head"] == created_commit
    assert repair["base_publish_tree"] == created_tree

    unrelated = run_request(
        repo,
        "connector-repair",
        "--publish-remote-head", "8" * 40,
        "--publish-remote-tree", "9" * 40,
        check=False,
    )
    assert unrelated.returncode != 0
    assert "not the active generation base" in unrelated.stderr

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
    parts = module._payload_parts_for_tree(repo, request_id, 3, payload)
    index = module._payload_index_document(prepared_request, request_id, 3, parts)
    assert index["generation"] == 3
    assert index["part_count"] == len(parts)
    assert [part["index"] for part in index["parts"]] == list(range(len(parts)))
    assert [part["blob_git_oid"] for part in index["parts"]] == [part["oid"] for part in parts]
    assert [part["path"] for part in index["parts"]] == [
        f"g0003/{i:04d}.b64" for i in range(len(parts))
    ]

def test_display_handoff_fields_do_not_multiply_tree_sends_within_capacity(tmp_path: Path) -> None:
    module = PUBLISH_REQUEST
    repo, base, base_tree = init_repo(tmp_path)
    request_id = "e" * 32
    prepared_request = {
        "request_id": request_id,
        "target_branch": "develop",
        "base_sha": base,
        "target_tree": base_tree,
        "publish_commit": base,
        "payload_b64": "A" * 33_752,
        "payload_sha256": "b" * 64,
    }
    generation = module._generation_plan(
        repo,
        prepared_request,
        0,
        base_publish_head=base,
        base_publish_tree=base_tree,
        retry=False,
    )
    assert generation["payload_part_count"] > 1
    assert generation["tree_batch_call_count"] == 1

def test_cancel_requires_unchanged_remote_target_and_publish_tree(tmp_path: Path) -> None:
    repo, base, base_tree = init_repo(tmp_path)
    (repo / "payload.txt").write_text("cancel me\n", encoding="utf-8")
    commit_all(repo, "obsolete checkpoint")
    run_request(repo, "prepare")
    run_request(repo, *_plan_args(base, base_tree))

    moved = run_request(
        repo, "cancel",
        "--target-remote-head", "8" * 40,
        "--publish-remote-tree", base_tree,
        check=False,
    )
    assert moved.returncode != 0
    assert manifest_path(repo).exists()

    changed_transport = run_request(
        repo, "cancel",
        "--target-remote-head", base,
        "--publish-remote-tree", "9" * 40,
        check=False,
    )
    assert changed_transport.returncode != 0
    assert manifest_path(repo).exists()

    cancelled = json.loads(run_request(
        repo, "cancel",
        "--target-remote-head", base,
        "--publish-remote-tree", base_tree,
    ).stdout)
    assert cancelled["cancelled"] is True
    assert cancelled["verified"] is True
    assert not manifest_path(repo).exists()


def test_standard_cli_has_no_alternative_repository_target_or_transaction_selectors() -> None:
    top = run_request(SCRIPT.parents[1], "--help").stdout
    assert "{init,prepare,connector-plan,connector-tree,connector-commit,connector-verify,connector-repair,cancel,record}" in top
    for forbidden in ("native-publish", "--repo"):
        assert forbidden not in f" {top.replace(chr(10), ' ')} "
    command_forbidden = {
        "init": ("--repo", "--local-ref", "--remote-commit", "--remote-tree", "source_snapshot"),
        "prepare": ("--repo", "--target-ref", "--output", "--target-branch", "--message"),
        "connector-plan": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                           "--publish-branch", "--output-dir", "--connector-call-budget-bytes"),
        "connector-tree": ("--repo", "--manifest", "--base-tree", "--content", "--path"),
        "connector-commit": ("--repo", "--manifest", "--branch", "--force"),
        "connector-verify": ("--repo", "--manifest", "--branch", "--force", "--commit-sha"),
        "connector-repair": ("--repo", "--manifest", "--plan-dir", "--github-repository",
                             "--publish-branch", "--path", "--content", "--request-id",
                             "--part-index", "--remote-blob-sha"),
        "cancel": ("--repo", "--manifest", "--request-id", "--force"),
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
