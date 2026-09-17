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

def test_service_capacity_requirement_is_distinct_from_capability_requirement():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids
    from space_idle.facilities import FacilityDef, ServiceCapacitySupply
    from space_idle.shared import DefinitionId
    from space_idle.site import ServiceCapacityRequirement, SiteRequirements, evaluate_site_requirements

    sim = build_game_application()._simulation
    service_type = "test.site_service_capacity"
    facility_definition_id = DefinitionId("test.facility.site_service_capacity")
    sim.facilities.definitions[facility_definition_id] = FacilityDef(
        facility_definition_id,
        "Site service-capacity fixture",
        service_capacity_supplies=(ServiceCapacitySupply(service_type, 1.0),),
    )
    sim.facilities.install(facility_definition_id, ids.EARTH)
    power = sim.power.snapshot(ids.EARTH, sim.facilities, sim.day)
    failures = evaluate_site_requirements(
        SiteRequirements(service_capacity_requirements=(
            ServiceCapacityRequirement(service_type, 2.0),
        )),
        ids.EARTH,
        sim.day,
        sim.environment,
        sim.facilities,
        power,
    )
    assert [(row.code, row.detail) for row in failures] == [
        ("service_capacity:available", f"{service_type}:1/2")
    ]


def test_service_capacity_dependency_order_is_upstream_first_deterministic_and_fail_closed():
    dependencies = (
        ServiceCapacityDependency("research", "surface"),
        ServiceCapacityDependency("surface", "power"),
        ServiceCapacityDependency("cargo", "surface"),
    )
    assert service_capacity_dependency_order(
        {"cargo", "research", "surface", "power"}, dependencies
    ) == ("power", "surface", "cargo", "research")

    cyclic = (
        ServiceCapacityDependency("surface", "cargo"),
        ServiceCapacityDependency("cargo", "surface"),
    )
    with pytest.raises(ValueError, match="service capacity dependency cycle"):
        service_capacity_dependency_order({"surface", "cargo"}, cyclic)

def test_configuration_validation_rejects_same_tick_service_dependency_cycle():
    from space_idle import build_game_application
    from space_idle.domain import DomainExtension
    from space_idle.service_capacity import ServiceCapacityScope
    from space_idle.validation import validate_simulation_configuration
    from space_idle.validation_support import ConfigurationError

    class CyclicProvider:
        def service_capacity_types(self):
            return ("test.cycle.a", "test.cycle.b")

        def service_capacity_scope(self, service_type):
            if service_type not in self.service_capacity_types():
                raise KeyError(service_type)
            return ServiceCapacityScope.OPERATIONAL_NODE

        def service_capacity_provider_definition_ids(self, service_type):
            if service_type not in self.service_capacity_types():
                raise KeyError(service_type)
            return frozenset()

        def service_capacity_upstream_services(self, service_type):
            if service_type == "test.cycle.a":
                return frozenset({"test.cycle.b"})
            if service_type == "test.cycle.b":
                return frozenset({"test.cycle.a"})
            raise KeyError(service_type)

        def service_capacity_supply_at(self, *_args, **_kwargs):
            return (0.0, 0.0)

    sim = build_game_application()._simulation
    provider = CyclicProvider()
    sim.domain_extensions += (
        DomainExtension(
            "test.cyclic_service_provider",
            service_capacity_provider=lambda _sim: provider,
        ),
    )

    with pytest.raises(ConfigurationError, match="service capacity dependency cycle"):
        validate_simulation_configuration(sim)
