from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from typing import Callable

from ..application import GameApplication
from ..application_commands import Command, GetWorld, Query
from ..persistence import load_game, save_game
from ..simulation import OfflineProgressPolicy, OfflineProgressResult
from ..version import VERSION
from .codec import to_jsonable


_SLOT_RE = re.compile(r"^[^/\\\x00-\x1f]{1,64}$")


@dataclass(frozen=True)
class RuntimeResult:
    revision: int
    data: object


class RevisionConflict(RuntimeError):
    def __init__(self, expected_revision: int, current_revision: int):
        super().__init__(f"expected revision {expected_revision}, current revision is {current_revision}")
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class GameRuntime:
    """Own one authoritative GameApplication session for browser clients.

    Mutations are serialized under one lock. When an offline/real-time policy is
    configured, elapsed wall time is lazily caught up before interactions. This
    means iPad Safari/PWA suspension cannot stall game time merely because the
    client stopped running JavaScript timers.
    """

    def __init__(
        self,
        *,
        factory: Callable[[], GameApplication],
        save_dir: str | Path = "saves",
        offline_policy: OfflineProgressPolicy | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._factory = factory
        self._save_dir = Path(save_dir)
        self._offline_policy = offline_policy
        self._clock = clock
        self._lock = RLock()
        self._app = factory()
        self._revision = 0
        self._last_clock = clock()

    def _sync_clock_locked(self) -> OfflineProgressResult | None:
        if self._offline_policy is None:
            return None
        now = self._clock()
        elapsed = max(0.0, now - self._last_clock)
        self._last_clock = now
        if elapsed <= 0.0:
            return None
        result = self._app.advance_offline(elapsed, self._offline_policy)
        # Fractional carry is intentionally not a visible revision: normal UI
        # query results only change once one or more simulation days advance.
        if result.advanced_days > 0:
            self._revision += 1
        return result

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def content_id(self) -> str:
        with self._lock:
            return self._app.content_id

    def _metadata_locked(self) -> dict[str, object]:
        world = self._app.query(GetWorld())
        return {
            "revision": self._revision,
            "app_version": VERSION,
            "content_id": self._app.content_id,
            "day": world.day,
            "offline_progress_enabled": self._offline_policy is not None,
        }

    def metadata(self) -> dict[str, object]:
        with self._lock:
            self._sync_clock_locked()
            return self._metadata_locked()

    def query(self, query: Query) -> RuntimeResult:
        with self._lock:
            self._sync_clock_locked()
            return RuntimeResult(self._revision, self._app.query(query))

    def execute(self, command: Command, *, expected_revision: int | None = None) -> RuntimeResult:
        with self._lock:
            self._sync_clock_locked()
            if expected_revision is not None and expected_revision != self._revision:
                raise RevisionConflict(expected_revision, self._revision)
            result = self._app.execute(command)
            self._revision += 1
            return RuntimeResult(self._revision, result)

    def new_game(self) -> RuntimeResult:
        with self._lock:
            self._app = self._factory()
            self._last_clock = self._clock()
            self._revision += 1
            return RuntimeResult(self._revision, self._metadata_locked())

    def _slot_path(self, slot: str) -> Path:
        if not isinstance(slot, str) or not _SLOT_RE.fullmatch(slot) or slot in {".", ".."}:
            raise ValueError("invalid save slot")
        return self._save_dir / f"{slot}.json"

    def save(self, slot: str) -> RuntimeResult:
        with self._lock:
            self._sync_clock_locked()
            path = self._slot_path(slot)
            save_game(self._app, path)
            return RuntimeResult(self._revision, {"slot": slot, "saved": True})

    def load(self, slot: str, *, apply_offline: bool = True) -> RuntimeResult:
        with self._lock:
            path = self._slot_path(slot)
            if not path.is_file():
                raise FileNotFoundError(path)
            policy = self._offline_policy if apply_offline else None
            app, offline_result = load_game(path, self._factory, offline_policy=policy)
            self._app = app
            self._last_clock = self._clock()
            self._revision += 1
            return RuntimeResult(self._revision, {
                "slot": slot,
                "loaded": True,
                "offline_progress": None if offline_result is None else to_jsonable(offline_result),
                "session": self._metadata_locked(),
            })
