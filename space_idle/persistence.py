from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .application import GameApplication
from .application_commands import ApplicationError, SetTimeControl
from .domain import validate_extension_registry
from .simulation import OfflineProgressPolicy, OfflineProgressResult


SAVE_SCHEMA_VERSION = 30


class SaveFormatError(ValueError):
    pass


@dataclass(frozen=True)
class SaveEnvelope:
    schema_version: int
    content_id: str
    saved_at: str
    state: dict[str, Any]


def _extensions(sim):
    validate_extension_registry(sim.domain_extensions)
    return sim.domain_extensions


def capture_state(sim) -> dict[str, Any]:
    data: dict[str, Any] = {
        "day": sim.day,
        "pending_offline_game_days": sim.pending_offline_game_days,
    }
    for extension in _extensions(sim):
        codec = extension.state_codec
        if codec is not None:
            data[codec.key] = codec.capture(sim)
    return data


def restore_state(sim, data: dict[str, Any]) -> None:
    sim.day = int(data["day"])
    sim.pending_offline_game_days = float(data.get("pending_offline_game_days", 0.0))
    for extension in _extensions(sim):
        codec = extension.state_codec
        if codec is None:
            continue
        if codec.key not in data:
            raise SaveFormatError(f"save state is missing domain section: {codec.key}")
        codec.restore(sim, data[codec.key])
    sim.refresh_storage()
    sim.refresh_resource_claims()


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
    try:
        app.execute(
            SetTimeControl(
                paused=data["time_paused"],
                speed_multiplier=data["time_speed_multiplier"],
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
    state = capture_state(app._simulation)
    state["application"] = _application_state(app)
    envelope = SaveEnvelope(
        SAVE_SCHEMA_VERSION,
        app.content_id,
        timestamp.astimezone(timezone.utc).isoformat(),
        state,
    )
    payload = {
        "schema_version": envelope.schema_version,
        "content_id": envelope.content_id,
        "saved_at": envelope.saved_at,
        "state": envelope.state,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return envelope


def _read_envelope(path: str | Path) -> SaveEnvelope:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SaveFormatError(f"invalid save file: {exc}") from exc
    if not isinstance(raw, dict):
        raise SaveFormatError("save root must be an object")
    required = {"schema_version", "content_id", "saved_at", "state"}
    if not required.issubset(raw):
        raise SaveFormatError("save file is missing required fields")
    if raw["schema_version"] != SAVE_SCHEMA_VERSION:
        raise SaveFormatError(
            f"unsupported save schema: {raw['schema_version']} (expected {SAVE_SCHEMA_VERSION})"
        )
    if not isinstance(raw["state"], dict):
        raise SaveFormatError("save state must be an object")
    return SaveEnvelope(
        int(raw["schema_version"]),
        str(raw["content_id"]),
        str(raw["saved_at"]),
        raw["state"],
    )


def load_game(
    path: str | Path,
    factory: Callable[[], GameApplication],
    *,
    now: datetime | None = None,
    offline_policy: OfflineProgressPolicy | None = None,
) -> tuple[GameApplication, OfflineProgressResult | None]:
    envelope = _read_envelope(path)
    app = factory()
    if envelope.content_id != app.content_id:
        raise SaveFormatError(
            f"save content mismatch: {envelope.content_id} != {app.content_id}"
        )
    restore_state(app._simulation, envelope.state)
    _restore_application_state(app, envelope.state)
    offline_result = None
    if now is not None and offline_policy is not None and not app.time_paused:
        current = now
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        try:
            saved = datetime.fromisoformat(envelope.saved_at)
        except ValueError as exc:
            raise SaveFormatError("saved_at is not a valid ISO timestamp") from exc
        if saved.tzinfo is None:
            raise SaveFormatError("saved_at must include timezone")
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
