#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

STATE_NAME = "space-idle-publish-state.json"
DEFAULT_CHUNK_SIZE = 8 * 1024
DEFAULT_CONNECTOR_CALL_BUDGET_BYTES = 96 * 1024
MAX_CHUNK_COUNT = 256
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


def _request_patch(repo: Path, base_tree: str, target_tree: str) -> str:
    patch_bytes = _git_bytes(
        "diff",
        "--binary",
        "--full-index",
        "--no-renames",
        "--no-color",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base_tree,
        target_tree,
        cwd=repo,
    )
    try:
        return patch_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublishStateError(
            "publish patch is not UTF-8; use native git transport for repositories with non-UTF-8 paths/content"
        ) from exc


def _default_message(repo: Path, state: dict[str, str], target_ref: str) -> str:
    local_head = state["local_head"]
    try:
        is_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", local_head, target_ref],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        is_ancestor = False
    if is_ancestor:
        commits = _git("rev-list", "--reverse", f"{local_head}..{target_ref}", cwd=repo).splitlines()
        if len(commits) == 1:
            return _git("show", "-s", "--format=%B", commits[0], cwd=repo).rstrip() + "\n"
    return _git("show", "-s", "--format=%B", target_ref, cwd=repo).rstrip() + "\n"




def _message_bytes(message: str) -> bytes:
    if not message.strip():
        raise PublishStateError("commit message must not be empty")
    if not message.endswith("\n"):
        message += "\n"
    return message.encode("utf-8")


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
            "source-snapshot or import a verified publish receipt before preparing a bundle request"
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


def _verify_bundle_payload(
    repo: Path,
    headers: dict[str, str],
    payload_bytes: bytes,
) -> dict[str, object]:
    actual_digest = hashlib.sha256(payload_bytes).hexdigest()
    if actual_digest != headers["payload-sha256"]:
        raise PublishStateError(
            "publish bundle sha256 mismatch: "
            f"expected={headers['payload-sha256']} actual={actual_digest}"
        )
    publish_commit = headers["publish-commit"]
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
    fields, body = _parse_commit_object(repo, publish_commit)
    trees = fields.get("tree", [])
    parents = fields.get("parent", [])
    if trees != [headers["target-tree"]]:
        raise PublishStateError(
            f"publish commit tree mismatch: expected={headers['target-tree']} actual={trees}"
        )
    if parents != [headers["base-sha"]]:
        raise PublishStateError(
            f"publish commit parent mismatch: expected={[headers['base-sha']]} actual={parents}"
        )
    try:
        expected_message = base64.b64decode(headers["message-b64"], validate=True)
    except Exception as exc:
        raise PublishStateError(f"invalid publish message encoding: {exc}") from exc
    if body != expected_message:
        raise PublishStateError("publish commit message does not match manifest")
    return {
        "payload_sha256": actual_digest,
        "payload_bytes": len(payload_bytes),
        "publish_commit": publish_commit,
        "target_tree": trees[0],
    }


