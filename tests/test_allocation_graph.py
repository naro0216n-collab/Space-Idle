from __future__ import annotations

from types import MethodType

import pytest

from space_idle import build_game_application
from space_idle.application_commands import (
    GetBottlenecks,
    GetLogisticsLanes,
    GetProjects,
    GetResearch,
    GetScientificExplorations,
)
from space_idle.allocation_graph import AllocationDependency, allocation_dependency_order
from space_idle.simulation import (
    ALLOCATION_FUNDS,
    ALLOCATION_LOGISTICS,
    ALLOCATION_MAINTENANCE,
    ALLOCATION_POWER,
    ALLOCATION_RESOURCES,
    ALLOCATION_TRANSPORT,
    _service_allocation_node,
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
    service_types = set(sim._service_allocation_types(sim._service_capacity_requests()))
    order = sim.tick_allocation_order(service_types)
    position = {node: index for index, node in enumerate(order)}

    assert position[ALLOCATION_FUNDS] < position[ALLOCATION_LOGISTICS]
    assert position[ALLOCATION_LOGISTICS] < position[ALLOCATION_RESOURCES]
    assert position[ALLOCATION_RESOURCES] < position[ALLOCATION_MAINTENANCE]
    assert position[ALLOCATION_MAINTENANCE] < position[ALLOCATION_POWER]
    assert all(
        position[ALLOCATION_POWER] < position[_service_allocation_node(service_type)]
        for service_type in service_types
    )
    assert all(
        position[_service_allocation_node(service_type)] < position[ALLOCATION_TRANSPORT]
        for service_type in service_types
    )
    for dependency in sim.service_capacity_dependencies():
        assert position[_service_allocation_node(dependency.upstream_service_type)] < position[
            _service_allocation_node(dependency.service_type)
        ]


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


def test_runtime_and_application_queries_do_not_use_standalone_power_allocator(monkeypatch):
    app = build_game_application()
    sim = app._simulation

    def forbidden_snapshot(*args, **kwargs):
        raise AssertionError("standalone Power snapshot allocator must not be used")

    monkeypatch.setattr(sim.power, "snapshot", forbidden_snapshot)

    decision = sim.tick_decision_projection()
    assert decision.allocations.power_by_location
    sim.refresh_storage(decision.allocations.power_by_location)

    for query in (
        GetProjects(),
        GetLogisticsLanes(),
        GetResearch(),
        GetScientificExplorations(),
        GetBottlenecks(),
    ):
        app.query(query)

    sim.advance_days(1)
