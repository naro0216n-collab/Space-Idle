from __future__ import annotations

import pytest

from space_idle.service_capacity import (
    ServiceCapacityDependency, ServiceCapacityRequest, allocate_service_capacity,
    service_capacity_dependency_order,
)
from space_idle.shared import EntityId, SpatialNodeId


def _request(name: str, requested: float, priority: int = 3) -> ServiceCapacityRequest:
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
    high = _request("high", 3.0, 5)
    low = _request("low", 3.0, 1)
    supply = {(SpatialNodeId("node.test"), "test_service"): 4.0}
    plan = allocate_service_capacity((low, high), nominal_supply=supply)

    assert plan.allocated(high.id) == pytest.approx(3.0)
    assert plan.allocated(low.id) == pytest.approx(1.0)



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


def test_service_capacity_dependency_order_is_upstream_first_and_deterministic():
    dependencies = (
        ServiceCapacityDependency("research", "surface"),
        ServiceCapacityDependency("surface", "power"),
        ServiceCapacityDependency("cargo", "surface"),
    )
    assert service_capacity_dependency_order(
        {"cargo", "research", "surface", "power"}, dependencies
    ) == ("power", "surface", "cargo", "research")


def test_service_capacity_dependency_cycle_fails_closed():
    dependencies = (
        ServiceCapacityDependency("surface", "cargo"),
        ServiceCapacityDependency("cargo", "surface"),
    )
    with pytest.raises(ValueError, match="service capacity dependency cycle"):
        service_capacity_dependency_order({"surface", "cargo"}, dependencies)


def test_configuration_validation_rejects_same_tick_service_dependency_cycle():
    from space_idle import build_game_application
    from space_idle.surface_infrastructure import SURFACE_DISTRIBUTION_SERVICE
    from space_idle.validation import validate_simulation_configuration
    from space_idle.validation_support import ConfigurationError

    sim = build_game_application()._simulation
    assert sim.surface_infrastructure is not None
    sim.surface_infrastructure.network_dependent_service_types = frozenset(
        {SURFACE_DISTRIBUTION_SERVICE}
    )

    with pytest.raises(ConfigurationError, match="service capacity dependency cycle"):
        validate_simulation_configuration(sim)
