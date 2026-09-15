from __future__ import annotations

from enum import IntEnum


class PriorityLevel(IntEnum):
    """Canonical ordinal allocation band shared by player-facing priorities."""

    LOWEST = 1
    LOW = 2
    NORMAL = 3
    HIGH = 4
    HIGHEST = 5


class _TypedPriority(int):
    """Validated integer value that preserves the semantic role of a priority."""

    role_name = "priority"

    def __new__(cls, value: int | PriorityLevel = PriorityLevel.NORMAL):
        if isinstance(value, _TypedPriority) and not isinstance(value, cls):
            raise ValueError(f"{cls.role_name} cannot use a different priority role")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{cls.role_name} must be an integer PriorityLevel")
        try:
            level = PriorityLevel(int(value))
        except ValueError as exc:
            raise ValueError(f"{cls.role_name} must be between 1 and 5") from exc
        return int.__new__(cls, int(level))

    @property
    def level(self) -> PriorityLevel:
        return PriorityLevel(int(self))


class ActivityPriority(_TypedPriority):
    """Priority for competing use of already-available resources/services/capacity."""

    role_name = "activity priority"


class ProvisioningPriority(_TypedPriority):
    """Priority for provisioning finite assets such as Fleet to Transport Allocations."""

    role_name = "provisioning priority"


DEFAULT_PRIORITY_LEVEL = PriorityLevel.NORMAL
DEFAULT_ACTIVITY_PRIORITY = ActivityPriority(DEFAULT_PRIORITY_LEVEL)
DEFAULT_PROVISIONING_PRIORITY = ProvisioningPriority(DEFAULT_PRIORITY_LEVEL)
