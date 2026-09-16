from __future__ import annotations

from types import MethodType

import pytest

from space_idle import build_game_application
from space_idle.allocation_graph import AllocationDependency, allocation_dependency_order
from space_idle.simulation import (
    ALLOCATION_FUNDS,
    ALLOCATION_LOGISTICS,
    ALLOCATION_MAINTENANCE,
    ALLOCATION_POWER,
    ALLOCATION_RESOURCES,
    ALLOCATION_TRANSPORT,
)
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError


def test_generic_allocation_dependency_order_is_deterministic_and_fail_closed():
    dependencies = (
        AllocationDependency("transport", "service"),
        AllocationDependency("service", "power"),
        AllocationDependency("power", "resources"),
    )
    assert allocation_dependency_order(
        {"transport", "service", "power", "resources"}, dependencies
    ) == ("resources", "power", "service", "transport")

    with pytest.raises(ValueError, match="allocation dependency cycle"):
        allocation_dependency_order(
            {"a", "b"},
            (AllocationDependency("a", "b"), AllocationDependency("b", "a")),
        )


def test_tick_allocation_graph_orders_cross_domain_and_service_dependencies():
    sim = build_game_application()._simulation
    service_plan = sim.service_capacity_allocation_projection()
    service_types = {row.service_type for row in service_plan.requests}
    for dependency in sim.service_capacity_dependencies():
        service_types.add(dependency.service_type)
        service_types.add(dependency.upstream_service_type)

    order = sim.tick_allocation_order(service_types)
    position = {node: index for index, node in enumerate(order)}
    dependencies = sim.tick_allocation_dependencies(service_types)

    assert position[ALLOCATION_FUNDS] < position[ALLOCATION_LOGISTICS]
    assert position[ALLOCATION_LOGISTICS] < position[ALLOCATION_RESOURCES]
    assert position[ALLOCATION_RESOURCES] < position[ALLOCATION_MAINTENANCE]
    assert position[ALLOCATION_MAINTENANCE] < position[ALLOCATION_POWER]
    assert position[ALLOCATION_POWER] < position[ALLOCATION_TRANSPORT]
    assert all(
        position[edge.upstream_node] < position[edge.node]
        for edge in dependencies
    )

def test_configuration_validation_rejects_cross_domain_allocation_cycle():
    sim = build_game_application()._simulation
    original = sim.tick_allocation_dependencies

    def cyclic_dependencies(self, service_types):
        return original(service_types) + (
            AllocationDependency(ALLOCATION_FUNDS, ALLOCATION_TRANSPORT),
        )

    sim.tick_allocation_dependencies = MethodType(cyclic_dependencies, sim)
    with pytest.raises(ConfigurationError, match="tick allocation dependency cycle"):
        validate_simulation_configuration(sim)
