from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
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

    Mutations are serialized under one lock. When a wall-clock progress policy is
    configured, elapsed real time is lazily caught up before interactions. This
    keeps the server authoritative even when Safari/PWA is suspended: browser
    timers are never part of simulation correctness.

    Pause and speed are runtime clock controls. The deterministic Simulation Core
    still advances only through its normal time-progress path. ``revision`` is an
    optimistic-concurrency token for explicit player/session mutations; passive
    clock ticks deliberately do not invalidate a just-issued player command.
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
        self._time_paused = False
        self._time_speed_multiplier = 1.0

    def _sync_clock_locked(self) -> OfflineProgressResult | None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_clock)
        self._last_clock = now
        if self._offline_policy is None or elapsed <= 0.0 or self._time_paused:
            return None
        return self._app.advance_offline(
            elapsed * self._time_speed_multiplier,
            self._offline_policy,
        )

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
            "automatic_progress_enabled": self._offline_policy is not None,
            "offline_progress_enabled": self._offline_policy is not None,
            "time_paused": self._time_paused,
            "time_speed_multiplier": self._time_speed_multiplier,
            "real_seconds_per_game_day": (
                None if self._offline_policy is None
                else self._offline_policy.real_seconds_per_game_day
            ),
        }

    def metadata(self) -> dict[str, object]:
        with self._lock:
            self._sync_clock_locked()
            return self._metadata_locked()

    def set_time_control(
        self,
        *,
        paused: bool | None = None,
        speed_multiplier: float | None = None,
    ) -> RuntimeResult:
        """Apply player-facing runtime clock controls without bypassing Core time rules."""
        if paused is None and speed_multiplier is None:
            raise ValueError("paused or speed_multiplier is required")
        if paused is not None and not isinstance(paused, bool):
            raise ValueError("paused must be boolean")
        if speed_multiplier is not None:
            if isinstance(speed_multiplier, bool) or not isinstance(speed_multiplier, (int, float)):
                raise ValueError("speed_multiplier must be a number")
            speed_multiplier = float(speed_multiplier)
            if not isfinite(speed_multiplier) or speed_multiplier <= 0.0 or speed_multiplier > 64.0:
                raise ValueError("speed_multiplier must be greater than 0 and at most 64")

        with self._lock:
            # Credit elapsed time using the previous control state first, so a
            # pause/speed change has a clean temporal boundary.
            self._sync_clock_locked()
            changed = False
            if paused is not None and paused != self._time_paused:
                self._time_paused = paused
                changed = True
            if speed_multiplier is not None and speed_multiplier != self._time_speed_multiplier:
                self._time_speed_multiplier = speed_multiplier
                changed = True
            if changed:
                self._revision += 1
            return RuntimeResult(self._revision, self._metadata_locked())

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
            self._time_paused = False
            self._time_speed_multiplier = 1.0
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
            policy = self._offline_policy if apply_offline and not self._time_paused else None
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
