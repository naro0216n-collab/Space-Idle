from __future__ import annotations

import base64
import gzip
import hashlib
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
    # Existing contract tests exercise the v3 patch fallback explicitly.
    # Bundle v4, the standard transport, has dedicated tests below.
    adjusted = list(args)
    if adjusted and adjusted[0] in {"prepare", "plan"} and "--transport" not in adjusted:
        adjusted[1:1] = ["--transport", "patch"]
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *adjusted],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def run_standard_request(repo: Path, *args: str) -> str:
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


def parse_request(manifest: str, chunk_dir: Path) -> tuple[dict[str, str], str]:
    headers: dict[str, str] = {}
    for line in manifest.splitlines():
        if line.startswith("# "):
            key, sep, value = line[2:].partition(": ")
            if sep:
                headers[key] = value
    chunk_count = int(headers["chunk-count"])
    payload_parts = []
    for index in range(chunk_count):
        chunk = (chunk_dir / f"{index:04d}.txt").read_text(encoding="ascii")
        assert hashlib.sha256(chunk.encode("ascii")).hexdigest() == headers[f"chunk-{index:04d}-sha256"]
        payload_parts.append(chunk)
    patch = gzip.decompress(base64.b64decode("".join(payload_parts), validate=True)).decode("utf-8")
    return headers, patch


