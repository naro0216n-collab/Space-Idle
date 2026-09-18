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

def test_site_eligibility_and_finite_service_allocation_are_separate_contracts():
    from space_idle import build_game_application
    from space_idle.content import base_ids as ids
    from space_idle.execution_requirements import (
        ExecutionRequirementBundle,
        ServiceCapacityRequirement,
        allocate_execution_requirements,
        service_constraint,
    )
    from space_idle.facilities import CapabilitySupply, FacilityDef, ServiceCapacitySupply
    from space_idle.priority import ActivityPriority
    from space_idle.shared import DefinitionId
    from space_idle.site import (
        CapabilityRequirement, CapabilityRequirementState, SiteRequirements,
        evaluate_site_requirements,
    )

    sim = build_game_application()._simulation
    service_type = "test.site_service_capacity"
    capability_id = "test.site_capability"
    facility_definition_id = DefinitionId("test.facility.site_service_capacity")
    sim.facilities.definitions[facility_definition_id] = FacilityDef(
        facility_definition_id,
        "Site eligibility / allocation fixture",
        capability_supplies=(CapabilitySupply(capability_id),),
        service_capacity_supplies=(ServiceCapacitySupply(service_type, 1.0),),
    )
    sim.facilities.install(facility_definition_id, ids.EARTH)

    eligibility = SiteRequirements(capability_requirements=(
        CapabilityRequirement(capability_id, CapabilityRequirementState.ACTIVE),
    ))
    assert not evaluate_site_requirements(
        eligibility, ids.EARTH, sim.day, sim.environment, sim.facilities
    )

    bundles = tuple(
        ExecutionRequirementBundle(
            EntityId(f"execution.{name}"),
            "test_activity",
            EntityId(name),
            "work",
            ids.EARTH,
            1.0,
            ActivityPriority(3),
            (ServiceCapacityRequirement(service_type, 1.0),),
        )
        for name in ("a", "b")
    )
    plan = allocate_execution_requirements(
        bundles, {service_constraint(ids.EARTH, service_type): 1.0}
    )
    assert plan.allocated(EntityId("execution.a")) == pytest.approx(0.5)
    assert plan.allocated(EntityId("execution.b")) == pytest.approx(0.5)
