"""Cross-domain test inputs, kept separate from the canonical game content."""

from dataclasses import replace

import pytest

from space_idle.spatial import SpatialGraph


@pytest.fixture
def short_interplanetary_transit(monkeypatch):
    """Exercise real multi-day interplanetary lifecycle without repeating years of ticks.

    Change only the representative *time* of interplanetary separation in this
    test's World instance(s). Distances, delta-v, Vehicle eligibility, resources,
    operation requirements, and all canonical day transitions stay unchanged.
    Patching the Graph class also applies to fresh graphs reconstructed by Load.

    Tests needing the full physical transit duration simply do not request the
    fixture; those test the unmodified base-game trajectory and Offline replay.
    """
    original = SpatialGraph.characteristic_transport_separation

    def shortened(self, origin_context_id, destination_context_id):
        separation = original(self, origin_context_id, destination_context_id)
        if (separation.scope == "interplanetary_transfer"
                and separation.representative_transit_days is not None):
            return replace(separation, representative_transit_days=min(3.0, separation.representative_transit_days))
        return separation

    monkeypatch.setattr(SpatialGraph, "characteristic_transport_separation", shortened)
