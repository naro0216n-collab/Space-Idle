from __future__ import annotations

import pytest

from space_idle.service_capacity import ServiceCapacityRequest, allocate_service_capacity
from space_idle.shared import EntityId, SpatialNodeId


def _request(name: str, requested: float, priority: int = 50) -> ServiceCapacityRequest:
    return ServiceCapacityRequest(
        EntityId(f"request.{name}"), SpatialNodeId("node.test"), "test_service",
        requested, priority, "test", EntityId(name), "work",
    )


def test_same_priority_service_scarcity_is_proportional_and_registration_order_independent():
    first = _request("first", 6.0)
    second = _request("second", 3.0)
    supply = {(SpatialNodeId("node.test"), "test_service"): 3.0}

    forward = allocate_service_capacity((first, second), nominal_supply=supply)
    reverse = allocate_service_capacity((second, first), nominal_supply=supply)

    assert forward.allocated(first.id) == pytest.approx(2.0)
    assert forward.allocated(second.id) == pytest.approx(1.0)
    assert reverse.allocated(first.id) == pytest.approx(2.0)
    assert reverse.allocated(second.id) == pytest.approx(1.0)


def test_higher_priority_service_request_is_allocated_before_lower_priority():
    high = _request("high", 3.0, 100)
    low = _request("low", 3.0, 10)
    supply = {(SpatialNodeId("node.test"), "test_service"): 4.0}
    plan = allocate_service_capacity((low, high), nominal_supply=supply)

    assert plan.allocated(high.id) == pytest.approx(3.0)
    assert plan.allocated(low.id) == pytest.approx(1.0)


def test_industry_and_extraction_publish_requests_into_shared_service_plan():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids

    sim = build_game_application()._simulation
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    plan = sim.service_capacity_allocation_projection({ids.EARTH: power})

    industry = tuple(
        request for request in plan.requests
        if request.operational_node_id == ids.EARTH and request.owner_kind == "industry_process"
    )
    extraction = tuple(
        request for request in plan.requests
        if request.operational_node_id == ids.EARTH and request.owner_kind == "extraction"
    )
    assert industry
    assert extraction
    assert all(request.service_type.startswith("process:") for request in industry)
    assert all(request.service_type.startswith("extraction:") for request in extraction)
    assert all(plan.allocated(request.id) == pytest.approx(request.requested_rate) for request in industry + extraction)


def test_service_capacity_requirement_is_distinct_from_capability_requirement():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids
    from space_idle.site import ServiceCapacityRequirement, SiteRequirements, evaluate_site_requirements

    sim = build_game_application()._simulation
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    failures = evaluate_site_requirements(
        SiteRequirements(service_capacity_requirements=(
            ServiceCapacityRequirement("research_execution", 2.0),
        )),
        ids.EARTH,
        sim.day,
        sim.environment,
        sim.facilities,
        power,
    )
    assert [(row.code, row.detail) for row in failures] == [
        ("service_capacity:available", "research_execution:1/2")
    ]