def _parse_request_manifest(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("# "):
            continue
        key, sep, value = line[2:].partition(": ")
        if sep:
            headers[key] = value
    common = {
        "version",
        "request-id",
        "target-branch",
        "base-sha",
        "target-tree",
        "chunk-count",
        "chunks-tree-git-oid",
        "message-b64",
    }
    missing = common - headers.keys()
    if missing:
        raise PublishStateError(f"invalid publish request: missing headers {sorted(missing)}")
    version = headers["version"]
    if version == "3":
        required = {"patch-sha256", "patch-encoding"}
        missing = required - headers.keys()
        if missing:
            raise PublishStateError(f"invalid publish request: missing headers {sorted(missing)}")
        if headers["patch-encoding"] != "gzip-base64-chunks":
            raise PublishStateError(f"unsupported patch encoding: {headers['patch-encoding']}")
    elif version == "4":
        required = {"payload-sha256", "payload-encoding", "publish-commit"}
        missing = required - headers.keys()
        if missing:
            raise PublishStateError(f"invalid publish request: missing headers {sorted(missing)}")
        if headers["payload-encoding"] != "git-bundle-base64-chunks":
            raise PublishStateError(f"unsupported payload encoding: {headers['payload-encoding']}")
        _require_hex_sha(headers["publish-commit"], name="publish commit")
    else:
        raise PublishStateError(f"unsupported publish request version: {version}")
    for key in ("base-sha", "target-tree"):
        _require_hex_sha(headers[key], name=f"request {key}")
    chunks_tree_oid = headers["chunks-tree-git-oid"]
    _require_hex_sha(chunks_tree_oid, name="chunks tree Git OID")
    try:
        chunk_count = int(headers["chunk-count"])
    except ValueError as exc:
        raise PublishStateError("invalid publish request chunk count") from exc
    if not 1 <= chunk_count <= MAX_CHUNK_COUNT:
        raise PublishStateError(
            f"invalid publish request chunk count: {chunk_count}; expected 1..{MAX_CHUNK_COUNT}"
        )
    return headers

def _verify_request_artifacts(repo: Path, manifest_path: Path, chunk_dir: Path) -> dict[str, object]:
    state = _read_state(repo)
    headers = _parse_request_manifest(manifest_path.read_text(encoding="utf-8"))
    if headers["base-sha"] != state["remote_commit"]:
        raise PublishStateError(
            "publish request base does not match recorded remote commit: "
            f"request={headers['base-sha']} state={state['remote_commit']}"
        )

    chunk_count = int(headers["chunk-count"])
    expected_chunk_names = [f"{index:04d}.txt" for index in range(chunk_count)]
    actual_chunk_names = sorted(path.name for path in chunk_dir.glob("*.txt") if path.is_file())
    if actual_chunk_names != expected_chunk_names:
        raise PublishStateError(
            "publish chunks directory does not exactly match manifest: "
            f"expected={expected_chunk_names} actual={actual_chunk_names}"
        )

    payload_parts: list[str] = []
    for index in range(chunk_count):
        digest_key = f"chunk-{index:04d}-sha256"
        expected = headers.get(digest_key)
        if expected is None:
            raise PublishStateError(f"publish request is missing {digest_key}")
        path = chunk_dir / f"{index:04d}.txt"
        if not path.is_file():
            raise PublishStateError(f"publish request is missing chunk {index:04d}: {path}")
        chunk = path.read_text(encoding="ascii")
        if chunk != chunk.strip():
            raise PublishStateError(f"chunk {index:04d} contains transport whitespace")
        actual = hashlib.sha256(chunk.encode("ascii")).hexdigest()
        if actual != expected:
            raise PublishStateError(
                f"chunk {index:04d} sha256 mismatch: expected={expected} actual={actual}"
            )
        payload_parts.append(chunk)

    expected_chunks_tree = headers["chunks-tree-git-oid"]
    actual_chunks_tree = _chunks_tree_oid(repo, payload_parts)
    if actual_chunks_tree != expected_chunks_tree:
        raise PublishStateError(
            "publish chunks Git tree mismatch: "
            f"expected={expected_chunks_tree} actual={actual_chunks_tree}"
        )

    joined = "".join(payload_parts)
    try:
        encoded_payload = base64.b64decode(joined, validate=True)
    except Exception as exc:
        raise PublishStateError(f"invalid Base64 publish payload: {exc}") from exc

    if headers["version"] == "4":
        bundle = _verify_bundle_payload(repo, headers, encoded_payload)
        return {
            "manifest": str(manifest_path),
            "chunk_dir": str(chunk_dir),
            "version": 4,
            "transport": "git-bundle",
            "chunk_count": chunk_count,
            "payload_bytes": bundle["payload_bytes"],
            "payload_sha256": bundle["payload_sha256"],
            "chunks_tree_git_oid": actual_chunks_tree,
            "publish_commit": bundle["publish_commit"],
            "target_tree": bundle["target_tree"],
            "verified": True,
        }

    try:
        patch_bytes = gzip.decompress(encoded_payload)
        patch_bytes.decode("utf-8")
    except Exception as exc:
        raise PublishStateError(f"invalid compressed publish payload: {exc}") from exc
    actual_patch_digest = hashlib.sha256(patch_bytes).hexdigest()
    if actual_patch_digest != headers["patch-sha256"]:
        raise PublishStateError(
            "publish patch sha256 mismatch: "
            f"expected={headers['patch-sha256']} actual={actual_patch_digest}"
        )

    with tempfile.TemporaryDirectory(prefix="space-idle-publish-verify-") as tmp:
        temp_dir = Path(tmp)
        index_path = temp_dir / "index"
        patch_path = temp_dir / "request.patch"
        patch_path.write_bytes(patch_bytes)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index_path)
        try:
            subprocess.run(
                ["git", "read-tree", state["remote_tree"]],
                cwd=repo,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "apply", "--cached", "--binary", str(patch_path)],
                cwd=repo,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            actual_tree = subprocess.run(
                ["git", "write-tree"],
                cwd=repo,
                env=env,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            raise PublishStateError(
                f"publish request could not recreate target tree: {(stderr or '').strip()}"
            ) from exc
    if actual_tree != headers["target-tree"]:
        raise PublishStateError(
            "publish request target tree mismatch: "
            f"expected={headers['target-tree']} actual={actual_tree}"
        )
    return {
        "manifest": str(manifest_path),
        "chunk_dir": str(chunk_dir),
        "version": 3,
        "transport": "patch",
        "chunk_count": chunk_count,
        "patch_bytes": len(patch_bytes),
        "compressed_bytes": len(encoded_payload),
        "patch_sha256": actual_patch_digest,
        "chunks_tree_git_oid": actual_chunks_tree,
        "target_tree": actual_tree,
        "verified": True,
    }

def _git_object_oid(repo: Path, object_type: str, content: bytes) -> str:
    object_format = _git("rev-parse", "--show-object-format", cwd=repo)
    if object_format not in {"sha1", "sha256"}:
        raise PublishStateError(f"unsupported Git object format: {object_format}")
    header = f"{object_type} {len(content)}\0".encode("ascii")
    return hashlib.new(object_format, header + content).hexdigest()


def _chunks_tree_oid(repo: Path, chunks: list[str]) -> str:
    entries = bytearray()
    for index, chunk in enumerate(chunks):
        name = f"{index:04d}.txt"
        blob_content = chunk.encode("ascii")
        blob_oid = _git_object_oid(repo, "blob", blob_content)
        entries.extend(b"100644 ")
        entries.extend(name.encode("ascii"))
        entries.append(0)
        entries.extend(bytes.fromhex(blob_oid))
    return _git_object_oid(repo, "tree", bytes(entries))


def _chunk_blob_oids(repo: Path, chunks: list[str]) -> list[str]:
    return [_git_object_oid(repo, "blob", chunk.encode("ascii")) for chunk in chunks]


def _named_blob_tree_oid(repo: Path, entries: list[tuple[str, str]]) -> str:
    raw = bytearray()
    for name, blob_oid in sorted(entries):
        raw.extend(b"100644 ")
        raw.extend(name.encode("ascii"))
        raw.append(0)
        raw.extend(bytes.fromhex(blob_oid))
    return _git_object_oid(repo, "tree", bytes(raw))


def _connector_tree_packet(
    github_repository: str,
    chunks: list[str],
    indices: list[int],
    *,
    stage: str,
    expected_tree_git_oid: str,
) -> dict[str, object]:
    return {
        "stage": stage,
        "expected_tree_git_oid": expected_tree_git_oid,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": github_repository,
            "base_tree_sha": None,
            "tree_elements": [
                {
                    "path": f"{index:04d}.txt",
                    "mode": "100644",
                    "type": "blob",
                    "content": chunks[index],
                }
                for index in indices
            ],
        },
    }


