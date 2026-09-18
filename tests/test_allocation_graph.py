from __future__ import annotations

from types import MethodType

import pytest

from space_idle import build_game_application
from space_idle.allocation_graph import AllocationDependency
from space_idle.simulation import (
    ALLOCATION_LOGISTICS,
    ALLOCATION_MAINTENANCE,
    ALLOCATION_POWER,
    ALLOCATION_RESOURCES,
    ALLOCATION_TRANSPORT,
)
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError
from space_idle.domain import DomainExtension
from space_idle.service_capacity import ServiceCapacityScope




def test_tick_allocation_graph_orders_dependencies_and_configuration_rejects_cycles():
    sim = build_game_application()._simulation
    service_plan = sim.service_capacity_allocation_projection()
    service_types = {row.service_type for row in service_plan.requests}
    for dependency in sim.service_capacity_dependencies():
        service_types.add(dependency.service_type)
        service_types.add(dependency.upstream_service_type)

    order = sim.tick_allocation_order(service_types)
    assert order == sim.tick_allocation_order(tuple(reversed(sorted(service_types))))
    position = {node: index for index, node in enumerate(order)}
    dependencies = sim.tick_allocation_dependencies(service_types)

    assert position[ALLOCATION_LOGISTICS] < position[ALLOCATION_RESOURCES]
    assert position[ALLOCATION_RESOURCES] < position[ALLOCATION_MAINTENANCE]
    assert position[ALLOCATION_MAINTENANCE] < position[ALLOCATION_POWER]
    assert position[ALLOCATION_POWER] < position[ALLOCATION_TRANSPORT]
    assert all(
        position[edge.upstream_node] < position[edge.node]
        for edge in dependencies
    )
    cross_domain = build_game_application()._simulation
    original = cross_domain.tick_allocation_dependencies

    def cyclic_dependencies(self, service_types):
        return original(service_types) + (
            AllocationDependency(ALLOCATION_LOGISTICS, ALLOCATION_TRANSPORT),
        )

    cross_domain.tick_allocation_dependencies = MethodType(cyclic_dependencies, cross_domain)
    with pytest.raises(ConfigurationError, match="tick allocation dependency cycle"):
        validate_simulation_configuration(cross_domain)

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

    service_cycle = build_game_application()._simulation
    provider = CyclicProvider()
    service_cycle.domain_extensions += (
        DomainExtension(
            "test.cyclic_service_provider",
            service_capacity_provider=lambda _sim: provider,
        ),
    )
    with pytest.raises(ConfigurationError, match="service capacity dependency cycle"):
        validate_simulation_configuration(service_cycle)
