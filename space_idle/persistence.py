from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from .application import GameApplication
from .application_commands import ApplicationError, SetTimeControl
from .domain import validate_extension_registry
from .simulation import OfflineProgressPolicy, OfflineProgressResult
from .validation import validate_runtime_state
from .validation_support import ConfigurationError


SAVE_SCHEMA_VERSION = 65


class SaveFormatError(ValueError):
    pass


@dataclass(frozen=True)
class SaveEnvelope:
    schema_version: int
    content_id: str
    world_definition_id: str
    scenario_id: str
    saved_at: str
    state: dict[str, Any]


def _extensions(sim):
    validate_extension_registry(sim.domain_extensions)
    return sim.domain_extensions


def capture_state(sim) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for extension in _extensions(sim):
        codec = extension.state_codec
        if codec is not None:
            data[codec.key] = codec.capture(sim)
    return data


def restore_state(sim, data: dict[str, Any]) -> None:
    for extension in _extensions(sim):
        codec = extension.state_codec
        if codec is None:
            continue
        if codec.key not in data:
            raise SaveFormatError(f"save state is missing domain section: {codec.key}")
        section = data[codec.key]
        if not isinstance(section, dict):
            raise SaveFormatError(f"save domain section must be an object: {codec.key}")
        expected = codec.capture(sim)
        if isinstance(expected, dict) and set(section) != set(expected):
            missing = sorted(set(expected) - set(section))
            unexpected = sorted(set(section) - set(expected))
            raise SaveFormatError(
                f"save domain section has invalid fields: {codec.key}; "
                f"missing={missing}; unexpected={unexpected}"
            )
        codec.restore(sim, section)
        if codec.capture(sim) != section:
            raise SaveFormatError(
                f"save domain section is not in canonical serialized form: {codec.key}"
            )
    sim.mark_runtime_state_initialized()
    sim.transport.invalidate_movement_plans()


def _application_state(app: GameApplication) -> dict[str, Any]:
    return {
        "time_paused": app.time_paused,
        "time_speed_multiplier": app.time_speed_multiplier,
    }


def _restore_application_state(app: GameApplication, state: dict[str, Any]) -> None:
    data = state.get("application")
    if not isinstance(data, dict):
        raise SaveFormatError("save state is missing application section")
    if set(data) != {"time_paused", "time_speed_multiplier"}:
        raise SaveFormatError("save application state has invalid fields")
    paused = data["time_paused"]
    speed = data["time_speed_multiplier"]
    if not isinstance(paused, bool):
        raise SaveFormatError("application time_paused must be boolean")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise SaveFormatError("application time_speed_multiplier must be numeric")
    try:
        app.execute(
            SetTimeControl(
                paused=paused,
                speed_multiplier=float(speed),
            )
        )
    except (ApplicationError, TypeError, ValueError) as exc:
        raise SaveFormatError(f"invalid application time state: {exc}") from exc


