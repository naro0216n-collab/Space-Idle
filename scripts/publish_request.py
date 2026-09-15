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
MANIFEST_VERSION = 8
CONNECTOR_CALL_BUDGET_BYTES = 144 * 1024
TRANSPORT_CHUNK_BYTES = 16 * 1024
MAX_PAYLOAD_PARTS = 256
CONNECTOR_STATE_NAME = "connector-state.json"
CONNECTOR_STATE_VERSION = 10
CONNECTOR_SUMMARY_NAME = "summary.json"
TRANSACTION_DIR_NAME = "space-idle-publish-transaction"
WORKFLOW_TRANSACTION_DIR_NAME = "space-idle-workflow-maintenance-transaction"
MANIFEST_NAME = "manifest.json"
CONNECTOR_DIR_NAME = "connector"
PUBLISH_BUNDLE_REF = "refs/space-idle/publish-request"
PUBLISH_IDENTITY_NAME = "space-idle-publish-gateway"
PUBLISH_IDENTITY_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
GITHUB_REPOSITORY = "naro0216n-collab/Space-Idle"
PUBLISH_BRANCH = "publish"
TARGET_BRANCH = "develop"
ALLOWED_TRANSPORT_TARGETS = ("develop", "temp")
TRUSTED_CONTROL_WORKFLOW = ".github/workflows/publish-gateway.yml"


class PublishStateError(RuntimeError):
    pass


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _git_bytes(*args: str, cwd: Path) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def _git_dir(repo: Path) -> Path:
    raw = _git("rev-parse", "--git-dir", cwd=repo)
    path = Path(raw)
    return path if path.is_absolute() else repo / path


def _repo_from_cwd() -> Path:
    cwd = Path.cwd().resolve()
    return Path(_git("rev-parse", "--show-toplevel", cwd=cwd)).resolve()


def _state_path(repo: Path) -> Path:
    return _git_dir(repo) / STATE_NAME


def _transaction_dir(repo: Path) -> Path:
    return _git_dir(repo) / TRANSACTION_DIR_NAME


def _manifest_path(repo: Path) -> Path:
    return _transaction_dir(repo) / MANIFEST_NAME


def _connector_dir(repo: Path) -> Path:
    return _transaction_dir(repo) / CONNECTOR_DIR_NAME


def _working_tree_clean(repo: Path) -> bool:
    return not bool(_git("status", "--porcelain", cwd=repo))


