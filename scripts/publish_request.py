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
from urllib.parse import unquote, urlparse

STATE_NAME = "space-idle-publish-state.json"
WORKFLOW_REHYDRATE_MARKER_NAME = "space-idle-workflow-maintenance-rehydrate-required"
REQUEST_VERSION = 7
RECEIPT_VERSION = 3
CONNECTOR_CALL_BUDGET_BYTES = 144 * 1024
CONNECTOR_HANDOFF_ELEMENT_CHARS = 6 * 1024
MAX_PAYLOAD_PARTS = 256
CONNECTOR_STATE_NAME = "connector-state.json"
CONNECTOR_STATE_VERSION = 8
PAYLOAD_INDEX_VERSION = 1
MAX_TRANSPORT_ATTEMPTS = 3
CONNECTOR_SUMMARY_NAME = "summary.json"
TRANSACTION_DIR_NAME = "space-idle-publish-transaction"
WORKFLOW_TRANSACTION_DIR_NAME = "space-idle-workflow-maintenance-transaction"
MANIFEST_NAME = "manifest.json"
CONNECTOR_DIR_NAME = "connector"
PUBLISH_BUNDLE_REF = "refs/space-idle/publish-request"
PUBLISH_IDENTITY_NAME = "space-idle-publish-gateway"
PUBLISH_IDENTITY_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
PUBLISH_COMMIT_DATE = "946684800 +0000"
GITHUB_REPOSITORY = "naro0216n-collab/Space-Idle"
PUBLISH_BRANCH = "publish"
TARGET_BRANCH = "develop"
TRUSTED_CONTROL_WORKFLOW = ".github/workflows/publish-gateway.yml"


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


def _repo_from_cwd() -> Path:
    cwd = Path.cwd().resolve()
    return Path(_git("rev-parse", "--show-toplevel", cwd=cwd)).resolve()


def _transaction_dir(repo: Path) -> Path:
    return _git_dir(repo) / TRANSACTION_DIR_NAME


def _manifest_path(repo: Path) -> Path:
    return _transaction_dir(repo) / MANIFEST_NAME


def _connector_dir(repo: Path) -> Path:
    return _transaction_dir(repo) / CONNECTOR_DIR_NAME


def _require_no_active_transaction(repo: Path) -> None:
    transaction = _transaction_dir(repo)
    if transaction.exists() and any(transaction.iterdir()):
        raise PublishStateError(
            "an active publish transaction already exists; finish or record it before preparing another"
        )


def _read_state(repo: Path) -> dict[str, str]:
    marker = _git_dir(repo) / WORKFLOW_REHYDRATE_MARKER_NAME
    if marker.exists():
        raise PublishStateError(
            "workflow maintenance updated develop; restore the latest source-snapshot and run init before normal publish"
        )
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


def _default_message(repo: Path, state: dict[str, str], target_commit: str) -> str:
    local_head = state["local_head"]
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", local_head, target_commit],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if is_ancestor:
        commits = _git("rev-list", "--reverse", f"{local_head}..{target_commit}", cwd=repo).splitlines()
        if len(commits) == 1:
            return _git("show", "-s", "--format=%B", commits[0], cwd=repo).rstrip() + "\n"
    return _git("show", "-s", "--format=%B", target_commit, cwd=repo).rstrip() + "\n"


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
    if data["version"] not in {6, REQUEST_VERSION}:
        raise PublishStateError(f"unsupported prepared request version: {data['version']}")
    request_id = data["request_id"]
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise PublishStateError("invalid prepared request id")
    try:
        int(request_id, 16)
    except ValueError as exc:
        raise PublishStateError("invalid prepared request id") from exc
    if data["target_branch"] != TARGET_BRANCH:
        raise PublishStateError("invalid prepared target branch; standard publish targets develop only")
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


def _retry_request_file_path(request_id: str, generation: int) -> str:
    return f".publish/retries/{request_id}/g{generation:04d}.json"


def _receipt_file_path(request_id: str) -> str:
    return f".publish/receipts/{request_id}.json"


def _payload_generation_name(generation: int) -> str:
    if generation < 0:
        raise PublishStateError("payload generation must be non-negative")
    return f"g{generation:04d}"


def _payload_part_name(index: int) -> str:
    if index < 0:
        raise PublishStateError("payload part index must be non-negative")
    return f"{index:04d}.b64"


def _payload_file_path(request_id: str, generation: int, index: int) -> str:
    return (
        f".publish/payloads/{request_id}/"
        f"{_payload_generation_name(generation)}/{_payload_part_name(index)}"
    )


def _payload_index_path(request_id: str, generation: int) -> str:
    return f".publish/payloads/{request_id}/index-{generation:04d}.json"


