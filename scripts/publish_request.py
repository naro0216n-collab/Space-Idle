#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

STATE_NAME = "space-idle-publish-state.json"
ACTIVE_SESSION_DIR_NAME = "space-idle-publish-active"
REQUEST_VERSION = 5
RECEIPT_VERSION = 3
DEFAULT_CONNECTOR_CALL_BUDGET_BYTES = 96 * 1024
DEFAULT_PAYLOAD_CHUNK_CHARS = 8 * 1024
MAX_PAYLOAD_CHUNKS = 256
PUBLISH_BUNDLE_REF = "refs/space-idle/publish-request"
GITHUB_REPOSITORY = "naro0216n-collab/Space-Idle"
PUBLISH_BRANCH = "publish"
PUBLISH_IDENTITY_NAME = "space-idle-publish-gateway"
PUBLISH_IDENTITY_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
PUBLISH_COMMIT_DATE = "946684800 +0000"


class PublishStateError(RuntimeError):
    pass


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _git_bytes(*args: str, cwd: Path) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _git_dir(repo: Path) -> Path:
    raw = _git("rev-parse", "--git-dir", cwd=repo)
    path = Path(raw)
    return path if path.is_absolute() else repo / path


def _state_path(repo: Path) -> Path:
    return _git_dir(repo) / STATE_NAME


def _active_session_dir(repo: Path) -> Path:
    return _git_dir(repo) / ACTIVE_SESSION_DIR_NAME


def _active_session_path(repo: Path) -> Path:
    return _active_session_dir(repo) / "session.json"