def _require_hex_sha(value: str, *, name: str) -> str:
    if len(value) not in {40, 64}:
        raise PublishStateError(f"invalid {name}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PublishStateError(f"invalid {name}") from exc
    return value


def _require_object(repo: Path, spec: str, *, name: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", spec], cwd=repo,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PublishStateError(f"{name} is not available locally: {spec}")


def _read_state(repo: Path) -> dict[str, str]:
    marker = _git_dir(repo) / WORKFLOW_REHYDRATE_MARKER_NAME
    if marker.exists():
        raise PublishStateError(
            "workflow maintenance updated develop; restore the latest source-snapshot and run init before normal publish"
        )
    path = _state_path(repo)
    if not path.exists():
        raise PublishStateError("publish state is not initialized; initialize it from the verified source artifact")
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ("remote_commit", "remote_tree", "local_head", "publish_commit", "publish_tree")
    for key in required:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise PublishStateError(f"invalid publish state: missing {key}")
        _require_hex_sha(value, name=f"publish state {key}")
    return {key: str(data[key]) for key in required}


def _write_state(
    repo: Path, *, remote_commit: str, remote_tree: str, local_head: str,
    publish_commit: str, publish_tree: str,
) -> None:
    _state_path(repo).write_text(
        json.dumps(
            {
                "remote_commit": remote_commit,
                "remote_tree": remote_tree,
                "local_head": local_head,
                "publish_commit": publish_commit,
                "publish_tree": publish_tree,
            },
            indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


def _require_no_active_transaction(repo: Path) -> None:
    transaction = _transaction_dir(repo)
    if transaction.exists() and any(transaction.iterdir()):
        raise PublishStateError(
            "an active publish transaction already exists; continue or close it before preparing another"
        )


def _changed_workflow_paths(repo: Path, base_commit: str, target_commit: str) -> list[str]:
    output = _git(
        "diff", "--name-only", base_commit, target_commit, "--", ".github/workflows", cwd=repo
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
        ["git", "merge-base", "--is-ancestor", local_head, target_commit], cwd=repo,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if is_ancestor:
        commits = _git("rev-list", "--reverse", f"{local_head}..{target_commit}", cwd=repo).splitlines()
        if len(commits) == 1:
            return _git("show", "-s", "--format=%B", commits[0], cwd=repo).rstrip() + "\n"
    return _git("show", "-s", "--format=%B", target_commit, cwd=repo).rstrip() + "\n"


def _create_publish_commit(
    repo: Path, base_commit: str, target_tree: str, target_commit: str, message: bytes,
) -> str:
    _require_object(repo, f"{base_commit}^{{commit}}", name="recorded develop base commit")
    target_date = _git("show", "-s", "--format=%cI", target_commit, cwd=repo)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": PUBLISH_IDENTITY_NAME,
            "GIT_AUTHOR_EMAIL": PUBLISH_IDENTITY_EMAIL,
            "GIT_AUTHOR_DATE": target_date,
            "GIT_COMMITTER_NAME": PUBLISH_IDENTITY_NAME,
            "GIT_COMMITTER_EMAIL": PUBLISH_IDENTITY_EMAIL,
            "GIT_COMMITTER_DATE": target_date,
        }
    )
    result = subprocess.run(
        ["git", "commit-tree", target_tree, "-p", base_commit], cwd=repo, env=env,
        input=message, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return _require_hex_sha(result.stdout.decode("ascii").strip(), name="publish commit")


def _bundle_bytes(repo: Path, base_commit: str, publish_commit: str) -> bytes:
    old_ref = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", PUBLISH_BUNDLE_REF], cwd=repo,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="space-idle-publish-bundle-") as tmp:
        bundle_path = Path(tmp) / "request.bundle"
        try:
            subprocess.run(
                ["git", "update-ref", PUBLISH_BUNDLE_REF, publish_commit], cwd=repo,
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "bundle", "create", str(bundle_path), PUBLISH_BUNDLE_REF, f"^{base_commit}"],
                cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return bundle_path.read_bytes()
        finally:
            if old_ref:
                subprocess.run(
                    ["git", "update-ref", PUBLISH_BUNDLE_REF, old_ref], cwd=repo,
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            else:
                subprocess.run(
                    ["git", "update-ref", "-d", PUBLISH_BUNDLE_REF], cwd=repo,
                    check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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


def _read_prepared_request(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishStateError(f"invalid prepared publish request: {exc}") from exc
    required = {
        "version", "request_id", "target_branch", "base_sha", "target_tree",
        "publish_commit", "payload_sha256", "payload_encoding", "payload_b64",
        "local_target_commit",
    }
    missing = required - data.keys()
    if missing:
        raise PublishStateError(f"invalid prepared publish request: missing fields {sorted(missing)}")
    if data["version"] != MANIFEST_VERSION:
        raise PublishStateError(f"unsupported prepared request version: {data['version']}")
    request_id = data["request_id"]
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise PublishStateError("invalid prepared request id")
    try:
        int(request_id, 16)
    except ValueError as exc:
        raise PublishStateError("invalid prepared request id") from exc
    if data["target_branch"] != TARGET_BRANCH:
        raise PublishStateError("standard publish targets develop only")
    for key in ("base_sha", "target_tree", "publish_commit", "local_target_commit"):
        if not isinstance(data[key], str):
            raise PublishStateError(f"invalid prepared {key}")
        _require_hex_sha(str(data[key]), name=f"prepared {key}")
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


def _verify_bundle_payload(repo: Path, request: dict[str, object], payload_bytes: bytes) -> dict[str, object]:
    actual_digest = hashlib.sha256(payload_bytes).hexdigest()
    if actual_digest != request["payload_sha256"]:
        raise PublishStateError(
            f"publish bundle sha256 mismatch: expected={request['payload_sha256']} actual={actual_digest}"
        )
    publish_commit = str(request["publish_commit"])
    with tempfile.TemporaryDirectory(prefix="space-idle-publish-bundle-verify-") as tmp:
        bundle_path = Path(tmp) / "request.bundle"
        bundle_path.write_bytes(payload_bytes)
        try:
            subprocess.run(
                ["git", "bundle", "verify", str(bundle_path)], cwd=repo,
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            heads = _git("bundle", "list-heads", str(bundle_path), cwd=repo).splitlines()
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            raise PublishStateError(f"invalid publish bundle: {(stderr or '').strip()}") from exc
    advertised = [line.split(maxsplit=1) for line in heads if line.strip()]
    if advertised != [[publish_commit, PUBLISH_BUNDLE_REF]]:
        raise PublishStateError(
            f"publish bundle advertises unexpected heads: expected={[[publish_commit, PUBLISH_BUNDLE_REF]]} actual={advertised}"
        )
    fields, _ = _parse_commit_object(repo, publish_commit)
    if fields.get("tree", []) != [request["target_tree"]]:
        raise PublishStateError("publish commit tree mismatch")
    if fields.get("parent", []) != [request["base_sha"]]:
        raise PublishStateError("publish commit parent mismatch")
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
        raise PublishStateError("publish request base does not match recorded develop commit")
    local_target = str(request["local_target_commit"])
    if _git("rev-parse", f"{local_target}^{{tree}}", cwd=repo) != request["target_tree"]:
        raise PublishStateError("prepared local target tree mismatch")
    payload = _decode_prepared_payload(request)
    bundle = _verify_bundle_payload(repo, request, payload)
    return {
        "manifest": str(path), "version": MANIFEST_VERSION, "transport": "git-bundle",
        "request_id": request["request_id"], "payload_bytes": bundle["payload_bytes"],
        "payload_chars": len(str(request["payload_b64"])), "payload_sha256": bundle["payload_sha256"],
        "publish_commit": bundle["publish_commit"], "target_tree": bundle["target_tree"], "verified": True,
    }


def _source_snapshot_from_origin(repo: Path) -> Path:
    try:
        origin = _git("remote", "get-url", "origin", cwd=repo)
    except subprocess.CalledProcessError as exc:
        raise PublishStateError("restored repository has no readable origin") from exc
    if origin.startswith("file://"):
        parsed = urlparse(origin)
        if parsed.netloc not in {"", "localhost"}:
            raise PublishStateError("origin must be the local source-snapshot repository.bundle")
        bundle_path = Path(unquote(parsed.path))
    else:
        if "://" in origin or (":" in origin and not Path(origin).is_absolute()):
            raise PublishStateError("origin must point to the local source-snapshot repository.bundle")
        bundle_path = Path(origin)
    bundle_path = (repo / bundle_path).resolve() if not bundle_path.is_absolute() else bundle_path.resolve()
    if bundle_path.name != "repository.bundle" or not bundle_path.is_file():
        raise PublishStateError("origin must point to an existing source-snapshot/repository.bundle")
    return bundle_path.parent


def _read_source_snapshot_metadata(source_snapshot: Path, *, repo: Path) -> dict[str, str]:
    names = (
        ".source-commit", ".source-tree", ".source-branch",
        ".source-publish-commit", ".source-publish-tree", "repository.bundle",
    )
    missing = [name for name in names if not (source_snapshot / name).is_file()]
    if missing:
        raise PublishStateError("source-snapshot directory is incomplete; missing: " + ", ".join(missing))
    values = {
        "remote_commit": (source_snapshot / ".source-commit").read_text(encoding="utf-8").strip(),
        "remote_tree": (source_snapshot / ".source-tree").read_text(encoding="utf-8").strip(),
        "branch": (source_snapshot / ".source-branch").read_text(encoding="utf-8").strip(),
        "publish_commit": (source_snapshot / ".source-publish-commit").read_text(encoding="utf-8").strip(),
        "publish_tree": (source_snapshot / ".source-publish-tree").read_text(encoding="utf-8").strip(),
    }
    for key in ("remote_commit", "remote_tree", "publish_commit", "publish_tree"):
        _require_hex_sha(values[key], name=f"source-snapshot {key}")
    if values["branch"] != TARGET_BRANCH:
        raise PublishStateError(f"source-snapshot branch must be {TARGET_BRANCH!r}, got {values['branch']!r}")
    bundle = source_snapshot / "repository.bundle"
    verify = subprocess.run(
        ["git", "bundle", "verify", str(bundle)], cwd=repo, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if verify.returncode != 0:
        raise PublishStateError("source-snapshot bundle verification failed: " + verify.stderr.strip())
    heads = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)], cwd=source_snapshot,
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.splitlines()
    expected = {
        f"{values['remote_commit']} refs/heads/{TARGET_BRANCH}",
        f"{values['publish_commit']} refs/space-idle/publish-base",
    }
    if not expected.issubset(set(heads)):
        raise PublishStateError("source-snapshot metadata does not match repository.bundle refs")
    return values


def cmd_init(_: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    source_snapshot = _source_snapshot_from_origin(repo)
    metadata = _read_source_snapshot_metadata(source_snapshot, repo=repo)
    local_branch = _git("branch", "--show-current", cwd=repo)
    local_commit = _git("rev-parse", "HEAD^{commit}", cwd=repo)
    local_tree = _git("rev-parse", "HEAD^{tree}", cwd=repo)
    if local_branch != TARGET_BRANCH:
        raise PublishStateError(f"restored repository branch must be {TARGET_BRANCH!r}, got {local_branch!r}")
    if local_commit != metadata["remote_commit"] or local_tree != metadata["remote_tree"]:
        raise PublishStateError("artifact/local develop commit or tree mismatch")
    subprocess.run(
        [
            "git", "fetch", "origin",
            "refs/space-idle/publish-base:refs/space-idle/publish-base",
        ],
        cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    publish_ref = _git("rev-parse", "refs/space-idle/publish-base^{commit}", cwd=repo)
    publish_tree = _git("rev-parse", "refs/space-idle/publish-base^{tree}", cwd=repo)
    if publish_ref != metadata["publish_commit"] or publish_tree != metadata["publish_tree"]:
        raise PublishStateError("artifact/local publish base commit or tree mismatch")
    _write_state(
        repo, remote_commit=local_commit, remote_tree=local_tree, local_head=local_commit,
        publish_commit=publish_ref, publish_tree=publish_tree,
    )
    for path in (
        _transaction_dir(repo), _git_dir(repo) / WORKFLOW_TRANSACTION_DIR_NAME,
    ):
        if path.exists():
            shutil.rmtree(path)
    marker = _git_dir(repo) / WORKFLOW_REHYDRATE_MARKER_NAME
    if marker.exists():
        marker.unlink()
    print(json.dumps({
        "remote_commit": local_commit, "remote_tree": local_tree, "local_head": local_commit,
        "publish_commit": publish_ref, "publish_tree": publish_tree,
    }, indent=2))
    return 0


def cmd_prepare(_: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_state(repo)
    _require_no_active_transaction(repo)
    target_commit = _git("rev-parse", "HEAD^{commit}", cwd=repo)
    target_tree = _git("rev-parse", "HEAD^{tree}", cwd=repo)
    if target_tree == state["remote_tree"]:
        raise PublishStateError("local target tree already matches the last published tree")
    workflow_paths = _changed_workflow_paths(repo, state["remote_commit"], target_commit)
    disallowed = [path for path in workflow_paths if path != TRUSTED_CONTROL_WORKFLOW]
    if disallowed:
        raise PublishStateError(
            "standard Publish Gateway cannot publish untrusted .github/workflows changes; "
            "use `python scripts/workflow_maintenance.py prepare` for workflow-only maintenance: "
            + ", ".join(disallowed)
        )
    publish_commit = _create_publish_commit(
        repo, state["remote_commit"], target_tree, target_commit,
        _message_bytes(_default_message(repo, state, target_commit)),
    )
    payload_bytes = _bundle_bytes(repo, state["remote_commit"], publish_commit)
    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    request = {
        "version": MANIFEST_VERSION,
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
    print(json.dumps({
        "manifest": str(output), "request_id": request["request_id"],
        "transport_slot": f".publish/transport/{TARGET_BRANCH}",
        "payload_bytes": len(payload_bytes), "payload_chars": len(payload_b64),
        "payload_sha256": request["payload_sha256"], "publish_commit": publish_commit,
        "target_tree": target_tree, "local_target_commit": target_commit,
        "working_tree_clean": _working_tree_clean(repo),
        "uncommitted_changes_excluded": not _working_tree_clean(repo),
        "verified": verified["verified"],
    }, indent=2))
    return 0


def _connector_call_bytes(packet: dict[str, object]) -> int:
    args = packet.get("action_args")
    if not isinstance(args, dict):
        raise PublishStateError("Connector packet is missing action_args")
    return len(json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _tree_blob_element(path: str, sha: str) -> dict[str, object]:
    return {"path": path, "mode": "100644", "type": "blob", "sha": sha}


def _tree_delete_element(path: str, *, mode: str = "100644", object_type: str = "blob") -> dict[str, object]:
    return {"path": path, "mode": mode, "type": object_type, "sha": None}


def _tree_packet(base_tree: str, elements: list[dict[str, object]], batch_index: int) -> dict[str, object]:
    return {
        "stage": "assemble-publish-transport-tree",
        "tree_batch_index": batch_index,
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "base_tree_sha": base_tree,
            "tree_elements": elements,
        },
    }


def _blob_packet(content: str, chunk_index: int, path: str) -> dict[str, object]:
    return {
        "stage": "upload-publish-transport-chunk",
        "chunk_index": chunk_index,
        "transport_path": path,
        "action": "GitHub.create_blob",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "content": content,
            "encoding": "utf-8",
        },
    }


def _list_publish_paths(repo: Path, tree: str) -> list[str]:
    _require_object(repo, f"{tree}^{{tree}}", name="publish transport base tree")
    output = _git("ls-tree", "-r", "--name-only", tree, "--", ".publish", cwd=repo)
    return [line for line in output.splitlines() if line]


def _direct_tree_entries(repo: Path, tree: str, directory: str) -> list[dict[str, str]]:
    spec = f"{tree}:{directory}"
    probe = subprocess.run(
        ["git", "cat-file", "-e", spec], cwd=repo,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        return []
    if _git("cat-file", "-t", spec, cwd=repo) != "tree":
        raise PublishStateError(f"publish transport path must be a tree: {directory}")
    output = _git("ls-tree", spec, cwd=repo)
    entries: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        metadata, name = line.split("\t", 1)
        mode, object_type, oid = metadata.split()
        entries.append({"name": name, "mode": mode, "type": object_type, "oid": oid})
    return entries


def _compact_stale_delete_elements(
    repo: Path, *, base_tree: str, target: str, stale: list[str],
) -> list[dict[str, object]]:
    deletes: list[dict[str, object]] = []
    stale_set = set(stale)
    for entry in _direct_tree_entries(repo, base_tree, ".publish"):
        name = entry["name"]
        path = f".publish/{name}"
        if name != "transport":
            deletes.append(
                _tree_delete_element(path, mode=entry["mode"], object_type=entry["type"])
            )
            continue
        if entry["type"] != "tree":
            raise PublishStateError(".publish/transport must be a tree")
        for transport_entry in _direct_tree_entries(repo, base_tree, ".publish/transport"):
            branch = transport_entry["name"]
            branch_path = f".publish/transport/{branch}"
            if branch in ALLOWED_TRANSPORT_TARGETS:
                if transport_entry["type"] != "tree":
                    raise PublishStateError(f"publish transport slot must be a tree: {branch_path}")
                if branch != target:
                    continue
                prefix = branch_path + "/"
                for stale_path in sorted(path for path in stale_set if path.startswith(prefix)):
                    deletes.append(_tree_delete_element(stale_path))
                continue
            deletes.append(
                _tree_delete_element(
                    branch_path, mode=transport_entry["mode"], object_type=transport_entry["type"]
                )
            )
    return deletes


def _payload_chunks(repo: Path, payload: str, *, target_branch: str) -> list[dict[str, object]]:
    slot = f".publish/transport/{target_branch}"
    chunks: list[dict[str, object]] = []
    for start in range(0, len(payload), TRANSPORT_CHUNK_BYTES):
        index = len(chunks)
        content = payload[start:start + TRANSPORT_CHUNK_BYTES]
        path = f"{slot}/{index:04d}.b64"
        chunks.append({
            "chunk_index": index,
            "path": path,
            "content": content,
            "expected_blob": _write_blob(repo, content),
        })
    if not chunks:
        raise PublishStateError("publish payload is empty")
    if len(chunks) > MAX_PAYLOAD_PARTS:
        raise PublishStateError(
            f"publish payload needs {len(chunks)} transport files, exceeding limit {MAX_PAYLOAD_PARTS}"
        )
    return chunks


def _desired_transport_elements(
    repo: Path, prepared: dict[str, object], *, base_tree: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    target = str(prepared["target_branch"])
    chunks = _payload_chunks(repo, str(prepared["payload_b64"]), target_branch=target)
    desired_paths = {str(chunk["path"]) for chunk in chunks}
    current_slot_prefix = f".publish/transport/{target}/"
    allowed_other_prefixes = tuple(
        f".publish/transport/{branch}/" for branch in ALLOWED_TRANSPORT_TARGETS if branch != target
    )
    stale: list[str] = []
    for path in _list_publish_paths(repo, base_tree):
        if path in desired_paths:
            continue
        if path.startswith(current_slot_prefix):
            stale.append(path)
            continue
        if any(path.startswith(prefix) for prefix in allowed_other_prefixes):
            continue
        # The fixed-slot transport owns .publish. Anything outside an allowed slot is obsolete transport state.
        stale.append(path)
    deletes = _compact_stale_delete_elements(
        repo, base_tree=base_tree, target=target, stale=stale
    )
    elements = [
        *[_tree_blob_element(str(chunk["path"]), str(chunk["expected_blob"])) for chunk in chunks],
        *deletes,
    ]
    return chunks, elements, stale


def _pack_tree_elements(base_tree: str, elements: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    batches: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for element in elements:
        candidate = [*current, element]
        if _connector_call_bytes(_tree_packet(base_tree, candidate, len(batches))) <= CONNECTOR_CALL_BUDGET_BYTES:
            current = candidate
            continue
        if not current:
            raise PublishStateError(f"single tree element exceeds Connector ceiling: {element['path']}")
        batches.append(current)
        current = [element]
        if _connector_call_bytes(_tree_packet(base_tree, current, len(batches))) > CONNECTOR_CALL_BUDGET_BYTES:
            raise PublishStateError(f"single tree element exceeds Connector ceiling: {element['path']}")
    if current:
        batches.append(current)
    return batches


def _write_blob(repo: Path, content: str) -> str:
    result = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=repo, input=content.encode("utf-8"),
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return _require_hex_sha(result.stdout.decode("ascii").strip(), name="local transport blob OID")


def _expected_tree_batches(
    repo: Path, *, base_tree: str, batches: list[list[dict[str, object]]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="space-idle-publish-index-") as tmp:
        index_path = Path(tmp) / "index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index_path)
        _git("read-tree", base_tree, cwd=repo, env=env)
        current_tree = base_tree
        for batch_index, elements in enumerate(batches):
            for element in elements:
                path = str(element["path"])
                if "content" in element:
                    oid = _write_blob(repo, str(element["content"]))
                    _git(
                        "update-index", "--add", "--cacheinfo", str(element["mode"]), oid, path,
                        cwd=repo, env=env,
                    )
                elif element.get("sha") is None:
                    if element.get("type") == "tree":
                        indexed = _git("ls-files", "--cached", "--", path, cwd=repo, env=env).splitlines()
                        for indexed_path in indexed:
                            subprocess.run(
                                ["git", "update-index", "--force-remove", "--", indexed_path],
                                cwd=repo, env=env, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            )
                    else:
                        subprocess.run(
                            ["git", "update-index", "--force-remove", "--", path], cwd=repo, env=env,
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        )
                else:
                    _git(
                        "update-index", "--add", "--cacheinfo", str(element["mode"]), str(element["sha"]), path,
                        cwd=repo, env=env,
                    )
            expected_tree = _git("write-tree", cwd=repo, env=env)
            result.append({
                "batch_index": batch_index,
                "base_tree": current_tree,
                "expected_tree": expected_tree,
                "elements": elements,
            })
            current_tree = expected_tree
    return result


def _build_transport_plan(
    repo: Path, prepared: dict[str, object], *, publish_head: str, publish_tree: str,
) -> dict[str, object]:
    chunks, elements, stale = _desired_transport_elements(repo, prepared, base_tree=publish_tree)
    raw_batches = _pack_tree_elements(publish_tree, elements)
    batches = _expected_tree_batches(repo, base_tree=publish_tree, batches=raw_batches)
    return {
        "publish_head": publish_head,
        "publish_tree": publish_tree,
        "target_branch": prepared["target_branch"],
        "transport_chunk_bytes": TRANSPORT_CHUNK_BYTES,
        "payload_part_count": len(chunks),
        "chunks": chunks,
        "stale_transport_path_count": len(stale),
        "stale_transport_paths": stale,
        "batches": batches,
        "tree_call_count": len(batches),
        "final_tree": batches[-1]["expected_tree"],
    }


def _connector_state_path(repo: Path) -> Path:
    return _connector_dir(repo) / CONNECTOR_STATE_NAME


def _write_connector_state(repo: Path, state: dict[str, object]) -> None:
    _connector_state_path(repo).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_connector_state(repo: Path) -> dict[str, object]:
    path = _connector_state_path(repo)
    if not path.exists():
        raise PublishStateError("Connector plan is not initialized; run connector-plan")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != CONNECTOR_STATE_VERSION:
        raise PublishStateError("unsupported Connector state version")
    return state


def _write_summary(repo: Path, summary: dict[str, object]) -> None:
    (_connector_dir(repo) / CONNECTOR_SUMMARY_NAME).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_blob_packet(repo: Path, state: dict[str, object]) -> dict[str, object]:
    plan = state["plan"]
    assert isinstance(plan, dict)
    chunks = plan["chunks"]
    assert isinstance(chunks, list)
    index = int(state["blob_chunk_index"])
    chunk = chunks[index]
    assert isinstance(chunk, dict)
    path_value = str(chunk["path"])
    packet = _blob_packet(str(chunk["content"]), index, path_value)
    call_bytes = _connector_call_bytes(packet)
    if call_bytes > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError("generated create_blob call exceeds Connector hard ceiling")
    path = _connector_dir(repo) / f"blob-chunk-{index:04d}.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state["stage"] = "blob-ready"
    state["blob_packet"] = str(path)
    _write_connector_state(repo, state)
    retry_counts = state.setdefault("blob_retry_counts", {})
    assert isinstance(retry_counts, dict)
    summary = {
        "stage": "blob-ready",
        "request_id": state["request_id"],
        "chunk_index": index,
        "chunk_count": len(chunks),
        "chunk_bytes": len(str(chunk["content"]).encode("utf-8")),
        "blob_call_bytes": call_bytes,
        "blob_packet": str(path),
        "retry_count": int(retry_counts.get(path_value, 0)),
        "integrity_decision": "helper-owned",
        "next": (
            "execute the generated GitHub.create_blob packet and pass only its returned blob SHA to connector-blob; "
            "the helper performs the integrity decision mechanically and emits either the same failed chunk or the next action"
        ),
        "verified": True,
    }
    _write_summary(repo, summary)
    return summary


def _write_tree_packet(repo: Path, state: dict[str, object]) -> dict[str, object]:
    plan = state["plan"]
    assert isinstance(plan, dict)
    chunks = plan["chunks"]
    assert isinstance(chunks, list)
    verified = state.get("verified_blob_shas", {})
    if not isinstance(verified, dict):
        raise PublishStateError("invalid verified blob state")
    for chunk in chunks:
        assert isinstance(chunk, dict)
        path_value = str(chunk["path"])
        if verified.get(path_value) != chunk["expected_blob"]:
            raise PublishStateError(
                f"transport chunk is not machine-verified: {path_value}"
            )
    batches = plan["batches"]
    assert isinstance(batches, list)
    index = int(state["tree_batch_index"])
    batch = batches[index]
    assert isinstance(batch, dict)
    packet = _tree_packet(str(batch["base_tree"]), list(batch["elements"]), index)
    call_bytes = _connector_call_bytes(packet)
    if call_bytes > CONNECTOR_CALL_BUDGET_BYTES:
        raise PublishStateError("generated create_tree call exceeds Connector hard ceiling")
    path = _connector_dir(repo) / f"tree-batch-{index:03d}.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state["stage"] = "tree-ready"
    state["tree_packet"] = str(path)
    _write_connector_state(repo, state)
    summary = {
        "stage": "tree-ready",
        "request_id": state["request_id"],
        "tree_batch_index": index,
        "tree_batch_count": len(batches),
        "tree_call_bytes": call_bytes,
        "tree_packet": str(path),
        "tree_retry_count": int(state.get("tree_retry_count", 0)),
        "integrity_decision": "helper-owned",
        "next": (
            "execute the generated GitHub.create_tree packet and pass only its returned tree SHA to connector-tree; "
            "the helper compares it mechanically with the locally precomputed expected tree and emits the next action"
        ),
        "verified": True,
    }
    _write_summary(repo, summary)
    return summary


def cmd_connector_plan(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    manifest = _manifest_path(repo)
    verified = _verify_prepared_request(repo, manifest)
    prepared = _read_prepared_request(manifest)
    state_base = _read_state(repo)
    target_head = _require_hex_sha(args.target_remote_head, name="observed develop HEAD")
    publish_head = _require_hex_sha(args.publish_remote_head, name="observed publish HEAD")
    if target_head != prepared["base_sha"] or target_head != state_base["remote_commit"]:
        raise PublishStateError(
            f"develop HEAD moved since prepare: expected={prepared['base_sha']} actual={target_head}"
        )
    if publish_head != state_base["publish_commit"]:
        raise PublishStateError(
            "publish transport HEAD moved since source state; refresh the publish base through the standard control/publish path: "
            f"expected={state_base['publish_commit']} actual={publish_head}"
        )
    _require_object(repo, f"{state_base['publish_tree']}^{{tree}}", name="recorded publish base tree")
    output = _connector_dir(repo)
    if output.exists() and any(output.iterdir()):
        raise PublishStateError("Connector plan already exists; continue its current stage")
    output.mkdir(parents=True, exist_ok=True)
    plan = _build_transport_plan(
        repo, prepared, publish_head=publish_head, publish_tree=state_base["publish_tree"]
    )
    state: dict[str, object] = {
        "version": CONNECTOR_STATE_VERSION,
        "stage": "blob-ready",
        "request_id": prepared["request_id"],
        "target_remote_head": target_head,
        "publish_base_head": publish_head,
        "publish_base_tree": state_base["publish_tree"],
        "blob_chunk_index": 0,
        "blob_retry_counts": {},
        "verified_blob_shas": {},
        "tree_batch_index": 0,
        "tree_retry_count": 0,
        "plan": plan,
        "request_verified": bool(verified["verified"]),
    }
    summary = _write_blob_packet(repo, state)
    summary.update({
        "strategy": "fixed-slot-16kib-blob-verified",
        "connector_call_budget_bytes": CONNECTOR_CALL_BUDGET_BYTES,
        "transport_chunk_bytes": TRANSPORT_CHUNK_BYTES,
        "payload_part_count": plan["payload_part_count"],
        "tree_call_count": plan["tree_call_count"],
        "stale_transport_path_count": plan["stale_transport_path_count"],
        "normal_pre_ref_verification_reads": 0,
        "index_files": 0,
        "trigger_files": 0,
    })
    _write_summary(repo, summary)
    print(json.dumps(summary, indent=2))
    return 0


def _write_commit_packet(repo: Path, state: dict[str, object]) -> dict[str, object]:
    plan = state["plan"]
    assert isinstance(plan, dict)
    request_id = str(state["request_id"])
    final_tree = str(plan["final_tree"])
    packet = {
        "stage": "create-publish-transport-commit",
        "action": "GitHub.create_commit",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "message": f"Publish transport {request_id}",
            "tree_sha": final_tree,
            "parent_sha": state["publish_base_head"],
        },
    }
    path = _connector_dir(repo) / "create-transport-commit.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state["stage"] = "commit-packet-ready"
    state["created_tree"] = final_tree
    state["commit_packet"] = str(path)
    state.pop("tree_packet", None)
    _write_connector_state(repo, state)
    summary = {
        "stage": state["stage"], "request_id": request_id, "commit_packet": str(path),
        "created_tree": final_tree,
        "next": "execute GitHub.create_commit and pass only the returned commit SHA to connector-commit",
        "verified": True,
    }
    _write_summary(repo, summary)
    return summary


def cmd_connector_blob(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_connector_state(repo)
    if state.get("stage") != "blob-ready":
        raise PublishStateError(f"connector-blob requires blob-ready, found {state.get('stage')}")
    actual = _require_hex_sha(args.blob_sha, name="created publish transport blob SHA")
    plan = state["plan"]
    assert isinstance(plan, dict)
    chunks = plan["chunks"]
    assert isinstance(chunks, list)
    index = int(state["blob_chunk_index"])
    chunk = chunks[index]
    assert isinstance(chunk, dict)
    path_value = str(chunk["path"])
    expected = str(chunk["expected_blob"])
    retry_counts = state.setdefault("blob_retry_counts", {})
    verified = state.setdefault("verified_blob_shas", {})
    assert isinstance(retry_counts, dict)
    assert isinstance(verified, dict)
    if actual != expected:
        retry_counts[path_value] = int(retry_counts.get(path_value, 0)) + 1
        state["last_blob_mismatch"] = {
            "chunk_index": index,
            "path": path_value,
            "expected": expected,
            "actual": actual,
        }
        summary = _write_blob_packet(repo, state)
        summary.update({
            "stage": "blob-retry-ready",
            "retry_failed_chunk_only": True,
            "integrity_result": "mismatch",
        })
        _write_summary(repo, summary)
        print(json.dumps(summary, indent=2))
        return 0

    verified[path_value] = actual
    state.pop("last_blob_mismatch", None)
    next_index = index + 1
    if next_index < len(chunks):
        state["blob_chunk_index"] = next_index
        summary = _write_blob_packet(repo, state)
        print(json.dumps(summary, indent=2))
        return 0
    state["tree_batch_index"] = 0
    state["tree_retry_count"] = 0
    state.pop("blob_packet", None)
    summary = _write_tree_packet(repo, state)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_connector_tree(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_connector_state(repo)
    if state.get("stage") != "tree-ready":
        raise PublishStateError(f"connector-tree requires tree-ready, found {state.get('stage')}")
    actual = _require_hex_sha(args.tree_sha, name="created publish transport tree SHA")
    plan = state["plan"]
    assert isinstance(plan, dict)
    batches = plan["batches"]
    assert isinstance(batches, list)
    index = int(state["tree_batch_index"])
    batch = batches[index]
    assert isinstance(batch, dict)
    expected = str(batch["expected_tree"])
    if actual != expected:
        state["tree_retry_count"] = int(state.get("tree_retry_count", 0)) + 1
        state["last_tree_mismatch"] = {"expected": expected, "actual": actual}
        summary = _write_tree_packet(repo, state)
        summary.update({
            "stage": "tree-retry-ready",
            "integrity_result": "mismatch",
        })
        _write_summary(repo, summary)
        print(json.dumps(summary, indent=2))
        return 0
    next_index = index + 1
    state["tree_retry_count"] = 0
    state.pop("last_tree_mismatch", None)
    if next_index < len(batches):
        state["tree_batch_index"] = next_index
        summary = _write_tree_packet(repo, state)
        print(json.dumps(summary, indent=2))
        return 0
    summary = _write_commit_packet(repo, state)
    print(json.dumps(summary, indent=2))
    return 0


def _write_update_packet(repo: Path, state: dict[str, object], commit_sha: str) -> dict[str, object]:
    packet = {
        "stage": "advance-publish-transport-ref",
        "action": "GitHub.update_ref",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "branch_name": PUBLISH_BRANCH,
            "sha": commit_sha,
            "force": False,
        },
    }
    path = _connector_dir(repo) / "advance-publish-ref.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    state["stage"] = "update-packet-ready"
    state["transport_commit_candidate"] = commit_sha
    state["update_packet"] = str(path)
    _write_connector_state(repo, state)
    summary = {
        "stage": state["stage"], "request_id": state["request_id"],
        "update_packet": str(path), "transport_commit_candidate": commit_sha,
        "payload_transport_verified": True,
        "next": (
            "execute the non-force GitHub.update_ref packet. Then observe the Publish Gateway run for this "
            "transport commit; on completed success call record with that run evidence"
        ),
        "verified": True,
    }
    _write_summary(repo, summary)
    return summary


def cmd_connector_commit(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_connector_state(repo)
    if state.get("stage") != "commit-packet-ready":
        raise PublishStateError(f"connector-commit requires commit-packet-ready, found {state.get('stage')}")
    commit_sha = _require_hex_sha(args.commit_sha, name="created publish transport commit SHA")
    summary = _write_update_packet(repo, state, commit_sha)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    manifest = _manifest_path(repo)
    if not manifest.exists():
        raise PublishStateError("no active publish transaction to cancel")
    prepared = _read_prepared_request(manifest)
    state = _read_state(repo)
    connector = _read_connector_state(repo)
    if connector.get("stage") == "update-packet-ready":
        raise PublishStateError("cannot cancel after a publish ref update may have occurred; inspect the Gateway run")
    target_head = _require_hex_sha(args.target_remote_head, name="observed develop HEAD")
    publish_head = _require_hex_sha(args.publish_remote_head, name="observed publish HEAD")
    if target_head != prepared["base_sha"] or target_head != state["remote_commit"]:
        raise PublishStateError("cannot cancel after develop moved")
    if publish_head != connector["publish_base_head"] or publish_head != state["publish_commit"]:
        raise PublishStateError("cannot cancel after publish transport moved")
    shutil.rmtree(_transaction_dir(repo))
    print(json.dumps({
        "cancelled": True, "request_id": prepared["request_id"],
        "target_remote_head": target_head, "publish_remote_head": publish_head, "verified": True,
    }, indent=2))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    state = _read_state(repo)
    prepared = _read_prepared_request(_manifest_path(repo))
    _verify_prepared_request(repo, _manifest_path(repo))
    connector = _read_connector_state(repo)
    if connector.get("stage") != "update-packet-ready":
        raise PublishStateError(f"record requires update-packet-ready, found {connector.get('stage')}")
    transport_commit = _require_hex_sha(args.gateway_transport_commit, name="Gateway transport commit")
    if transport_commit != connector.get("transport_commit_candidate"):
        raise PublishStateError("Gateway run does not correspond to the prepared transport commit")
    if args.gateway_conclusion != "success":
        raise PublishStateError("Gateway run has not completed successfully; keep the active transaction for rerun or diagnosis")
    try:
        run_id = int(args.gateway_run_id)
    except ValueError as exc:
        raise PublishStateError("invalid Gateway run id") from exc
    if run_id <= 0:
        raise PublishStateError("invalid Gateway run id")
    plan = connector["plan"]
    assert isinstance(plan, dict)
    local_target = str(prepared["local_target_commit"])
    _write_state(
        repo,
        remote_commit=str(prepared["publish_commit"]),
        remote_tree=str(prepared["target_tree"]),
        local_head=local_target,
        publish_commit=transport_commit,
        publish_tree=str(plan["final_tree"]),
    )
    shutil.rmtree(_transaction_dir(repo))
    print(json.dumps({
        "remote_commit": prepared["publish_commit"],
        "remote_tree": prepared["target_tree"],
        "local_head": local_target,
        "publish_commit": transport_commit,
        "publish_tree": plan["final_tree"],
        "gateway_run_id": run_id,
        "gateway_conclusion": args.gateway_conclusion,
        "working_tree_clean": _working_tree_clean(repo),
        "uncommitted_changes_excluded": not _working_tree_clean(repo),
        "verified": True,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and track the single standard Space-Idle develop publish transaction."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize state from the source-snapshot bundle and publish base").set_defaults(func=cmd_init)
    sub.add_parser("prepare", help="prepare HEAD as the single active develop publish transaction").set_defaults(func=cmd_prepare)

    plan = sub.add_parser(
        "connector-plan",
        help="plan fixed-slot publish transport after one combined develop/publish ref observation",
    )
    plan.add_argument("--target-remote-head", required=True)
    plan.add_argument("--publish-remote-head", required=True)
    plan.set_defaults(func=cmd_connector_plan)

    blob = sub.add_parser(
        "connector-blob",
        help="mechanically verify one returned transport chunk blob SHA and emit only the next required action",
    )
    blob.add_argument("--blob-sha", required=True)
    blob.set_defaults(func=cmd_connector_blob)

    tree = sub.add_parser(
        "connector-tree",
        help="verify returned create_tree SHA against the locally expected tree and advance or retry",
    )
    tree.add_argument("--tree-sha", required=True)
    tree.set_defaults(func=cmd_connector_tree)

    commit = sub.add_parser(
        "connector-commit",
        help="after the transport commit is created, generate the one non-force publish ref update",
    )
    commit.add_argument("--commit-sha", required=True)
    commit.set_defaults(func=cmd_connector_commit)

    cancel = sub.add_parser("cancel", help="cancel a pre-ref active transaction after one combined ref observation")
    cancel.add_argument("--target-remote-head", required=True)
    cancel.add_argument("--publish-remote-head", required=True)
    cancel.set_defaults(func=cmd_cancel)

    record = sub.add_parser("record", help="close the transaction from one successful Publish Gateway run observation")
    record.add_argument("--gateway-transport-commit", required=True)
    record.add_argument("--gateway-run-id", required=True)
    record.add_argument("--gateway-conclusion", required=True, choices=("success", "failure", "cancelled"))
    record.set_defaults(func=cmd_record)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (PublishStateError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