def _connector_call_bytes(packet: dict[str, object]) -> int:
    action_args = packet.get("action_args")
    if not isinstance(action_args, dict):
        raise PublishStateError("Connector packet is missing action_args")
    return len(json.dumps(action_args, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _payload_parts_for_tree(
    repo: Path,
    request_id: str,
    generation: int,
    payload: str,
    *,
    handoff_element_chars: int = CONNECTOR_HANDOFF_ELEMENT_CHARS,
) -> list[dict[str, object]]:
    if handoff_element_chars <= 0:
        raise PublishStateError("Connector handoff element size must be positive")
    parts: list[dict[str, object]] = []
    for start in range(0, len(payload), handoff_element_chars):
        content = payload[start : start + handoff_element_chars]
        index = len(parts)
        remote_path = _payload_file_path(request_id, generation, index)
        parts.append(
            {
                "index": index,
                "chars": len(content),
                "oid": _git_object_oid(repo, "blob", content.encode("utf-8")),
                "remote_path": remote_path,
                "content": content,
            }
        )
    if not parts:
        raise PublishStateError("publish payload is empty")
    if len(parts) > MAX_PAYLOAD_PARTS:
        raise PublishStateError(
            f"publish payload needs {len(parts)} handoff fields, exceeding limit {MAX_PAYLOAD_PARTS}; "
            "publish an earlier coherent target-ref or revise the transport design"
        )
    return parts


def _payload_index_document(
    prepared: dict[str, object],
    request_id: str,
    generation: int,
    parts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "version": PAYLOAD_INDEX_VERSION,
        "request_id": request_id,
        "generation": generation,
        "payload_chars": len(str(prepared["payload_b64"])),
        "payload_sha256": prepared["payload_sha256"],
        "part_count": len(parts),
        "parts": [
            {
                "index": int(part["index"]),
                "path": (
                    f"{_payload_generation_name(generation)}/"
                    f"{_payload_part_name(int(part['index']))}"
                ),
                "chars": int(part["chars"]),
                "blob_git_oid": str(part["oid"]),
            }
            for part in parts
        ],
    }


def _tree_content_element(path: str, content: str) -> dict[str, str]:
    return {
        "path": path,
        "mode": "100644",
        "type": "blob",
        "content": content,
    }


def _generation_tree_packet(
    *,
    base_tree: str,
    elements: list[dict[str, str]],
    generation: int,
    batch_index: int,
) -> dict[str, object]:
    return {
        "stage": "assemble-publish-generation-tree",
        "generation": generation,
        "tree_batch_index": batch_index,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "base_tree_sha": base_tree,
            "tree_elements": elements,
        },
    }


def _pack_tree_elements(
    elements: list[dict[str, str]],
    *,
    generation: int,
) -> list[list[dict[str, str]]]:
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    dummy_base = "0" * 40
    for element in elements:
        candidate = [*current, element]
        packet = _generation_tree_packet(
            base_tree=dummy_base,
            elements=candidate,
            generation=generation,
            batch_index=len(batches),
        )
        if _connector_call_bytes(packet) <= CONNECTOR_CALL_BUDGET_BYTES:
            current = candidate
            continue
        if not current:
            raise PublishStateError(
                f"single inline tree element at {element['path']} exceeds the fixed "
                f"{CONNECTOR_CALL_BUDGET_BYTES}-byte Connector ceiling"
            )
        batches.append(current)
        current = [element]
        single = _generation_tree_packet(
            base_tree=dummy_base,
            elements=current,
            generation=generation,
            batch_index=len(batches),
        )
        if _connector_call_bytes(single) > CONNECTOR_CALL_BUDGET_BYTES:
            raise PublishStateError(
                f"single inline tree element at {element['path']} exceeds the fixed "
                f"{CONNECTOR_CALL_BUDGET_BYTES}-byte Connector ceiling"
            )
    if current:
        batches.append(current)
    return batches


def _write_tree_batch_packet(
    output_dir: Path,
    generation: dict[str, object],
    batch_index: int,
    base_tree: str,
) -> dict[str, object]:
    batches = generation.get("tree_batches")
    if not isinstance(batches, list) or not (0 <= batch_index < len(batches)):
        raise PublishStateError("Connector generation tree batch index is invalid")
    elements = batches[batch_index]
    if not isinstance(elements, list) or not elements:
        raise PublishStateError("Connector generation tree batch is empty")
    generation_number = int(generation["generation"])
    packet = _generation_tree_packet(
        base_tree=base_tree,
        elements=elements,
        generation=generation_number,
        batch_index=batch_index,
    )
    call_bytes = _connector_call_bytes(packet)
    if call_bytes > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError(
            f"publish generation tree batch {batch_index} needs a {call_bytes}-byte Connector call, "
            f"exceeding the fixed Connector ceiling {CONNECTOR_CALL_BUDGET_BYTES}-byte budget"
        )
    prefix = f"g{generation_number:04d}-tree-batch-{batch_index:03d}"
    packet_path = output_dir / f"{prefix}.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    header_path = output_dir / f"{prefix}-header.json"
    header_path.write_text(
        json.dumps(
            {
                "repository_full_name": GITHUB_REPOSITORY,
                "base_tree_sha": base_tree,
                "tree_element_count": len(elements),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    element_paths: list[str] = []
    for element_index, element in enumerate(elements):
        element_path = output_dir / f"{prefix}-element-{element_index:03d}.json"
        element_path.write_text(
            json.dumps(element, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        element_paths.append(str(element_path))
    return {
        "packet": str(packet_path),
        "header": str(header_path),
        "elements": element_paths,
        "call_bytes": call_bytes,
        "batch_index": batch_index,
        "batch_count": len(batches),
    }


def _generation_plan(
    repo: Path,
    prepared: dict[str, object],
    generation: int,
    *,
    base_publish_head: str,
    base_publish_tree: str,
    retry: bool,
    handoff_element_chars: int = CONNECTOR_HANDOFF_ELEMENT_CHARS,
) -> dict[str, object]:
    request_id = str(prepared["request_id"])
    payload = str(prepared["payload_b64"])
    parts = _payload_parts_for_tree(
        repo,
        request_id,
        generation,
        payload,
        handoff_element_chars=handoff_element_chars,
    )
    elements: list[dict[str, str]] = [
        _tree_content_element(str(part["remote_path"]), str(part["content"]))
        for part in parts
    ]

    index = _payload_index_document(prepared, request_id, generation, parts)
    index_content = json.dumps(index, separators=(",", ":"), sort_keys=True) + "\n"
    index_path = _payload_index_path(request_id, generation)
    elements.append(_tree_content_element(index_path, index_content))

    request = _v7_transport_request_for_generation(prepared, generation)
    trigger_content = json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n"
    trigger_path = (
        _retry_request_file_path(request_id, generation)
        if retry
        else _request_file_path(request_id)
    )
    elements.append(_tree_content_element(trigger_path, trigger_content))

    batches = _pack_tree_elements(elements, generation=generation)
    return {
        "generation": generation,
        "retry": retry,
        "base_publish_head": base_publish_head,
        "base_publish_tree": base_publish_tree,
        "payload_part_count": len(parts),
        "payload_handoff_element_chars": handoff_element_chars,
        "expected_payload_blob_git_oids": [str(part["oid"]) for part in parts],
        "expected_payload_chars": [int(part["chars"]) for part in parts],
        "remote_payload_paths": [str(part["remote_path"]) for part in parts],
        "remote_index_path": index_path,
        "expected_index_blob_git_oid": _git_object_oid(repo, "blob", index_content.encode("utf-8")),
        "trigger_path": trigger_path,
        "expected_trigger_blob_git_oid": _git_object_oid(repo, "blob", trigger_content.encode("utf-8")),
        "tree_batches": batches,
        "tree_batch_call_count": len(batches),
    }


def _source_snapshot_from_origin(repo: Path) -> Path:
    try:
        origin = _git("remote", "get-url", "origin", cwd=repo)
    except subprocess.CalledProcessError as exc:
        raise PublishStateError(
            "restored repository has no readable origin; restore it from source-snapshot/repository.bundle"
        ) from exc

    if origin.startswith("file://"):
        parsed = urlparse(origin)
        if parsed.netloc not in {"", "localhost"}:
            raise PublishStateError(
                "origin must be the local source-snapshot repository.bundle, not a remote file URL"
            )
        bundle_path = Path(unquote(parsed.path))
    else:
        if "://" in origin or (":" in origin and not Path(origin).is_absolute()):
            raise PublishStateError(
                "origin must point to the local source-snapshot repository.bundle"
            )
        bundle_path = Path(origin)

    if not bundle_path.is_absolute():
        bundle_path = (repo / bundle_path).resolve()
    else:
        bundle_path = bundle_path.resolve()
    if bundle_path.name != "repository.bundle" or not bundle_path.is_file():
        raise PublishStateError(
            "origin must point to an existing source-snapshot/repository.bundle"
        )
    return bundle_path.parent


def _read_source_snapshot_metadata(source_snapshot: Path, *, repo: Path) -> tuple[str, str]:
    source_snapshot = source_snapshot.resolve()
    commit_path = source_snapshot / ".source-commit"
    tree_path = source_snapshot / ".source-tree"
    branch_path = source_snapshot / ".source-branch"
    bundle_path = source_snapshot / "repository.bundle"
    missing = [
        str(path.name)
        for path in (commit_path, tree_path, branch_path, bundle_path)
        if not path.is_file()
    ]
    if missing:
        raise PublishStateError(
            "source-snapshot directory is incomplete; missing: " + ", ".join(missing)
        )
    remote_commit = commit_path.read_text(encoding="utf-8").strip()
    remote_tree = tree_path.read_text(encoding="utf-8").strip()
    branch = branch_path.read_text(encoding="utf-8").strip()
    _require_hex_sha(remote_commit, name="source-snapshot commit")
    _require_hex_sha(remote_tree, name="source-snapshot tree")
    if branch != TARGET_BRANCH:
        raise PublishStateError(
            f"source-snapshot branch must be {TARGET_BRANCH!r}, got {branch!r}"
        )
    verify = subprocess.run(
        ["git", "bundle", "verify", str(bundle_path)],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if verify.returncode != 0:
        raise PublishStateError(
            "source-snapshot bundle verification failed: " + verify.stderr.strip()
        )
    heads = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle_path)],
        cwd=source_snapshot,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.splitlines()
    expected_head = f"{remote_commit} refs/heads/{TARGET_BRANCH}"
    if expected_head not in heads:
        raise PublishStateError(
            "source-snapshot metadata does not match repository.bundle develop head"
        )
    return remote_commit, remote_tree


def cmd_init(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    source_snapshot = _source_snapshot_from_origin(repo)
    remote_commit, remote_tree = _read_source_snapshot_metadata(source_snapshot, repo=repo)
    local_branch = _git("branch", "--show-current", cwd=repo)
    local_commit = _git("rev-parse", "HEAD^{commit}", cwd=repo)
    local_tree = _git("rev-parse", "HEAD^{tree}", cwd=repo)
    if local_branch != TARGET_BRANCH:
        raise PublishStateError(
            f"restored repository branch must be {TARGET_BRANCH!r}, got {local_branch!r}"
        )
    if local_commit != remote_commit:
        raise PublishStateError(
            f"artifact/local commit mismatch: local={local_commit} artifact={remote_commit}"
        )
    if local_tree != remote_tree:
        raise PublishStateError(
            f"artifact/local tree mismatch: local={local_tree} artifact={remote_tree}"
        )
    _write_state(repo, remote_commit, remote_tree, local_commit)
    transaction = _transaction_dir(repo)
    if transaction.exists():
        shutil.rmtree(transaction)
    workflow_transaction = _git_dir(repo) / WORKFLOW_TRANSACTION_DIR_NAME
    if workflow_transaction.exists():
        shutil.rmtree(workflow_transaction)
    marker = _git_dir(repo) / WORKFLOW_REHYDRATE_MARKER_NAME
    if marker.exists():
        marker.unlink()
    print(json.dumps({"remote_commit": remote_commit, "remote_tree": remote_tree, "local_head": local_commit}, indent=2))
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_state(repo)
    _require_no_active_transaction(repo)
    target_commit = _git("rev-parse", "HEAD^{commit}", cwd=repo)
    target_tree = _git("rev-parse", "HEAD^{tree}", cwd=repo)
    if target_tree == state["remote_tree"]:
        raise PublishStateError("local target tree already matches the last published tree")
    workflow_paths = _changed_workflow_paths(repo, state["remote_commit"], target_commit)
    disallowed_workflow_paths = [
        path for path in workflow_paths if path != TRUSTED_CONTROL_WORKFLOW
    ]
    if disallowed_workflow_paths:
        raise PublishStateError(
            "standard Publish Gateway cannot publish untrusted .github/workflows changes; "
            "use `python scripts/workflow_maintenance.py prepare` for workflow-only maintenance: "
            + ", ".join(disallowed_workflow_paths)
        )
    message = _message_bytes(_default_message(repo, state, target_commit))
    publish_commit = _create_publish_commit(repo, state["remote_commit"], target_tree, message)
    payload_bytes = _bundle_bytes(repo, state["remote_commit"], publish_commit)
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    request = {
        "version": REQUEST_VERSION,
        "request_id": uuid.uuid4().hex,
        "target_branch": TARGET_BRANCH,
        "base_sha": state["remote_commit"],
        "target_tree": target_tree,
        "publish_commit": publish_commit,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload_encoding": "git-bundle-base64",
        "payload_b64": payload_b64,
        "local_target_commit": target_commit,
    }
    output = _manifest_path(repo)
    output.parent.mkdir(parents=True, exist_ok=False)
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


def _connector_state_path(output_dir: Path) -> Path:
    return output_dir / CONNECTOR_STATE_NAME


def _connector_summary_path(output_dir: Path) -> Path:
    return output_dir / CONNECTOR_SUMMARY_NAME


def _write_connector_state(output_dir: Path, state: dict[str, object]) -> None:
    _connector_state_path(output_dir).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_connector_summary(output_dir: Path, summary: dict[str, object]) -> None:
    _connector_summary_path(output_dir).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _read_connector_state(repo: Path) -> dict[str, object]:
    path = _connector_state_path(_connector_dir(repo))
    if not path.is_file():
        raise PublishStateError(
            "Connector plan is not initialized; run connector-plan before continuing transport"
        )
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishStateError(f"invalid Connector state: {exc}") from exc
    if state.get("version") != CONNECTOR_STATE_VERSION:
        raise PublishStateError("unsupported Connector state version")
    if state.get("stage") not in {
        "tree-ready",
        "commit-packet-ready",
        "verification-packet-ready",
        "update-packet-ready",
        "transport-failed",
    }:
        raise PublishStateError("unsupported or incomplete Connector state stage")
    request_id = state.get("request_id")
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise PublishStateError("invalid Connector state request_id")
    generations = state.get("generations")
    current_generation = state.get("current_generation")
    if not isinstance(generations, list) or not generations:
        raise PublishStateError("Connector state has no payload generations")
    if not isinstance(current_generation, int):
        raise PublishStateError("Connector state current generation is invalid")
    for expected_generation, generation in enumerate(generations):
        if not isinstance(generation, dict) or generation.get("generation") != expected_generation:
            raise PublishStateError("Connector state payload generation sequence is invalid")
        paths = generation.get("remote_payload_paths")
        part_count = generation.get("payload_part_count")
        expected_oids = generation.get("expected_payload_blob_git_oids")
        expected_chars = generation.get("expected_payload_chars")
        batches = generation.get("tree_batches")
        if not isinstance(part_count, int) or part_count <= 0:
            raise PublishStateError("Connector generation has no payload handoff fields")
        if not isinstance(paths, list) or len(paths) != part_count:
            raise PublishStateError("Connector generation payload path list is inconsistent")
        if not isinstance(expected_oids, list) or len(expected_oids) != part_count:
            raise PublishStateError("Connector generation payload OID list is inconsistent")
        if not isinstance(expected_chars, list) or len(expected_chars) != part_count:
            raise PublishStateError("Connector generation payload size list is inconsistent")
        if not isinstance(batches, list) or not batches:
            raise PublishStateError("Connector generation has no tree batches")
        for batch in batches:
            if not isinstance(batch, list) or not batch:
                raise PublishStateError("Connector generation tree batch is invalid")
            for element in batch:
                if not isinstance(element, dict):
                    raise PublishStateError("Connector generation tree element is invalid")
                if not all(key in element for key in ("path", "mode", "type", "content")):
                    raise PublishStateError("Connector generation tree element is incomplete")
    if current_generation != int(generations[-1]["generation"]):
        raise PublishStateError("Connector state current generation is inconsistent")
    transport_attempt = state.get("transport_attempt", 0)
    if not isinstance(transport_attempt, int) or not 0 <= transport_attempt < MAX_TRANSPORT_ATTEMPTS:
        raise PublishStateError("Connector state transport attempt is invalid")
    if state.get("stage") == "tree-ready":
        batch_index = state.get("tree_batch_index")
        current = generations[-1]
        assert isinstance(current, dict)
        batches = current["tree_batches"]
        assert isinstance(batches, list)
        if not isinstance(batch_index, int) or not 0 <= batch_index < len(batches):
            raise PublishStateError("Connector state tree batch index is invalid")
        packet = state.get("tree_packet")
        if not isinstance(packet, str) or not Path(packet).is_file():
            raise PublishStateError("Connector state current tree packet is missing")
    return state


def _v7_transport_request_for_generation(
    prepared: dict[str, object], generation: int
) -> dict[str, object]:
    request_id = str(prepared["request_id"])
    return _transport_request(
        prepared,
        {
            "kind": "indexed-files",
            "directory": f".publish/payloads/{request_id}",
            "minimum_generation": generation,
        },
    )


def _require_publish_base(head: str, tree: str) -> tuple[str, str]:
    _require_hex_sha(head, name="publish remote HEAD")
    _require_hex_sha(tree, name="publish remote tree")
    return head, tree


def _generation_summary(generation: dict[str, object]) -> dict[str, object]:
    batches = generation["tree_batches"]
    assert isinstance(batches, list)
    return {
        "generation": generation["generation"],
        "payload_handoff_field_count": generation["payload_part_count"],
        "payload_handoff_field_chars": generation["payload_handoff_element_chars"],
        "tree_call_count": len(batches),
        "trigger_path": generation["trigger_path"],
        "remote_payload_paths": generation["remote_payload_paths"],
        "remote_payload_index_path": generation["remote_index_path"],
        "base_publish_head": generation["base_publish_head"],
        "base_publish_tree": generation["base_publish_tree"],
    }


def _tree_ready_summary(
    state: dict[str, object],
    generation: dict[str, object],
    materialized: dict[str, object],
) -> dict[str, object]:
    return {
        "stage": "tree-ready",
        "request_id": state["request_id"],
        "generation": generation["generation"],
        "tree_batch_index": materialized["batch_index"],
        "tree_batch_count": materialized["batch_count"],
        "tree_call_bytes": materialized["call_bytes"],
        "tree_packet": materialized["packet"],
        "tree_header": materialized["header"],
        "tree_element_files": materialized["elements"],
        "next": (
            "assemble one GitHub.create_tree call from the generated header and tree element files; "
            "pass only the returned tree SHA to connector-tree"
        ),
        "verified": True,
    }


def cmd_connector_plan(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    manifest = _manifest_path(repo)
    verified = _verify_prepared_request(repo, manifest)
    prepared = _read_prepared_request(manifest)
    _require_hex_sha(args.target_remote_head, name="target remote HEAD")
    if args.target_remote_head != prepared["base_sha"]:
        raise PublishStateError(
            "target branch HEAD moved since prepare: "
            f"expected={prepared['base_sha']} actual={args.target_remote_head}"
        )
    publish_head, publish_tree = _require_publish_base(
        args.publish_remote_head, args.publish_remote_tree
    )

    output_dir = _connector_dir(repo)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PublishStateError(
            f"Connector plan directory is already initialized: {output_dir}; "
            "continue its generated packets instead of replanning transport"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    generation = _generation_plan(
        repo,
        prepared,
        0,
        base_publish_head=publish_head,
        base_publish_tree=publish_tree,
        retry=False,
    )
    materialized = _write_tree_batch_packet(output_dir, generation, 0, publish_tree)
    request_id = str(prepared["request_id"])
    state = {
        "version": CONNECTOR_STATE_VERSION,
        "stage": "tree-ready",
        "manifest": str(manifest),
        "request_id": request_id,
        "github_repository": GITHUB_REPOSITORY,
        "publish_branch": PUBLISH_BRANCH,
        "target_branch": prepared["target_branch"],
        "target_remote_head": args.target_remote_head,
        "current_generation": 0,
        "transport_attempt": 0,
        "tree_batch_index": 0,
        "tree_packet": materialized["packet"],
        "tree_header": materialized["header"],
        "tree_element_files": materialized["elements"],
        "generations": [generation],
    }
    _write_connector_state(output_dir, state)
    summary = {
        "strategy": "atomic-inline-tree-generation",
        "manifest": str(manifest),
        "request_id": request_id,
        "github_repository": GITHUB_REPOSITORY,
        "publish_branch": PUBLISH_BRANCH,
        "target_branch": prepared["target_branch"],
        "target_remote_head": args.target_remote_head,
        "connector_profile": "github-create-tree-inline-content",
        "connector_call_budget_bytes": CONNECTOR_CALL_BUDGET_BYTES,
        "call_size_basis": "compact-json-action-args",
        "current_generation": 0,
        **_generation_summary(generation),
        "normal_remote_target_probe_calls": 1,
        "normal_publish_transport_probe_calls": 1,
        "blob_response_sha_handoff_required": False,
        "branch_updates_per_generation": 1,
        "max_transport_attempts": MAX_TRANSPORT_ATTEMPTS,
        "request_verified": bool(verified["verified"]),
        "remote_request_path": _request_file_path(request_id),
        "remote_receipt_path": _receipt_file_path(request_id),
        **_tree_ready_summary(state, generation, materialized),
    }
    _write_connector_summary(output_dir, summary)
    print(json.dumps(summary, indent=2))
    return 0


def _write_generation_commit_packet(
    repo: Path,
    state: dict[str, object],
    generation: dict[str, object],
    tree_sha: str,
) -> dict[str, object]:
    request_id = str(state["request_id"])
    generation_number = int(generation["generation"])
    message = (
        f"Retry publish request {request_id} generation {generation_number:04d}"
        if generation.get("retry")
        else f"Submit publish request {request_id} generation {generation_number:04d}"
    )
    transport_attempt = int(state.get("transport_attempt", 0))
    if transport_attempt:
        message += f" transport attempt {transport_attempt + 1}"
    packet = {
        "stage": "create-publish-generation-commit",
        "generation": generation_number,
        "action": "GitHub.create_commit",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "message": message,
            "tree_sha": tree_sha,
            "parent_sha": generation["base_publish_head"],
        },
    }
    packet_path = _connector_dir(repo) / f"g{generation_number:04d}-create-commit.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if _connector_call_bytes(packet) > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError("publish generation commit packet exceeds Connector hard ceiling")
    state["stage"] = "commit-packet-ready"
    state["created_tree"] = tree_sha
    state["commit_packet"] = str(packet_path)
    state.pop("tree_packet", None)
    state.pop("tree_header", None)
    state.pop("tree_element_files", None)
    _write_connector_state(_connector_dir(repo), state)
    summary = {
        "stage": state["stage"],
        "request_id": request_id,
        "generation": generation_number,
        "commit_packet": str(packet_path),
        "next": (
            "copy/paste the commit packet action_args into GitHub.create_commit; pass only the "
            "returned commit SHA to connector-commit"
        ),
        "verified": True,
    }
    _write_connector_summary(_connector_dir(repo), summary)
    return summary


def cmd_connector_tree(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_connector_state(repo)
    if state.get("stage") != "tree-ready":
        raise PublishStateError(
            f"connector-tree requires tree-ready, found {state.get('stage')}"
        )
    tree_sha = args.tree_sha
    _require_hex_sha(tree_sha, name="created publish generation tree SHA")
    generations = state["generations"]
    assert isinstance(generations, list)
    generation = generations[-1]
    assert isinstance(generation, dict)
    batches = generation["tree_batches"]
    assert isinstance(batches, list)
    batch_index = int(state["tree_batch_index"])
    next_index = batch_index + 1
    if next_index < len(batches):
        materialized = _write_tree_batch_packet(
            _connector_dir(repo), generation, next_index, tree_sha
        )
        state["tree_batch_index"] = next_index
        state["tree_packet"] = materialized["packet"]
        state["tree_header"] = materialized["header"]
        state["tree_element_files"] = materialized["elements"]
        _write_connector_state(_connector_dir(repo), state)
        summary = _tree_ready_summary(state, generation, materialized)
        _write_connector_summary(_connector_dir(repo), summary)
        print(json.dumps(summary, indent=2))
        return 0

    summary = _write_generation_commit_packet(repo, state, generation, tree_sha)
    print(json.dumps(summary, indent=2))
    return 0


def _payload_verification_url(request_id: str, generation: int, commit_sha: str) -> str:
    generation_name = _payload_generation_name(generation)
    return (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/"
        f".publish/payloads/{request_id}/{generation_name}?ref={commit_sha}"
    )


def _write_payload_verification_packet(
    repo: Path,
    state: dict[str, object],
    generation: dict[str, object],
    commit_sha: str,
) -> dict[str, object]:
    request_id = str(state["request_id"])
    generation_number = int(generation["generation"])
    packet = {
        "stage": "verify-publish-generation-payload",
        "generation": generation_number,
        "transport_attempt": int(state.get("transport_attempt", 0)),
        "action": "GitHub.fetch",
        "action_args": {
            "url": _payload_verification_url(request_id, generation_number, commit_sha),
        },
    }
    packet_path = _connector_dir(repo) / f"g{generation_number:04d}-verify-payload.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if _connector_call_bytes(packet) > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError("publish payload verification packet exceeds Connector hard ceiling")
    state["stage"] = "verification-packet-ready"
    state["verification_commit"] = commit_sha
    state["verification_packet"] = str(packet_path)
    state.pop("update_packet", None)
    state.pop("published_commit_candidate", None)
    _write_connector_state(_connector_dir(repo), state)
    summary = {
        "stage": state["stage"],
        "request_id": request_id,
        "generation": generation_number,
        "transport_attempt": int(state.get("transport_attempt", 0)),
        "max_transport_attempts": MAX_TRANSPORT_ATTEMPTS,
        "verification_packet": str(packet_path),
        "expected_payload_part_count": int(generation["payload_part_count"]),
        "next": (
            "execute the generated GitHub.fetch packet once; pass every returned payload file to "
            "connector-verify as --remote-part NAME=SHA:SIZE"
        ),
        "verified": True,
    }
    _write_connector_summary(_connector_dir(repo), summary)
    return summary


def cmd_connector_commit(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_connector_state(repo)
    if state.get("stage") != "commit-packet-ready":
        raise PublishStateError(
            f"connector-commit requires commit-packet-ready, found {state.get('stage')}"
        )
    commit_sha = args.commit_sha
    _require_hex_sha(commit_sha, name="created publish generation commit SHA")
    generations = state["generations"]
    assert isinstance(generations, list)
    generation = generations[-1]
    assert isinstance(generation, dict)
    summary = _write_payload_verification_packet(repo, state, generation, commit_sha)
    print(json.dumps(summary, indent=2))
    return 0


def _parse_remote_payload_parts(values: list[str]) -> dict[str, tuple[str, int]]:
    observed: dict[str, tuple[str, int]] = {}
    for value in values:
        name, sep, metadata = value.partition("=")
        if not sep or not name or not metadata:
            raise PublishStateError(
                "remote payload part must use NAME=SHA:SIZE from the generated verification response"
            )
        sha, sep, raw_size = metadata.partition(":")
        if not sep:
            raise PublishStateError(
                "remote payload part must use NAME=SHA:SIZE from the generated verification response"
            )
        _require_hex_sha(sha, name=f"remote payload part {name} SHA")
        try:
            size = int(raw_size)
        except ValueError as exc:
            raise PublishStateError(f"remote payload part {name} size is invalid") from exc
        if size < 0:
            raise PublishStateError(f"remote payload part {name} size is invalid")
        if name in observed:
            raise PublishStateError(f"duplicate remote payload part: {name}")
        observed[name] = (sha, size)
    return observed


def _expected_payload_parts(generation: dict[str, object]) -> dict[str, tuple[str, int]]:
    paths = generation["remote_payload_paths"]
    oids = generation["expected_payload_blob_git_oids"]
    sizes = generation["expected_payload_chars"]
    assert isinstance(paths, list)
    assert isinstance(oids, list)
    assert isinstance(sizes, list)
    expected: dict[str, tuple[str, int]] = {}
    for path, oid, size in zip(paths, oids, sizes, strict=True):
        name = Path(str(path)).name
        if name in expected:
            raise PublishStateError(f"duplicate expected payload part: {name}")
        expected[name] = (str(oid), int(size))
    return expected


def _payload_mismatches(
    expected: dict[str, tuple[str, int]],
    observed: dict[str, tuple[str, int]],
) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    for name in sorted(expected.keys() - observed.keys()):
        oid, size = expected[name]
        mismatches.append(
            {"name": name, "kind": "missing", "expected_sha": oid, "expected_size": size}
        )
    for name in sorted(observed.keys() - expected.keys()):
        sha, size = observed[name]
        mismatches.append(
            {"name": name, "kind": "unexpected", "actual_sha": sha, "actual_size": size}
        )
    for name in sorted(expected.keys() & observed.keys()):
        expected_sha, expected_size = expected[name]
        actual_sha, actual_size = observed[name]
        if expected_sha != actual_sha or expected_size != actual_size:
            mismatches.append(
                {
                    "name": name,
                    "kind": "content",
                    "expected_sha": expected_sha,
                    "actual_sha": actual_sha,
                    "expected_size": expected_size,
                    "actual_size": actual_size,
                }
            )
    return mismatches


def _clear_post_tree_state(state: dict[str, object]) -> None:
    for key in (
        "created_tree",
        "commit_packet",
        "verification_commit",
        "verification_packet",
        "published_commit_candidate",
        "update_packet",
    ):
        state.pop(key, None)


def _retry_current_generation(
    repo: Path,
    state: dict[str, object],
    prepared: dict[str, object],
    generation: dict[str, object],
    mismatches: list[dict[str, object]],
) -> dict[str, object]:
    current_attempt = int(state.get("transport_attempt", 0))
    next_attempt = current_attempt + 1
    if next_attempt >= MAX_TRANSPORT_ATTEMPTS:
        state["stage"] = "transport-failed"
        state["last_transport_mismatches"] = mismatches
        _write_connector_state(_connector_dir(repo), state)
        summary = {
            "stage": state["stage"],
            "request_id": state["request_id"],
            "generation": generation["generation"],
            "transport_attempt": current_attempt,
            "max_transport_attempts": MAX_TRANSPORT_ATTEMPTS,
            "mismatches": mismatches,
            "next": (
                "automatic transport retries are exhausted; do not update the publish ref. "
                "Investigate Connector degradation or explicitly enter higher-level recovery."
            ),
            "verified": False,
        }
        _write_connector_summary(_connector_dir(repo), summary)
        raise PublishStateError(
            f"payload transport verification failed after {MAX_TRANSPORT_ATTEMPTS} attempts; "
            "publish ref was not updated"
        )

    generation_number = int(generation["generation"])
    current_chars = int(generation["payload_handoff_element_chars"])
    if next_attempt == 1:
        handoff_chars = current_chars
    else:
        payload_chars = len(str(prepared["payload_b64"]))
        minimum_chars_for_part_limit = max(1, (payload_chars + MAX_PAYLOAD_PARTS - 1) // MAX_PAYLOAD_PARTS)
        handoff_chars = max(minimum_chars_for_part_limit, current_chars // 2, 1)
    rebuilt = _generation_plan(
        repo,
        prepared,
        generation_number,
        base_publish_head=str(generation["base_publish_head"]),
        base_publish_tree=str(generation["base_publish_tree"]),
        retry=bool(generation.get("retry")),
        handoff_element_chars=handoff_chars,
    )
    generations = state["generations"]
    assert isinstance(generations, list)
    generations[-1] = rebuilt
    output_dir = _connector_dir(repo)
    materialized = _write_tree_batch_packet(
        output_dir,
        rebuilt,
        0,
        str(rebuilt["base_publish_tree"]),
    )
    state["stage"] = "tree-ready"
    state["transport_attempt"] = next_attempt
    state["tree_batch_index"] = 0
    state["tree_packet"] = materialized["packet"]
    state["tree_header"] = materialized["header"]
    state["tree_element_files"] = materialized["elements"]
    state["last_transport_mismatches"] = mismatches
    _clear_post_tree_state(state)
    _write_connector_state(output_dir, state)
    result = {
        **_tree_ready_summary(state, rebuilt, materialized),
        "stage": "transport-retry-tree-ready",
        "request_id": state["request_id"],
        "generation": generation_number,
        "transport_attempt": next_attempt,
        "attempt_number": next_attempt + 1,
        "max_transport_attempts": MAX_TRANSPORT_ATTEMPTS,
        "mismatches": mismatches,
        "payload_handoff_element_chars": handoff_chars,
        "adaptive_handoff": next_attempt >= 2,
    }
    _write_connector_summary(output_dir, result)
    return result


def _write_update_packet(
    repo: Path,
    state: dict[str, object],
    generation: dict[str, object],
    commit_sha: str,
) -> dict[str, object]:
    generation_number = int(generation["generation"])
    packet = {
        "stage": "advance-publish-transport-ref",
        "generation": generation_number,
        "action": "GitHub.update_ref",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "branch_name": PUBLISH_BRANCH,
            "sha": commit_sha,
            "force": False,
        },
    }
    packet_path = _connector_dir(repo) / f"g{generation_number:04d}-advance-publish-ref.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state["stage"] = "update-packet-ready"
    state["published_commit_candidate"] = commit_sha
    state["update_packet"] = str(packet_path)
    _write_connector_state(_connector_dir(repo), state)
    summary = {
        "stage": state["stage"],
        "request_id": state["request_id"],
        "generation": generation_number,
        "transport_attempt": int(state.get("transport_attempt", 0)),
        "payload_transport_verified": True,
        "update_packet": str(packet_path),
        "branch_updates_per_generation": 1,
        "next": (
            "copy/paste the ref packet action_args into GitHub.update_ref. A successful non-force "
            "update publishes the verified payload generation and its request/retry trigger atomically; "
            "then wait for the Gateway receipt"
        ),
        "verified": True,
    }
    _write_connector_summary(_connector_dir(repo), summary)
    return summary


def cmd_connector_verify(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    manifest = _manifest_path(repo)
    prepared = _read_prepared_request(manifest)
    _verify_prepared_request(repo, manifest)
    state = _read_connector_state(repo)
    if state.get("stage") != "verification-packet-ready":
        raise PublishStateError(
            f"connector-verify requires verification-packet-ready, found {state.get('stage')}"
        )
    generations = state["generations"]
    assert isinstance(generations, list)
    generation = generations[-1]
    assert isinstance(generation, dict)
    expected = _expected_payload_parts(generation)
    observed = _parse_remote_payload_parts(args.remote_part)
    mismatches = _payload_mismatches(expected, observed)
    if mismatches:
        result = _retry_current_generation(repo, state, prepared, generation, mismatches)
        print(json.dumps(result, indent=2))
        return 0

    commit_sha = state.get("verification_commit")
    if not isinstance(commit_sha, str):
        raise PublishStateError("Connector state has no verification commit")
    _require_hex_sha(commit_sha, name="verified publish generation commit SHA")
    summary = _write_update_packet(repo, state, generation, commit_sha)
    print(json.dumps(summary, indent=2))
    return 0


def _allowed_repair_publish_bases(
    state: dict[str, object], current: dict[str, object]
) -> set[tuple[str, str]]:
    allowed = {
        (str(current["base_publish_head"]), str(current["base_publish_tree"]))
    }
    if state.get("stage") == "update-packet-ready":
        candidate = state.get("published_commit_candidate")
        created_tree = state.get("created_tree")
        if isinstance(candidate, str) and isinstance(created_tree, str):
            allowed.add((candidate, created_tree))
    return allowed


def cmd_connector_repair(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    manifest = _manifest_path(repo)
    prepared = _read_prepared_request(manifest)
    _verify_prepared_request(repo, manifest)
    state = _read_connector_state(repo)
    generations = state["generations"]
    assert isinstance(generations, list)
    current = generations[-1]
    assert isinstance(current, dict)
    publish_head, publish_tree = _require_publish_base(
        args.publish_remote_head, args.publish_remote_tree
    )
    allowed = _allowed_repair_publish_bases(state, current)
    if (publish_head, publish_tree) not in allowed:
        expected = ", ".join(f"{head}/{tree}" for head, tree in sorted(allowed))
        raise PublishStateError(
            "publish transport base is not the active generation base or its atomic commit; "
            f"observed={publish_head}/{publish_tree} expected one of [{expected}]. "
            "If the Gateway already wrote a receipt, fetch and record it instead of repairing."
        )

    next_generation = int(state["current_generation"]) + 1
    output_dir = _connector_dir(repo)
    generation = _generation_plan(
        repo,
        prepared,
        next_generation,
        base_publish_head=publish_head,
        base_publish_tree=publish_tree,
        retry=True,
    )
    materialized = _write_tree_batch_packet(output_dir, generation, 0, publish_tree)
    previous_count = int(current["payload_part_count"])
    next_count = int(generation["payload_part_count"])
    generations.append(generation)
    state["current_generation"] = next_generation
    state["transport_attempt"] = 0
    state["stage"] = "tree-ready"
    state["tree_batch_index"] = 0
    state["tree_packet"] = materialized["packet"]
    state["tree_header"] = materialized["header"]
    state["tree_element_files"] = materialized["elements"]
    state.pop("created_tree", None)
    state.pop("commit_packet", None)
    state.pop("verification_commit", None)
    state.pop("verification_packet", None)
    state.pop("published_commit_candidate", None)
    state.pop("update_packet", None)
    state.pop("last_transport_mismatches", None)
    _write_connector_state(output_dir, state)
    result = {
        "stage": "repair-generation-ready",
        "strategy": "atomic-inline-tree-generation",
        "request_id": state["request_id"],
        "previous_generation": next_generation - 1,
        "generation": next_generation,
        "previous_payload_handoff_field_count": previous_count,
        "payload_handoff_field_count": next_count,
        "connector_call_budget_bytes": CONNECTOR_CALL_BUDGET_BYTES,
        "branch_updates_per_generation": 1,
        **_generation_summary(generation),
        **_tree_ready_summary(state, generation, materialized),
    }
    _write_connector_summary(output_dir, result)
    print(json.dumps(result, indent=2))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    transaction = _transaction_dir(repo)
    manifest = _manifest_path(repo)
    if not manifest.exists():
        raise PublishStateError("no active publish transaction to cancel")
    request = _read_prepared_request(manifest)
    state = _read_state(repo)
    target_remote_head = args.target_remote_head
    publish_remote_tree = args.publish_remote_tree
    _require_hex_sha(target_remote_head, name="observed develop HEAD")
    _require_hex_sha(publish_remote_tree, name="observed publish tree")
    expected_target = str(request["base_sha"])
    if target_remote_head != expected_target or target_remote_head != state["remote_commit"]:
        raise PublishStateError(
            "cannot cancel active publish transaction after develop moved; "
            f"observed={target_remote_head} expected={expected_target}"
        )
    connector_state_path = _connector_dir(repo) / CONNECTOR_STATE_NAME
    if connector_state_path.exists():
        connector_state = _read_connector_state(repo)
        generations = connector_state.get("generations")
        if not isinstance(generations, list) or not generations or not isinstance(generations[0], dict):
            raise PublishStateError("active Connector state has no initial publish base")
        initial_tree = str(generations[0]["base_publish_tree"])
        if publish_remote_tree != initial_tree:
            raise PublishStateError(
                "cannot cancel active publish transaction after publish transport content changed; "
                f"observed_tree={publish_remote_tree} expected_tree={initial_tree}"
            )
    else:
        raise PublishStateError(
            "cannot cancel after prepare before publish transport base was recorded; run connector-plan first"
        )
    shutil.rmtree(transaction)
    print(json.dumps({
        "cancelled": True,
        "request_id": request["request_id"],
        "target_remote_head": target_remote_head,
        "publish_remote_tree": publish_remote_tree,
        "local_target_commit": request["local_target_commit"],
        "verified": True,
    }, indent=2))
    return 0

def _read_publish_receipt(path: Path, *, expected_request_version: int) -> dict[str, object]:
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
    if data["request_version"] != expected_request_version:
        raise PublishStateError(
            "publish receipt request version does not match the active transaction: "
            f"expected={expected_request_version} actual={data['request_version']}"
        )
    if data["target_branch"] != TARGET_BRANCH:
        raise PublishStateError("invalid publish receipt target_branch; standard publish targets develop only")
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
    repo = _repo_from_cwd()
    state = _read_state(repo)
    manifest = _manifest_path(repo)
    verified = _verify_prepared_request(repo, manifest)
    request = _read_prepared_request(manifest)
    receipt = _read_publish_receipt(Path(args.receipt).resolve(), expected_request_version=int(request["version"]))
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
    transaction = _transaction_dir(repo)
    if transaction.exists():
        shutil.rmtree(transaction)
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
        description="Generate and track the single standard Space-Idle develop publish transaction."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init",
        help="initialize state from the source-snapshot repository.bundle recorded as origin",
    )
    init.set_defaults(func=cmd_init)

    prepare = sub.add_parser("prepare", help="prepare HEAD as the single active develop publish transaction")
    prepare.set_defaults(func=cmd_prepare)

    connector_plan = sub.add_parser(
        "connector-plan",
        help="after the single develop and publish transport base observations, plan an atomic payload generation",
    )
    connector_plan.add_argument(
        "--target-remote-head",
        required=True,
        help="observed develop HEAD from the single pre-publish target check; verification input, not a target selector",
    )
    connector_plan.add_argument(
        "--publish-remote-head",
        required=True,
        help="observed publish transport HEAD used as the atomic generation parent",
    )
    connector_plan.add_argument(
        "--publish-remote-tree",
        required=True,
        help="observed publish transport tree used as the atomic generation base tree",
    )
    connector_plan.set_defaults(func=cmd_connector_plan)

    connector_tree = sub.add_parser(
        "connector-tree",
        help="advance the atomic tree assembly or create the commit packet after the final tree call",
    )
    connector_tree.add_argument(
        "--tree-sha", required=True, help="tree SHA returned by the generated GitHub.create_tree call"
    )
    connector_tree.set_defaults(func=cmd_connector_tree)

    connector_commit = sub.add_parser(
        "connector-commit",
        help="create the one-read payload verification packet for the atomic generation commit",
    )
    connector_commit.add_argument(
        "--commit-sha", required=True, help="commit SHA returned by the generated GitHub.create_commit call"
    )
    connector_commit.set_defaults(func=cmd_connector_commit)

    connector_verify = sub.add_parser(
        "connector-verify",
        help="verify all payload part OIDs/sizes and either emit the ref update or retry transport",
    )
    connector_verify.add_argument(
        "--remote-part",
        action="append",
        required=True,
        help="one payload file from the verification response as NAME=SHA:SIZE; repeat for every file",
    )
    connector_verify.set_defaults(func=cmd_connector_verify)

    connector_repair = sub.add_parser(
        "connector-repair",
        help=(
            "generate the next atomic retry generation using the same 144 KiB remote action ceiling "
            "from the observed publish transport base"
        ),
    )
    connector_repair.add_argument(
        "--publish-remote-head", required=True,
        help="publish HEAD observed once when recovery is required",
    )
    connector_repair.add_argument(
        "--publish-remote-tree", required=True,
        help="publish tree observed with the recovery HEAD",
    )
    connector_repair.set_defaults(func=cmd_connector_repair)

    cancel = sub.add_parser(
        "cancel",
        help="cancel an unpublished active transaction after verifying develop and publish content are unchanged",
    )
    cancel.add_argument(
        "--target-remote-head", required=True,
        help="observed develop HEAD; must still equal the transaction base",
    )
    cancel.add_argument(
        "--publish-remote-tree", required=True,
        help="observed publish tree; must still equal the transaction initial transport base tree",
    )
    cancel.set_defaults(func=cmd_cancel)

    record = sub.add_parser("record", help="verify a Gateway receipt and close the active transaction")
    record.add_argument(
        "--receipt",
        required=True,
        help="local file containing the fetched Gateway receipt for the active request",
    )
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
