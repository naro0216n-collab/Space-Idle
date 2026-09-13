from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PauseFacility:
    facility_id: str


@dataclass(frozen=True)
class ResumeFacility:
    facility_id: str


@dataclass(frozen=True)
class SetFacilityProcess:
    facility_id: str
    process_id: str


@dataclass(frozen=True)
class SetPowerPriority:
    facility_id: str
    priority: int | None


@dataclass(frozen=True)
class SetMaintenancePriority:
    facility_id: str
    priority: int


@dataclass(frozen=True)
class SetTimeControl:
    paused: bool | None = None
    speed_multiplier: float | None = None

    def __post_init__(self) -> None:
        if self.paused is None and self.speed_multiplier is None:
            raise ValueError("paused or speed_multiplier is required")
        if self.paused is not None and not isinstance(self.paused, bool):
            raise ValueError("paused must be boolean")
        if self.speed_multiplier is not None:
            if isinstance(self.speed_multiplier, bool) or not isinstance(
                self.speed_multiplier, (int, float)
            ):
                raise ValueError("speed_multiplier must be a number")
            speed = float(self.speed_multiplier)
            if not isfinite(speed) or speed <= 0.0 or speed > 64.0:
                raise ValueError(
                    "speed_multiplier must be greater than 0 and at most 64"
                )
            object.__setattr__(self, "speed_multiplier", speed)


@dataclass(frozen=True)
class AdvanceTime:
    days: int
