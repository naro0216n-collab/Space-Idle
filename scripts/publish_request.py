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
MAX_BLOB_PARTS = 256
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


def _connector_blob_packet(
    repo: Path,
    github_repository: str,
    content: str,
    index: int,
) -> dict[str, object]:
    oid = _git_object_oid(repo, "blob", content.encode("ascii"))
    return {
        "stage": "upload-payload-part",
        "part_index": index,
        "expected_blob_git_oid": oid,
        "action": "GitHub.create_blob",
        "action_args": {
            "repository_full_name": github_repository,
            "content": content,
            "encoding": "utf-8",
        },
    }


def _connector_call_bytes(packet: dict[str, object]) -> int:
    action_args = packet.get("action_args")
    if not isinstance(action_args, dict):
        raise PublishStateError("Connector packet is missing action_args")
    return len(json.dumps(action_args, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _split_payload_for_blob_calls(
    repo: Path,
    github_repository: str,
    payload: str,
    call_budget: int,
) -> list[dict[str, object]]:
    if call_budget <= 0:
        raise PublishStateError("Connector call budget must be positive")
    empty = _connector_blob_packet(repo, github_repository, "", 0)
    max_chars = call_budget - _connector_call_bytes(empty)
    if max_chars <= 0:
        raise PublishStateError(
            f"Connector call budget {call_budget} is too small even for an empty blob upload"
        )
    parts: list[dict[str, object]] = []
    for start in range(0, len(payload), max_chars):
        content = payload[start : start + max_chars]
        packet = _connector_blob_packet(repo, github_repository, content, len(parts))
        size = _connector_call_bytes(packet)
        if size > call_budget:
            raise PublishStateError(
                f"payload part {len(parts)} needs a {size}-byte Connector call, exceeding "
                f"the configured {call_budget}-byte budget"
            )
        parts.append(
            {
                "index": len(parts),
                "chars": len(content),
                "oid": packet["expected_blob_git_oid"],
                "packet_bytes": size,
                "packet": packet,
            }
        )
    if len(parts) > MAX_BLOB_PARTS:
        raise PublishStateError(
            f"publish payload needs {len(parts)} blob uploads, exceeding limit {MAX_BLOB_PARTS}; "
            "publish an earlier coherent target-ref or increase the verified Connector call budget"
        )
    return parts


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
    defer_submit_for_split: bool = False,
    always_blob: bool = False,
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
    for stale in output_dir.glob("upload-part-*.json"):
        stale.unlink()
    submit_path = output_dir / "submit-request.json"
    if submit_path.exists():
        submit_path.unlink()

    payload = str(prepared["payload_b64"])
    inline_request = _transport_request(prepared, {"kind": "inline", "data": payload})
    inline_packet = _connector_submit_packet(
        github_repository, publish_branch, inline_request
    )
    inline_call_bytes = _connector_call_bytes(inline_packet)
    upload_packets: list[str] = []
    blob_parts: list[dict[str, object]] = []

    if not always_blob and inline_call_bytes <= call_budget:
        strategy = "single-request-file"
        submit_packet = inline_packet
    else:
        strategy = (
            "verified-blobs-then-request-file"
            if always_blob
            else "parallel-blobs-then-request-file"
        )
        parts = _split_payload_for_blob_calls(
            repo, github_repository, payload, call_budget
        )
        for part in parts:
            packet_path = output_dir / f"upload-part-{int(part['index']):03d}.json"
            packet_path.write_text(
                json.dumps(part["packet"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            upload_packets.append(str(packet_path))
            blob_parts.append({"oid": part["oid"], "chars": part["chars"]})
        if defer_submit_for_split:
            submit_packet = None
        else:
            submit_request = _transport_request(
                prepared, {"kind": "git-blobs", "parts": blob_parts}
            )
            submit_packet = _connector_submit_packet(
                github_repository, publish_branch, submit_request
            )
            submit_bytes = _connector_call_bytes(submit_packet)
            if submit_bytes > call_budget:
                raise PublishStateError(
                    f"publish request metadata needs a {submit_bytes}-byte Connector call, exceeding "
                    f"the configured {call_budget}-byte budget"
                )

    if submit_packet is not None:
        submit_path.write_text(
            json.dumps(submit_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        submit_call_bytes = _connector_call_bytes(submit_packet)
        submit_packet_path: str | None = str(submit_path)
    else:
        if submit_path.exists():
            submit_path.unlink()
        submit_call_bytes = 0
        submit_packet_path = None
    upload_call_count = len(upload_packets)
    summary = {
        "strategy": strategy,
        "manifest": str(manifest),
        "request_id": prepared["request_id"],
        "github_repository": github_repository,
        "publish_branch": publish_branch,
        "target_branch": prepared["target_branch"],
        "target_remote_head": target_remote_head,
        "connector_call_budget_bytes": call_budget,
        "inline_submit_call_bytes": inline_call_bytes,
        "submit_call_bytes": submit_call_bytes,
        "call_size_basis": "compact-json-action-args",
        "upload_call_count": upload_call_count,
        "upload_packets": upload_packets,
        "uploads_are_independent": bool(upload_packets),
        "connector_uploads_may_run_in_parallel": bool(upload_packets),
        "returned_upload_blob_shas_are_required": bool(always_blob and upload_packets),
        "returned_upload_blob_shas_are_not_required": bool(upload_packets and not always_blob),
        "submit_request_packet": submit_packet_path,
        "submit_deferred_until_upload_phase_complete": bool(
            defer_submit_for_split and upload_packets
        ),
        "remote_request_path": _request_file_path(str(prepared["request_id"])),
        "remote_receipt_path": _receipt_file_path(str(prepared["request_id"])),
        "normal_remote_target_probe_calls": 1,
        "normal_publish_transport_probe_calls": 0,
        "normal_github_mutation_calls": upload_call_count + 1,
        "normal_github_calls_before_gateway": upload_call_count + 2,
        "normal_sha_handoffs": 0,
        "normal_per_upload_verification_calls": 0,
        "gateway_completes_target_publish": True,
        "next_after_transport": (
            "execute submit-request.json; the Gateway validates the request and publishes the exact target commit automatically"
            if not upload_packets
            else (
                "execute all upload-part packets, then pass their returned blob SHAs to gateway-submit; the helper verifies exact upload identity before generating the final request action"
                if defer_submit_for_split
                else "execute all upload-part packets in parallel, then submit-request.json; returned blob SHAs are not inputs to later steps and the Gateway validates OIDs before publishing"
            )
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
        "payload_parts",
        "next_packet_index",
    }
    missing = required - data.keys()
    if missing:
        raise PublishStateError(
            f"invalid active Gateway publish session: missing fields {sorted(missing)}"
        )
    if data["version"] != 2:
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
        "part_index": packet.get("part_index"),
    }


def cmd_gateway_begin(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    active_dir = _active_session_dir(repo)
    if _active_session_path(repo).exists():
        active = _read_active_session(repo)
        raise PublishStateError(
            "an active Gateway publish session already exists: "
            f"request_id={active['request_id']} phase={active['phase']}; "
            "continue it through gateway-refine/gateway-submit/gateway-complete or inspect it with gateway-status"
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
        defer_submit_for_split=True,
        always_blob=True,
    )
    prepared = _read_prepared_request(manifest)
    phase = "upload-payload-parts"
    connector_actions = [
        _packet_action_summary(path) for path in list(plan["upload_packets"])
    ]
    next_helper_command = (
        "python scripts/publish_request.py gateway-submit "
        "--uploaded-blob-sha <SHA returned by each create_blob action>"
    )
    session = {
        "version": 2,
        "request_id": prepared["request_id"],
        "manifest": str(manifest),
        "connector_dir": str(connector_dir),
        "strategy": plan["strategy"],
        "phase": phase,
        "target_branch": prepared["target_branch"],
        "base_sha": prepared["base_sha"],
        "target_tree": prepared["target_tree"],
        "publish_commit": prepared["publish_commit"],
        "local_target_commit": prepared["local_target_commit"],
        "remote_request_path": plan["remote_request_path"],
        "remote_receipt_path": plan["remote_receipt_path"],
        "upload_packets": list(plan["upload_packets"]),
        "payload_parts": [
            {
                "packet": path,
                "oid": json.loads(Path(path).read_text(encoding="utf-8"))["expected_blob_git_oid"],
                "chars": len(json.loads(Path(path).read_text(encoding="utf-8"))["action_args"]["content"]),
                "confirmed_sha": None,
            }
            for path in list(plan["upload_packets"])
        ],
        "next_packet_index": len(list(plan["upload_packets"])),
        "submit_request_packet": plan["submit_request_packet"],
    }
    _write_active_session(repo, session)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-begin",
                "session": str(_active_session_path(repo)),
                "request_id": prepared["request_id"],
                "strategy": plan["strategy"],
                "phase": phase,
                "target_branch": prepared["target_branch"],
                "target_remote_head": target_remote_head,
                "target_tree": prepared["target_tree"],
                "local_target_commit": prepared["local_target_commit"],
                "initial_connector_action_budget_bytes": DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
                "adaptive_split_on_blob_sha_mismatch": True,
                "metadata_call_budget_bytes": DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
                "connector_actions": connector_actions,
                "connector_action_selection_is_not_a_decision": True,
                "execute_packet_action_exactly": True,
                "bridge_refinement_command": "python scripts/publish_request.py gateway-refine",
                "bridge_refinement_condition": (
                    "use only when the current helper packet cannot be faithfully forwarded "
                    "before any Connector write"
                ),
                "next_helper_command": next_helper_command,
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


def _split_payload_part(
    repo: Path,
    *,
    github_repository: str,
    part: dict[str, object],
    next_packet_index: int,
    connector_dir: Path,
) -> tuple[list[dict[str, object]], int]:
    packet_path = Path(str(part["packet"]))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    args_data = packet.get("action_args")
    content = args_data.get("content") if isinstance(args_data, dict) else None
    if not isinstance(content, str) or len(content) <= 1:
        raise PublishStateError(
            "payload part cannot be split further; stop and inspect the Connector transport"
        )
    midpoint = len(content) // 2
    children: list[dict[str, object]] = []
    for child_content in (content[:midpoint], content[midpoint:]):
        index = next_packet_index
        next_packet_index += 1
        child_packet = _connector_blob_packet(repo, github_repository, child_content, index)
        child_path = connector_dir / f"upload-part-{index:03d}.json"
        child_path.write_text(
            json.dumps(child_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        children.append(
            {
                "packet": str(child_path),
                "oid": child_packet["expected_blob_git_oid"],
                "chars": len(child_content),
                "confirmed_sha": None,
            }
        )
    return children, next_packet_index


def cmd_gateway_refine(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = _read_active_session(repo)
    if session["strategy"] not in {
        "verified-blobs-then-request-file",
        "parallel-blobs-then-request-file",
    }:
        raise PublishStateError("gateway-refine requires a blob-upload Gateway session")
    if session["phase"] != "upload-payload-parts":
        raise PublishStateError(
            "gateway-refine is only valid before the final request action is generated"
        )

    payload_parts = session.get("payload_parts")
    if not isinstance(payload_parts, list) or not payload_parts:
        raise PublishStateError("active Gateway session is missing ordered payload parts")
    pending_parts = [
        part
        for part in payload_parts
        if isinstance(part, dict) and part.get("confirmed_sha") is None
    ]
    if not pending_parts:
        raise PublishStateError("no unconfirmed payload part remains to refine")

    # Keep bridge-capability handling deterministic. The operator neither chooses
    # a boundary nor supplies a size threshold: refine only the largest pending
    # helper-owned part, preserving every already-confirmed part unchanged.
    selected = max(
        pending_parts,
        key=lambda part: (int(part.get("chars", 0)), str(part.get("packet", ""))),
    )
    connector_dir = Path(str(session["connector_dir"]))
    next_packet_index = int(session.get("next_packet_index", len(payload_parts)))
    children, next_packet_index = _split_payload_part(
        repo,
        github_repository=GITHUB_REPOSITORY,
        part=selected,
        next_packet_index=next_packet_index,
        connector_dir=connector_dir,
    )

    rebuilt: list[dict[str, object]] = []
    selected_packet = str(selected["packet"])
    for part in payload_parts:
        if not isinstance(part, dict):
            raise PublishStateError("invalid ordered payload part in active Gateway session")
        if str(part.get("packet")) == selected_packet:
            rebuilt.extend(children)
        else:
            rebuilt.append(part)
    pending_paths = [
        str(part["packet"])
        for part in rebuilt
        if part.get("confirmed_sha") is None
    ]
    session["payload_parts"] = rebuilt
    session["upload_packets"] = pending_paths
    session["next_packet_index"] = next_packet_index
    _write_active_session(repo, session)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-refine",
                "request_id": session["request_id"],
                "phase": "upload-payload-parts",
                "refined_pending_parts": 1,
                "verified_upload_parts": sum(
                    1 for part in rebuilt if part.get("confirmed_sha") is not None
                ),
                "connector_actions": [
                    _packet_action_summary(path) for path in pending_paths
                ],
                "connector_action_selection_is_not_a_decision": True,
                "execute_packet_action_exactly": True,
                "request_action_generated": False,
                "remote_mutation_performed": False,
                "note": (
                    "Use this only when the execution bridge cannot faithfully forward the current "
                    "helper packet. The helper chooses the part and split boundary; no fixed bridge "
                    "size or intentionally corrupted upload is required."
                ),
                "next_helper_command": (
                    "execute the emitted GitHub.create_blob actions exactly, then run "
                    "gateway-submit with their returned blob SHAs"
                ),
                "verified": True,
            },
            indent=2,
        )
    )
    return 0


def cmd_gateway_submit(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session = _read_active_session(repo)
    if session["strategy"] not in {
        "verified-blobs-then-request-file",
        "parallel-blobs-then-request-file",
    }:
        raise PublishStateError("gateway-submit requires a blob-upload Gateway session")
    if session["phase"] not in {"upload-payload-parts", "submit-request"}:
        raise PublishStateError(f"invalid Gateway publish phase: {session['phase']}")

    if session["phase"] == "submit-request":
        raise PublishStateError(
            "payload uploads are already verified and the final request action has been generated"
        )

    payload_parts = session.get("payload_parts")
    if not isinstance(payload_parts, list) or not payload_parts:
        raise PublishStateError("active Gateway session is missing ordered payload parts")
    pending_parts = [
        part for part in payload_parts
        if isinstance(part, dict) and part.get("confirmed_sha") is None
    ]
    provided_upload_oids = [str(value).lower() for value in args.uploaded_blob_sha]
    if len(provided_upload_oids) != len(pending_parts):
        raise PublishStateError(
            "uploaded blob SHA count does not match the current helper-generated upload actions; "
            f"expected={len(pending_parts)} actual={len(provided_upload_oids)}"
        )
    for oid in provided_upload_oids:
        _require_hex_sha(oid, name="uploaded blob SHA")

    connector_dir = Path(str(session["connector_dir"]))
    next_packet_index = int(session.get("next_packet_index", len(payload_parts)))
    replacement_by_packet: dict[str, list[dict[str, object]]] = {}
    mismatches = 0
    for part, actual_oid in zip(pending_parts, provided_upload_oids, strict=True):
        expected_oid = str(part.get("oid", "")).lower()
        _require_hex_sha(expected_oid, name="expected upload blob SHA")
        if actual_oid == expected_oid:
            part["confirmed_sha"] = actual_oid
            continue
        mismatches += 1
        children, next_packet_index = _split_payload_part(
            repo,
            github_repository=GITHUB_REPOSITORY,
            part=part,
            next_packet_index=next_packet_index,
            connector_dir=connector_dir,
        )
        replacement_by_packet[str(part["packet"])] = children

    if mismatches:
        rebuilt: list[dict[str, object]] = []
        for part in payload_parts:
            if not isinstance(part, dict):
                raise PublishStateError("invalid ordered payload part in active Gateway session")
            replacement = replacement_by_packet.get(str(part.get("packet")))
            if replacement is not None:
                rebuilt.extend(replacement)
            else:
                rebuilt.append(part)
        payload_parts = rebuilt
        pending_paths = [
            str(part["packet"])
            for part in payload_parts
            if part.get("confirmed_sha") is None
        ]
        session["payload_parts"] = payload_parts
        session["upload_packets"] = pending_paths
        session["next_packet_index"] = next_packet_index
        _write_active_session(repo, session)
        print(
            json.dumps(
                {
                    "entrypoint": "gateway-submit",
                    "request_id": session["request_id"],
                    "phase": "upload-payload-parts",
                    "verified_upload_parts": sum(
                        1 for part in payload_parts if part.get("confirmed_sha") is not None
                    ),
                    "resplit_mismatched_parts": mismatches,
                    "connector_actions": [
                        _packet_action_summary(path) for path in pending_paths
                    ],
                    "connector_action_selection_is_not_a_decision": True,
                    "execute_packet_action_exactly": True,
                    "next_helper_command": (
                        "python scripts/publish_request.py gateway-submit "
                        "--uploaded-blob-sha <SHA returned by each newly emitted create_blob action>"
                    ),
                    "request_action_generated": False,
                    "verified": True,
                },
                indent=2,
            )
        )
        return 0

    if any(part.get("confirmed_sha") is None for part in payload_parts):
        raise PublishStateError("not all payload parts are verified")

    manifest = Path(str(session["manifest"]))
    prepared = _read_prepared_request(manifest)
    blob_parts = [
        {"oid": str(part["oid"]), "chars": int(part["chars"])}
        for part in payload_parts
    ]
    submit_request = _transport_request(
        prepared, {"kind": "git-blobs", "parts": blob_parts}
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
    submit_path = connector_dir / "submit-request.json"
    submit_path.write_text(
        json.dumps(submit_packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    session["phase"] = "submit-request"
    session["submit_request_packet"] = str(submit_path)
    session["upload_packets"] = []
    session["payload_parts"] = payload_parts
    _write_active_session(repo, session)
    print(
        json.dumps(
            {
                "entrypoint": "gateway-submit",
                "request_id": session["request_id"],
                "phase": "submit-request",
                "verified_payload_part_count": len(payload_parts),
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
            "Gateway request has not reached submit-request phase; verify payload uploads "
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
            "finish payload uploads with gateway-submit first"
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
            "verify Connector-returned blob SHAs; re-split only mismatched payload parts, "
            "and emit the final small request action only after every part is confirmed"
        ),
    )
    gateway_submit.add_argument(
        "--uploaded-blob-sha",
        action="append",
        required=True,
        help="blob SHA returned by each helper-specified GitHub.create_blob action; repeat once per upload",
    )
    gateway_submit.set_defaults(func=cmd_gateway_submit)

    gateway_refine = sub.add_parser(
        "gateway-refine",
        help=(
            "split the largest unconfirmed upload part when the execution bridge cannot faithfully "
            "forward the current helper packet; performs no Connector write"
        ),
    )
    gateway_refine.set_defaults(func=cmd_gateway_refine)

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
