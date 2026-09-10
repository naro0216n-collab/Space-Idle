#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

STATE_NAME = "space-idle-publish-state.json"


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
            "publish state is not initialized; run init with the artifact commit/tree first"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("remote_commit", "remote_tree"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise PublishStateError(f"invalid publish state: missing {key}")
    return data


def _write_state(repo: Path, remote_commit: str, remote_tree: str) -> None:
    path = _state_path(repo)
    path.write_text(
        json.dumps(
            {"remote_commit": remote_commit, "remote_tree": remote_tree},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _require_clean(repo: Path) -> None:
    status = _git("status", "--porcelain", cwd=repo)
    if status:
        raise PublishStateError(
            "working tree is not clean; commit the coherent local change before preparing publish"
        )


@dataclass(frozen=True)
class ChangedObject:
    status: str
    path: str
    mode: str | None
    blob_sha: str | None
    size_bytes: int | None


def _changed_objects(repo: Path, base_tree: str, target_tree: str) -> list[ChangedObject]:
    output = _git(
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "--no-renames",
        "-r",
        base_tree,
        target_tree,
        cwd=repo,
    )
    if not output:
        return []
    result: list[ChangedObject] = []
    for line in output.splitlines():
        status, path = line.split("\t", 1)
        if status == "D":
            result.append(ChangedObject(status=status, path=path, mode=None, blob_sha=None, size_bytes=None))
            continue
        entry = _git("ls-tree", target_tree, "--", path, cwd=repo)
        if not entry:
            raise PublishStateError(f"cannot resolve target tree entry for {path}")
        meta, resolved_path = entry.split("\t", 1)
        mode, object_type, blob_sha = meta.split()
        if object_type != "blob":
            raise PublishStateError(f"unsupported non-blob tree entry for {resolved_path}: {object_type}")
        size = int(_git("cat-file", "-s", blob_sha, cwd=repo))
        result.append(
            ChangedObject(
                status=status,
                path=resolved_path,
                mode=mode,
                blob_sha=blob_sha,
                size_bytes=size,
            )
        )
    return result


def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    local_tree = _git("rev-parse", f"{args.local_ref}^{{tree}}", cwd=repo)
    if local_tree != args.remote_tree:
        raise PublishStateError(
            f"artifact/local tree mismatch: local={local_tree} remote={args.remote_tree}"
        )
    _write_state(repo, args.remote_commit, args.remote_tree)
    print(json.dumps({"remote_commit": args.remote_commit, "remote_tree": args.remote_tree}, indent=2))
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    _require_clean(repo)
    state = _read_state(repo)
    target_commit = _git("rev-parse", "HEAD", cwd=repo)
    target_tree = _git("rev-parse", "HEAD^{tree}", cwd=repo)
    changes = _changed_objects(repo, state["remote_tree"], target_tree)
    manifest = {
        "base_remote_commit": state["remote_commit"],
        "base_remote_tree": state["remote_tree"],
        "local_head": target_commit,
        "target_tree": target_tree,
        "changes": [asdict(item) for item in changes],
    }
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    _require_clean(repo)
    target_tree = _git("rev-parse", "HEAD^{tree}", cwd=repo)
    if args.remote_tree != target_tree:
        raise PublishStateError(
            f"published tree does not match local HEAD tree: local={target_tree} remote={args.remote_tree}"
        )
    _write_state(repo, args.remote_commit, args.remote_tree)
    print(json.dumps({"remote_commit": args.remote_commit, "remote_tree": args.remote_tree}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and track deterministic GitHub publish state for Space-Idle."
    )
    parser.add_argument("--repo", default=".", help="repository path (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize publish state from a verified source artifact")
    init.add_argument("--remote-commit", required=True)
    init.add_argument("--remote-tree", required=True)
    init.add_argument("--local-ref", default="HEAD", help="local ref whose tree must match the verified remote tree")
    init.set_defaults(func=cmd_init)

    prepare = sub.add_parser("prepare", help="emit changed blobs and target tree for one publish")
    prepare.add_argument("--output")
    prepare.set_defaults(func=cmd_prepare)

    record = sub.add_parser("record", help="record the remote commit/tree after successful ref update")
    record.add_argument("--remote-commit", required=True)
    record.add_argument("--remote-tree", required=True)
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
