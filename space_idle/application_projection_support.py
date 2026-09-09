from __future__ import annotations

from typing import Mapping


class ApplicationProjectionSupportMixin:
    """Shared conversion helpers for application-layer read models."""

    def _transport_value(self, value: object) -> object:
        if isinstance(value, Mapping):
            return tuple(
                (str(key), self._transport_value(item))
                for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            )
        if isinstance(value, (tuple, list)):
            return tuple(self._transport_value(item) for item in value)
        return value
