#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path

PUBLISH_STATE_NAME = "space-idle-publish-state.json"
REHYDRATE_MARKER_NAME = "space-idle-workflow-maintenance-rehydrate-required"
MANIFEST_VERSION = 1
CONNECTOR_CALL_BUDGET_BYTES = 96 * 1024
CONNECTOR_STATE_NAME = "workflow-maintenance-state.json"
SUMMARY_NAME = "summary.json"
TARGET_BRANCH = "develop"
WORKFLOW_PREFIX = ".github/workflows/"
GITHUB_REPOSITORY = "naro0216n-collab/Space-Idle"


class WorkflowMaintenanceError(RuntimeError):
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


def _publish_state_path(repo: Path) -> Path:
    return _git_dir(repo) / PUBLISH_STATE_NAME


def _rehydrate_marker_path(repo: Path) -> Path:
    return _git_dir(repo) / REHYDRATE_MARKER_NAME


def _read_publish_state(repo: Path) -> dict[str, str]:
    path = _publish_state_path(repo)
    if not path.exists():
        raise WorkflowMaintenanceError(
            "normal publish state is not initialized; restore the latest develop source-snapshot first"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("remote_commit", "remote_tree", "local_head"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise WorkflowMaintenanceError(f"invalid publish state: missing {key}")
    return data


def _require_hex_sha(value: str, *, name: str) -> None:
    if len(value) not in {40, 64}:
        raise WorkflowMaintenanceError(f"invalid {name}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise WorkflowMaintenanceError(f"invalid {name}") from exc


def _changed_paths(repo: Path, base_commit: str, target_commit: str) -> list[tuple[str, str]]:
    output = _git(
        "diff",
        "--name-status",
        "--no-renames",
        base_commit,
        target_commit,
        "--",
        cwd=repo,
    )
    changes: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        status = status[0]
        if status not in {"A", "M", "D"}:
            raise WorkflowMaintenanceError(f"unsupported workflow change status {status}: {path}")
        changes.append((status, path))
    return changes


def _tree_entry(repo: Path, commit: str, path: str) -> tuple[str, str] | None:
    output = _git("ls-tree", commit, "--", path, cwd=repo)
    if not output:
        return None
    metadata, actual_path = output.split("\t", 1)
    if actual_path != path:
        raise WorkflowMaintenanceError(f"unexpected Git path while reading {path}")
    mode, object_type, oid = metadata.split()
    if object_type != "blob":
        raise WorkflowMaintenanceError(f"workflow path is not a blob: {path}")
    return mode, oid


def _connector_call_bytes(packet: dict[str, object]) -> int:
    return len(json.dumps(packet["action_args"], separators=(",", ":")).encode("utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise WorkflowMaintenanceError(f"maintenance manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != MANIFEST_VERSION or data.get("kind") != "workflow-maintenance":
        raise WorkflowMaintenanceError("unsupported workflow maintenance manifest")
    if data.get("target_branch") != TARGET_BRANCH:
        raise WorkflowMaintenanceError("workflow maintenance target must be develop")
    return data


def _state_path(plan_dir: Path) -> Path:
    return plan_dir / CONNECTOR_STATE_NAME


def _read_connector_state(plan_dir: Path) -> dict[str, object]:
    path = _state_path(plan_dir)
    if not path.exists():
        raise WorkflowMaintenanceError(f"workflow maintenance connector state not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_connector_state(plan_dir: Path, state: dict[str, object]) -> None:
    _write_json(_state_path(plan_dir), state)


def _write_summary(plan_dir: Path, state: dict[str, object], **extra: object) -> dict[str, object]:
    summary = {
        "strategy": "workflow-maintenance-staged-git-data",
        "stage": state["stage"],
        "target_branch": state["target_branch"],
        "base_commit": state["base_commit"],
        "base_tree": state["base_tree"],
        "target_tree": state["target_tree"],
        "connector_profile": "github-connector-fixed",
        "connector_call_budget_bytes": CONNECTOR_CALL_BUDGET_BYTES,
        **extra,
    }
    _write_json(plan_dir / SUMMARY_NAME, summary)
    return summary


def cmd_prepare(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = _read_publish_state(repo)
    if _rehydrate_marker_path(repo).exists():
        raise WorkflowMaintenanceError(
            "a prior workflow maintenance update requires source-snapshot rehydration before another change"
        )
    target_commit = _git("rev-parse", f"{args.target_ref}^{{commit}}", cwd=repo)
    target_tree = _git("rev-parse", f"{args.target_ref}^{{tree}}", cwd=repo)
    if target_tree == state["remote_tree"]:
        raise WorkflowMaintenanceError("local target tree already matches the recorded develop tree")

    changes = _changed_paths(repo, state["remote_commit"], target_commit)
    if not changes:
        raise WorkflowMaintenanceError("workflow maintenance has no committed changes")
    non_workflow = [path for _, path in changes if not path.startswith(WORKFLOW_PREFIX)]
    if non_workflow:
        raise WorkflowMaintenanceError(
            "workflow maintenance accepts workflow-only commits; publish non-workflow changes first: "
            + ", ".join(non_workflow)
        )

    manifest_changes: list[dict[str, object]] = []
    for status, path in changes:
        if status == "D":
            base_entry = _tree_entry(repo, state["remote_commit"], path)
            if base_entry is None:
                raise WorkflowMaintenanceError(f"deleted workflow is absent from recorded base: {path}")
            mode, _ = base_entry
            manifest_changes.append({"status": status, "path": path, "mode": mode})
            continue
        entry = _tree_entry(repo, target_commit, path)
        if entry is None:
            raise WorkflowMaintenanceError(f"workflow target blob is missing: {path}")
        mode, oid = entry
        content = _git_bytes("cat-file", "blob", oid, cwd=repo)
        manifest_changes.append(
            {
                "status": status,
                "path": path,
                "mode": mode,
                "blob_oid": oid,
                "content_b64": base64.b64encode(content).decode("ascii"),
            }
        )

    message = _git("show", "-s", "--format=%B", target_commit, cwd=repo).rstrip()
    if not message:
        raise WorkflowMaintenanceError("workflow maintenance commit message must not be empty")
    manifest = {
        "version": MANIFEST_VERSION,
        "kind": "workflow-maintenance",
        "target_branch": TARGET_BRANCH,
        "base_commit": state["remote_commit"],
        "base_tree": state["remote_tree"],
        "target_tree": target_tree,
        "local_target_commit": target_commit,
        "message": message,
        "changes": manifest_changes,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, manifest)
    print(
        json.dumps(
            {
                "prepared": True,
                "kind": "workflow-maintenance",
                "target_branch": TARGET_BRANCH,
                "base_commit": state["remote_commit"],
                "target_tree": target_tree,
                "local_target_commit": target_commit,
                "workflow_paths": [item["path"] for item in manifest_changes],
                "next": "fetch develop HEAD once, then run connector-plan",
            },
            indent=2,
        )
    )
    return 0


def cmd_connector_plan(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest_path = Path(args.manifest).resolve()
    manifest = _load_manifest(manifest_path)
    _require_hex_sha(args.target_remote_head, name="target remote HEAD")
    if args.target_remote_head != manifest["base_commit"]:
        raise WorkflowMaintenanceError(
            "develop HEAD moved since workflow maintenance prepare; do not create connector packets"
        )
    plan_dir = Path(str(manifest_path) + ".connector")
    if _state_path(plan_dir).exists():
        raise WorkflowMaintenanceError(
            "workflow maintenance connector plan already exists; continue its recorded stage instead of replanning"
        )
    plan_dir.mkdir(parents=True, exist_ok=True)

    upload_packets: list[str] = []
    for index, change in enumerate(manifest["changes"]):
        if change["status"] == "D":
            continue
        packet = {
            "action": "GitHub.create_blob",
            "action_args": {
                "repository_full_name": GITHUB_REPOSITORY,
                "content": change["content_b64"],
                "encoding": "base64",
            },
            "expected_blob_git_oid": change["blob_oid"],
            "workflow_path": change["path"],
        }
        size = _connector_call_bytes(packet)
        if size >= CONNECTOR_CALL_BUDGET_BYTES:
            raise WorkflowMaintenanceError(
                f"workflow blob exceeds the fixed GitHub connector call budget: {change['path']} ({size} bytes)"
            )
        packet_path = plan_dir / f"upload-workflow-{index:04d}.json"
        _write_json(packet_path, packet)
        upload_packets.append(str(packet_path))

    state = {
        "version": 1,
        "stage": "uploads-planned",
        "manifest": str(manifest_path),
        "github_repository": GITHUB_REPOSITORY,
        "target_branch": TARGET_BRANCH,
        "base_commit": manifest["base_commit"],
        "base_tree": manifest["base_tree"],
        "target_tree": manifest["target_tree"],
        "local_target_commit": manifest["local_target_commit"],
        "upload_packets": upload_packets,
    }
    _write_connector_state(plan_dir, state)
    summary = _write_summary(
        plan_dir,
        state,
        upload_packets=upload_packets,
        upload_call_count=len(upload_packets),
        tree_packet=None,
        commit_packet=None,
        update_packet=None,
        next="execute every workflow blob upload, then run connector-tree",
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_connector_tree(args: argparse.Namespace) -> int:
    plan_dir = Path(args.plan_dir).resolve()
    state = _read_connector_state(plan_dir)
    if state["stage"] != "uploads-planned":
        raise WorkflowMaintenanceError(
            f"connector-tree requires stage uploads-planned, found {state['stage']}"
        )
    manifest = _load_manifest(Path(state["manifest"]))
    elements: list[dict[str, object]] = []
    for change in manifest["changes"]:
        element: dict[str, object] = {
            "path": change["path"],
            "mode": change["mode"],
            "type": "blob",
            "sha": None if change["status"] == "D" else change["blob_oid"],
        }
        elements.append(element)
    packet = {
        "action": "GitHub.create_tree",
        "action_args": {
            "repository_full_name": state["github_repository"],
            "base_tree_sha": state["base_tree"],
            "tree_elements": elements,
        },
        "expected_tree_git_oid": state["target_tree"],
    }
    if _connector_call_bytes(packet) >= CONNECTOR_CALL_BUDGET_BYTES:
        raise WorkflowMaintenanceError("workflow tree packet exceeds the fixed connector call budget")
    packet_path = plan_dir / "assemble-workflow-tree.json"
    _write_json(packet_path, packet)
    state["stage"] = "tree-packet-ready"
    state["tree_packet"] = str(packet_path)
    _write_connector_state(plan_dir, state)
    summary = _write_summary(
        plan_dir,
        state,
        tree_packet=str(packet_path),
        expected_tree_git_oid=state["target_tree"],
        next="execute the workflow tree packet; after success pass its returned tree SHA to connector-commit",
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_connector_commit(args: argparse.Namespace) -> int:
    plan_dir = Path(args.plan_dir).resolve()
    state = _read_connector_state(plan_dir)
    if state["stage"] != "tree-packet-ready":
        raise WorkflowMaintenanceError(
            f"connector-commit requires stage tree-packet-ready, found {state['stage']}"
        )
    _require_hex_sha(args.tree_sha, name="created workflow tree SHA")
    if args.tree_sha != state["target_tree"]:
        raise WorkflowMaintenanceError(
            f"created workflow tree {args.tree_sha} does not match expected target tree {state['target_tree']}"
        )
    manifest = _load_manifest(Path(state["manifest"]))
    packet = {
        "action": "GitHub.create_commit",
        "action_args": {
            "repository_full_name": state["github_repository"],
            "message": manifest["message"],
            "tree_sha": state["target_tree"],
            "parent_sha": state["base_commit"],
        },
    }
    packet_path = plan_dir / "create-workflow-commit.json"
    _write_json(packet_path, packet)
    state["stage"] = "commit-packet-ready"
    state["commit_packet"] = str(packet_path)
    _write_connector_state(plan_dir, state)
    summary = _write_summary(
        plan_dir,
        state,
        commit_packet=str(packet_path),
        next="execute the workflow commit packet; pass its returned commit SHA to connector-update",
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_connector_update(args: argparse.Namespace) -> int:
    plan_dir = Path(args.plan_dir).resolve()
    state = _read_connector_state(plan_dir)
    if state["stage"] != "commit-packet-ready":
        raise WorkflowMaintenanceError(
            f"connector-update requires stage commit-packet-ready, found {state['stage']}"
        )
    _require_hex_sha(args.commit_sha, name="created workflow commit SHA")
    packet = {
        "action": "GitHub.update_ref",
        "action_args": {
            "repository_full_name": state["github_repository"],
            "branch_name": TARGET_BRANCH,
            "sha": args.commit_sha,
            "force": False,
        },
    }
    packet_path = plan_dir / "advance-workflow-ref.json"
    _write_json(packet_path, packet)
    state["stage"] = "update-packet-ready"
    state["published_commit_candidate"] = args.commit_sha
    state["update_packet"] = str(packet_path)
    _write_connector_state(plan_dir, state)
    summary = _write_summary(
        plan_dir,
        state,
        update_packet=str(packet_path),
        published_commit_candidate=args.commit_sha,
        next="execute the non-force ref update, fetch develop once, then run verify-remote",
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_verify_remote(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    plan_dir = Path(args.plan_dir).resolve()
    state = _read_connector_state(plan_dir)
    if state["stage"] != "update-packet-ready":
        raise WorkflowMaintenanceError(
            f"verify-remote requires stage update-packet-ready, found {state['stage']}"
        )
    _require_hex_sha(args.remote_head, name="remote develop HEAD")
    _require_hex_sha(args.remote_tree, name="remote develop tree")
    if args.remote_head != state["published_commit_candidate"]:
        raise WorkflowMaintenanceError(
            f"remote develop HEAD mismatch: expected {state['published_commit_candidate']}, got {args.remote_head}"
        )
    if args.remote_tree != state["target_tree"]:
        raise WorkflowMaintenanceError(
            f"remote develop tree mismatch: expected {state['target_tree']}, got {args.remote_tree}"
        )
    state["stage"] = "remote-verified"
    _write_connector_state(plan_dir, state)
    _rehydrate_marker_path(repo).write_text(
        json.dumps(
            {
                "published_commit": args.remote_head,
                "published_tree": args.remote_tree,
                "local_target_commit": state["local_target_commit"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = _write_summary(
        plan_dir,
        state,
        remote_head=args.remote_head,
        remote_tree=args.remote_tree,
        verified=True,
        rehydrate_required=True,
        next="restore the new develop source-snapshot and run publish_request.py init before normal development/publish",
    )
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish committed .github/workflows-only changes through the separately authorized "
            "GitHub connector path. Normal source/game changes belong to publish_request.py."
        )
    )
    parser.add_argument("--repo", default=".", help="local repository path")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="prepare one workflow-only develop maintenance target")
    prepare.add_argument("--target-ref", default="HEAD")
    prepare.add_argument("--output", required=True)
    prepare.set_defaults(func=cmd_prepare)

    connector_plan = sub.add_parser(
        "connector-plan", help="after one develop HEAD check, generate workflow blob upload packets only"
    )
    connector_plan.add_argument("--manifest", required=True)
    connector_plan.add_argument("--target-remote-head", required=True)
    connector_plan.set_defaults(func=cmd_connector_plan)

    connector_tree = sub.add_parser(
        "connector-tree", help="after workflow blob uploads, generate the exact target tree packet"
    )
    connector_tree.add_argument("--plan-dir", required=True)
    connector_tree.set_defaults(func=cmd_connector_tree)

    connector_commit = sub.add_parser(
        "connector-commit", help="after target tree creation, verify its SHA and generate commit packet"
    )
    connector_commit.add_argument("--plan-dir", required=True)
    connector_commit.add_argument("--tree-sha", required=True)
    connector_commit.set_defaults(func=cmd_connector_commit)

    connector_update = sub.add_parser(
        "connector-update", help="after commit creation, generate the non-force develop ref update packet"
    )
    connector_update.add_argument("--plan-dir", required=True)
    connector_update.add_argument("--commit-sha", required=True)
    connector_update.set_defaults(func=cmd_connector_update)

    verify_remote = sub.add_parser(
        "verify-remote", help="verify develop ref/tree after update and require source-snapshot rehydration"
    )
    verify_remote.add_argument("--plan-dir", required=True)
    verify_remote.add_argument("--remote-head", required=True)
    verify_remote.add_argument("--remote-tree", required=True)
    verify_remote.set_defaults(func=cmd_verify_remote)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (WorkflowMaintenanceError, subprocess.CalledProcessError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
