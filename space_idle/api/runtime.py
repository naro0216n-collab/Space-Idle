from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from typing import Callable

from ..application import GameApplication
from ..application_commands import Command, GetWorld, Query, SetTimeControl
from ..persistence import load_game, save_game
from ..simulation import OfflineProgressPolicy, OfflineProgressResult
from ..version import VERSION
from .codec import to_jsonable


_SLOT_RE = re.compile(r"^[^/\\\x00-\x1f]{1,64}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuntimeResult:
    revision: int
    data: object


class RevisionConflict(RuntimeError):
    def __init__(self, expected_revision: int, current_revision: int):
        super().__init__(
            f"expected revision {expected_revision}, current revision is {current_revision}"
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class GameRuntime:
    """Own one authoritative GameApplication session and its wall-clock mapping.

    The Simulation remains deterministic and knows only game time. Time control is
    Application-owned mutable state; this runtime maps wall-clock elapsed time
    through that state and never lets browser timers drive simulation correctness.
    """

    def __init__(
        self,
        *,
        factory: Callable[[], GameApplication],
        save_dir: str | Path = "saves",
        offline_policy: OfflineProgressPolicy | None = None,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._factory = factory
        self._save_dir = Path(save_dir)
        self._offline_policy = offline_policy
        self._clock = clock
        self._utcnow = utcnow
        self._lock = RLock()
        self._app = factory()
        self._revision = 0
        self._last_explicit_mutation_revision = 0
        self._last_clock = clock()

    def _sync_clock_locked(self) -> OfflineProgressResult | None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_clock)
        self._last_clock = now
        if (
            self._offline_policy is None
            or elapsed <= 0.0
            or self._app.time_paused
        ):
            return None
        result = self._app.advance_offline(
            elapsed * self._app.time_speed_multiplier,
            self._offline_policy,
        )
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
            "automatic_progress_enabled": self._offline_policy is not None,
            "offline_progress_enabled": self._offline_policy is not None,
            "time_paused": self._app.time_paused,
            "time_speed_multiplier": self._app.time_speed_multiplier,
            "real_seconds_per_game_day": (
                None
                if self._offline_policy is None
                else self._offline_policy.real_seconds_per_game_day
            ),
        }

    def metadata(self) -> dict[str, object]:
        with self._lock:
            self._sync_clock_locked()
            return self._metadata_locked()

    def snapshot(self, queries: Mapping[str, Query]) -> RuntimeResult:
        """Read several projections at one authoritative simulation instant.

        A UI refresh must not observe research at day N, logistics at day N+1 and
        inventory at day N+2 merely because separate HTTP requests each advanced
        the lazy wall clock. The clock is synchronized once, then every projection
        is read while the runtime lock is held.
        """
        with self._lock:
            self._sync_clock_locked()
            data: dict[str, object] = {"session": self._metadata_locked()}
            data.update(
                {name: self._app.query(query) for name, query in queries.items()}
            )
            return RuntimeResult(self._revision, data)

    def set_time_control(
        self,
        *,
        paused: bool | None = None,
        speed_multiplier: float | None = None,
    ) -> RuntimeResult:
        command = SetTimeControl(
            paused=paused,
            speed_multiplier=speed_multiplier,
        )
        with self._lock:
            self._sync_clock_locked()
            before = (
                self._app.time_paused,
                self._app.time_speed_multiplier,
            )
            self._app.execute(command)
            after = (
                self._app.time_paused,
                self._app.time_speed_multiplier,
            )
            if after != before:
                self._revision += 1
                self._last_explicit_mutation_revision = self._revision
            return RuntimeResult(self._revision, self._metadata_locked())

    def query(self, query: Query) -> RuntimeResult:
        with self._lock:
            self._sync_clock_locked()
            return RuntimeResult(self._revision, self._app.query(query))

    def execute(
        self,
        command: Command,
        *,
        expected_revision: int | None = None,
    ) -> RuntimeResult:
        with self._lock:
            self._sync_clock_locked()
            if expected_revision is not None:
                conflict = (
                    expected_revision > self._revision
                    or self._last_explicit_mutation_revision > expected_revision
                )
                if conflict:
                    raise RevisionConflict(expected_revision, self._revision)
            result = self._app.execute(command)
            self._revision += 1
            self._last_explicit_mutation_revision = self._revision
            return RuntimeResult(self._revision, result)

    def new_game(self) -> RuntimeResult:
        with self._lock:
            self._app = self._factory()
            self._last_clock = self._clock()
            self._revision += 1
            self._last_explicit_mutation_revision = self._revision
            return RuntimeResult(self._revision, self._metadata_locked())

    def _slot_path(self, slot: str) -> Path:
        if (
            not isinstance(slot, str)
            or not _SLOT_RE.fullmatch(slot)
            or slot in {".", ".."}
        ):
            raise ValueError("invalid save slot")
        return self._save_dir / f"{slot}.json"

    def save(self, slot: str) -> RuntimeResult:
        with self._lock:
            self._sync_clock_locked()
            path = self._slot_path(slot)
            save_game(self._app, path, saved_at=self._utcnow())
            return RuntimeResult(
                self._revision,
                {"slot": slot, "saved": True},
            )

    def load(
        self,
        slot: str,
        *,
        apply_offline: bool = True,
    ) -> RuntimeResult:
        with self._lock:
            path = self._slot_path(slot)
            if not path.is_file():
                raise FileNotFoundError(path)
            policy = self._offline_policy if apply_offline else None
            app, offline_result = load_game(
                path,
                self._factory,
                now=self._utcnow(),
                offline_policy=policy,
            )
            self._app = app
            self._last_clock = self._clock()
            self._revision += 1
            self._last_explicit_mutation_revision = self._revision
            return RuntimeResult(
                self._revision,
                {
                    "slot": slot,
                    "loaded": True,
                    "offline_progress": (
                        None
                        if offline_result is None
                        else to_jsonable(offline_result)
                    ),
                    "session": self._metadata_locked(),
                },
            )