def save_game(
    app: GameApplication,
    path: str | Path,
    *,
    saved_at: datetime | None = None,
) -> SaveEnvelope:
    timestamp = saved_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("saved_at must be timezone-aware")
    validate_runtime_state(app._simulation)
    state = capture_state(app._simulation)
    state["application"] = _application_state(app)
    envelope = SaveEnvelope(
        schema_version=SAVE_SCHEMA_VERSION,
        content_id=app.content_id,
        world_definition_id=app.world_definition_id,
        scenario_id=app.scenario_id,
        saved_at=timestamp.astimezone(timezone.utc).isoformat(),
        state=state,
    )
    payload = {
        "schema_version": envelope.schema_version,
        "content_id": envelope.content_id,
        "world_definition_id": envelope.world_definition_id,
        "scenario_id": envelope.scenario_id,
        "saved_at": envelope.saved_at,
        "state": envelope.state,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    return envelope




def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SaveFormatError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> None:
    raise SaveFormatError(f"non-finite JSON number is not allowed: {value}")


def _read_envelope(path: str | Path) -> SaveEnvelope:
    try:
        raw = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except SaveFormatError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SaveFormatError(f"invalid save file: {exc}") from exc
    if not isinstance(raw, dict):
        raise SaveFormatError("save root must be an object")
    required = {
        "schema_version", "content_id", "world_definition_id", "scenario_id",
        "saved_at", "state",
    }
    if set(raw) != required:
        missing = sorted(required - set(raw))
        unexpected = sorted(set(raw) - required)
        raise SaveFormatError(
            "save file has invalid fields; "
            f"missing={missing}; unexpected={unexpected}"
        )
    if isinstance(raw["schema_version"], bool) or not isinstance(raw["schema_version"], int):
        raise SaveFormatError("schema_version must be an integer")
    for identity_field in ("content_id", "world_definition_id", "scenario_id"):
        if not isinstance(raw[identity_field], str):
            raise SaveFormatError(f"{identity_field} must be a string")
    if raw["schema_version"] != SAVE_SCHEMA_VERSION:
        raise SaveFormatError(
            f"unsupported save schema: {raw['schema_version']} (expected {SAVE_SCHEMA_VERSION})"
        )
    if not isinstance(raw["state"], dict):
        raise SaveFormatError("save state must be an object")
    saved_at = raw["saved_at"]
    if not isinstance(saved_at, str):
        raise SaveFormatError("saved_at must be a string")
    try:
        parsed_saved_at = datetime.fromisoformat(saved_at)
    except ValueError as exc:
        raise SaveFormatError("saved_at is not a valid ISO timestamp") from exc
    if parsed_saved_at.tzinfo is None:
        raise SaveFormatError("saved_at must include timezone")
    return SaveEnvelope(
        schema_version=raw["schema_version"],
        content_id=raw["content_id"],
        world_definition_id=raw["world_definition_id"],
        scenario_id=raw["scenario_id"],
        saved_at=parsed_saved_at.astimezone(timezone.utc).isoformat(),
        state=raw["state"],
    )


def load_game(
    path: str | Path,
    load_factory: Callable[[], GameApplication],
    *,
    now: datetime | None = None,
    offline_policy: OfflineProgressPolicy | None = None,
) -> tuple[GameApplication, OfflineProgressResult | None]:
    envelope = _read_envelope(path)
    app = load_factory()
    if envelope.content_id != app.content_id:
        raise SaveFormatError(
            f"save content mismatch: {envelope.content_id} != {app.content_id}"
        )
    if envelope.world_definition_id != app.world_definition_id:
        raise SaveFormatError(
            "save world definition mismatch: "
            f"{envelope.world_definition_id} != {app.world_definition_id}"
        )
    if envelope.scenario_id != app.scenario_id:
        raise SaveFormatError(
            f"save scenario mismatch: {envelope.scenario_id} != {app.scenario_id}"
        )
    expected_state_fields = {
        "application",
        *(
            extension.state_codec.key
            for extension in _extensions(app._simulation)
            if extension.state_codec is not None
        ),
    }
    if set(envelope.state) != expected_state_fields:
        missing = sorted(expected_state_fields - set(envelope.state))
        unexpected = sorted(set(envelope.state) - expected_state_fields)
        raise SaveFormatError(
            "save state has invalid fields; "
            f"missing={missing}; unexpected={unexpected}"
        )
    try:
        restore_state(app._simulation, envelope.state)
        _restore_application_state(app, envelope.state)
        validate_runtime_state(app._simulation)
        app._simulation.refresh_storage()
        validate_runtime_state(app._simulation)
    except SaveFormatError:
        raise
    except (ConfigurationError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise SaveFormatError(f"invalid saved runtime state: {exc}") from exc
    offline_result = None
    if now is not None and offline_policy is not None and not app.time_paused:
        current = now
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        saved = datetime.fromisoformat(envelope.saved_at)
        elapsed = max(
            0.0,
            (
                current.astimezone(timezone.utc)
                - saved.astimezone(timezone.utc)
            ).total_seconds(),
        )
        offline_result = app.advance_offline(
            elapsed * app.time_speed_multiplier,
            offline_policy,
        )
    return app, offline_result
