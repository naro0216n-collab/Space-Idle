#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from typing import Any


class GatewayPayloadError(RuntimeError):
    pass


def _gh_json(endpoint: str) -> Any:
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def _oid_length(object_format: str) -> int:
    if object_format == "sha1":
        return 40
    if object_format == "sha256":
        return 64
    raise GatewayPayloadError(f"unsupported Git object format: {object_format}")


def _require_oid(value: object, *, object_format: str, name: str) -> str:
    length = _oid_length(object_format)
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
        raise GatewayPayloadError(f"invalid {name}")
    return value


def _git_blob_oid(content: bytes, *, object_format: str) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.new(object_format, header + content).hexdigest()


def load_indexed_payload(
    *,
    request_id: str,
    request: dict[str, object],
    trigger_generation: int,
    object_format: str,
) -> tuple[bytes, int, int]:
    source = request.get("payload_source")
    if not isinstance(source, dict) or source.get("kind") != "indexed-files":
        raise GatewayPayloadError("unsupported payload source")
    payload_dir = source.get("directory")
    minimum_generation = source.get("minimum_generation")
    expected_dir = f".publish/payloads/{request_id}"
    if payload_dir != expected_dir:
        raise GatewayPayloadError("invalid payload source directory")
    if not isinstance(minimum_generation, int) or minimum_generation < trigger_generation:
        raise GatewayPayloadError("invalid payload minimum generation")

    repository = os.environ["GITHUB_REPOSITORY"]
    directory = _gh_json(f"repos/{repository}/contents/{payload_dir}?ref=publish")
    if not isinstance(directory, list):
        raise GatewayPayloadError("invalid payload directory response")
    indexes: list[tuple[int, str]] = []
    for entry in directory:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        match = re.fullmatch(r"index-(\d{4})\.json", str(entry.get("name") or ""))
        if match:
            indexes.append((int(match.group(1)), str(entry["name"])))
    if not indexes:
        raise GatewayPayloadError("payload index not found")

    generation, index_name = max(indexes)
    if generation < minimum_generation:
        raise GatewayPayloadError(
            f"payload generation is older than request floor: required {minimum_generation:04d}, "
            f"found {generation:04d}"
        )
    response = _gh_json(
        f"repos/{repository}/contents/{payload_dir}/{index_name}?ref=publish"
    )
    if not isinstance(response, dict) or response.get("type") != "file" or response.get("encoding") != "base64":
        raise GatewayPayloadError("invalid payload index response")
    try:
        index_raw = base64.b64decode(response["content"], validate=False)
        index = json.loads(index_raw.decode("utf-8"))
    except Exception as exc:
        raise GatewayPayloadError(f"invalid payload index: {exc}") from exc

    if index.get("version") != 1:
        raise GatewayPayloadError("unsupported payload index version")
    if index.get("request_id") != request_id:
        raise GatewayPayloadError("payload index request id mismatch")
    if index.get("generation") != generation:
        raise GatewayPayloadError("payload index generation mismatch")
    if index.get("payload_chars") != request.get("payload_chars"):
        raise GatewayPayloadError("payload index character count mismatch")
    if index.get("payload_sha256") != request.get("payload_sha256"):
        raise GatewayPayloadError("payload index sha256 mismatch")

    part_count = index.get("part_count")
    parts = index.get("parts")
    if not isinstance(part_count, int) or not 1 <= part_count <= 256:
        raise GatewayPayloadError("invalid payload index part count")
    if not isinstance(parts, list) or len(parts) != part_count:
        raise GatewayPayloadError("payload index part list mismatch")

    print(f"Using payload generation {generation:04d} with {part_count} parts")
    payload_parts: list[str] = []
    for part_index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise GatewayPayloadError(f"invalid payload part metadata at {part_index}")
        expected_path = f"g{generation:04d}/{part_index:04d}.b64"
        if part.get("index") != part_index or part.get("path") != expected_path:
            raise GatewayPayloadError(f"invalid payload part ordering at {part_index}")
        expected_chars = part.get("chars")
        if not isinstance(expected_chars, int) or expected_chars <= 0:
            raise GatewayPayloadError(f"invalid payload part size at {part_index}")
        blob_oid = _require_oid(
            part.get("blob_git_oid"), object_format=object_format, name=f"payload blob oid at part {part_index}"
        )

        path_result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repository}/contents/{payload_dir}/{expected_path}?ref=publish",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if path_result.returncode != 0:
            raise GatewayPayloadError(
                f"payload part path missing generation {generation:04d} part {part_index}: {expected_path}"
            )
        path_response = json.loads(path_result.stdout)
        actual_path_oid = path_response.get("sha") if isinstance(path_response, dict) else None
        if actual_path_oid != blob_oid:
            raise GatewayPayloadError(
                f"payload part path blob mismatch generation {generation:04d} part {part_index}: "
                f"expected {blob_oid}, got {actual_path_oid or '<missing>'}"
            )

        blob = _gh_json(f"repos/{repository}/git/blobs/{blob_oid}")
        if not isinstance(blob, dict) or blob.get("sha") != blob_oid or blob.get("encoding") != "base64":
            raise GatewayPayloadError(f"GitHub payload blob identity mismatch at part {part_index}")
        try:
            raw = base64.b64decode(blob["content"], validate=False)
            text = raw.decode("ascii")
        except Exception as exc:
            raise GatewayPayloadError(f"invalid GitHub payload blob at part {part_index}: {exc}") from exc
        actual_oid = _git_blob_oid(text.encode("ascii"), object_format=object_format)
        if actual_oid != blob_oid:
            raise GatewayPayloadError(
                f"GitHub payload blob Git OID mismatch at part {part_index}: expected {blob_oid}, got {actual_oid}"
            )
        if len(text) != expected_chars:
            raise GatewayPayloadError(
                f"payload part character count mismatch at part {part_index}: expected {expected_chars}, got {len(text)}"
            )
        payload_parts.append(text)

    payload_text = "".join(payload_parts)
    expected_payload_chars = request.get("payload_chars")
    if len(payload_text) != expected_payload_chars:
        raise GatewayPayloadError(
            f"payload character count mismatch: expected {expected_payload_chars}, got {len(payload_text)}"
        )
    try:
        payload_bytes = base64.b64decode(payload_text, validate=True)
    except Exception as exc:
        raise GatewayPayloadError(f"invalid bundle Base64: {exc}") from exc
    digest = hashlib.sha256(payload_bytes).hexdigest()
    if digest != request.get("payload_sha256"):
        raise GatewayPayloadError(
            f"bundle sha256 mismatch: expected {request.get('payload_sha256')}, got {digest}"
        )
    return payload_bytes, generation, part_count
