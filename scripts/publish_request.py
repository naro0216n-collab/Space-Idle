#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

STATE_NAME = "space-idle-publish-state.json"
PATCH_MARKER = "--- SPACE-IDLE PATCH ---\n"


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


def _require_clean(repo: Path) -> None:
    if _git("status", "--porcelain", cwd=repo):
        raise PublishStateError(
            "working tree is not clean; commit the coherent local change before preparing publish"
        )


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
    _require_clean(repo)
    state = _read_state(repo)
    target_ref = args.target_ref
    target_tree = _git("rev-parse", f"{target_ref}^{{tree}}", cwd=repo)
    if target_tree == state["remote_tree"]:
        raise PublishStateError("local HEAD tree already matches the last published tree")

    patch = _request_patch(repo, state["remote_tree"], target_tree)
    if not patch:
        raise PublishStateError("no publish patch was generated")
    patch_bytes = patch.encode("utf-8")
    patch_digest = hashlib.sha256(patch_bytes).hexdigest()
    patch_payload = base64.b64encode(gzip.compress(patch_bytes, compresslevel=9)).decode("ascii")
    message = args.message if args.message is not None else _default_message(repo, state, target_ref)
    if not message.strip():
        raise PublishStateError("commit message must not be empty")
    if not message.endswith("\n"):
        message += "\n"
    message_b64 = base64.b64encode(message.encode("utf-8")).decode("ascii")

    request = (
        "# version: 2\n"
        f"# target-branch: {args.target_branch}\n"
        f"# base-sha: {state['remote_commit']}\n"
        f"# target-tree: {target_tree}\n"
        f"# patch-sha256: {patch_digest}\n"
        f"# patch-encoding: gzip-base64\n"
        f"# message-b64: {message_b64}\n"
        f"{PATCH_MARKER}"
        f"{patch_payload}\n"
    )
    if args.output:
        Path(args.output).write_text(request, encoding="utf-8", newline="")
    else:
        print(request, end="")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    _require_clean(repo)
    local_head = _git("rev-parse", args.local_ref, cwd=repo)
    target_tree = _git("rev-parse", f"{args.local_ref}^{{tree}}", cwd=repo)
    if args.remote_tree != target_tree:
        raise PublishStateError(
            f"published tree does not match local HEAD tree: local={target_tree} remote={args.remote_tree}"
        )
    _write_state(repo, args.remote_commit, args.remote_tree, local_head)
    print(
        json.dumps(
            {
                "remote_commit": args.remote_commit,
                "remote_tree": args.remote_tree,
                "local_head": local_head,
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

    prepare = sub.add_parser("prepare", help="generate one exact-tree publish gateway request")
    prepare.add_argument("--target-branch", choices=("develop", "temp"), default="develop")
    prepare.add_argument("--target-ref", default="HEAD", help="local ref/tree state to publish (default: HEAD)")
    prepare.add_argument("--message", help="remote commit message; defaults to the current local commit message")
    prepare.add_argument("--output")
    prepare.set_defaults(func=cmd_prepare)

    record = sub.add_parser("record", help="record the remote commit/tree after gateway publish")
    record.add_argument("--remote-commit", required=True)
    record.add_argument("--remote-tree", required=True)
    record.add_argument("--local-ref", default="HEAD", help="local ref whose tree was published (default: HEAD)")
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
