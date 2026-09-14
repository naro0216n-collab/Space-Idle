#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from publish_gateway_payload import GatewayPayloadError, load_indexed_payload


TRUSTED_CONTROL_WORKFLOW = ".github/workflows/publish-gateway.yml"


class GatewayRequestError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _trigger(request_path: Path, request_id: str) -> int:
    path = request_path.as_posix()
    initial = re.fullmatch(r"\.publish/requests/([0-9a-f]{32})\.json", path)
    retry = re.fullmatch(r"\.publish/retries/([0-9a-f]{32})/g([0-9]{4})\.json", path)
    if initial:
        path_request_id = initial.group(1)
        generation = 0
    elif retry:
        path_request_id = retry.group(1)
        generation = int(retry.group(2))
    else:
        raise GatewayRequestError("invalid publish request path")
    if path_request_id != request_id:
        raise GatewayRequestError("request id does not match request path")
    return generation


def _require_oid(value: object, *, length: int, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
        raise GatewayRequestError(f"invalid {name}")
    return value



def verify_trusted_workflow() -> int:
    base_sha = os.environ.get("BASE_SHA", "")
    publish_commit = os.environ.get("PUBLISH_COMMIT", "")
    control_commit = os.environ.get("GITHUB_SHA", "")
    if not base_sha or not publish_commit or not control_commit:
        raise GatewayRequestError("trusted workflow verification environment is incomplete")

    output = _git(
        "diff",
        "--name-status",
        "--no-renames",
        base_sha,
        publish_commit,
        "--",
        ".github/workflows",
    )
    for line in output.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        status = status[0]
        if path != TRUSTED_CONTROL_WORKFLOW:
            raise GatewayRequestError(f"untrusted workflow change in publish target: {path}")
        if status not in {"A", "M"}:
            raise GatewayRequestError(
                f"trusted control workflow must exist in publish target: {path}"
            )
        target_oid = _git("rev-parse", f"{publish_commit}:{path}")
        control_oid = _git("rev-parse", f"{control_commit}:{path}")
        if target_oid != control_oid:
            raise GatewayRequestError(
                f"trusted control workflow blob mismatch: target {target_oid}, control {control_oid}"
            )
    return 0

def main() -> int:
    request_path = Path(os.environ["REQUEST_FILE"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    required = {
        "version",
        "request_id",
        "target_branch",
        "base_sha",
        "target_tree",
        "publish_commit",
        "payload_sha256",
        "payload_encoding",
        "payload_chars",
        "payload_source",
    }
    missing = required - request.keys()
    if missing:
        raise GatewayRequestError(f"missing request fields: {sorted(missing)}")
    if request["version"] != 7:
        raise GatewayRequestError("unsupported request version")
    request_id = request["request_id"]
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise GatewayRequestError("invalid request id")
    trigger_generation = _trigger(request_path, request_id)
    if request["target_branch"] not in {"develop", "temp"}:
        raise GatewayRequestError("unsupported target branch")

    object_format = _git("rev-parse", "--show-object-format")
    oid_length = 40 if object_format == "sha1" else 64 if object_format == "sha256" else 0
    if oid_length == 0:
        raise GatewayRequestError(f"unsupported Git object format: {object_format}")
    for key in ("base_sha", "target_tree", "publish_commit"):
        _require_oid(request[key], length=oid_length, name=key)
    if not isinstance(request["payload_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", request["payload_sha256"]
    ):
        raise GatewayRequestError("invalid payload sha256")
    if request["payload_encoding"] != "git-bundle-base64":
        raise GatewayRequestError("unsupported payload encoding")
    if not isinstance(request["payload_chars"], int) or request["payload_chars"] <= 0:
        raise GatewayRequestError("invalid payload size")

    current = _git("ls-remote", "origin", f"refs/heads/{request['target_branch']}").split()
    if not current or current[0] != request["base_sha"]:
        actual = current[0] if current else "<missing>"
        raise GatewayRequestError(
            f"target moved before payload validation: expected {request['base_sha']}, got {actual}"
        )

    payload_bytes, _, _ = load_indexed_payload(
        request_id=request_id,
        request=request,
        trigger_generation=trigger_generation,
        object_format=object_format,
    )
    bundle_path = Path(os.environ["RUNNER_TEMP"]) / "publish.bundle"
    bundle_path.write_bytes(payload_bytes)
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as env:
        env.write(f"REQUEST_ID={request_id}\n")
        env.write(f"TARGET_BRANCH={request['target_branch']}\n")
        env.write(f"BASE_SHA={request['base_sha']}\n")
        env.write(f"TARGET_TREE={request['target_tree']}\n")
        env.write(f"PUBLISH_COMMIT={request['publish_commit']}\n")
        env.write(f"BUNDLE_FILE={bundle_path}\n")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-trusted-workflow", action="store_true")
    args = parser.parse_args()
    if args.verify_trusted_workflow:
        return verify_trusted_workflow()
    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(cli())
    except (GatewayRequestError, GatewayPayloadError) as exc:
        raise SystemExit(str(exc)) from exc
