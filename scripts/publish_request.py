#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

STATE_NAME = "space-idle-publish-state.json"
REQUEST_VERSION = 6
RECEIPT_VERSION = 3
CONNECTOR_CALL_BUDGET_BYTES = 96 * 1024
MAX_BLOB_PARTS = 256
CONNECTOR_STATE_NAME = "connector-state.json"
CONNECTOR_SUMMARY_NAME = "summary.json"
PUBLISH_BUNDLE_REF = "refs/space-idle/publish-request"
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


def _changed_workflow_paths(repo: Path, base_commit: str, target_commit: str) -> list[str]:
    output = _git(
        "diff",
        "--name-only",
        base_commit,
        target_commit,
        "--",
        ".github/workflows",
        cwd=repo,
    )
    return [line for line in output.splitlines() if line.strip()]


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


def _verify_prepared_request(repo: Path, path: Path) -> dict[str, object]:
    state = _read_state(repo)
    request = _read_prepared_request(path)
    if request["base_sha"] != state["remote_commit"]:
        raise PublishStateError(
            "publish request base does not match recorded remote commit: "
            f"request={request['base_sha']} state={state['remote_commit']}"
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


def _payload_tree_path(index: int) -> str:
    return f"{index:04d}.b64"


def _git_tree_oid(repo: Path, blob_oids: list[str]) -> str:
    raw = bytearray()
    for index, oid in enumerate(blob_oids):
        _require_hex_sha(oid, name=f"payload blob oid {index}")
        raw.extend(b"100644 ")
        raw.extend(_payload_tree_path(index).encode("ascii"))
        raw.append(0)
        raw.extend(bytes.fromhex(oid))
    return _git_object_oid(repo, "tree", bytes(raw))


def _connector_payload_root_packet(
    repo: Path,
    github_repository: str,
    blob_oids: list[str],
) -> dict[str, object]:
    root_oid = _git_tree_oid(repo, blob_oids)
    return {
        "stage": "assemble-payload-root",
        "expected_tree_git_oid": root_oid,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": github_repository,
            "tree_elements": [
                {
                    "path": _payload_tree_path(index),
                    "mode": "100644",
                    "type": "blob",
                    "sha": oid,
                }
                for index, oid in enumerate(blob_oids)
            ],
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
            "publish an earlier coherent target-ref or revise the Connector profile in code with tests"
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


def cmd_prepare(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = _read_state(repo)
    target_commit = _git("rev-parse", f"{args.target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{args.target_ref}^{{tree}}", cwd=repo)
    if target_tree == state["remote_tree"]:
        raise PublishStateError("local target tree already matches the last published tree")
    workflow_paths = _changed_workflow_paths(repo, state["remote_commit"], target_commit)
    if workflow_paths:
        raise PublishStateError(
            "standard Publish Gateway cannot publish .github/workflows changes; "
            "use the separately authorized workflow-maintenance path: "
            + ", ".join(workflow_paths)
        )
    message_text = args.message if args.message is not None else _default_message(repo, state, args.target_ref)
    message = _message_bytes(message_text)
    publish_commit = _create_publish_commit(repo, state["remote_commit"], target_tree, message)
    payload_bytes = _bundle_bytes(repo, state["remote_commit"], publish_commit)
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    request = {
        "version": REQUEST_VERSION,
        "request_id": uuid.uuid4().hex,
        "target_branch": args.target_branch,
        "base_sha": state["remote_commit"],
        "target_tree": target_tree,
        "publish_commit": publish_commit,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload_encoding": "git-bundle-base64",
        "payload_b64": payload_b64,
        "local_target_commit": target_commit,
    }
    if not args.output:
        raise PublishStateError("prepare requires --output")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verified = _verify_prepared_request(repo, output)
    print(
        json.dumps(
            {
                "manifest": str(output),
                "request_id": request["request_id"],
                "remote_request_path": _request_file_path(str(request["request_id"])),
                "remote_receipt_path": _receipt_file_path(str(request["request_id"])),
                "transport": "git-bundle",
                "payload_bytes": len(payload_bytes),
                "payload_chars": len(payload_b64),
                "payload_sha256": request["payload_sha256"],
                "publish_commit": publish_commit,
                "target_tree": target_tree,
                "local_target_commit": target_commit,
                "working_tree_clean": _working_tree_clean(repo),
                "uncommitted_changes_excluded": not _working_tree_clean(repo),
                "verified": verified["verified"],
            },
            indent=2,
        )
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    verified = _verify_prepared_request(repo, Path(args.manifest).resolve())
    print(json.dumps(verified, indent=2))
    return 0


def _connector_state_path(output_dir: Path) -> Path:
    return output_dir / CONNECTOR_STATE_NAME


def _connector_summary_path(output_dir: Path) -> Path:
    return output_dir / CONNECTOR_SUMMARY_NAME


def _write_connector_state(output_dir: Path, state: dict[str, object]) -> None:
    _connector_state_path(output_dir).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _read_connector_state(output_dir: Path) -> dict[str, object]:
    path = _connector_state_path(output_dir)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishStateError(f"invalid Connector state: {exc}") from exc
    required = {
        "version",
        "stage",
        "manifest",
        "request_id",
        "github_repository",
        "publish_branch",
        "target_branch",
        "target_remote_head",
        "expected_blob_git_oids",
        "expected_payload_tree_git_oid",
        "upload_packets",
    }
    missing = required - state.keys()
    if missing:
        raise PublishStateError(f"invalid Connector state: missing fields {sorted(missing)}")
    if state["version"] != 1:
        raise PublishStateError(f"unsupported Connector state version: {state['version']}")
    if state["stage"] not in {"uploads-planned", "root-packet-ready", "submit-ready"}:
        raise PublishStateError(f"invalid Connector stage: {state['stage']}")
    if not isinstance(state["expected_blob_git_oids"], list) or not state["expected_blob_git_oids"]:
        raise PublishStateError("invalid Connector state: no payload blob OIDs")
    return state


def _write_connector_summary(output_dir: Path, summary: dict[str, object]) -> None:
    _connector_summary_path(output_dir).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _validate_connector_state_manifest(
    repo: Path, state: dict[str, object]
) -> dict[str, object]:
    manifest = Path(str(state["manifest"])).resolve()
    _verify_prepared_request(repo, manifest)
    prepared = _read_prepared_request(manifest)
    if prepared["request_id"] != state["request_id"]:
        raise PublishStateError("Connector state request id no longer matches its manifest")
    if prepared["target_branch"] != state["target_branch"]:
        raise PublishStateError("Connector state target branch no longer matches its manifest")
    if prepared["base_sha"] != state["target_remote_head"]:
        raise PublishStateError("Connector state remote base no longer matches its manifest")
    return prepared


def cmd_connector_plan(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    verified = _verify_prepared_request(repo, manifest)
    prepared = _read_prepared_request(manifest)
    _require_hex_sha(args.target_remote_head, name="target remote HEAD")
    if args.target_remote_head != prepared["base_sha"]:
        raise PublishStateError(
            "target branch HEAD moved since prepare: "
            f"expected={prepared['base_sha']} actual={args.target_remote_head}"
        )

    output_dir = Path(args.output_dir).resolve() if args.output_dir else Path(f"{manifest}.connector")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PublishStateError(
            f"Connector plan directory is already initialized: {output_dir}; "
            "continue its recorded stage instead of replanning transport"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = str(prepared["payload_b64"])
    parts = _split_payload_for_blob_calls(
        repo, args.github_repository, payload, CONNECTOR_CALL_BUDGET_BYTES
    )
    upload_packets: list[str] = []
    blob_oids: list[str] = []
    upload_call_bytes: list[int] = []
    for part in parts:
        packet_path = output_dir / f"upload-part-{int(part['index']):03d}.json"
        packet_path.write_text(
            json.dumps(part["packet"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        upload_packets.append(str(packet_path))
        blob_oids.append(str(part["oid"]))
        upload_call_bytes.append(int(part["packet_bytes"]))

    root_packet = _connector_payload_root_packet(repo, args.github_repository, blob_oids)
    root_call_bytes = _connector_call_bytes(root_packet)
    if root_call_bytes > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError(
            f"payload root tree needs a {root_call_bytes}-byte Connector call, exceeding "
            f"the fixed Connector profile {CONNECTOR_CALL_BUDGET_BYTES}-byte budget"
        )
    expected_root_oid = str(root_packet["expected_tree_git_oid"])

    state = {
        "version": 1,
        "stage": "uploads-planned",
        "manifest": str(manifest),
        "request_id": prepared["request_id"],
        "github_repository": args.github_repository,
        "publish_branch": args.publish_branch,
        "target_branch": prepared["target_branch"],
        "target_remote_head": args.target_remote_head,
        "expected_blob_git_oids": blob_oids,
        "expected_payload_tree_git_oid": expected_root_oid,
        "upload_packets": upload_packets,
    }
    _write_connector_state(output_dir, state)
    summary = {
        "stage": state["stage"],
        "strategy": "staged-blobs-root-then-request",
        "manifest": str(manifest),
        "request_id": prepared["request_id"],
        "github_repository": args.github_repository,
        "publish_branch": args.publish_branch,
        "target_branch": prepared["target_branch"],
        "target_remote_head": args.target_remote_head,
        "connector_profile": "github-connector-fixed",
        "connector_call_budget_bytes": CONNECTOR_CALL_BUDGET_BYTES,
        "call_size_basis": "compact-json-action-args",
        "upload_call_count": len(upload_packets),
        "upload_call_bytes": upload_call_bytes,
        "upload_packets": upload_packets,
        "payload_root_packet": None,
        "submit_request_packet": None,
        "expected_payload_tree_git_oid": expected_root_oid,
        "submit_deferred_until_root_verified": True,
        "normal_remote_target_probe_calls": 1,
        "root_tree_sha_verification_handoff_required": True,
        "request_verified": bool(verified["verified"]),
        "next": "execute every upload packet successfully, then run connector-root for this plan directory",
        "verified": True,
    }
    _write_connector_summary(output_dir, summary)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_connector_root(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    output_dir = Path(args.plan_dir).resolve()
    state = _read_connector_state(output_dir)
    if state["stage"] != "uploads-planned":
        raise PublishStateError(
            f"connector-root requires stage uploads-planned, found {state['stage']}"
        )
    _validate_connector_state_manifest(repo, state)
    blob_oids = [str(value) for value in state["expected_blob_git_oids"]]
    root_packet = _connector_payload_root_packet(
        repo, str(state["github_repository"]), blob_oids
    )
    if root_packet["expected_tree_git_oid"] != state["expected_payload_tree_git_oid"]:
        raise PublishStateError("Connector payload root OID changed from the recorded plan")
    root_call_bytes = _connector_call_bytes(root_packet)
    if root_call_bytes > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError(
            f"payload root tree needs a {root_call_bytes}-byte Connector call, exceeding "
            f"the fixed Connector profile {CONNECTOR_CALL_BUDGET_BYTES}-byte budget"
        )
    root_path = output_dir / "assemble-payload-root.json"
    root_path.write_text(
        json.dumps(root_packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    state["stage"] = "root-packet-ready"
    state["payload_root_packet"] = str(root_path)
    _write_connector_state(output_dir, state)
    summary = {
        "stage": state["stage"],
        "request_id": state["request_id"],
        "payload_root_packet": str(root_path),
        "expected_payload_tree_git_oid": state["expected_payload_tree_git_oid"],
        "root_tree_call_bytes": root_call_bytes,
        "submit_request_packet": None,
        "next": "execute the payload root packet; after success pass its returned tree SHA to connector-submit",
        "verified": True,
    }
    _write_connector_summary(output_dir, summary)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_connector_submit(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    output_dir = Path(args.plan_dir).resolve()
    state = _read_connector_state(output_dir)
    if state["stage"] != "root-packet-ready":
        raise PublishStateError(
            f"connector-submit requires stage root-packet-ready, found {state['stage']}"
        )
    prepared = _validate_connector_state_manifest(repo, state)
    _require_hex_sha(args.root_tree_sha, name="created payload root tree SHA")
    expected_root_oid = str(state["expected_payload_tree_git_oid"])
    if args.root_tree_sha != expected_root_oid:
        raise PublishStateError(
            "created payload root tree SHA does not match the precomputed root: "
            f"expected={expected_root_oid} actual={args.root_tree_sha}"
        )
    submit_request = _transport_request(
        prepared,
        {
            "kind": "git-tree",
            "oid": expected_root_oid,
            "part_count": len(state["expected_blob_git_oids"]),
        },
    )
    submit_packet = _connector_submit_packet(
        str(state["github_repository"]), str(state["publish_branch"]), submit_request
    )
    submit_call_bytes = _connector_call_bytes(submit_packet)
    if submit_call_bytes > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError(
            f"publish request metadata needs a {submit_call_bytes}-byte Connector call, exceeding "
            f"the fixed Connector profile {CONNECTOR_CALL_BUDGET_BYTES}-byte budget"
        )
    submit_path = output_dir / "submit-request.json"
    submit_path.write_text(
        json.dumps(submit_packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    state["stage"] = "submit-ready"
    state["submit_request_packet"] = str(submit_path)
    _write_connector_state(output_dir, state)
    summary = {
        "stage": state["stage"],
        "request_id": state["request_id"],
        "expected_payload_tree_git_oid": expected_root_oid,
        "root_tree_sha_verified": True,
        "submit_request_packet": str(submit_path),
        "submit_call_bytes": submit_call_bytes,
        "remote_request_path": _request_file_path(str(state["request_id"])),
        "remote_receipt_path": _receipt_file_path(str(state["request_id"])),
        "next": "execute the submit request packet once; Gateway owns all subsequent verification and publication",
        "verified": True,
    }
    _write_connector_summary(output_dir, summary)
    print(json.dumps(summary, indent=2))
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


def cmd_record(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = _read_state(repo)
    manifest = Path(args.manifest).resolve()
    verified = _verify_prepared_request(repo, manifest)
    request = _read_prepared_request(manifest)
    receipt = _read_publish_receipt(Path(args.receipt).resolve())
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
        "receipt_base_matches_recorded_remote": receipt["base_commit"] == state["remote_commit"],
        "receipt_base_matches_manifest": receipt["base_commit"] == request["base_sha"],
        "receipt_target_matches_manifest": receipt["target_tree"] == request["target_tree"],
        "published_commit_matches_manifest": receipt["published_commit"] == request["publish_commit"],
        "published_tree_matches_receipt_target": remote_tree == receipt["target_tree"],
        "published_tree_matches_local_tree": remote_tree == local_tree,
        "local_ref_matches_prepared_target": local_head == request["local_target_commit"],
        "remote_commit_advanced": remote_commit != state["remote_commit"],
    }
    checks.update(receipt_object_checks)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise PublishStateError("publish receipt verification failed: " + ", ".join(failed))
    _write_state(repo, remote_commit, remote_tree, local_head)
    print(
        json.dumps(
            {
                "remote_commit": remote_commit,
                "remote_tree": remote_tree,
                "local_head": local_head,
                "working_tree_clean": _working_tree_clean(repo),
                "uncommitted_changes_excluded": not _working_tree_clean(repo),
                "checks": checks,
                "verified": all(checks.values()),
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

    prepare = sub.add_parser("prepare", help="generate one verified Git bundle publish request")
    prepare.add_argument(
        "--target-branch",
        choices=("develop", "temp"),
        default="develop",
        help="develop is standard; temp is only for explicitly requested isolated validation",
    )
    prepare.add_argument("--target-ref", default="HEAD")
    prepare.add_argument("--message")
    prepare.add_argument("--output", required=True)
    prepare.set_defaults(func=cmd_prepare)

    connector_plan = sub.add_parser(
        "connector-plan",
        help="generate minimum-call Connector packets; Gateway performs commit/ref publication after verification",
    )
    connector_plan.add_argument("--manifest", required=True)
    connector_plan.add_argument("--github-repository", required=True)
    connector_plan.add_argument("--target-remote-head", required=True)
    connector_plan.add_argument("--publish-branch", default="publish")
    connector_plan.add_argument("--output-dir")
    connector_plan.set_defaults(func=cmd_connector_plan)

    connector_root = sub.add_parser(
        "connector-root",
        help="generate the payload root packet after all planned blob uploads succeeded",
    )
    connector_root.add_argument("--plan-dir", required=True)
    connector_root.set_defaults(func=cmd_connector_root)

    connector_submit = sub.add_parser(
        "connector-submit",
        help="generate the final request packet only after the payload root was created",
    )
    connector_submit.add_argument("--plan-dir", required=True)
    connector_submit.add_argument("--root-tree-sha", required=True)
    connector_submit.set_defaults(func=cmd_connector_submit)

    verify = sub.add_parser("verify", help="re-run local verification of a prepared request")
    verify.add_argument("--manifest", required=True)
    verify.set_defaults(func=cmd_verify)

    record = sub.add_parser("record", help="verify a Gateway receipt and advance recorded remote state")
    record.add_argument("--manifest", required=True)
    record.add_argument("--receipt", required=True)
    record.set_defaults(func=cmd_record)
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