def _read_state(repo: Path) -> dict[str, str]:
    path = _state_path(repo)
    if not path.exists():
        raise PublishStateError(
            "publish state is not initialized; initialize it from the verified source artifact"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("remote_commit", "remote_tree", "local_head"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise PublishStateError(f"invalid publish state: missing {key}")
    return data


def _write_state(repo: Path, remote_commit: str, remote_tree: str, local_head: str) -> None:
    _state_path(repo).write_text(
        json.dumps(
            {
                "remote_commit": remote_commit,
                "remote_tree": remote_tree,
                "local_head": local_head,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _working_tree_clean(repo: Path) -> bool:
    return not bool(_git("status", "--porcelain", cwd=repo))


def _message_bytes(message: str) -> bytes:
    if not message.strip():
        raise PublishStateError("commit message must not be empty")
    if not message.endswith("\n"):
        message += "\n"
    return message.encode("utf-8")


def _default_message(repo: Path, state: dict[str, str], target_ref: str) -> str:
    local_head = state["local_head"]
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", local_head, target_ref],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if is_ancestor:
        commits = _git("rev-list", "--reverse", f"{local_head}..{target_ref}", cwd=repo).splitlines()
        if len(commits) == 1:
            return _git("show", "-s", "--format=%B", commits[0], cwd=repo).rstrip() + "\n"
    return _git("show", "-s", "--format=%B", target_ref, cwd=repo).rstrip() + "\n"


def _require_hex_sha(value: str, *, name: str) -> None:
    if len(value) not in {40, 64}:
        raise PublishStateError(f"invalid {name}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PublishStateError(f"invalid {name}") from exc


def _require_commit_object(repo: Path, commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PublishStateError(
            "recorded remote commit object is not available locally; restore from the latest "
            "source-snapshot or import a verified publish receipt"
        )


def _create_publish_commit(repo: Path, base_commit: str, target_tree: str, message: bytes) -> str:
    _require_commit_object(repo, base_commit)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": PUBLISH_IDENTITY_NAME,
            "GIT_AUTHOR_EMAIL": PUBLISH_IDENTITY_EMAIL,
            "GIT_AUTHOR_DATE": PUBLISH_COMMIT_DATE,
            "GIT_COMMITTER_NAME": PUBLISH_IDENTITY_NAME,
            "GIT_COMMITTER_EMAIL": PUBLISH_IDENTITY_EMAIL,
            "GIT_COMMITTER_DATE": PUBLISH_COMMIT_DATE,
        }
    )
    result = subprocess.run(
        ["git", "commit-tree", target_tree, "-p", base_commit],
        cwd=repo,
        env=env,
        input=message,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    publish_commit = result.stdout.decode("ascii").strip()
    _require_hex_sha(publish_commit, name="publish commit")
    return publish_commit


def _bundle_bytes(repo: Path, base_commit: str, publish_commit: str) -> bytes:
    ref = PUBLISH_BUNDLE_REF
    old_ref = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="space-idle-publish-bundle-") as tmp:
        bundle_path = Path(tmp) / "request.bundle"
        try:
            subprocess.run(
                ["git", "update-ref", ref, publish_commit],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "bundle", "create", str(bundle_path), ref, f"^{base_commit}"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return bundle_path.read_bytes()
        finally:
            if old_ref:
                subprocess.run(
                    ["git", "update-ref", ref, old_ref],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                subprocess.run(
                    ["git", "update-ref", "-d", ref],
                    cwd=repo,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )


def _parse_commit_object(repo: Path, commit: str) -> tuple[dict[str, list[str]], bytes]:
    raw = _git_bytes("cat-file", "commit", commit, cwd=repo)
    header, sep, body = raw.partition(b"\n\n")
    if not sep:
        raise PublishStateError(f"invalid commit object: {commit}")
    fields: dict[str, list[str]] = {}
    for line in header.decode("utf-8").splitlines():
        key, _, value = line.partition(" ")
        fields.setdefault(key, []).append(value)
    return fields, body


def _git_object_oid(repo: Path, object_type: str, content: bytes) -> str:
    object_format = _git("rev-parse", "--show-object-format", cwd=repo)
    if object_format not in {"sha1", "sha256"}:
        raise PublishStateError(f"unsupported Git object format: {object_format}")
    header = f"{object_type} {len(content)}\0".encode("ascii")
    return hashlib.new(object_format, header + content).hexdigest()


def _bundle_payload_metrics(
    repo: Path,
    base_commit: str,
    target_tree: str,
    message: bytes,
) -> dict[str, object]:
    publish_commit = _create_publish_commit(repo, base_commit, target_tree, message)
    bundle = _bundle_bytes(repo, base_commit, publish_commit)
    payload = base64.b64encode(bundle).decode("ascii")
    return {
        "transport": "git-bundle",
        "payload_bytes": len(bundle),
        "payload_chars": len(payload),
        "payload_sha256": hashlib.sha256(bundle).hexdigest(),
        "publish_commit": publish_commit,
    }


def _read_prepared_request(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishStateError(f"invalid prepared publish request: {exc}") from exc
    required = {
        "version",
        "request_id",
        "target_branch",
        "base_sha",
        "target_tree",
        "publish_commit",
        "payload_sha256",
        "payload_encoding",
        "payload_b64",
        "connector_call_budget_bytes",
        "local_target_commit",
    }
    missing = required - data.keys()
    if missing:
        raise PublishStateError(f"invalid prepared publish request: missing fields {sorted(missing)}")
    if data["version"] != REQUEST_VERSION:
        raise PublishStateError(f"unsupported prepared request version: {data['version']}")
    request_id = data["request_id"]
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise PublishStateError("invalid prepared request id")
    try:
        int(request_id, 16)
    except ValueError as exc:
        raise PublishStateError("invalid prepared request id") from exc
    if data["target_branch"] not in {"develop", "temp"}:
        raise PublishStateError("invalid prepared target branch")
    for key in ("base_sha", "target_tree", "publish_commit", "local_target_commit"):
        value = data[key]
        if not isinstance(value, str):
            raise PublishStateError(f"invalid prepared {key}")
        _require_hex_sha(value, name=f"prepared {key}")
    digest = data["payload_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise PublishStateError("invalid prepared payload sha256")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise PublishStateError("invalid prepared payload sha256") from exc
    if data["payload_encoding"] != "git-bundle-base64":
        raise PublishStateError("unsupported prepared payload encoding")
    if not isinstance(data["payload_b64"], str) or not data["payload_b64"]:
        raise PublishStateError("prepared request has no payload")
    budget = data["connector_call_budget_bytes"]
    if not isinstance(budget, int) or budget <= 0:
        raise PublishStateError("invalid prepared Connector call budget")
    return data


def _decode_prepared_payload(request: dict[str, object]) -> bytes:
    try:
        return base64.b64decode(str(request["payload_b64"]), validate=True)
    except Exception as exc:
        raise PublishStateError(f"invalid prepared bundle Base64: {exc}") from exc


def _verify_bundle_payload(
    repo: Path,
    request: dict[str, object],
    payload_bytes: bytes,
) -> dict[str, object]:
    actual_digest = hashlib.sha256(payload_bytes).hexdigest()
    if actual_digest != request["payload_sha256"]:
        raise PublishStateError(
            "publish bundle sha256 mismatch: "
            f"expected={request['payload_sha256']} actual={actual_digest}"
        )
    publish_commit = str(request["publish_commit"])
    with tempfile.TemporaryDirectory(prefix="space-idle-publish-bundle-verify-") as tmp:
        bundle_path = Path(tmp) / "request.bundle"
        bundle_path.write_bytes(payload_bytes)
        try:
            subprocess.run(
                ["git", "bundle", "verify", str(bundle_path)],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            heads = _git("bundle", "list-heads", str(bundle_path), cwd=repo).splitlines()
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            raise PublishStateError(f"invalid publish bundle: {(stderr or '').strip()}") from exc
    advertised = [line.split(maxsplit=1)[0] for line in heads if line.strip()]
    if advertised != [publish_commit]:
        raise PublishStateError(
            f"publish bundle advertises unexpected heads: expected={[publish_commit]} actual={advertised}"
        )
    fields, _ = _parse_commit_object(repo, publish_commit)
    if fields.get("tree", []) != [request["target_tree"]]:
        raise PublishStateError(
            "publish commit tree mismatch: "
            f"expected={request['target_tree']} actual={fields.get('tree', [])}"
        )
    if fields.get("parent", []) != [request["base_sha"]]:
        raise PublishStateError(
            "publish commit parent mismatch: "
            f"expected={[request['base_sha']]} actual={fields.get('parent', [])}"
        )
    return {
        "payload_sha256": actual_digest,
        "payload_bytes": len(payload_bytes),
        "publish_commit": publish_commit,
        "target_tree": str(request["target_tree"]),
    }


def _verify_prepared_request(
    repo: Path, path: Path, *, expected_base_sha: str | None = None
) -> dict[str, object]:
    request = _read_prepared_request(path)
    if expected_base_sha is not None and request["base_sha"] != expected_base_sha:
        raise PublishStateError(
            "publish request base does not match the expected target-branch base: "
            f"request={request['base_sha']} expected={expected_base_sha}"
        )
    local_target = str(request["local_target_commit"])
    local_tree = _git("rev-parse", f"{local_target}^{{tree}}", cwd=repo)
    if local_tree != request["target_tree"]:
        raise PublishStateError(
            "prepared local target tree mismatch: "
            f"commit={local_target} local={local_tree} request={request['target_tree']}"
        )
    payload_bytes = _decode_prepared_payload(request)
    bundle = _verify_bundle_payload(repo, request, payload_bytes)
    return {
        "manifest": str(path),
        "version": REQUEST_VERSION,
        "transport": "git-bundle",
        "request_id": request["request_id"],
        "payload_bytes": bundle["payload_bytes"],
        "payload_chars": len(str(request["payload_b64"])),
        "payload_sha256": bundle["payload_sha256"],
        "publish_commit": bundle["publish_commit"],
        "target_tree": bundle["target_tree"],
        "verified": True,
    }


def _transport_request(
    prepared: dict[str, object],
    payload_source: dict[str, object],
) -> dict[str, object]:
    return {
        "version": REQUEST_VERSION,
        "request_id": prepared["request_id"],
        "target_branch": prepared["target_branch"],
        "base_sha": prepared["base_sha"],
        "target_tree": prepared["target_tree"],
        "publish_commit": prepared["publish_commit"],
        "payload_sha256": prepared["payload_sha256"],
        "payload_encoding": "git-bundle-base64",
        "payload_chars": len(str(prepared["payload_b64"])),
        "payload_source": payload_source,
    }


def _request_file_path(request_id: str) -> str:
    return f".publish/requests/{request_id}.json"


def _receipt_file_path(request_id: str) -> str:
    return f".publish/receipts/{request_id}.json"


def _connector_submit_packet(
    github_repository: str,
    publish_branch: str,
    transport_request: dict[str, object],
) -> dict[str, object]:
    request_id = str(transport_request["request_id"])
    content = json.dumps(transport_request, separators=(",", ":"), sort_keys=True) + "\n"
    return {
        "stage": "submit-publish-request",
        "action": "GitHub.create_file",
        "action_args": {
            "repository_full_name": github_repository,
            "path": _request_file_path(request_id),
            "content": content,
            "message": f"Submit publish request {request_id}",
            "branch": publish_branch,
        },
    }


def _named_blob_tree_oid(repo: Path, entries: list[tuple[str, str]]) -> str:
    raw = bytearray()
    for name, blob_oid in sorted(entries):
        raw.extend(b"100644 ")
        raw.extend(name.encode("ascii"))
        raw.append(0)
        raw.extend(bytes.fromhex(blob_oid))
    return _git_object_oid(repo, "tree", bytes(raw))


def _connector_payload_chunk_packet(
    repo: Path,
    github_repository: str,
    content: str,
    index: int,
) -> dict[str, object]:
    path = f"{index:04d}.txt"
    blob_oid = _git_object_oid(repo, "blob", content.encode("ascii"))
    tree_oid = _named_blob_tree_oid(repo, [(path, blob_oid)])
    return {
        "stage": "materialize-payload-chunk",
        "chunk_index": index,
        "expected_blob_git_oid": blob_oid,
        "expected_tree_git_oid": tree_oid,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": github_repository,
            "base_tree_sha": None,
            "tree_elements": [
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "content": content,
                }
            ],
        },
    }


def _connector_call_bytes(packet: dict[str, object]) -> int:
    action_args = packet.get("action_args")
    if not isinstance(action_args, dict):
        raise PublishStateError("Connector packet is missing action_args")
    return len(json.dumps(action_args, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _split_payload_chunks(payload: str) -> list[str]:
    chunks = [
        payload[start : start + DEFAULT_PAYLOAD_CHUNK_CHARS]
        for start in range(0, len(payload), DEFAULT_PAYLOAD_CHUNK_CHARS)
    ]
    if not chunks:
        raise PublishStateError("publish payload is empty")
    if len(chunks) > MAX_PAYLOAD_CHUNKS:
        raise PublishStateError(
            f"publish payload needs {len(chunks)} transport chunks, exceeding limit {MAX_PAYLOAD_CHUNKS}; "
            "publish an earlier coherent target-ref"
        )
    return chunks


def _connector_payload_root_packet(
    repo: Path,
    github_repository: str,
    chunks: list[str],
) -> dict[str, object]:
    entries: list[tuple[str, str]] = []
    elements: list[dict[str, object]] = []
    for index, content in enumerate(chunks):
        path = f"{index:04d}.txt"
        blob_oid = _git_object_oid(repo, "blob", content.encode("ascii"))
        entries.append((path, blob_oid))
        elements.append(
            {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_oid,
            }
        )
    expected_tree_oid = _named_blob_tree_oid(repo, entries)
    return {
        "stage": "assemble-payload-tree",
        "expected_tree_git_oid": expected_tree_oid,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": github_repository,
            "base_tree_sha": None,
            "tree_elements": elements,
        },
    }


def _build_payload_tree_packets(
    repo: Path,
    *,
    github_repository: str,
    payload: str,
    call_budget: int,
    output_dir: Path,
) -> tuple[list[str], str, str, list[str]]:
    if call_budget <= 0:
        raise PublishStateError("Connector call budget must be positive")
    chunks = _split_payload_chunks(payload)
    upload_paths: list[str] = []
    for index, content in enumerate(chunks):
        packet = _connector_payload_chunk_packet(repo, github_repository, content, index)
        size = _connector_call_bytes(packet)
        if size > call_budget:
            raise PublishStateError(
                f"payload chunk {index} needs a {size}-byte Connector call, exceeding "
                f"the configured {call_budget}-byte budget"
            )
        path = output_dir / f"upload-chunk-{index:03d}.json"
        path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        upload_paths.append(str(path))

    root_packet = _connector_payload_root_packet(repo, github_repository, chunks)
    root_size = _connector_call_bytes(root_packet)
    if root_size > call_budget:
        raise PublishStateError(
            f"payload root tree needs a {root_size}-byte Connector call, exceeding "
            f"the configured {call_budget}-byte budget"
        )
    root_path = output_dir / "assemble-payload-tree.json"
    root_path.write_text(json.dumps(root_packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return upload_paths, str(root_path), str(root_packet["expected_tree_git_oid"]), chunks

def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    _require_hex_sha(args.remote_commit, name="remote commit")
    _require_hex_sha(args.remote_tree, name="remote tree")
    local_commit = _git("rev-parse", f"{args.local_ref}^{{commit}}", cwd=repo)
    local_tree = _git("rev-parse", f"{args.local_ref}^{{tree}}", cwd=repo)
    if local_tree != args.remote_tree:
        raise PublishStateError(
            f"artifact/local tree mismatch: local={local_tree} remote={args.remote_tree}"
        )
    _write_state(repo, args.remote_commit, args.remote_tree, local_commit)
    print(json.dumps({"remote_commit": args.remote_commit, "remote_tree": args.remote_tree, "local_head": local_commit}, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = _read_state(repo)
    target_commit = _git("rev-parse", f"{args.target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{args.target_ref}^{{tree}}", cwd=repo)
    combined = _bundle_payload_metrics(
        repo,
        state["remote_commit"],
        target_tree,
        _message_bytes(_default_message(repo, state, args.target_ref)),
    )
    combined.update({"target_ref": target_commit, "target_tree": target_tree})

    commits: list[dict[str, object]] = []
    local_head = state["local_head"]
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", local_head, target_commit],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if ancestor:
        previous_remote_commit = state["remote_commit"]
        for commit_id in _git("rev-list", "--reverse", f"{local_head}..{target_commit}", cwd=repo).splitlines():
            commit_tree = _git("rev-parse", f"{commit_id}^{{tree}}", cwd=repo)
            message = _message_bytes(_git("show", "-s", "--format=%B", commit_id, cwd=repo).rstrip() + "\n")
            metrics = _bundle_payload_metrics(repo, previous_remote_commit, commit_tree, message)
            previous_remote_commit = str(metrics["publish_commit"])
            metrics.update(
                {
                    "local_commit": commit_id,
                    "subject": _git("show", "-s", "--format=%s", commit_id, cwd=repo),
                    "target_tree": commit_tree,
                }
            )
            commits.append(metrics)

    print(
        json.dumps(
            {
                "recorded_remote_commit": state["remote_commit"],
                "recorded_remote_tree": state["remote_tree"],
                "recorded_local_head": local_head,
                "working_tree_clean": _working_tree_clean(repo),
                "uncommitted_changes_excluded": not _working_tree_clean(repo),
                "target_ref": target_commit,
                "transport": "git-bundle",
                "combined_request": combined,
                "sequential_local_commits_available": ancestor,
                "sequential_requests": commits,
            },
            indent=2,
        )
    )
    return 0


def _prepare_request(
    repo: Path,
    *,
    target_branch: str,
    target_ref: str,
    message_text: str | None,
    connector_call_budget_bytes: int,
    output: Path,
    base_sha: str | None = None,
) -> dict[str, object]:
    state = _read_state(repo)
    request_base = base_sha or state["remote_commit"]
    _require_hex_sha(request_base, name="publish request base")
    _require_commit_object(repo, request_base)
    base_tree = _git("rev-parse", f"{request_base}^{{tree}}", cwd=repo)
    target_commit = _git("rev-parse", f"{target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{target_ref}^{{tree}}", cwd=repo)
    if target_tree == base_tree:
        raise PublishStateError("local target tree already matches the target branch tree")
    resolved_message = message_text if message_text is not None else _default_message(repo, state, target_ref)
    message = _message_bytes(resolved_message)
    publish_commit = _create_publish_commit(repo, request_base, target_tree, message)
    payload_bytes = _bundle_bytes(repo, request_base, publish_commit)
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    budget = connector_call_budget_bytes
    if budget <= 0:
        raise PublishStateError("Connector call budget must be positive")
    request = {
        "version": REQUEST_VERSION,
        "request_id": uuid.uuid4().hex,
        "target_branch": target_branch,
        "base_sha": request_base,
        "target_tree": target_tree,
        "publish_commit": publish_commit,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload_encoding": "git-bundle-base64",
        "payload_b64": payload_b64,
        "connector_call_budget_bytes": budget,
        "local_target_commit": target_commit,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verified = _verify_prepared_request(repo, output, expected_base_sha=request_base)
    return {
        "manifest": str(output),
        "request_id": request["request_id"],
        "remote_request_path": _request_file_path(str(request["request_id"])),
        "remote_receipt_path": _receipt_file_path(str(request["request_id"])),
        "transport": "git-bundle",
        "connector_call_budget_bytes": budget,
        "payload_bytes": len(payload_bytes),
        "payload_chars": len(payload_b64),
        "payload_sha256": request["payload_sha256"],
        "publish_commit": publish_commit,
        "target_tree": target_tree,
        "local_target_commit": target_commit,
        "working_tree_clean": _working_tree_clean(repo),
        "uncommitted_changes_excluded": not _working_tree_clean(repo),
        "verified": verified["verified"],
    }


def _build_connector_plan(
    repo: Path,
    *,
    manifest: Path,
    github_repository: str,
    target_remote_head: str,
    publish_branch: str,
    output_dir: Path,
    connector_call_budget_bytes: int | None = None,
) -> dict[str, object]:
    verified = _verify_prepared_request(repo, manifest)
    prepared = _read_prepared_request(manifest)
    _require_hex_sha(target_remote_head, name="target remote HEAD")
    if target_remote_head != prepared["base_sha"]:
        raise PublishStateError(
            "target branch HEAD moved since prepare: "
            f"expected={prepared['base_sha']} actual={target_remote_head}"
        )
    call_budget = (
        connector_call_budget_bytes
        if connector_call_budget_bytes is not None
        else int(prepared["connector_call_budget_bytes"])
    )
    if call_budget <= 0:
        raise PublishStateError("Connector call budget must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("upload-part-*.json", "upload-chunk-*.json"):
        for stale in output_dir.glob(pattern):
            stale.unlink()
    for fixed in ("assemble-payload-tree.json", "submit-request.json"):
        path = output_dir / fixed
        if path.exists():
            path.unlink()

    payload = str(prepared["payload_b64"])
    upload_packets, root_packet, expected_tree_oid, chunks = _build_payload_tree_packets(
        repo,
        github_repository=github_repository,
        payload=payload,
        call_budget=call_budget,
        output_dir=output_dir,
    )

    summary = {
        "strategy": "create-trees-then-request-file",
        "manifest": str(manifest),
        "request_id": prepared["request_id"],
        "github_repository": github_repository,
        "publish_branch": publish_branch,
        "target_branch": prepared["target_branch"],
        "target_remote_head": target_remote_head,
        "connector_call_budget_bytes": call_budget,
        "transport_chunk_chars": DEFAULT_PAYLOAD_CHUNK_CHARS,
        "payload_chunk_count": len(chunks),
        "upload_call_count": len(upload_packets),
        "upload_packets": upload_packets,
        "uploads_are_independent": True,
        "connector_uploads_may_run_in_parallel": True,
        "upload_result_shas_are_not_inputs": True,
        "payload_root_packet": root_packet,
        "expected_payload_tree_git_oid": expected_tree_oid,
        "submit_request_packet": None,
        "remote_request_path": _request_file_path(str(prepared["request_id"])),
        "remote_receipt_path": _receipt_file_path(str(prepared["request_id"])),
        "normal_remote_target_probe_calls": 1,
        "normal_publish_transport_probe_calls": 0,
        "normal_github_mutation_calls": len(upload_packets) + 2,
        "normal_github_calls_before_gateway": len(upload_packets) + 3,
        "normal_sha_handoffs": 1,
        "normal_per_upload_verification_calls": 0,
        "gateway_completes_target_publish": True,
        "next_after_transport": (
            "execute all helper-specified GitHub.create_tree chunk uploads; then execute the small "
            "assemble-payload-tree action. The root action references helper-precomputed blob OIDs, "
            "so corrupted chunk uploads cannot satisfy it. Pass only the returned root tree SHA to "
            "gateway-submit, which emits the final small request action."
        ),
        "request_verified": bool(verified["verified"]),
        "verified": True,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary

def _read_active_session(repo: Path) -> dict[str, object]:
    path = _active_session_path(repo)
    if not path.exists():
        raise PublishStateError("no active Gateway publish session")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishStateError(f"invalid active Gateway publish session: {exc}") from exc
    required = {
        "version",
        "request_id",
        "manifest",
        "connector_dir",
        "strategy",
        "phase",
        "target_branch",
        "base_sha",
        "target_tree",
        "publish_commit",
        "local_target_commit",
        "remote_request_path",
        "remote_receipt_path",
        "upload_packets",
        "payload_root_packet",
        "expected_payload_tree_git_oid",
        "payload_chunk_count",
        "submit_request_packet",
    }
    missing = required - data.keys()
    if missing:
        raise PublishStateError(
            f"invalid active Gateway publish session: missing fields {sorted(missing)}"
        )
    if data["version"] != 3:
        raise PublishStateError(
            f"unsupported active Gateway publish session version: {data['version']}"
        )
    return data

def _write_active_session(repo: Path, session: dict[str, object]) -> None:
    path = _active_session_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clear_active_session(repo: Path) -> None:
    directory = _active_session_dir(repo)
    if directory.exists():
        shutil.rmtree(directory)


def _packet_action_summary(path: str) -> dict[str, object]:
    packet_path = Path(path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    action = packet.get("action")
    if not isinstance(action, str) or not action:
        raise PublishStateError(f"invalid Connector packet action: {packet_path}")
    return {
        "action": action,
        "connector_namespace": action.split(".", 1)[0],
        "connector_function": action.split(".", 1)[1] if "." in action else action,
        "packet": str(packet_path),
        "stage": packet.get("stage"),
        "chunk_index": packet.get("chunk_index"),
    }


def cmd_gateway_begin(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    active_dir = _active_session_dir(repo)
    if _active_session_path(repo).exists():
        active = _read_active_session(repo)
        raise PublishStateError(
            "an active Gateway publish session already exists: "
            f"request_id={active['request_id']} phase={active['phase']}; "
            "continue it through gateway-submit/gateway-complete or inspect it with gateway-status"
        )
    if active_dir.exists():
        shutil.rmtree(active_dir)
    active_dir.mkdir(parents=True, exist_ok=True)

    state = _read_state(repo)
    target_remote_head = str(args.target_remote_head).lower()
    _require_hex_sha(target_remote_head, name="target remote HEAD")
    if args.target_branch == "develop" and target_remote_head != state["remote_commit"]:
        _clear_active_session(repo)
        raise PublishStateError(
            "develop HEAD moved since the recorded publish base: "
            f"recorded={state['remote_commit']} actual={target_remote_head}"
        )
    try:
        _require_commit_object(repo, target_remote_head)
    except PublishStateError:
        _clear_active_session(repo)
        raise

    manifest = active_dir / "manifest.json"
    prepared_summary = _prepare_request(
        repo,
        target_branch=args.target_branch,
        target_ref=args.target_ref,
        message_text=args.message,
        connector_call_budget_bytes=DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
        output=manifest,
        base_sha=target_remote_head,
    )
    connector_dir = active_dir / "connector"
    plan = _build_connector_plan(
        repo,
        manifest=manifest,
        github_repository=GITHUB_REPOSITORY,
        target_remote_head=target_remote_head,
        publish_branch=PUBLISH_BRANCH,
        output_dir=connector_dir,
        connector_call_budget_bytes=DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
    )
    prepared = _read_prepared_request(manifest)
    session = {
        "version": 3,
        "request_id": prepared["request_id"],
        "manifest": str(manifest),
        "connector_dir": str(connector_dir),
        "strategy": plan["strategy"],
        "phase": "materialize-payload-tree",
        "target_branch": prepared["target_branch"],
        "base_sha": prepared["base_sha"],
        "target_tree": prepared["target_tree"],
        "publish_commit": prepared["publish_commit"],
        "local_target_commit": prepared["local_target_commit"],
        "remote_request_path": plan["remote_request_path"],
        "remote_receipt_path": plan["remote_receipt_path"],
        "upload_packets": list(plan["upload_packets"]),
        "payload_root_packet": plan["payload_root_packet"],
        "expected_payload_tree_git_oid": plan["expected_payload_tree_git_oid"],
        "payload_chunk_count": plan["payload_chunk_count"],
        "submit_request_packet": None,
    }
    _write_active_session(repo, session)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-begin",
                "session": str(_active_session_path(repo)),
                "request_id": prepared["request_id"],
                "strategy": plan["strategy"],
                "phase": session["phase"],
                "target_branch": prepared["target_branch"],
                "target_remote_head": target_remote_head,
                "target_tree": prepared["target_tree"],
                "local_target_commit": prepared["local_target_commit"],
                "transport_chunk_chars": DEFAULT_PAYLOAD_CHUNK_CHARS,
                "payload_chunk_count": plan["payload_chunk_count"],
                "connector_actions": [
                    _packet_action_summary(path) for path in plan["upload_packets"]
                ],
                "then_connector_action": _packet_action_summary(str(plan["payload_root_packet"])),
                "connector_action_selection_is_not_a_decision": True,
                "execute_packet_actions_exactly": True,
                "upload_result_shas_are_not_inputs": True,
                "next_helper_command": (
                    "after all chunk create_tree actions succeed, execute then_connector_action; "
                    "then run gateway-submit --payload-tree-sha <SHA returned by that root create_tree>"
                ),
                "remote_receipt_path": plan["remote_receipt_path"],
                "after_gateway_success": (
                    "observe the target branch HEAD once and run gateway-complete; "
                    "gateway-record remains available only for receipt-based audit/recovery"
                ),
                "prepared": prepared_summary,
                "verified": True,
            },
            indent=2,
        )
    )
    return 0


def cmd_gateway_submit(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = _read_active_session(repo)
    if session["strategy"] != "create-trees-then-request-file":
        raise PublishStateError("gateway-submit requires a create-tree Gateway session")
    if session["phase"] != "materialize-payload-tree":
        raise PublishStateError(
            "gateway-submit is only valid after payload chunk materialization and root tree creation"
        )

    actual_tree = str(args.payload_tree_sha).lower()
    _require_hex_sha(actual_tree, name="payload tree SHA")
    expected_tree = str(session["expected_payload_tree_git_oid"]).lower()
    _require_hex_sha(expected_tree, name="expected payload tree SHA")
    if actual_tree != expected_tree:
        raise PublishStateError(
            "payload root tree mismatch: "
            f"expected={expected_tree} actual={actual_tree}; "
            "do not submit a request. Re-run the helper-specified chunk create_tree actions and root tree action exactly."
        )

    manifest = Path(str(session["manifest"]))
    prepared = _read_prepared_request(manifest)
    submit_request = _transport_request(
        prepared,
        {
            "kind": "git-tree",
            "oid": expected_tree,
            "chunk_count": int(session["payload_chunk_count"]),
        },
    )
    submit_packet = _connector_submit_packet(
        GITHUB_REPOSITORY, PUBLISH_BRANCH, submit_request
    )
    size = _connector_call_bytes(submit_packet)
    if size > DEFAULT_CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError(
            f"publish request metadata needs a {size}-byte Connector call, exceeding "
            f"the fixed {DEFAULT_CONNECTOR_CALL_BUDGET_BYTES}-byte normal budget"
        )
    connector_dir = Path(str(session["connector_dir"]))
    submit_path = connector_dir / "submit-request.json"
    submit_path.write_text(
        json.dumps(submit_packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    session["phase"] = "submit-request"
    session["submit_request_packet"] = str(submit_path)
    _write_active_session(repo, session)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-submit",
                "request_id": session["request_id"],
                "phase": "submit-request",
                "verified_payload_tree": expected_tree,
                "connector_action": _packet_action_summary(str(submit_path)),
                "connector_action_selection_is_not_a_decision": True,
                "execute_packet_action_exactly": True,
                "remote_receipt_path": session["remote_receipt_path"],
                "after_gateway_success": (
                    "observe the target branch HEAD once and run gateway-complete; "
                    "do not fetch or rewrite payload data"
                ),
                "verified": True,
            },
            indent=2,
        )
    )
    return 0

def cmd_gateway_complete(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = _read_active_session(repo)
    if session["phase"] != "submit-request":
        raise PublishStateError(
            "Gateway request has not reached submit-request phase; verify the payload root tree "
            "with gateway-submit first"
        )
    observed = str(args.target_remote_head).lower()
    _require_hex_sha(observed, name="target remote HEAD")
    expected = str(session["publish_commit"]).lower()
    if observed != expected:
        raise PublishStateError(
            "target branch has not reached the deterministic publish commit: "
            f"expected={expected} actual={observed}; keep the active session and inspect Gateway status"
        )
    state = _read_state(repo)
    if session["target_branch"] == "develop" and state["remote_commit"] != session["base_sha"]:
        raise PublishStateError(
            "recorded develop publish base changed during the active session: "
            f"session={session['base_sha']} state={state['remote_commit']}"
        )
    local_target = str(session["local_target_commit"])
    local_tree = _git("rev-parse", f"{local_target}^{{tree}}", cwd=repo)
    if local_tree != session["target_tree"]:
        raise PublishStateError(
            "active session target tree no longer matches its local target commit"
        )
    update_state = session["target_branch"] == "develop"
    if update_state:
        _write_state(repo, observed, str(session["target_tree"]), local_target)
    request_id = session["request_id"]
    target_branch = session["target_branch"]
    _clear_active_session(repo)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-complete",
                "request_id": request_id,
                "target_branch": target_branch,
                "remote_commit": observed,
                "remote_tree": local_tree,
                "local_head": local_target,
                "publish_state_updated": update_state,
                "develop_publish_state_unchanged": target_branch == "temp",
                "active_session_cleared": True,
                "verified": True,
            },
            indent=2,
        )
    )
    return 0


def cmd_gateway_reconcile(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if _active_session_path(repo).exists():
        raise PublishStateError(
            "cannot reconcile while a Gateway session is active; finish or inspect that session first"
        )
    state = _read_state(repo)
    observed = str(args.target_remote_head).lower()
    _require_hex_sha(observed, name="target remote HEAD")
    local_target = _git("rev-parse", f"{args.target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{args.target_ref}^{{tree}}", cwd=repo)
    resolved_message = (
        args.message
        if args.message is not None
        else _default_message(repo, state, args.target_ref)
    )
    expected = _create_publish_commit(
        repo, state["remote_commit"], target_tree, _message_bytes(resolved_message)
    )
    if observed != expected:
        raise PublishStateError(
            "observed develop HEAD is not the deterministic publish commit for the recorded base "
            "and selected local checkpoint: "
            f"expected={expected} actual={observed}"
        )
    _write_state(repo, observed, target_tree, local_target)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-reconcile",
                "previous_remote_commit": state["remote_commit"],
                "remote_commit": observed,
                "remote_tree": target_tree,
                "local_head": local_target,
                "publish_state_updated": True,
                "verified": True,
            },
            indent=2,
        )
    )
    return 0


def cmd_gateway_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = _read_state(repo)
    active = None
    if _active_session_path(repo).exists():
        active = _read_active_session(repo)
    print(
        json.dumps(
            {
                "publish_state": state,
                "active_session": active,
                "working_tree_clean": _working_tree_clean(repo),
            },
            indent=2,
        )
    )
    return 0


def _remote_branch_head(repo: Path, remote: str, branch: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < 2:
        raise PublishStateError(f"could not resolve exactly one remote head for {remote}:{branch}")
    head = rows[0][0]
    _require_hex_sha(head, name="remote branch head")
    return head


def _fetch_remote_branch_tree(repo: Path, remote: str, branch: str) -> str:
    subprocess.run(
        ["git", "fetch", "--quiet", "--no-tags", remote, f"refs/heads/{branch}"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tree = _git("rev-parse", "FETCH_HEAD^{tree}", cwd=repo)
    _require_hex_sha(tree, name="remote branch tree")
    return tree


def _commit_identity_env(repo: Path, target_commit: str) -> dict[str, str]:
    fields = _git(
        "show",
        "-s",
        "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI",
        target_commit,
        cwd=repo,
    ).split("\x00")
    if len(fields) != 6 or not all(fields):
        raise PublishStateError("could not derive commit identity from local target commit")
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": fields[0],
            "GIT_AUTHOR_EMAIL": fields[1],
            "GIT_AUTHOR_DATE": fields[2],
            "GIT_COMMITTER_NAME": fields[3],
            "GIT_COMMITTER_EMAIL": fields[4],
            "GIT_COMMITTER_DATE": fields[5],
        }
    )
    return env


def cmd_native_publish(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = _read_state(repo)
    target_commit = _git("rev-parse", f"{args.target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{target_commit}^{{tree}}", cwd=repo)
    _require_hex_sha(target_commit, name="local target commit")
    _require_hex_sha(target_tree, name="local target tree")

    remote_before = _remote_branch_head(repo, args.remote, args.target_branch)
    checks: dict[str, bool] = {
        "remote_head_matches_recorded_base": remote_before == state["remote_commit"],
    }
    if not checks["remote_head_matches_recorded_base"]:
        raise PublishStateError(
            "remote target moved before native publish: "
            f"recorded={state['remote_commit']} remote={remote_before}"
        )
    remote_tree_before = _fetch_remote_branch_tree(repo, args.remote, args.target_branch)
    checks["remote_tree_matches_recorded_base"] = remote_tree_before == state["remote_tree"]
    if not checks["remote_tree_matches_recorded_base"]:
        raise PublishStateError(
            "remote target tree does not match recorded publish base: "
            f"recorded={state['remote_tree']} remote={remote_tree_before}"
        )
    if target_tree == remote_tree_before:
        raise PublishStateError("local target tree is already published; nothing to publish")

    message = args.message or _default_message(repo, state, target_commit)
    if not message.strip():
        raise PublishStateError("native publish commit message is empty")
    commit_result = subprocess.run(
        ["git", "commit-tree", target_tree, "-p", remote_before],
        cwd=repo,
        check=True,
        text=True,
        input=message.rstrip() + "\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_commit_identity_env(repo, target_commit),
    )
    published_commit = commit_result.stdout.strip()
    _require_hex_sha(published_commit, name="native publish commit")
    subprocess.run(
        ["git", "push", args.remote, f"{published_commit}:refs/heads/{args.target_branch}"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    remote_after = _remote_branch_head(repo, args.remote, args.target_branch)
    checks["remote_head_matches_published_commit"] = remote_after == published_commit
    if not checks["remote_head_matches_published_commit"]:
        raise PublishStateError(
            "native publish remote ref verification failed: "
            f"expected={published_commit} remote={remote_after}"
        )
    remote_tree_after = _fetch_remote_branch_tree(repo, args.remote, args.target_branch)
    checks["remote_tree_matches_local_target"] = remote_tree_after == target_tree
    if not checks["remote_tree_matches_local_target"]:
        raise PublishStateError(
            "native publish remote tree verification failed: "
            f"local={target_tree} remote={remote_tree_after}"
        )
    if args.target_branch == "develop":
        _write_state(repo, published_commit, target_tree, target_commit)
    print(
        json.dumps(
            {
                "transport": "native-git",
                "target_branch": args.target_branch,
                "remote": args.remote,
                "base_commit": remote_before,
                "published_commit": published_commit,
                "published_tree": target_tree,
                "local_head": target_commit,
                "publish_state_updated": args.target_branch == "develop",
                "working_tree_clean": _working_tree_clean(repo),
                "uncommitted_changes_excluded": not _working_tree_clean(repo),
                "checks": checks,
                "verified": all(checks.values()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _read_publish_receipt(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishStateError(f"invalid publish receipt: {exc}") from exc
    required = {
        "version",
        "request_id",
        "request_version",
        "target_branch",
        "base_commit",
        "target_tree",
        "published_commit",
        "published_tree",
        "published_commit_object_b64",
    }
    missing = required - data.keys()
    if missing:
        raise PublishStateError(f"invalid publish receipt: missing fields {sorted(missing)}")
    if data["version"] != RECEIPT_VERSION:
        raise PublishStateError(f"unsupported publish receipt version: {data['version']}")
    if data["request_version"] != REQUEST_VERSION:
        raise PublishStateError(f"unsupported receipt request version: {data['request_version']}")
    if data["target_branch"] not in {"develop", "temp"}:
        raise PublishStateError("invalid publish receipt target_branch")
    for key in ("base_commit", "target_tree", "published_commit", "published_tree"):
        value = data[key]
        if not isinstance(value, str):
            raise PublishStateError(f"invalid publish receipt {key}")
        _require_hex_sha(value, name=f"publish receipt {key}")
    request_id = data["request_id"]
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise PublishStateError("invalid publish receipt request_id")
    try:
        int(request_id, 16)
    except ValueError as exc:
        raise PublishStateError("invalid publish receipt request_id") from exc
    if not isinstance(data["published_commit_object_b64"], str) or not data["published_commit_object_b64"]:
        raise PublishStateError("invalid publish receipt published_commit_object_b64")
    return data


def _import_receipt_commit_object(repo: Path, receipt: dict[str, object]) -> dict[str, bool]:
    try:
        raw = base64.b64decode(str(receipt["published_commit_object_b64"]), validate=True)
    except Exception as exc:
        raise PublishStateError(f"invalid published commit object encoding: {exc}") from exc
    result = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
        cwd=repo,
        input=raw,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    actual = result.stdout.decode("ascii").strip()
    expected = str(receipt["published_commit"])
    if actual != expected:
        raise PublishStateError(
            f"published commit object OID mismatch: expected={expected} actual={actual}"
        )
    fields, _ = _parse_commit_object(repo, actual)
    tree_ok = fields.get("tree", []) == [str(receipt["published_tree"])]
    parent_ok = fields.get("parent", []) == [str(receipt["base_commit"])]
    if not tree_ok or not parent_ok:
        raise PublishStateError("published commit object does not match receipt tree/parent")
    return {
        "receipt_commit_object_imported": True,
        "receipt_commit_object_tree_matches": tree_ok,
        "receipt_commit_object_parent_matches": parent_ok,
    }


def _record_publish(
    repo: Path,
    *,
    manifest: Path,
    receipt_path: Path,
    update_state: bool = True,
) -> dict[str, object]:
    state = _read_state(repo)
    verified = _verify_prepared_request(repo, manifest)
    request = _read_prepared_request(manifest)
    receipt = _read_publish_receipt(receipt_path)
    local_head = str(request["local_target_commit"])
    _require_commit_object(repo, local_head)
    local_tree = _git("rev-parse", f"{local_head}^{{tree}}", cwd=repo)
    receipt_object_checks = _import_receipt_commit_object(repo, receipt)
    remote_commit = str(receipt["published_commit"])
    remote_tree = str(receipt["published_tree"])
    checks: dict[str, bool] = {
        "request_verified": bool(verified["verified"]),
        "receipt_request_matches_manifest": receipt["request_id"] == request["request_id"],
        "receipt_branch_matches_manifest": receipt["target_branch"] == request["target_branch"],
        "receipt_base_matches_manifest": receipt["base_commit"] == request["base_sha"],
        "receipt_target_matches_manifest": receipt["target_tree"] == request["target_tree"],
        "published_commit_matches_manifest": receipt["published_commit"] == request["publish_commit"],
        "published_tree_matches_receipt_target": remote_tree == receipt["target_tree"],
        "published_tree_matches_local_tree": remote_tree == local_tree,
        "local_ref_matches_prepared_target": local_head == request["local_target_commit"],
        "remote_commit_advanced": remote_commit != request["base_sha"],
    }
    if update_state:
        checks["receipt_base_matches_recorded_remote"] = (
            receipt["base_commit"] == state["remote_commit"]
        )
    checks.update(receipt_object_checks)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise PublishStateError("publish receipt verification failed: " + ", ".join(failed))
    if update_state:
        _write_state(repo, remote_commit, remote_tree, local_head)
    return {
        "remote_commit": remote_commit,
        "remote_tree": remote_tree,
        "local_head": local_head,
        "publish_state_updated": update_state,
        "working_tree_clean": _working_tree_clean(repo),
        "uncommitted_changes_excluded": not _working_tree_clean(repo),
        "checks": checks,
        "verified": all(checks.values()),
    }


def cmd_gateway_record(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = _read_active_session(repo)
    if session["phase"] != "submit-request":
        raise PublishStateError(
            "Gateway request has not reached submit-request phase; "
            "finish payload tree verification with gateway-submit first"
        )
    recorded = _record_publish(
        repo,
        manifest=Path(str(session["manifest"])),
        receipt_path=Path(args.receipt).resolve(),
        update_state=session["target_branch"] == "develop",
    )
    request_id = session["request_id"]
    _clear_active_session(repo)
    recorded.update(
        {
            "entrypoint": "gateway-record",
            "request_id": request_id,
            "active_session_cleared": True,
            "develop_publish_state_unchanged": session["target_branch"] == "temp",
        }
    )
    print(json.dumps(recorded, indent=2))
    return 0


def cmd_gateway_abort(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = _read_active_session(repo)
    if args.request_id != session["request_id"]:
        raise PublishStateError(
            "gateway-abort request id does not match the active session: "
            f"active={session['request_id']} provided={args.request_id}"
        )
    _clear_active_session(repo)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-abort",
                "request_id": args.request_id,
                "active_session_cleared": True,
                "note": (
                    "This only discards local helper state. Use it only after confirming the "
                    "request was not submitted or cannot still publish."
                ),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and track exact-tree publish requests for Space-Idle."
    )
    parser.add_argument("--repo", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize state from a verified source artifact")
    init.add_argument("--remote-commit", required=True)
    init.add_argument("--remote-tree", required=True)
    init.add_argument("--local-ref", default="HEAD")
    init.set_defaults(func=cmd_init)

    native_publish = sub.add_parser(
        "native-publish",
        help="publish a committed target directly with native git when authenticated push is available",
    )
    native_publish.add_argument("--remote", default="origin")
    native_publish.add_argument("--target-branch", choices=("develop", "temp"), default="develop")
    native_publish.add_argument("--target-ref", default="HEAD")
    native_publish.add_argument("--message")
    native_publish.set_defaults(func=cmd_native_publish)

    plan = sub.add_parser("plan", help="estimate combined and per-local-commit Git bundle transport")
    plan.add_argument("--target-ref", default="HEAD")
    plan.set_defaults(func=cmd_plan)

    gateway_begin = sub.add_parser(
        "gateway-begin",
        help=(
            "prepare the exact target and emit the only allowed Connector action phase for "
            "the standard Publish Gateway path"
        ),
    )
    gateway_begin.add_argument(
        "--target-branch",
        choices=("develop", "temp"),
        default="develop",
        help="develop is standard; temp is only for explicitly requested isolated validation",
    )
    gateway_begin.add_argument(
        "--target-ref",
        required=True,
        help="committed local checkpoint to publish; selection of the responsibility boundary is explicit",
    )
    gateway_begin.add_argument(
        "--target-remote-head",
        required=True,
        help="the single target-branch HEAD observation made immediately before publish",
    )
    gateway_begin.add_argument("--message")
    gateway_begin.set_defaults(func=cmd_gateway_begin)

    gateway_submit = sub.add_parser(
        "gateway-submit",
        help=(
            "verify the returned payload root tree SHA and emit the final small Gateway request action"
        ),
    )
    gateway_submit.add_argument(
        "--payload-tree-sha",
        required=True,
        help="SHA returned by the helper-specified assemble-payload-tree GitHub.create_tree action",
    )
    gateway_submit.set_defaults(func=cmd_gateway_submit)

    gateway_complete = sub.add_parser(
        "gateway-complete",
        help="verify the observed target HEAD equals the deterministic publish commit and close the session",
    )
    gateway_complete.add_argument(
        "--target-remote-head",
        required=True,
        help="target branch HEAD observed after the Gateway has processed the request",
    )
    gateway_complete.set_defaults(func=cmd_gateway_complete)

    gateway_reconcile = sub.add_parser(
        "gateway-reconcile",
        help="repair a missed develop state handoff only when remote HEAD equals the deterministic expected publish commit",
    )
    gateway_reconcile.add_argument("--target-ref", required=True)
    gateway_reconcile.add_argument("--target-remote-head", required=True)
    gateway_reconcile.add_argument("--message")
    gateway_reconcile.set_defaults(func=cmd_gateway_reconcile)

    gateway_record = sub.add_parser(
        "gateway-record",
        help="verify the Gateway receipt for the active session and advance publish state",
    )
    gateway_record.add_argument("--receipt", required=True)
    gateway_record.set_defaults(func=cmd_gateway_record)

    gateway_status = sub.add_parser(
        "gateway-status",
        help="show recorded publish state and the active Gateway session without mutation",
    )
    gateway_status.set_defaults(func=cmd_gateway_status)

    gateway_abort = sub.add_parser(
        "gateway-abort",
        help="discard an unsubmitted or irrecoverably failed active Gateway session",
    )
    gateway_abort.add_argument("--request-id", required=True)
    gateway_abort.set_defaults(func=cmd_gateway_abort)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (PublishStateError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
