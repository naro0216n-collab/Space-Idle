#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

GITHUB_REPOSITORY = "naro0216n-collab/Space-Idle"
TARGET_BRANCH = "publish"
TRANSACTION_DIR_NAME = "space-idle-publish-control-maintenance-transaction"
MANIFEST_NAME = "manifest.json"
CONNECTOR_DIR_NAME = "connector"
STATE_NAME = "state.json"
SUMMARY_NAME = "summary.json"
MANIFEST_VERSION = 1
CONNECTOR_CALL_HARD_CEILING_BYTES = 144 * 1024
CONTROL_PATHS = (
    ".github/workflows/publish-gateway.yml",
    "scripts/publish_gateway_payload.py",
    "scripts/publish_gateway_validate.py",
)


class ControlMaintenanceError(RuntimeError):
    pass


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _repo() -> Path:
    cwd = Path.cwd().resolve()
    return Path(_git("rev-parse", "--show-toplevel", cwd=cwd)).resolve()


def _git_dir(repo: Path) -> Path:
    raw = _git("rev-parse", "--git-dir", cwd=repo)
    path = Path(raw)
    return path if path.is_absolute() else repo / path


def _transaction_dir(repo: Path) -> Path:
    return _git_dir(repo) / TRANSACTION_DIR_NAME


def _manifest_path(repo: Path) -> Path:
    return _transaction_dir(repo) / MANIFEST_NAME


def _connector_dir(repo: Path) -> Path:
    return _transaction_dir(repo) / CONNECTOR_DIR_NAME


