from __future__ import annotations

from typing import Mapping


class ApplicationProjectionSupportMixin:
    """Shared conversion helpers for application-layer read models."""

    def _tick_decision_projection(self):
        """Reuse one transient tick decision across an Application query snapshot.

        A single Application query or Runtime UI snapshot may ask several read-model
        projectors about the same authoritative simulation instant.  The decision
        projection is derived state and can be expensive, so all projectors in that
        query scope observe the same derived value.  The cache is discarded when the
        outer query completes, so commands cannot observe stale derived state.
        """
        cache = getattr(self, "_query_projection_cache", None)
        if cache is None:
            return self._simulation.tick_decision_projection()
        decision = cache.get("tick_decision")
        if decision is None:
            decision = self._simulation.tick_decision_projection()
            cache["tick_decision"] = decision
        return decision

    def _transport_value(self, value: object) -> object:
        if isinstance(value, Mapping):
            return tuple(
                (str(key), self._transport_value(item))
                for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            )
        if isinstance(value, (tuple, list)):
            return tuple(self._transport_value(item) for item in value)
        return value