def test_publish_request_recreates_exact_target_tree_and_tracks_next_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    (repo / "b.txt").write_text("keep\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "c.txt").write_text("new\n", encoding="utf-8")
    (repo / "b.txt").unlink()
    commit_all(repo, "coherent change")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    published_local_ref = git(repo, "rev-parse", "HEAD")
    request_path = tmp_path / "publish-request.patch"
    run_request(
        repo, "prepare", "--target-branch", "temp", "--target-ref", published_local_ref,
        "--output", str(request_path),
    )
    headers, patch = parse_request(request_path.read_text(encoding="utf-8"), Path(f"{request_path}.chunks"))
    assert headers["version"] == "3"
    assert headers["patch-encoding"] == "gzip-base64-chunks"
    assert headers["target-branch"] == "temp"
    assert headers["base-sha"] == base_commit
    assert headers["target-tree"] == target_tree
    assert headers["patch-sha256"] == hashlib.sha256(patch.encode("utf-8")).hexdigest()
    assert base64.b64decode(headers["message-b64"]).decode("utf-8") == "coherent change\n"
    verify_meta = run_request(repo, "verify", "--manifest", str(request_path))
    assert '"verified": true' in verify_meta

    apply_repo = tmp_path / "apply"
    git(tmp_path, "clone", str(repo), str(apply_repo))
    git(apply_repo, "checkout", "--detach", base_commit)
    patch_path = tmp_path / "request.patch"
    patch_path.write_text(patch, encoding="utf-8", newline="")
    git(apply_repo, "apply", "--index", "--binary", str(patch_path))
    assert git(apply_repo, "write-tree") == target_tree

    published_commit = "1" * 40
    run_request(
        repo,
        "record",
        "--remote-commit",
        published_commit,
        "--remote-tree",
        target_tree,
        "--local-ref",
        published_local_ref,
    )

    (repo / "c.txt").write_text("newer\n", encoding="utf-8")
    commit_all(repo, "next")
    next_path = tmp_path / "next-request.patch"
    run_request(repo, "prepare", "--output", str(next_path))
    next_headers, next_patch = parse_request(next_path.read_text(encoding="utf-8"), Path(f"{next_path}.chunks"))
    assert next_headers["base-sha"] == published_commit
    assert "a/a.txt" not in next_patch
    assert "b/b.txt" not in next_patch
    assert "a/c.txt" in next_patch


def test_publish_request_uses_large_bounded_deterministic_chunks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    # Use incompressible-enough deterministic text so the transport spans several chunks.
    content = "\n".join(f"{index:06d}:{hashlib.sha256(str(index).encode()).hexdigest()}" for index in range(1000))
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large change")

    first = tmp_path / "first.patch"
    second = tmp_path / "second.patch"
    first_meta = run_request(repo, "prepare", "--output", str(first))
    time.sleep(1.1)
    second_meta = run_request(repo, "prepare", "--output", str(second))

    first_headers, first_patch = parse_request(first.read_text(encoding="utf-8"), Path(f"{first}.chunks"))
    second_headers, second_patch = parse_request(second.read_text(encoding="utf-8"), Path(f"{second}.chunks"))
    assert first_patch == second_patch
    assert first_headers["patch-sha256"] == second_headers["patch-sha256"]
    assert first_headers["chunks-tree-git-oid"] == second_headers["chunks-tree-git-oid"]
    assert first_headers["chunk-size"] == str(8 * 1024)
    assert int(first_headers["chunk-count"]) < 20

    first_chunks = sorted(Path(f"{first}.chunks").glob("*.txt"))
    second_chunks = sorted(Path(f"{second}.chunks").glob("*.txt"))
    assert len(first_chunks) == len(second_chunks)
    assert [p.read_bytes() for p in first_chunks] == [p.read_bytes() for p in second_chunks]
    assert all(not p.read_bytes().endswith(b"\n") for p in first_chunks)
    assert all(p.read_text(encoding="ascii") == p.read_text(encoding="ascii").strip() for p in first_chunks)

    # The machine-readable prepare result exposes transport sizing for Connector planning.
    assert '"chunk_size": 8192' in first_meta
    assert '"compressed_bytes":' in first_meta
    assert '"payload_chars":' in first_meta
    assert '"connector_call_budget_bytes": 98304' in first_meta
    assert '"transport_batches"' not in first_meta
    assert '"remote_receipt_path": ".publish/receipts/' in first_meta


def test_publish_request_verify_rejects_corrupted_chunk(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    request = tmp_path / "request.patch"
    prepare_meta = run_request(repo, "prepare", "--output", str(request))
    assert '"verified": true' in prepare_meta

    first_chunk = Path(f"{request}.chunks") / "0000.txt"
    chunk = first_chunk.read_text(encoding="ascii")
    first_chunk.write_text(("A" if chunk[0] != "A" else "B") + chunk[1:], encoding="ascii")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "verify", "--manifest", str(request)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr


def test_publish_request_rejects_transport_above_gateway_chunk_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    (repo / "payload.txt").write_text("changed enough to span chunks\n" * 100, encoding="utf-8")
    commit_all(repo, "change")

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--repo", str(repo), "prepare",
            "--chunk-size", "1", "--output", str(tmp_path / "too-many.patch"),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "exceeding gateway limit 256" in result.stderr


def test_publish_plan_reports_combined_and_sequential_transport(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "payload.txt").write_text("first\n" * 500, encoding="utf-8")
    commit_all(repo, "first checkpoint")
    first_commit = git(repo, "rev-parse", "HEAD")
    (repo / "second.txt").write_text("second\n" * 500, encoding="utf-8")
    commit_all(repo, "second checkpoint")
    second_commit = git(repo, "rev-parse", "HEAD")

    import json
    plan = json.loads(run_request(repo, "plan"))
    assert plan["chunk_size"] == 8 * 1024
    assert plan["target_ref"] == second_commit
    assert plan["sequential_local_commits_available"] is True
    assert [item["local_commit"] for item in plan["sequential_requests"]] == [first_commit, second_commit]
    assert [item["subject"] for item in plan["sequential_requests"]] == [
        "first checkpoint",
        "second checkpoint",
    ]
    assert plan["combined_request"]["target_tree"] == git(repo, "rev-parse", "HEAD^{tree}")
    assert all(item["chunk_count"] >= 1 for item in plan["sequential_requests"])


def test_publish_request_chunks_tree_oid_matches_git_tree_object(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")

    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    content = "\n".join(f"{index:06d}:{hashlib.sha256(str(index).encode()).hexdigest()}" for index in range(400))
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "change")

    request = tmp_path / "request.patch"
    run_request(repo, "prepare", "--output", str(request), "--chunk-size", "4096")
    headers, _ = parse_request(request.read_text(encoding="utf-8"), Path(f"{request}.chunks"))

    lines = []
    for chunk_path in sorted(Path(f"{request}.chunks").glob("*.txt")):
        blob_oid = subprocess.run(
            ["git", "hash-object", "--stdin"],
            cwd=repo,
            input=chunk_path.read_bytes(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.decode().strip()
        lines.append(f"100644 blob {blob_oid}\t{chunk_path.name}\n")
    actual_tree_oid = subprocess.run(
        ["git", "mktree", "--missing"],
        cwd=repo,
        input="".join(lines),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    assert headers["chunks-tree-git-oid"] == actual_tree_oid



def test_connector_upload_groups_pack_by_serialized_call_budget(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("publish_request", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    chunks = ["A" * 8192 for _ in range(10)]
    groups = module._connector_upload_groups(repo, chunks, 20_000, "owner/repo")
    assert len(groups) == 5
    assert all(group["chunk_count"] == 2 for group in groups)
    assert all(group["packet_bytes"] <= 20_000 for group in groups)
    covered = []
    for group in groups:
        covered.extend(range(group["start_chunk"], group["end_chunk"] + 1))
    assert covered == list(range(10))

def test_fleet_sized_payload_fits_one_normal_publish_tree_call(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("publish_request_fleet_size", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")

    # Fleet redesign publish used 81,780 Base64 characters: 9 x 8192 + 8052.
    chunks = ["A" * 8192 for _ in range(9)] + ["B" * 8052]
    assert sum(map(len, chunks)) == 81_780
    blob_oids = module._chunk_blob_oids(repo, chunks)
    manifest = "# request metadata\n" + ("m" * 1560)
    packet = module._connector_publish_root_packet(
        "naro0216n-collab/Space-Idle",
        chunks,
        blob_oids,
        manifest,
        "1" * 40,
        include_chunk_content=True,
        expected_chunks_tree_git_oid="2" * 40,
    )
    call_bytes = module._connector_call_bytes(packet)

    assert call_bytes == len(
        __import__("json").dumps(
            packet["action_args"], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    )
    assert call_bytes < 96 * 1024


def test_publish_gateway_emits_request_scoped_receipt() -> None:
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "Record verified publish receipt" in workflow
    assert ".publish/receipts/${REQUEST_ID}.json" in workflow
    assert '"request_id": os.environ["REQUEST_ID"]' in workflow
    assert '"published_commit": os.environ["PUBLISHED_SHA"]' in workflow
    assert '"published_tree": os.environ["PUBLISHED_TREE"]' in workflow
    assert "paths:\n      - '.publish/request.patch'" in workflow



def test_connector_plan_uses_single_create_tree_when_complete_packet_fits(tmp_path: Path) -> None:
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    content = "\n".join(
        f"{index:06d}:{hashlib.sha256(str(index).encode()).hexdigest()}"
        for index in range(1000)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "connector transport")

    manifest = tmp_path / "request.patch"
    run_request(repo, "prepare", "--output", str(manifest), "--chunk-size", "8192")
    headers, _ = parse_request(manifest.read_text(encoding="utf-8"), Path(f"{manifest}.chunks"))
    plan_dir = tmp_path / "connector"
    plan = json.loads(run_request(
        repo, "connector-plan", "--manifest", str(manifest),
        "--github-repository", "owner/repo", "--output-dir", str(plan_dir),
        "--publish-base-commit", "1" * 40, "--publish-base-tree", "2" * 40,
        "--target-remote-head", base_commit,
    ))

    assert plan["strategy"] == "single-create-tree-publish"
    assert plan["connector_call_budget_bytes"] == 96 * 1024
    assert plan["call_size_basis"] == "compact-json-action-args"
    assert plan["upload_call_count"] == 0
    assert plan["assembly_required"] is False
    assert plan["upload_packets"] == []
    assert plan["chunks_tree_packet"] is None
    assert plan["normal_github_mutation_calls"] == 3
    assert plan["normal_remote_target_probe_calls"] == 1
    assert plan["normal_publish_transport_probe_calls"] == 1
    assert plan["normal_remote_probe_calls"] == 2
    assert plan["normal_total_github_calls"] == 5
    assert plan["normal_per_upload_verification_calls"] == 0
    assert plan["normal_sha_handoffs"] == 2
    root_packet = json.loads(Path(plan["transport_root_tree_packet"]).read_text(encoding="utf-8"))
    assert root_packet["stage"] == "create-transport-root-tree"
    assert root_packet["expected_chunks_tree_git_oid"] == headers["chunks-tree-git-oid"]
    assert root_packet["action_args"]["base_tree_sha"] == "2" * 40
    chunk_entries = [
        entry for entry in root_packet["action_args"]["tree_elements"]
        if entry["path"].startswith(".publish/chunks/")
    ]
    assert chunk_entries
    assert all("content" in entry and "sha" not in entry for entry in chunk_entries)
    assert root_packet["action_args"]["tree_elements"][-1]["path"] == ".publish/request.patch"


def test_connector_plan_splits_only_when_serialized_packet_exceeds_budget(tmp_path: Path) -> None:
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    content = "\n".join(
        f"{index:06d}:{hashlib.sha256(str(index).encode()).hexdigest()}"
        for index in range(1600)
    )
    (repo / "payload.txt").write_text(content + "\n", encoding="utf-8")
    commit_all(repo, "large connector transport")

    manifest = tmp_path / "request.patch"
    run_request(
        repo, "prepare", "--output", str(manifest), "--chunk-size", "8192",
        "--connector-call-budget-bytes", "20000",
    )
    plan_dir = tmp_path / "connector"
    plan = json.loads(run_request(
        repo, "connector-plan", "--manifest", str(manifest),
        "--github-repository", "owner/repo", "--output-dir", str(plan_dir),
        "--publish-base-commit", "1" * 40, "--publish-base-tree", "2" * 40,
        "--target-remote-head", base_commit,
    ))
    assert plan["strategy"] == "parallel-upload-then-create-tree-publish"
    assert plan["assembly_required"] is False
    assert plan["upload_call_count"] >= 2
    assert plan["chunks_tree_packet"] is None
    assert plan["normal_github_mutation_calls"] == plan["upload_call_count"] + 3
    assert plan["normal_total_github_calls"] == plan["upload_call_count"] + 5
    for packet_name in plan["upload_packets"]:
        packet = json.loads(Path(packet_name).read_text(encoding="utf-8"))
        compact_size = len(json.dumps(packet["action_args"], separators=(",", ":")).encode("utf-8"))
        assert compact_size <= 20_000
    root_packet = json.loads(Path(plan["transport_root_tree_packet"]).read_text(encoding="utf-8"))
    assert root_packet["stage"] == "create-transport-root-tree"
    chunk_entries = [
        entry for entry in root_packet["action_args"]["tree_elements"]
        if entry["path"].startswith(".publish/chunks/")
    ]
    assert chunk_entries
    assert all("content" not in entry and "sha" in entry for entry in chunk_entries)

def test_connector_plan_rejects_target_head_mismatch_before_transport(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    manifest = tmp_path / "request.patch"
    run_request(repo, "prepare", "--output", str(manifest))

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--repo", str(repo), "connector-plan",
            "--manifest", str(manifest), "--github-repository", "owner/repo",
            "--publish-base-commit", "1" * 40, "--publish-base-tree", "2" * 40,
            "--target-remote-head", "3" * 40,
        ],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert result.returncode != 0
    assert "target branch HEAD moved since prepare" in result.stderr


def test_connector_publish_step_emits_atomic_transport_mutations(tmp_path: Path) -> None:
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    (repo / "payload.txt").write_text("changed\n", encoding="utf-8")
    commit_all(repo, "change")
    manifest = tmp_path / "request.patch"
    run_request(repo, "prepare", "--output", str(manifest))
    headers, _ = parse_request(manifest.read_text(encoding="utf-8"), Path(f"{manifest}.chunks"))

    root = json.loads(run_request(
        repo, "connector-publish-step", "--manifest", str(manifest),
        "--github-repository", "owner/repo", "--publish-base-commit", "1" * 40,
        "--publish-base-tree", "2" * 40,
    ))
    assert root["stage"] == "create-transport-root-tree"
    assert root["action"] == "GitHub.create_tree"
    assert root["action_args"]["base_tree_sha"] == "2" * 40

    commit = json.loads(run_request(
        repo, "connector-publish-step", "--manifest", str(manifest),
        "--github-repository", "owner/repo", "--publish-base-commit", "1" * 40,
        "--publish-base-tree", "2" * 40,
        "--transport-root-tree", "3" * 40,
    ))
    assert commit["stage"] == "create-transport-commit"
    assert commit["action_args"]["parent_sha"] == "1" * 40

    update = json.loads(run_request(
        repo, "connector-publish-step", "--manifest", str(manifest),
        "--github-repository", "owner/repo", "--publish-base-commit", "1" * 40,
        "--publish-base-tree", "2" * 40,
        "--transport-root-tree", "3" * 40, "--transport-commit", "4" * 40,
    ))
    assert update["stage"] == "update-publish-ref"
    assert update["action_args"]["force"] is False


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
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    local_base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "push", str(remote), f"{local_base}:refs/heads/develop")
    remote_base = make_commit_tree(repo, base_tree, local_base, "remote synthetic baseline")
    git(repo, "push", str(remote), f"{remote_base}:refs/heads/develop")

    run_request(repo, "init", "--remote-commit", remote_base, "--remote-tree", base_tree)
    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    commit_all(repo, "local checkpoint")
    local_target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    output = json.loads(
        run_request(
            repo,
            "native-publish",
            "--remote",
            str(remote),
            "--target-branch",
            "develop",
        )
    )
    published = output["published_commit"]
    assert output["transport"] == "native-git"
    assert output["base_commit"] == remote_base
    assert output["published_tree"] == target_tree
    assert output["local_head"] == local_target
    assert output["verified"] is True
    assert git(repo, "rev-parse", f"{published}^") == remote_base
    assert git(repo, "rev-parse", f"{published}^{{tree}}") == target_tree
    assert git(repo, "ls-remote", "--heads", str(remote), "refs/heads/develop").split()[0] == published

    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state == {
        "local_head": local_target,
        "remote_commit": published,
        "remote_tree": target_tree,
    }


def test_native_publish_rejects_remote_head_move_before_mutation(tmp_path: Path) -> None:
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    local_base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "push", str(remote), f"{local_base}:refs/heads/develop")
    recorded_remote = make_commit_tree(repo, base_tree, local_base, "recorded remote")
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
    state = json.loads((repo / ".git" / "space-idle-publish-state.json").read_text(encoding="utf-8"))
    assert state["remote_commit"] == recorded_remote
    assert state["remote_tree"] == base_tree


def parse_manifest_headers(manifest: Path) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            key, sep, value = line[2:].partition(": ")
            if sep:
                headers[key] = value
    return headers


def bundle_payload(manifest: Path) -> bytes:
    headers = parse_manifest_headers(manifest)
    chunk_dir = Path(f"{manifest}.chunks")
    return base64.b64decode(
        "".join(
            (chunk_dir / f"{index:04d}.txt").read_text(encoding="ascii")
            for index in range(int(headers["chunk-count"]))
        ),
        validate=True,
    )


def test_git_bundle_is_the_default_publish_transport_and_encodes_exact_target_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "payload.txt").write_text("target\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    commit_all(repo, "bundle checkpoint")
    local_target = git(repo, "rev-parse", "HEAD")
    target_tree = git(repo, "rev-parse", "HEAD^{tree}")

    manifest = tmp_path / "request.patch"
    meta = __import__("json").loads(
        run_standard_request(repo, "prepare", "--target-branch", "temp", "--output", str(manifest))
    )
    headers = parse_manifest_headers(manifest)
    assert headers["version"] == "4"
    assert headers["payload-encoding"] == "git-bundle-base64-chunks"
    assert headers["base-sha"] == base_commit
    assert headers["target-tree"] == target_tree
    assert headers["local-target-commit"] == local_target
    assert meta["transport"] == "git-bundle"
    assert meta["publish_commit"] == headers["publish-commit"]
    assert meta["payload_bytes"] == len(bundle_payload(manifest))
    assert hashlib.sha256(bundle_payload(manifest)).hexdigest() == headers["payload-sha256"]

    publish_commit = headers["publish-commit"]
    assert git(repo, "rev-parse", f"{publish_commit}^") == base_commit
    assert git(repo, "rev-parse", f"{publish_commit}^{{tree}}") == target_tree
    assert git(repo, "show", "-s", "--format=%B", publish_commit) == "bundle checkpoint"

    bundle = tmp_path / "request.bundle"
    bundle.write_bytes(bundle_payload(manifest))
    git(repo, "bundle", "verify", str(bundle))
    heads = git(repo, "bundle", "list-heads", str(bundle)).splitlines()
    assert len(heads) == 1
    assert heads[0].split()[0] == publish_commit
    assert run_standard_request(repo, "verify", "--manifest", str(manifest)).find('"verified": true') >= 0


def test_git_bundle_publish_payload_is_deterministic_for_same_base_tree_and_message(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    (repo / "payload.txt").write_text("target\n" * 200, encoding="utf-8")
    commit_all(repo, "same checkpoint")

    first = tmp_path / "first.patch"
    second = tmp_path / "second.patch"
    run_standard_request(repo, "prepare", "--output", str(first))
    time.sleep(1.1)
    run_standard_request(repo, "prepare", "--output", str(second))
    first_headers = parse_manifest_headers(first)
    second_headers = parse_manifest_headers(second)
    assert first_headers["request-id"] != second_headers["request-id"]
    assert first_headers["publish-commit"] == second_headers["publish-commit"]
    assert first_headers["payload-sha256"] == second_headers["payload-sha256"]
    assert first_headers["chunks-tree-git-oid"] == second_headers["chunks-tree-git-oid"]
    assert bundle_payload(first) == bundle_payload(second)


def test_bundle_plan_chains_deterministic_remote_publish_commits(tmp_path: Path) -> None:
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)
    (repo / "payload.txt").write_text("first\n", encoding="utf-8")
    commit_all(repo, "first")
    (repo / "second.txt").write_text("second\n", encoding="utf-8")
    commit_all(repo, "second")

    plan = json.loads(run_standard_request(repo, "plan"))
    assert plan["transport"] == "bundle"
    assert plan["combined_request"]["transport"] == "git-bundle"
    assert len(plan["sequential_requests"]) == 2
    first_publish = plan["sequential_requests"][0]["publish_commit"]
    second_publish = plan["sequential_requests"][1]["publish_commit"]
    assert git(repo, "rev-parse", f"{first_publish}^") == base_commit
    assert git(repo, "rev-parse", f"{second_publish}^") == first_publish
    assert plan["combined_request"]["payload_bytes"] > 0


def test_publish_gateway_supports_bundle_v4_and_emits_commit_object_receipt() -> None:
    workflow = (SCRIPT.parents[1] / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "version == '4'" in workflow
    assert "git-bundle-base64-chunks" in workflow
    assert "git bundle verify" in workflow
    assert "refs/space-idle/publish-request:${incoming_ref}" in workflow
    assert 'actual_parent="$(git rev-parse "${PUBLISH_COMMIT}^")"' in workflow
    assert 'actual_tree="$(git rev-parse "${PUBLISH_COMMIT}^{tree}")"' in workflow
    assert '"version": 2' in workflow
    assert '"published_commit_object_b64"' in workflow


def test_prepare_uses_committed_target_while_worktree_has_newer_uncommitted_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "tracked.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")

    # Ongoing work after the checkpoint must neither block publish nor leak into it.
    (repo / "tracked.txt").write_text("uncommitted follow-up\n", encoding="utf-8")
    (repo / "later.txt").write_text("not published yet\n", encoding="utf-8")

    manifest = tmp_path / "request"
    meta = run_standard_request(
        repo,
        "prepare",
        "--transport",
        "bundle",
        "--target-ref",
        checkpoint,
        "--output",
        str(manifest),
    )
    result = __import__("json").loads(meta)
    assert result["target_tree"] == checkpoint_tree
    assert result["local_target_commit"] == checkpoint
    assert result["working_tree_clean"] is False
    assert result["uncommitted_changes_excluded"] is True
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "uncommitted follow-up\n"
    assert (repo / "later.txt").read_text(encoding="utf-8") == "not published yet\n"

    verify = __import__("json").loads(
        run_standard_request(repo, "verify", "--manifest", str(manifest))
    )
    assert verify["target_tree"] == checkpoint_tree
    assert verify["verified"] is True


def test_plan_allows_ongoing_uncommitted_work_without_including_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    base_commit = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    run_request(repo, "init", "--remote-commit", base_commit, "--remote-tree", base_tree)

    (repo / "tracked.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "tracked.txt").write_text("later\n", encoding="utf-8")

    result = __import__("json").loads(
        run_standard_request(repo, "plan", "--target-ref", checkpoint)
    )
    assert result["target_ref"] == checkpoint
    assert result["combined_request"]["target_tree"] == checkpoint_tree
    assert result["working_tree_clean"] is False
    assert result["uncommitted_changes_excluded"] is True
