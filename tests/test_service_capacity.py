from __future__ import annotations

import pytest

from space_idle.service_capacity import ServiceCapacityRequest, allocate_service_capacity
from space_idle.shared import EntityId, SpatialNodeId


def _request(name: str, requested: float, priority: int = 3) -> ServiceCapacityRequest:
    return ServiceCapacityRequest(
        EntityId(f"request.{name}"), SpatialNodeId("node.test"), "test_service",
        requested, priority, "test", EntityId(name), "work",
    )


def test_service_capacity_allocator_honors_priority_and_is_order_independent_within_band():
    first = _request("first", 6.0)
    second = _request("second", 3.0)
    supply = {(SpatialNodeId("node.test"), "test_service"): 3.0}

    forward = allocate_service_capacity((first, second), nominal_supply=supply)
    reverse = allocate_service_capacity((second, first), nominal_supply=supply)

    assert forward.allocated(first.id) == pytest.approx(2.0)
    assert forward.allocated(second.id) == pytest.approx(1.0)
    assert reverse.allocated(first.id) == pytest.approx(2.0)
    assert reverse.allocated(second.id) == pytest.approx(1.0)

    high = _request("high", 3.0, 5)
    low = _request("low", 3.0, 1)
    priority_supply = {(SpatialNodeId("node.test"), "test_service"): 4.0}
    priority_plan = allocate_service_capacity((low, high), nominal_supply=priority_supply)

    assert priority_plan.allocated(high.id) == pytest.approx(3.0)
    assert priority_plan.allocated(low.id) == pytest.approx(1.0)