def _connector_call_bytes(packet: dict[str, object]) -> int:
    """Return the serialized bytes actually passed to the Connector action.

    Planning metadata such as stage names and expected OIDs is local-only and must not
    consume the configured Connector call budget.
    """
    action_args = packet.get("action_args")
    if not isinstance(action_args, dict):
        raise PublishStateError("Connector packet is missing action_args")
    return len(
        json.dumps(action_args, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _connector_publish_root_packet(
    github_repository: str,
    chunks: list[str],
    blob_oids: list[str],
    manifest_text: str,
    publish_base_tree: str,
    *,
    include_chunk_content: bool,
    expected_chunks_tree_git_oid: str,
) -> dict[str, object]:
    chunk_entries: list[dict[str, object]] = []
    for index, blob_oid in enumerate(blob_oids):
        entry: dict[str, object] = {
            "path": f".publish/chunks/{index:04d}.txt",
            "mode": "100644",
            "type": "blob",
        }
        if include_chunk_content:
            entry["content"] = chunks[index]
        else:
            entry["sha"] = blob_oid
        chunk_entries.append(entry)
    return {
        "stage": "create-transport-root-tree",
        "expected_chunks_tree_git_oid": expected_chunks_tree_git_oid,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": github_repository,
            "base_tree_sha": publish_base_tree,
            "tree_elements": [
                *chunk_entries,
                {
                    "path": ".publish/request.patch",
                    "mode": "100644",
                    "type": "blob",
                    "content": manifest_text,
                },
            ],
        },
    }


def _connector_upload_groups(
    repo: Path,
    chunks: list[str],
    max_call_bytes: int,
    github_repository: str,
) -> list[dict[str, object]]:
    """Pack chunks into the fewest independent Connector calls that fit the budget."""
    if max_call_bytes <= 0:
        raise PublishStateError("Connector call budget must be positive")
    blob_oids = _chunk_blob_oids(repo, chunks)
    groups: list[dict[str, object]] = []
    start = 0
    while start < len(chunks):
        end = start
        best_packet: dict[str, object] | None = None
        best_size = 0
        while end < len(chunks):
            indices = list(range(start, end + 1))
            expected = _named_blob_tree_oid(
                repo, [(f"{i:04d}.txt", blob_oids[i]) for i in indices]
            )
            packet = _connector_tree_packet(
                github_repository,
                chunks,
                indices,
                stage="materialize-chunk-group",
                expected_tree_git_oid=expected,
            )
            packet_size = _connector_call_bytes(packet)
            if packet_size > max_call_bytes:
                break
            best_packet = packet
            best_size = packet_size
            end += 1
        if best_packet is None:
            single = _connector_tree_packet(
                github_repository,
                chunks,
                [start],
                stage="materialize-chunk-group",
                expected_tree_git_oid=_named_blob_tree_oid(
                    repo, [(f"{start:04d}.txt", blob_oids[start])]
                ),
            )
            required = _connector_call_bytes(single)
            raise PublishStateError(
                f"chunk {start:04d} needs a {required}-byte Connector call, exceeding "
                f"the configured {max_call_bytes}-byte budget; reduce --chunk-size or "
                "increase --connector-call-budget-bytes after verifying Connector capacity"
            )
        actual_end = end - 1
        groups.append({
            "index": len(groups),
            "start_chunk": start,
            "end_chunk": actual_end,
            "chunk_count": actual_end - start + 1,
            "payload_chars": sum(len(chunks[i]) for i in range(start, actual_end + 1)),
            "packet_bytes": best_size,
            "packet": best_packet,
        })
        start = actual_end + 1
    return groups

def _bundle_payload_metrics(
    repo: Path,
    base_commit: str,
    target_tree: str,
    message: bytes,
    chunk_size: int,
) -> dict[str, object]:
    publish_commit = _create_publish_commit(repo, base_commit, target_tree, message)
    bundle = _bundle_bytes(repo, base_commit, publish_commit)
    payload_chars = len(base64.b64encode(bundle))
    chunk_count = max(1, (payload_chars + chunk_size - 1) // chunk_size)
    return {
        "transport": "git-bundle",
        "payload_bytes": len(bundle),
        "payload_chars": payload_chars,
        "chunk_count": chunk_count,
        "publish_commit": publish_commit,
    }


def _payload_metrics(
    repo: Path,
    base_tree: str,
    target_tree: str,
    chunk_size: int,
) -> dict[str, int]:
    patch = _request_patch(repo, base_tree, target_tree)
    patch_bytes = patch.encode("utf-8")
    compressed_patch = gzip.compress(patch_bytes, compresslevel=9, mtime=0)
    payload_chars = len(base64.b64encode(compressed_patch))
    chunk_count = max(1, (payload_chars + chunk_size - 1) // chunk_size)
    return {
        "patch_bytes": len(patch_bytes),
        "compressed_bytes": len(compressed_patch),
        "payload_chars": payload_chars,
        "chunk_count": chunk_count,
    }


def cmd_plan(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    working_tree_clean = _working_tree_clean(repo)
    state = _read_state(repo)
    target_ref = args.target_ref
    target_commit = _git("rev-parse", f"{target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{target_ref}^{{tree}}", cwd=repo)
    chunk_size = args.chunk_size
    if chunk_size <= 0:
        raise PublishStateError("chunk size must be positive")
    combined_message = _message_bytes(_default_message(repo, state, target_ref))
    if args.transport == "bundle":
        combined = _bundle_payload_metrics(
            repo,
            state["remote_commit"],
            target_tree,
            combined_message,
            chunk_size,
        )
    else:
        combined = _payload_metrics(
            repo, state["remote_tree"], target_tree, chunk_size
        )
        combined["transport"] = "patch"
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
        commit_ids = _git("rev-list", "--reverse", f"{local_head}..{target_commit}", cwd=repo).splitlines()
        previous_tree = state["remote_tree"]
        previous_remote_commit = state["remote_commit"]
        for commit_id in commit_ids:
            commit_tree = _git("rev-parse", f"{commit_id}^{{tree}}", cwd=repo)
            message = _message_bytes(_git("show", "-s", "--format=%B", commit_id, cwd=repo).rstrip() + "\n")
            if args.transport == "bundle":
                metrics = _bundle_payload_metrics(
                    repo,
                    previous_remote_commit,
                    commit_tree,
                    message,
                    chunk_size,
                )
                previous_remote_commit = str(metrics["publish_commit"])
            else:
                metrics = _payload_metrics(
                    repo, previous_tree, commit_tree, chunk_size
                )
                metrics["transport"] = "patch"
            metrics.update(
                {
                    "local_commit": commit_id,
                    "subject": _git("show", "-s", "--format=%s", commit_id, cwd=repo),
                    "target_tree": commit_tree,
                }
            )
            commits.append(metrics)
            previous_tree = commit_tree

    print(
        json.dumps(
            {
                "recorded_remote_commit": state["remote_commit"],
                "recorded_remote_tree": state["remote_tree"],
                "recorded_local_head": local_head,
                "working_tree_clean": working_tree_clean,
                "uncommitted_changes_excluded": not working_tree_clean,
                "target_ref": target_commit,
                "transport": args.transport,
                "chunk_size": chunk_size,
                "combined_request": combined,
                "sequential_local_commits_available": ancestor,
                "sequential_requests": commits,
            },
            indent=2,
        )
    )
    return 0

def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    local_commit = _git("rev-parse", args.local_ref, cwd=repo)
    local_tree = _git("rev-parse", f"{args.local_ref}^{{tree}}", cwd=repo)
    if local_tree != args.remote_tree:
        raise PublishStateError(
            f"artifact/local tree mismatch: local={local_tree} remote={args.remote_tree}"
        )
    _write_state(repo, args.remote_commit, args.remote_tree, local_commit)
    print(
        json.dumps(
            {
                "remote_commit": args.remote_commit,
                "remote_tree": args.remote_tree,
                "local_head": local_commit,
            },
            indent=2,
        )
    )
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    working_tree_clean = _working_tree_clean(repo)
    state = _read_state(repo)
    target_ref = args.target_ref
    target_commit = _git("rev-parse", f"{target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{target_ref}^{{tree}}", cwd=repo)
    if target_tree == state["remote_tree"]:
        raise PublishStateError("local HEAD tree already matches the last published tree")

    message_text = args.message if args.message is not None else _default_message(repo, state, target_ref)
    message = _message_bytes(message_text)
    message_b64 = base64.b64encode(message).decode("ascii")
    chunk_size = args.chunk_size
    if chunk_size <= 0:
        raise PublishStateError("chunk size must be positive")
    connector_call_budget_bytes = args.connector_call_budget_bytes
    if connector_call_budget_bytes <= 0:
        raise PublishStateError("Connector call budget must be positive")
    request_id = uuid.uuid4().hex
    if args.transport == "bundle":
        publish_commit = _create_publish_commit(repo, state["remote_commit"], target_tree, message)
        payload_bytes = _bundle_bytes(repo, state["remote_commit"], publish_commit)
        payload_digest = hashlib.sha256(payload_bytes).hexdigest()
        payload = base64.b64encode(payload_bytes).decode("ascii")
        request_lines = [
            "# version: 4",
            f"# request-id: {request_id}",
            f"# target-branch: {args.target_branch}",
            f"# base-sha: {state['remote_commit']}",
            f"# target-tree: {target_tree}",
            f"# publish-commit: {publish_commit}",
            f"# payload-sha256: {payload_digest}",
            "# payload-encoding: git-bundle-base64-chunks",
        ]
        metrics = {
            "transport": "git-bundle",
            "payload_bytes": len(payload_bytes),
            "payload_sha256": payload_digest,
            "publish_commit": publish_commit,
        }
    else:
        patch = _request_patch(repo, state["remote_tree"], target_tree)
        if not patch:
            raise PublishStateError("no publish patch was generated")
        patch_bytes = patch.encode("utf-8")
        patch_digest = hashlib.sha256(patch_bytes).hexdigest()
        compressed_patch = gzip.compress(patch_bytes, compresslevel=9, mtime=0)
        payload_bytes = compressed_patch
        payload = base64.b64encode(compressed_patch).decode("ascii")
        request_lines = [
            "# version: 3",
            f"# request-id: {request_id}",
            f"# target-branch: {args.target_branch}",
            f"# base-sha: {state['remote_commit']}",
            f"# target-tree: {target_tree}",
            f"# patch-sha256: {patch_digest}",
            "# patch-encoding: gzip-base64-chunks",
        ]
        metrics = {
            "transport": "patch",
            "patch_bytes": len(patch_bytes),
            "compressed_bytes": len(compressed_patch),
            "patch_sha256": patch_digest,
        }

    chunks = [payload[i : i + chunk_size] for i in range(0, len(payload), chunk_size)]
    if len(chunks) > MAX_CHUNK_COUNT:
        raise PublishStateError(
            f"publish payload needs {len(chunks)} chunks, exceeding gateway limit {MAX_CHUNK_COUNT}; "
            "publish an earlier coherent target-ref first or explicitly choose a larger --chunk-size"
        )
    chunk_digests = [hashlib.sha256(chunk.encode("ascii")).hexdigest() for chunk in chunks]
    chunks_tree_oid = _chunks_tree_oid(repo, chunks)
    request_lines.extend(
        [
            f"# chunk-count: {len(chunks)}",
            f"# chunks-tree-git-oid: {chunks_tree_oid}",
            f"# chunk-size: {chunk_size}",
            f"# connector-call-budget-bytes: {connector_call_budget_bytes}",
            f"# payload-bytes: {len(payload_bytes)}",
            f"# payload-chars: {len(payload)}",
            f"# local-target-commit: {target_commit}",
            f"# message-b64: {message_b64}",
        ]
    )
    request_lines.extend(
        f"# chunk-{index:04d}-sha256: {digest}"
        for index, digest in enumerate(chunk_digests)
    )
    request = "\n".join(request_lines) + "\n"

    if not args.output:
        print(request, end="")
        raise PublishStateError("chunked requests require --output so payload chunks can be written")
    output = Path(args.output)
    output.write_text(request, encoding="utf-8", newline="")
    chunk_dir = Path(f"{output}.chunks")
    chunk_dir.mkdir(parents=True, exist_ok=True)
    for stale in chunk_dir.glob("*.txt"):
        stale.unlink()
    for index, chunk in enumerate(chunks):
        (chunk_dir / f"{index:04d}.txt").write_text(chunk, encoding="ascii", newline="")
    verified = _verify_request_artifacts(repo, output, chunk_dir)
    result = {
        "manifest": str(output),
        "chunk_dir": str(chunk_dir),
        "request_id": request_id,
        "remote_receipt_path": f".publish/receipts/{request_id}.json",
        "transport": args.transport,
        "connector_call_budget_bytes": connector_call_budget_bytes,
        "chunk_count": len(chunks),
        "chunk_size": chunk_size,
        "payload_chars": len(payload),
        "chunks_tree_git_oid": chunks_tree_oid,
        "target_tree": target_tree,
        "local_target_commit": target_commit,
        "working_tree_clean": working_tree_clean,
        "uncommitted_changes_excluded": not working_tree_clean,
        "verified": verified["verified"],
    }
    result.update(metrics)
    print(json.dumps(result, indent=2))
    return 0

def _manifest_connector_call_budget_bytes(headers: dict[str, str]) -> int:
    raw = headers.get("connector-call-budget-bytes")
    if raw is None:
        return DEFAULT_CONNECTOR_CALL_BUDGET_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise PublishStateError("invalid connector-call-budget-bytes in manifest") from exc
    if value <= 0:
        raise PublishStateError("invalid connector-call-budget-bytes in manifest")
    return value


def cmd_connector_plan(args: argparse.Namespace) -> int:
    """Generate the minimum-call Connector transport plan for a prepared request."""
    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    manifest_text = manifest.read_text(encoding="utf-8")
    chunk_dir = Path(args.chunk_dir).resolve() if args.chunk_dir else Path(f"{manifest}.chunks")
    verified = _verify_request_artifacts(repo, manifest, chunk_dir)
    headers = _parse_request_manifest(manifest_text)
    chunk_count = int(headers["chunk-count"])
    chunks = [
        (chunk_dir / f"{index:04d}.txt").read_text(encoding="ascii")
        for index in range(chunk_count)
    ]
    blob_oids = _chunk_blob_oids(repo, chunks)
    call_budget = (
        args.connector_call_budget_bytes
        if args.connector_call_budget_bytes is not None
        else _manifest_connector_call_budget_bytes(headers)
    )
    if call_budget <= 0:
        raise PublishStateError("Connector call budget must be positive")

    if bool(args.publish_base_commit) != bool(args.publish_base_tree):
        raise PublishStateError(
            "--publish-base-commit and --publish-base-tree must be supplied together"
        )
    if args.publish_base_commit:
        if not args.target_remote_head:
            raise PublishStateError(
                "--target-remote-head is required with publish base metadata so the prepared "
                "request base is checked mechanically before transport"
            )
        _require_hex_sha(args.publish_base_commit, name="publish base commit SHA")
        _require_hex_sha(args.publish_base_tree, name="publish base tree SHA")
        _require_hex_sha(args.target_remote_head, name="target remote HEAD SHA")
        if args.target_remote_head != headers["base-sha"]:
            raise PublishStateError(
                "target branch HEAD moved since prepare: "
                f"expected={headers['base-sha']} actual={args.target_remote_head}"
            )

    output_dir = Path(args.output_dir).resolve() if args.output_dir else Path(f"{manifest}.connector")
    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("upload-group-*.json", "upload-batch-*.json", "chunk-*.json"):
        for stale in output_dir.glob(pattern):
            stale.unlink()
    for fixed_name in ("chunks-tree.json", "transport-root-tree.json"):
        stale = output_dir / fixed_name
        if stale.exists():
            stale.unlink()

    upload_packets: list[str] = []
    upload_call_count = 0
    assembly_required = False
    chunks_tree_packet_path: Path | None = None
    transport_root_packet_path: Path | None = None
    direct_publish_call_bytes: int | None = None

    if args.publish_base_commit:
        direct_root_packet = _connector_publish_root_packet(
            args.github_repository,
            chunks,
            blob_oids,
            manifest_text,
            args.publish_base_tree,
            include_chunk_content=True,
            expected_chunks_tree_git_oid=headers["chunks-tree-git-oid"],
        )
        direct_publish_call_bytes = _connector_call_bytes(direct_root_packet)
        transport_root_packet_path = output_dir / "transport-root-tree.json"
        if direct_publish_call_bytes <= call_budget:
            strategy = "single-create-tree-publish"
            transport_root_packet = direct_root_packet
        else:
            strategy = "parallel-upload-then-create-tree-publish"
            groups = _connector_upload_groups(
                repo, chunks, call_budget, args.github_repository
            )
            for group in groups:
                group_index = int(group["index"])
                packet_path = output_dir / f"upload-group-{group_index:03d}.json"
                packet_path.write_text(
                    json.dumps(group["packet"], indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                upload_packets.append(str(packet_path))
            upload_call_count = len(upload_packets)
            transport_root_packet = _connector_publish_root_packet(
                args.github_repository,
                chunks,
                blob_oids,
                manifest_text,
                args.publish_base_tree,
                include_chunk_content=False,
                expected_chunks_tree_git_oid=headers["chunks-tree-git-oid"],
            )
            root_call_bytes = _connector_call_bytes(transport_root_packet)
            if root_call_bytes > call_budget:
                raise PublishStateError(
                    f"SHA-only publish root needs a {root_call_bytes}-byte Connector call, exceeding "
                    f"the configured {call_budget}-byte budget; increase --connector-call-budget-bytes "
                    "after verifying Connector capacity"
                )
        transport_root_packet_path.write_text(
            json.dumps(transport_root_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        normal_mutation_calls = upload_call_count + 3
    else:
        complete_packet = _connector_tree_packet(
            args.github_repository,
            chunks,
            list(range(chunk_count)),
            stage="materialize-chunks-tree",
            expected_tree_git_oid=headers["chunks-tree-git-oid"],
        )
        complete_call_bytes = _connector_call_bytes(complete_packet)
        chunks_tree_packet_path = output_dir / "chunks-tree.json"
        if complete_call_bytes <= call_budget:
            strategy = "single-create-tree-transport"
            chunks_tree_packet = complete_packet
            upload_call_count = 1
        else:
            strategy = "parallel-create-tree-transport"
            assembly_required = True
            groups = _connector_upload_groups(
                repo, chunks, call_budget, args.github_repository
            )
            for group in groups:
                group_index = int(group["index"])
                packet_path = output_dir / f"upload-group-{group_index:03d}.json"
                packet_path.write_text(
                    json.dumps(group["packet"], indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                upload_packets.append(str(packet_path))
            upload_call_count = len(upload_packets)
            chunks_tree_packet = {
                "stage": "assemble-chunks-tree",
                "expected_tree_git_oid": headers["chunks-tree-git-oid"],
                "action": "GitHub.create_tree",
                "action_args": {
                    "repository_full_name": args.github_repository,
                    "base_tree_sha": None,
                    "tree_elements": [
                        {
                            "path": f"{index:04d}.txt",
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob_oid,
                        }
                        for index, blob_oid in enumerate(blob_oids)
                    ],
                },
            }
        chunks_tree_packet_path.write_text(
            json.dumps(chunks_tree_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        direct_publish_call_bytes = complete_call_bytes
        normal_mutation_calls = upload_call_count + (1 if assembly_required else 0) + 3

    summary = {
        "strategy": strategy,
        "manifest": str(manifest),
        "chunk_dir": str(chunk_dir),
        "request_id": headers["request-id"],
        "github_repository": args.github_repository,
        "chunk_count": chunk_count,
        "connector_call_budget_bytes": call_budget,
        "single_call_bytes": direct_publish_call_bytes,
        "call_size_basis": "compact-json-action-args",
        "upload_call_count": upload_call_count,
        "upload_packets": upload_packets,
        "assembly_required": assembly_required,
        "uploads_are_independent": bool(upload_packets),
        "connector_uploads_may_run_in_parallel": bool(upload_packets),
        "returned_upload_tree_shas_are_not_required": True,
        "chunks_tree_packet": (str(chunks_tree_packet_path) if chunks_tree_packet_path else None),
        "expected_chunks_tree_git_oid": headers["chunks-tree-git-oid"],
        "transport_root_tree_packet": (str(transport_root_packet_path) if transport_root_packet_path else None),
        "publish_base_commit": args.publish_base_commit,
        "publish_base_tree": args.publish_base_tree,
        "publish_branch": args.publish_branch,
        "normal_github_mutation_calls": normal_mutation_calls,
        "normal_remote_target_probe_calls": 1 if args.publish_base_commit else 0,
        "normal_publish_transport_probe_calls": 1 if args.publish_base_commit else 0,
        "normal_remote_probe_calls": 2 if args.publish_base_commit else 0,
        "normal_total_github_calls": normal_mutation_calls + (2 if args.publish_base_commit else 0),
        "normal_sha_handoffs": 2,
        "normal_per_upload_verification_calls": 0,
        "next_after_transport": (
            "execute transport-root-tree.json; if upload groups exist, run them in parallel first. "
            "Use the returned root tree SHA to create one transport commit, then non-force update "
            "the publish ref. No chunks-tree assembly or per-upload SHA handoff is needed in the "
            "normal publish path."
            if args.publish_base_commit
            else
            "materialize the prepared chunks tree; supply publish base metadata to connector-plan "
            "for the lower-call direct-root publish path"
        ),
        "request_verified": bool(verified["verified"]),
        "verified": True,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0

def _require_hex_sha(value: str, *, name: str) -> None:
    if len(value) not in {40, 64}:
        raise PublishStateError(f"invalid {name}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PublishStateError(f"invalid {name}") from exc


def cmd_connector_publish_step(args: argparse.Namespace) -> int:
    """Emit the next small GitHub mutation for compatibility/debug workflows."""
    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    chunk_dir = Path(args.chunk_dir).resolve() if args.chunk_dir else Path(f"{manifest}.chunks")
    verified = _verify_request_artifacts(repo, manifest, chunk_dir)
    headers = _parse_request_manifest(manifest.read_text(encoding="utf-8"))

    _require_hex_sha(args.publish_base_commit, name="publish base commit SHA")
    _require_hex_sha(args.publish_base_tree, name="publish base tree SHA")
    chunks_tree = args.chunks_tree or headers["chunks-tree-git-oid"]
    _require_hex_sha(chunks_tree, name="chunks tree SHA")
    if chunks_tree != headers["chunks-tree-git-oid"]:
        raise PublishStateError(
            "chunks tree does not match prepared request: "
            f"expected={headers['chunks-tree-git-oid']} actual={chunks_tree}"
        )

    if args.transport_commit:
        if not args.transport_root_tree:
            raise PublishStateError("--transport-commit requires --transport-root-tree")
        _require_hex_sha(args.transport_root_tree, name="transport root tree SHA")
        _require_hex_sha(args.transport_commit, name="transport commit SHA")
        result = {
            "status": "ready",
            "stage": "update-publish-ref",
            "request_id": headers["request-id"],
            "action": "GitHub.update_ref",
            "action_args": {
                "repository_full_name": args.github_repository,
                "branch_name": args.publish_branch,
                "sha": args.transport_commit,
                "force": False,
            },
            "request_verified": bool(verified["verified"]),
        }
    elif args.transport_root_tree:
        _require_hex_sha(args.transport_root_tree, name="transport root tree SHA")
        result = {
            "status": "ready",
            "stage": "create-transport-commit",
            "request_id": headers["request-id"],
            "action": "GitHub.create_commit",
            "action_args": {
                "repository_full_name": args.github_repository,
                "message": f"Publish request {headers['request-id']}",
                "tree_sha": args.transport_root_tree,
                "parent_sha": args.publish_base_commit,
            },
            "request_verified": bool(verified["verified"]),
        }
    else:
        result = {
            "status": "ready",
            "stage": "create-transport-root-tree",
            "request_id": headers["request-id"],
            "action": "GitHub.create_tree",
            "action_args": {
                "repository_full_name": args.github_repository,
                "base_tree_sha": args.publish_base_tree,
                "tree_elements": [
                    {
                        "path": ".publish/chunks",
                        "mode": "040000",
                        "type": "tree",
                        "sha": chunks_tree,
                    },
                    {
                        "path": ".publish/request.patch",
                        "mode": "100644",
                        "type": "blob",
                        "content": manifest.read_text(encoding="utf-8"),
                    },
                ],
            },
            "request_verified": bool(verified["verified"]),
        }
    print(json.dumps(result, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    chunk_dir = Path(args.chunk_dir).resolve() if args.chunk_dir else Path(f"{manifest}.chunks")
    result = _verify_request_artifacts(repo, manifest, chunk_dir)
    print(json.dumps(result, indent=2))
    return 0

def cmd_verify_transport(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    chunk_dir = Path(args.chunk_dir).resolve() if args.chunk_dir else Path(f"{manifest}.chunks")
    local = _verify_request_artifacts(repo, manifest, chunk_dir)
    headers = _parse_request_manifest(manifest.read_text(encoding="utf-8"))
    actual = args.remote_chunks_tree
    if args.batch_end_chunk is None:
        expected = headers["chunks-tree-git-oid"]
        scope = "complete"
    else:
        chunk_count = int(headers["chunk-count"])
        if not 0 <= args.batch_end_chunk < chunk_count:
            raise PublishStateError(
                f"batch end chunk must be within 0..{chunk_count - 1}"
            )
        chunks = [
            (chunk_dir / f"{index:04d}.txt").read_text(encoding="ascii")
            for index in range(args.batch_end_chunk + 1)
        ]
        expected = _chunks_tree_oid(repo, chunks)
        scope = f"through chunk {args.batch_end_chunk:04d}"
    if actual != expected:
        raise PublishStateError(
            f"transport chunks tree does not match prepared request ({scope}): "
            f"expected={expected} actual={actual}"
        )
    print(
        json.dumps(
            {
                "manifest": str(manifest),
                "scope": scope,
                "expected_chunks_tree_git_oid": expected,
                "remote_chunks_tree_git_oid": actual,
                "request_verified": bool(local["verified"]),
                "verified": True,
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
        raise PublishStateError(
            f"could not resolve exactly one remote head for {remote}:{branch}"
        )
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
    working_tree_clean = _working_tree_clean(repo)
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
                "working_tree_clean": working_tree_clean,
                "uncommitted_changes_excluded": not working_tree_clean,
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
        "target_branch",
        "base_commit",
        "target_tree",
        "chunks_tree_git_oid",
        "published_commit",
        "published_tree",
    }
    missing = required - data.keys()
    if missing:
        raise PublishStateError(f"invalid publish receipt: missing fields {sorted(missing)}")
    if data["version"] not in {1, 2}:
        raise PublishStateError(f"unsupported publish receipt version: {data['version']}")
    for key in ("base_commit", "target_tree", "published_commit", "published_tree"):
        value = data[key]
        if not isinstance(value, str) or len(value) != 40:
            raise PublishStateError(f"invalid publish receipt {key}")
        try:
            int(value, 16)
        except ValueError as exc:
            raise PublishStateError(f"invalid publish receipt {key}") from exc
    request_id = data["request_id"]
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise PublishStateError("invalid publish receipt request_id")
    try:
        int(request_id, 16)
    except ValueError as exc:
        raise PublishStateError("invalid publish receipt request_id") from exc
    chunks_tree_oid = data["chunks_tree_git_oid"]
    if not isinstance(chunks_tree_oid, str) or len(chunks_tree_oid) not in {40, 64}:
        raise PublishStateError("invalid publish receipt chunks_tree_git_oid")
    try:
        int(chunks_tree_oid, 16)
    except ValueError as exc:
        raise PublishStateError("invalid publish receipt chunks_tree_git_oid") from exc
    if data["target_branch"] not in {"develop", "temp"}:
        raise PublishStateError("invalid publish receipt target_branch")
    return data



def _import_receipt_commit_object(repo: Path, receipt: dict[str, object]) -> dict[str, bool]:
    encoded = receipt.get("published_commit_object_b64")
    if encoded is None:
        return {"receipt_commit_object_imported": False}
    if not isinstance(encoded, str) or not encoded:
        raise PublishStateError("invalid publish receipt published_commit_object_b64")
    try:
        raw = base64.b64decode(encoded, validate=True)
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
    working_tree_clean = _working_tree_clean(repo)
    state = _read_state(repo)
    local_head = _git("rev-parse", args.local_ref, cwd=repo)
    local_tree = _git("rev-parse", f"{args.local_ref}^{{tree}}", cwd=repo)

    if args.receipt:
        if not args.manifest:
            raise PublishStateError("--receipt requires --manifest")
        if args.remote_commit or args.remote_tree:
            raise PublishStateError("use either --receipt or --remote-commit/--remote-tree, not both")
        manifest = Path(args.manifest).resolve()
        chunk_dir = Path(args.chunk_dir).resolve() if args.chunk_dir else Path(f"{manifest}.chunks")
        verified = _verify_request_artifacts(repo, manifest, chunk_dir)
        headers = _parse_request_manifest(manifest.read_text(encoding="utf-8"))
        receipt = _read_publish_receipt(Path(args.receipt).resolve())
        receipt_object_checks = _import_receipt_commit_object(repo, receipt)
        remote_commit = str(receipt["published_commit"])
        remote_tree = str(receipt["published_tree"])
        checks: dict[str, bool] = {
            "request_verified": bool(verified["verified"]),
            "receipt_request_matches_manifest": receipt["request_id"] == headers["request-id"],
            "receipt_branch_matches_manifest": receipt["target_branch"] == headers["target-branch"],
            "receipt_base_matches_recorded_remote": receipt["base_commit"] == state["remote_commit"],
            "receipt_base_matches_manifest": receipt["base_commit"] == headers["base-sha"],
            "receipt_target_matches_manifest": receipt["target_tree"] == headers["target-tree"],
            "receipt_chunks_tree_matches_manifest": receipt["chunks_tree_git_oid"] == headers["chunks-tree-git-oid"],
            "published_tree_matches_receipt_target": remote_tree == receipt["target_tree"],
            "published_tree_matches_local_tree": remote_tree == local_tree,
            "remote_commit_advanced": remote_commit != state["remote_commit"],
        }
        if headers["version"] == "4":
            checks["published_commit_matches_manifest"] = remote_commit == headers["publish-commit"]
        checks.update({name: passed for name, passed in receipt_object_checks.items() if passed})
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise PublishStateError("publish receipt verification failed: " + ", ".join(failed))
    else:
        if not args.remote_commit or not args.remote_tree:
            raise PublishStateError(
                "record requires --receipt with --manifest, or both --remote-commit and --remote-tree"
            )
        remote_commit = args.remote_commit
        remote_tree = args.remote_tree
        checks = {"remote_tree_matches_local_tree": remote_tree == local_tree}
        if not checks["remote_tree_matches_local_tree"]:
            raise PublishStateError(
                f"published tree does not match local target tree: local={local_tree} remote={remote_tree}"
            )
        if args.manifest:
            manifest = Path(args.manifest).resolve()
            chunk_dir = Path(args.chunk_dir).resolve() if args.chunk_dir else Path(f"{manifest}.chunks")
            verified = _verify_request_artifacts(repo, manifest, chunk_dir)
            headers = _parse_request_manifest(manifest.read_text(encoding="utf-8"))
            checks.update(
                {
                    "request_verified": bool(verified["verified"]),
                    "request_base_matches_recorded_remote": headers["base-sha"] == state["remote_commit"],
                    "request_target_matches_local_tree": headers["target-tree"] == local_tree,
                    "request_target_matches_remote_tree": headers["target-tree"] == remote_tree,
                    "remote_commit_advanced": remote_commit != state["remote_commit"],
                }
            )
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
                "working_tree_clean": working_tree_clean,
                "uncommitted_changes_excluded": not working_tree_clean,
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
    parser.add_argument("--repo", default=".", help="repository path (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize state from a verified source artifact")
    init.add_argument("--remote-commit", required=True)
    init.add_argument("--remote-tree", required=True)
    init.add_argument("--local-ref", default="HEAD")
    init.set_defaults(func=cmd_init)

    native_publish = sub.add_parser(
        "native-publish",
        help="publish a local target tree directly with authenticated native Git and verify the remote tree",
    )
    native_publish.add_argument("--target-branch", choices=("develop", "temp"), default="develop")
    native_publish.add_argument("--target-ref", default="HEAD", help="local commit/tree state to publish (default: HEAD)")
    native_publish.add_argument("--remote", default="origin", help="authenticated Git remote name or URL (default: origin)")
    native_publish.add_argument("--message", help="remote commit message; defaults to the local checkpoint message")
    native_publish.set_defaults(func=cmd_native_publish)

    plan = sub.add_parser("plan", help="estimate combined and per-local-commit publish transport")
    plan.add_argument("--target-ref", default="HEAD", help="local ref/tree state to inspect (default: HEAD)")
    plan.add_argument(
        "--transport",
        choices=("bundle", "patch"),
        default="bundle",
        help="transport format to estimate (default: bundle; patch is compatibility fallback)",
    )
    plan.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Base64 characters per transport chunk (default: {DEFAULT_CHUNK_SIZE})",
    )
    plan.set_defaults(func=cmd_plan)

    prepare = sub.add_parser("prepare", help="generate one exact-tree publish gateway request")
    prepare.add_argument("--target-branch", choices=("develop", "temp"), default="develop")
    prepare.add_argument(
        "--transport",
        choices=("bundle", "patch"),
        default="bundle",
        help="payload transport (default: bundle; patch is compatibility fallback)",
    )
    prepare.add_argument("--target-ref", default="HEAD", help="local ref/tree state to publish (default: HEAD)")
    prepare.add_argument("--message", help="remote commit message; defaults to the current local commit message")
    prepare.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=(
            "maximum Base64 characters per transport chunk "
            f"(default: {DEFAULT_CHUNK_SIZE}; keep near Connector-safe request sizes)"
        ),
    )
    prepare.add_argument(
        "--connector-call-budget-bytes",
        type=int,
        default=DEFAULT_CONNECTOR_CALL_BUDGET_BYTES,
        help=(
            "maximum serialized Connector create_tree request size used for automatic packing "
            f"(default: {DEFAULT_CONNECTOR_CALL_BUDGET_BYTES})"
        ),
    )
    prepare.add_argument("--output")
    prepare.set_defaults(func=cmd_prepare)

    connector_plan = sub.add_parser(
        "connector-plan",
        help="generate a minimum-call direct publish-root transport plan with automatic parallel overflow groups",
    )
    connector_plan.add_argument("--manifest", required=True)
    connector_plan.add_argument("--github-repository", required=True)
    connector_plan.add_argument("--chunk-dir")
    connector_plan.add_argument("--output-dir")
    connector_plan.add_argument(
        "--publish-base-commit",
        help="current publish branch commit; with --publish-base-tree pre-generates the root-tree mutation",
    )
    connector_plan.add_argument(
        "--publish-base-tree",
        help="current publish branch tree; with --publish-base-commit pre-generates the root-tree mutation",
    )
    connector_plan.add_argument(
        "--target-remote-head",
        help="current target branch HEAD from the required pre-publish remote probe; must match manifest base-sha",
    )
    connector_plan.add_argument("--publish-branch", default="publish")
    connector_plan.add_argument(
        "--connector-call-budget-bytes",
        type=int,
        help=(
            "override the serialized Connector call budget; defaults to the value recorded by prepare"
        ),
    )
    connector_plan.set_defaults(func=cmd_connector_plan)

    connector_publish = sub.add_parser(
        "connector-publish-step",
        help="emit the next GitHub mutation for root tree, transport commit, or non-force ref update",
    )
    connector_publish.add_argument("--manifest", required=True)
    connector_publish.add_argument("--github-repository", required=True)
    connector_publish.add_argument("--publish-branch", default="publish")
    connector_publish.add_argument("--publish-base-commit", required=True)
    connector_publish.add_argument("--publish-base-tree", required=True)
    connector_publish.add_argument(
        "--chunks-tree",
        help="prepared chunks tree OID; defaults to the manifest OID so normal flow needs no upload result handoff",
    )
    connector_publish.add_argument("--transport-root-tree")
    connector_publish.add_argument("--transport-commit")
    connector_publish.add_argument("--chunk-dir")
    connector_publish.set_defaults(func=cmd_connector_publish_step)

    verify = sub.add_parser("verify", help="verify a generated request recreates its exact target tree")
    verify.add_argument("--manifest", required=True, help="generated request manifest path")
    verify.add_argument(
        "--chunk-dir",
        help="payload chunk directory (default: <manifest>.chunks)",
    )
    verify.set_defaults(func=cmd_verify)

    verify_transport = sub.add_parser(
        "verify-transport",
        help="verify a remote chunks subtree OID matches the prepared request before publishing its ref",
    )
    verify_transport.add_argument("--manifest", required=True, help="generated request manifest path")
    verify_transport.add_argument("--remote-chunks-tree", required=True, help="Git OID returned for the remote chunks subtree")
    verify_transport.add_argument(
        "--batch-end-chunk",
        type=int,
        help="verify the cumulative transport tree only through this zero-based chunk index",
    )
    verify_transport.add_argument(
        "--chunk-dir",
        help="payload chunk directory (default: <manifest>.chunks)",
    )
    verify_transport.set_defaults(func=cmd_verify_transport)

    record = sub.add_parser("record", help="verify a publish receipt and advance the recorded remote state")
    record.add_argument("--remote-commit", help="published remote commit (manual/fallback mode)")
    record.add_argument("--remote-tree", help="published remote tree (manual/fallback mode)")
    record.add_argument("--receipt", help="Gateway receipt JSON; preferred standard mode")
    record.add_argument("--local-ref", default="HEAD", help="local ref whose tree was published (default: HEAD)")
    record.add_argument(
        "--manifest",
        help="prepared request manifest; when supplied, verify the full publish receipt before recording",
    )
    record.add_argument(
        "--chunk-dir",
        help="payload chunk directory for --manifest (default: <manifest>.chunks)",
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
