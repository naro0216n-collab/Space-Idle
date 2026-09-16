from __future__ import annotations

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
        "--develop-head", develop_head,
        "--publish-head", publish_head,
    ).stdout)


def verify_all_chunks(repo: Path, summary: dict[str, object]) -> dict[str, object]:
    current = summary
    while current["stage"] in {"blob-ready", "blob-retry-ready"}:
        state = connector_state(repo)
        plan_data = state["plan"]
        assert isinstance(plan_data, dict)
        chunks = plan_data["chunks"]
        assert isinstance(chunks, list)
        chunk = chunks[int(state["blob_chunk_index"])]
        assert isinstance(chunk, dict)
        current = json.loads(run_request(
            repo, "connector-blob", "--blob-sha", str(chunk["expected_blob"])
        ).stdout)
    return current


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


def test_publish_commit_inherits_target_commit_time(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    result = prepare_change(repo)
    target_commit = str(result["local_target_commit"])
    publish_commit = str(result["publish_commit"])

    assert git(repo, "show", "-s", "--format=%cI", publish_commit) == git(
        repo, "show", "-s", "--format=%cI", target_commit
    )
    assert git(repo, "show", "-s", "--format=%ct", publish_commit) != "946684800"

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


def test_connector_transport_uses_fixed_verified_chunks_and_retries_only_current_chunk(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    (repo / "large.bin").write_bytes(os.urandom(40_000))
    commit_all(repo, "large checkpoint")
    run_request(repo, "prepare")
    first = plan(repo, base, publish_head)

    assert first["strategy"] == "fixed-slot-16kib-blob-verified"
    assert first["transport_chunk_bytes"] == 16 * 1024
    assert first["payload_part_count"] > 1
    state = connector_state(repo)
    plan_data = state["plan"]
    assert isinstance(plan_data, dict)
    chunks = plan_data["chunks"]
    assert isinstance(chunks, list) and len(chunks) == first["payload_part_count"]
    assert all(len(str(chunk["content"]).encode("utf-8")) <= 16 * 1024 for chunk in chunks)

    first_packet = json.loads(Path(str(first["blob_packet"])).read_text(encoding="utf-8"))
    assert first_packet["action"] == "GitHub.create_blob"
    assert first_packet["action_args"]["encoding"] == "utf-8"
    assert first_packet["action_args"]["content"] == chunks[0]["content"]

    expected_first_blob = str(chunks[0]["expected_blob"])
    next_chunk = json.loads(run_request(
        repo, "connector-blob", "--blob-sha", expected_first_blob
    ).stdout)
    assert next_chunk["chunk_index"] == 1
    second_packet_text = Path(str(next_chunk["blob_packet"])).read_text(encoding="utf-8")

    previous_segment_bytes = 16 * 1024
    for attempt in range(1, 6):
        failed = json.loads(run_request(
            repo, "connector-blob", "--blob-sha", "a" * 40
        ).stdout)
        assert failed["stage"] == "blob-retry-ready"
        assert failed["chunk_index"] == 1
        assert failed["retry_count"] == attempt
        assert failed["retry_failed_chunk_only"] is True
        assert failed["transcription_segment_bytes"] <= max(1, previous_segment_bytes // 2)
        segment_files = [Path(path) for path in failed["transcription_segment_files"]]
        state_now = connector_state(repo)
        chunk_now = state_now["plan"]["chunks"][1]
        assert "".join(path.read_text(encoding="utf-8") for path in segment_files) == chunk_now["content"]
        assert Path(str(failed["blob_packet"])).read_text(encoding="utf-8") == second_packet_text
        assert state_now["blob_chunk_index"] == 1
        assert state_now["verified_blob_shas"][".publish/transport/develop/0000.b64"] == expected_first_blob
        assert not (transaction(repo) / "connector" / "create-transport-commit.json").exists()
        assert not (transaction(repo) / "connector" / "advance-publish-ref.json").exists()
        previous_segment_bytes = int(failed["transcription_segment_bytes"])

    current = json.loads(run_request(
        repo, "connector-blob", "--blob-sha", str(chunks[1]["expected_blob"])
    ).stdout)
    tree = verify_all_chunks(repo, current)
    assert tree["stage"] == "tree-ready"

    tree_packet = json.loads(Path(str(tree["tree_packet"])).read_text(encoding="utf-8"))
    assert tree_packet["action"] == "GitHub.create_tree"
    elements = tree_packet["action_args"]["tree_elements"]
    payload_entries = {
        entry["path"]: entry
        for entry in elements
        if entry["path"].endswith(".b64")
    }
    assert set(payload_entries) == {str(chunk["path"]) for chunk in chunks}
    for chunk in chunks:
        entry = payload_entries[str(chunk["path"])]
        assert entry == {
            "mode": "100644",
            "path": str(chunk["path"]),
            "sha": str(chunk["expected_blob"]),
            "type": "blob",
        }
    encoded_args = json.dumps(
        tree_packet["action_args"], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded_args) <= 144 * 1024

    tree_state = connector_state(repo)
    expected_tree = str(tree_state["plan"]["batches"][0]["expected_tree"])
    succeeded = json.loads(run_request(
        repo, "connector-tree", "--tree-sha", expected_tree
    ).stdout)
    assert succeeded["stage"] == "commit-packet-ready"
    commit_packet = json.loads(Path(str(succeeded["commit_packet"])).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["tree_sha"] == expected_tree

def test_tree_mismatch_is_machine_retried_without_commit_or_ref_packet(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    tree = verify_all_chunks(repo, plan(repo, base, publish_head))
    original_packet = Path(str(tree["tree_packet"])).read_text(encoding="utf-8")

    for attempt in range(1, 6):
        retry = json.loads(run_request(repo, "connector-tree", "--tree-sha", "e" * 40).stdout)
        assert retry["stage"] == "tree-retry-ready"
        assert retry["tree_retry_count"] == attempt
        assert Path(str(retry["tree_packet"])).read_text(encoding="utf-8") == original_packet
        assert not (transaction(repo) / "connector" / "create-transport-commit.json").exists()
        assert not (transaction(repo) / "connector" / "advance-publish-ref.json").exists()


def test_commit_then_ref_is_only_remaining_normal_write_sequence_and_record_uses_gateway_run(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    result = prepare_change(repo)
    first = plan(repo, base, publish_head)
    tree = verify_all_chunks(repo, first)
    state = connector_state(repo)
    expected_tree = str(state["plan"]["batches"][0]["expected_tree"])
    commit = json.loads(run_request(repo, "connector-tree", "--tree-sha", expected_tree).stdout)
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
    tree = verify_all_chunks(repo, plan(repo, base, publish_head))
    state = connector_state(repo)
    expected_tree = str(state["plan"]["batches"][0]["expected_tree"])
    run_request(repo, "connector-tree", "--tree-sha", expected_tree)
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
        repo, "connector-plan", "--develop-head", "c" * 40,
        "--publish-head", publish_head, check=False,
    )
    assert moved_target.returncode != 0
    moved_publish = run_request(
        repo, "connector-plan", "--develop-head", base,
        "--publish-head", "d" * 40, check=False,
    )
    assert moved_publish.returncode != 0


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


def test_gateway_contract_validates_fixed_slot_then_publishes_exact_commit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "publish_gateway_validate.py").read_text(encoding="utf-8")
    assert "'.publish/transport/**'" in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "Dispatch Fast CI for published branch" in workflow
    assert "_transport_parts" in validator
