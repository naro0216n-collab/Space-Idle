from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable, Any

from .application import GameApplication
from .simulation import OfflineProgressPolicy, OfflineProgressResult, Simulation
from .validation import ConfigurationError, validate_runtime_state

SAVE_SCHEMA_VERSION = 17


class SaveFormatError(ValueError):
    pass

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)

def capture_state(sim: Simulation) -> dict[str, Any]:
    state: dict[str, Any] = {"day": sim.day, "pending_offline_game_days": sim.pending_offline_game_days, "account": {"funds_musd": sim.account.funds_musd, "passive_income_musd_per_day": sim.account.passive_income_musd_per_day}}
    for extension in sim.domain_extensions:
        codec = extension.state_codec
        if codec is not None:
            state[codec.key] = codec.capture(sim)
    return state

def restore_state(sim: Simulation, state: dict[str, Any]) -> None:
    sim.day = int(state["day"])
    sim.pending_offline_game_days = float(state.get("pending_offline_game_days", 0.0))
    sim.account.funds_musd = float(state["account"]["funds_musd"])
    sim.account.passive_income_musd_per_day = float(state["account"]["passive_income_musd_per_day"])
    for extension in sim.domain_extensions:
        codec = extension.state_codec
        if codec is not None:
            codec.restore(sim, state.get(codec.key, {} if codec.optional else None))
    sim.refresh_storage()

def make_save_document(app: GameApplication, *, saved_at: datetime | None = None) -> dict[str, Any]:
    timestamp = _as_utc(saved_at or _utc_now())
    sim = app._simulation
    validate_runtime_state(sim)
    return {"schema_version": SAVE_SCHEMA_VERSION, "content_id": app.content_id, "saved_at_utc": timestamp.isoformat(), "state": capture_state(sim)}

def save_game(app: GameApplication, path: str | Path, *, saved_at: datetime | None = None) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = make_save_document(app, saved_at=saved_at)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temp.replace(destination)

def load_game(path: str | Path, factory: Callable[[], GameApplication], *, now: datetime | None = None, offline_policy: OfflineProgressPolicy | None = None) -> tuple[GameApplication, OfflineProgressResult | None]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SaveFormatError("save file is unreadable or invalid JSON") from exc
    if not isinstance(document, dict):
        raise SaveFormatError("save document must be an object")
    if document.get("schema_version") != SAVE_SCHEMA_VERSION:
        raise SaveFormatError(f"unsupported save schema: {document.get('schema_version')}")
    app = factory()
    sim = app._simulation
    if document.get("content_id") != app.content_id:
        raise SaveFormatError(f"save content {document.get('content_id')!r} does not match current content {app.content_id!r}")
    try:
        restore_state(sim, document["state"])
        validate_runtime_state(sim)
        saved_at_value = document["saved_at_utc"]
    except (KeyError, TypeError, ValueError, ConfigurationError) as exc:
        raise SaveFormatError("save state is malformed") from exc
    result = None
    if offline_policy is not None:
        try:
            saved_at = datetime.fromisoformat(saved_at_value)
            current = _as_utc(now or _utc_now())
            elapsed = max(0.0, (current - _as_utc(saved_at)).total_seconds())
        except (TypeError, ValueError) as exc:
            raise SaveFormatError("saved_at_utc is invalid") from exc
        result = sim.advance_offline(elapsed, offline_policy)
        validate_runtime_state(sim)
    return app, result