def _state_path(repo: Path) -> Path:
    return _connector_dir(repo) / STATE_NAME


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ControlMaintenanceError(f"required control maintenance state is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlMaintenanceError(f"invalid control maintenance state: {path}")
    return value


def _require_sha(value: str, *, name: str) -> str:
    if len(value) not in {40, 64}:
        raise ControlMaintenanceError(f"invalid {name}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ControlMaintenanceError(f"invalid {name}") from exc
    return value


def _packet_bytes(packet: dict[str, object]) -> int:
    return len(json.dumps(packet["action_args"], separators=(",", ":")).encode("utf-8"))


def _write_packet(path: Path, packet: dict[str, object]) -> int:
    size = _packet_bytes(packet)
    if size >= CONNECTOR_CALL_HARD_CEILING_BYTES:
        raise ControlMaintenanceError(
            f"control connector call exceeds 144 KiB hard ceiling: {path.name} ({size} bytes)"
        )
    _write_json(path, packet)
    return size


def _require_clean(repo: Path) -> None:
    if _git("status", "--porcelain", cwd=repo):
        raise ControlMaintenanceError("publish control maintenance requires a clean worktree")


def _head_entry(repo: Path, path: str) -> tuple[str, str, str]:
    output = _git("ls-tree", "HEAD", "--", path, cwd=repo)
    if not output:
        raise ControlMaintenanceError(f"publish control file is not committed at HEAD: {path}")
    metadata, actual_path = output.split("\t", 1)
    if actual_path != path:
        raise ControlMaintenanceError(f"unexpected Git path while reading {path}")
    mode, object_type, oid = metadata.split()
    if object_type != "blob":
        raise ControlMaintenanceError(f"publish control path is not a blob: {path}")
    content = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=repo)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ControlMaintenanceError(f"publish control file must be UTF-8 text: {path}") from exc
    return mode, oid, text


def _load_manifest(repo: Path) -> dict[str, object]:
    manifest = _read_json(_manifest_path(repo))
    if manifest.get("version") != MANIFEST_VERSION or manifest.get("kind") != "publish-control-maintenance":
        raise ControlMaintenanceError("unsupported publish control maintenance manifest")
    return manifest


def _load_state(repo: Path) -> dict[str, object]:
    return _read_json(_state_path(repo))


def _summary(repo: Path, state: dict[str, object], **extra: object) -> dict[str, object]:
    result = {
        "strategy": "publish-control-staged-git-data",
        "stage": state["stage"],
        "target_branch": TARGET_BRANCH,
        "base_commit": state.get("base_commit"),
        "base_tree": state.get("base_tree"),
        **extra,
    }
    _write_json(_connector_dir(repo) / SUMMARY_NAME, result)
    return result


def cmd_prepare(_: argparse.Namespace) -> int:
    repo = _repo()
    _require_clean(repo)
    transaction = _transaction_dir(repo)
    if transaction.exists() and any(transaction.iterdir()):
        raise ControlMaintenanceError(
            "an active publish control maintenance transaction already exists; continue it"
        )
    files: list[dict[str, object]] = []
    for path in CONTROL_PATHS:
        mode, oid, text = _head_entry(repo, path)
        files.append({"path": path, "mode": mode, "blob_oid": oid, "content": text})
    manifest = {
        "version": MANIFEST_VERSION,
        "kind": "publish-control-maintenance",
        "target_branch": TARGET_BRANCH,
        "local_head": _git("rev-parse", "HEAD^{commit}", cwd=repo),
        "message": "Update publish gateway control plane",
        "files": files,
    }
    transaction.mkdir(parents=True, exist_ok=False)
    _write_json(_manifest_path(repo), manifest)
    print(json.dumps({
        "prepared": True,
        "target_branch": TARGET_BRANCH,
        "local_head": manifest["local_head"],
        "control_paths": list(CONTROL_PATHS),
        "next": "fetch publish HEAD and tree once, then run connector-plan",
    }, indent=2))
    return 0


def cmd_connector_plan(args: argparse.Namespace) -> int:
    repo = _repo()
    manifest = _load_manifest(repo)
    base_commit = _require_sha(args.target_remote_head, name="publish HEAD")
    base_tree = _require_sha(args.target_remote_tree, name="publish tree")
    connector = _connector_dir(repo)
    if _state_path(repo).exists():
        raise ControlMaintenanceError("publish control connector plan already exists; continue its stage")
    connector.mkdir(parents=True, exist_ok=True)

    packets: list[str] = []
    packet_sizes: list[int] = []
    for index, file in enumerate(manifest["files"]):
        packet = {
            "action": "GitHub.create_blob",
            "action_args": {
                "repository_full_name": GITHUB_REPOSITORY,
                "content": file["content"],
                "encoding": "utf-8",
            },
            "control_path": file["path"],
            "expected_blob_git_oid": file["blob_oid"],
        }
        path = connector / f"upload-control-{index:04d}.json"
        packet_sizes.append(_write_packet(path, packet))
        packets.append(str(path))

    state = {
        "version": 1,
        "stage": "uploads-planned",
        "base_commit": base_commit,
        "base_tree": base_tree,
        "upload_packets": packets,
    }
    _write_json(_state_path(repo), state)
    result = _summary(
        repo,
        state,
        upload_packets=packets,
        upload_call_bytes=packet_sizes,
        next="copy/paste each generated blob packet action_args into GitHub.create_blob; pass returned path=SHA values to connector-tree",
    )
    print(json.dumps(result, indent=2))
    return 0


def _parse_observed_blobs(values: list[str]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ControlMaintenanceError("--blob must be PATH=SHA")
        path, sha = value.rsplit("=", 1)
        if not path or path in observed:
            raise ControlMaintenanceError(f"invalid or duplicate observed blob path: {path}")
        observed[path] = _require_sha(sha, name=f"blob SHA for {path}")
    return observed


def cmd_connector_tree(args: argparse.Namespace) -> int:
    repo = _repo()
    manifest = _load_manifest(repo)
    state = _load_state(repo)
    if state.get("stage") != "uploads-planned":
        raise ControlMaintenanceError(f"connector-tree requires uploads-planned, found {state.get('stage')}")
    observed = _parse_observed_blobs(args.blob)
    expected = {str(file["path"]): str(file["blob_oid"]) for file in manifest["files"]}
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise ControlMaintenanceError(f"observed blob set mismatch; missing={missing}, extra={extra}")
    for path, expected_oid in expected.items():
        if observed[path] != expected_oid:
            raise ControlMaintenanceError(
                f"control blob OID mismatch for {path}: expected {expected_oid}, got {observed[path]}"
            )

    elements = [
        {"path": file["path"], "mode": file["mode"], "type": "blob", "sha": file["blob_oid"]}
        for file in manifest["files"]
    ]
    packet = {
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "base_tree_sha": state["base_tree"],
            "tree_elements": elements,
        },
    }
    packet_path = _connector_dir(repo) / "assemble-control-tree.json"
    size = _write_packet(packet_path, packet)
    state["stage"] = "tree-packet-ready"
    state["tree_packet"] = str(packet_path)
    _write_json(_state_path(repo), state)
    result = _summary(
        repo, state, tree_packet=str(packet_path), tree_call_bytes=size,
        next="copy/paste the tree packet action_args into GitHub.create_tree; pass the returned tree SHA to connector-commit",
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_connector_commit(args: argparse.Namespace) -> int:
    repo = _repo()
    manifest = _load_manifest(repo)
    state = _load_state(repo)
    if state.get("stage") != "tree-packet-ready":
        raise ControlMaintenanceError(f"connector-commit requires tree-packet-ready, found {state.get('stage')}")
    tree_sha = _require_sha(args.tree_sha, name="created control tree SHA")
    packet = {
        "action": "GitHub.create_commit",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "message": manifest["message"],
            "tree_sha": tree_sha,
            "parent_sha": state["base_commit"],
        },
    }
    packet_path = _connector_dir(repo) / "create-control-commit.json"
    _write_packet(packet_path, packet)
    state["stage"] = "commit-packet-ready"
    state["created_tree"] = tree_sha
    state["commit_packet"] = str(packet_path)
    _write_json(_state_path(repo), state)
    result = _summary(
        repo, state, commit_packet=str(packet_path),
        next="copy/paste the commit packet action_args into GitHub.create_commit; fetch that commit once and pass its SHA/tree/parent to connector-update",
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_connector_update(args: argparse.Namespace) -> int:
    repo = _repo()
    state = _load_state(repo)
    if state.get("stage") != "commit-packet-ready":
        raise ControlMaintenanceError(f"connector-update requires commit-packet-ready, found {state.get('stage')}")
    commit_sha = _require_sha(args.commit_sha, name="created control commit SHA")
    commit_tree = _require_sha(args.commit_tree_sha, name="created control commit tree SHA")
    commit_parent = _require_sha(args.commit_parent_sha, name="created control commit parent SHA")
    if commit_tree != state["created_tree"]:
        raise ControlMaintenanceError(
            f"created control commit tree mismatch: expected {state['created_tree']}, got {commit_tree}"
        )
    if commit_parent != state["base_commit"]:
        raise ControlMaintenanceError(
            f"created control commit parent mismatch: expected {state['base_commit']}, got {commit_parent}"
        )
    packet = {
        "action": "GitHub.update_ref",
        "action_args": {
            "repository_full_name": GITHUB_REPOSITORY,
            "branch_name": TARGET_BRANCH,
            "sha": commit_sha,
            "force": False,
        },
    }
    packet_path = _connector_dir(repo) / "advance-publish-control-ref.json"
    _write_packet(packet_path, packet)
    state["stage"] = "update-packet-ready"
    state["published_commit_candidate"] = commit_sha
    state["update_packet"] = str(packet_path)
    _write_json(_state_path(repo), state)
    result = _summary(
        repo, state, update_packet=str(packet_path),
        next="copy/paste the ref packet action_args into GitHub.update_ref; fetch publish HEAD/tree once and pass them to verify-remote",
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_verify_remote(args: argparse.Namespace) -> int:
    repo = _repo()
    state = _load_state(repo)
    if state.get("stage") != "update-packet-ready":
        raise ControlMaintenanceError(f"verify-remote requires update-packet-ready, found {state.get('stage')}")
    remote_head = _require_sha(args.remote_head, name="remote publish HEAD")
    remote_tree = _require_sha(args.remote_tree, name="remote publish tree")
    if remote_head != state["published_commit_candidate"]:
        raise ControlMaintenanceError(
            f"remote publish HEAD mismatch: expected {state['published_commit_candidate']}, got {remote_head}"
        )
    if remote_tree != state["created_tree"]:
        raise ControlMaintenanceError(
            f"remote publish tree mismatch: expected {state['created_tree']}, got {remote_tree}"
        )
    result = {
        "verified": True,
        "target_branch": TARGET_BRANCH,
        "published_commit": remote_head,
        "published_tree": remote_tree,
    }
    shutil.rmtree(_transaction_dir(repo))
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain the fixed Publish Gateway control plane on the publish branch."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").set_defaults(func=cmd_prepare)

    plan = sub.add_parser("connector-plan")
    plan.add_argument("--target-remote-head", required=True)
    plan.add_argument("--target-remote-tree", required=True)
    plan.set_defaults(func=cmd_connector_plan)

    tree = sub.add_parser("connector-tree")
    tree.add_argument("--blob", action="append", required=True, help="Observed create_blob result as PATH=SHA")
    tree.set_defaults(func=cmd_connector_tree)

    commit = sub.add_parser("connector-commit")
    commit.add_argument("--tree-sha", required=True)
    commit.set_defaults(func=cmd_connector_commit)

    update = sub.add_parser("connector-update")
    update.add_argument("--commit-sha", required=True)
    update.add_argument("--commit-tree-sha", required=True)
    update.add_argument("--commit-parent-sha", required=True)
    update.set_defaults(func=cmd_connector_update)

    verify = sub.add_parser("verify-remote")
    verify.add_argument("--remote-head", required=True)
    verify.add_argument("--remote-tree", required=True)
    verify.set_defaults(func=cmd_verify_remote)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (ControlMaintenanceError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
