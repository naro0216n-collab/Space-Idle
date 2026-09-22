from __future__ import annotations

import pytest

from space_idle import GetOperationalNode, build_game_application
from space_idle.catalog import ResourceDef
from space_idle.content import base_ids as ids
from space_idle.inventory import DEFAULT_STORAGE_POOL_KEY, InventoryBook
from space_idle.shared import DefinitionId, SpatialNodeId


def test_inventory_admission_preserves_stock_and_enforces_resource_pool_compatibility():
    node = SpatialNodeId("node.test")
    a = DefinitionId("resource.a")
    b = DefinitionId("resource.b")
    special = DefinitionId("resource.special")
    inventory = InventoryBook({
        a: ResourceDef(a, "A"),
        b: ResourceDef(b, "B"),
        special: ResourceDef(special, "Special", storage_pool_key="cryogenic"),
    })
    no_storage_node = SpatialNodeId("node.no-storage")
    assert inventory.admission_state(no_storage_node, a).admission_capacity_t == pytest.approx(0.0)
    assert inventory.admit(no_storage_node, a, 1.0).admitted_t == pytest.approx(0.0)
    pool = DEFAULT_STORAGE_POOL_KEY
    inventory.set_capacity_snapshot({(node, pool): 10.0}, {(node, pool): 10.0})

    admitted = inventory.admit(node, a, 8.0)
    assert admitted.fully_admitted
    assert inventory.amount(node, a) == pytest.approx(8.0)

    inventory.set_capacity_snapshot(
        {(node, pool): 10.0}, {(node, pool): 5.0}, {(node, pool): ("storage_power_limited",)}
    )
    constrained = inventory.admission_state(node, a)
    assert inventory.amount(node, a) == pytest.approx(8.0)
    assert constrained.physical_capacity_t == pytest.approx(10.0)
    assert constrained.usable_capacity_t == pytest.approx(5.0)
    assert constrained.over_capacity_t == pytest.approx(3.0)
    assert constrained.admission_capacity_t == pytest.approx(0.0)
    assert constrained.limiting_factors == ("storage_power_limited",)
    assert "storage_over_capacity" in constrained.blockers

    blocked = inventory.admit(node, b, 2.0)
    assert blocked.admitted_t == pytest.approx(0.0)
    assert blocked.rejected_t == pytest.approx(2.0)

    inventory.set_capacity_snapshot({(node, pool): 10.0}, {(node, pool): 10.0})
    recovered = inventory.admit(node, b, 2.0)
    assert recovered.fully_admitted
    assert inventory.stored_in_pool(node, pool) == pytest.approx(10.0)

    special_state = inventory.admission_state(node, special)
    assert special_state.storage_pool_key == "cryogenic"
    assert special_state.physical_capacity_t == pytest.approx(0.0)
    assert special_state.admission_capacity_t == pytest.approx(0.0)
    assert "storage_capacity_unavailable" in special_state.blockers
    assert inventory.admit(node, special, 1.0).admitted_t == pytest.approx(0.0)

def test_execution_bundles_share_one_default_pool_admission_capacity():
    app = build_game_application()
    sim = app._simulation
    node = ids.EARTH
    pool = DEFAULT_STORAGE_POOL_KEY
    capacity = sim.inventory.usable_storage_capacity_t[(node, pool)]
    sim.inventory.admit(node, ids.MINERAL_FEEDSTOCK, capacity - sim.inventory.stored_in_pool(node, pool) - 1.0)

    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[node]
    rows = sim.extraction.snapshots(
        node, sim.facilities, sim.inventory, power, sim.day, decision.allocations.execution
    )
    default_pool_output = sum(
        row.output_t_per_day
        for row in rows
        if sim.inventory.storage_pool_for_resource(row.output_resource_id) == pool
    )
    assert default_pool_output == pytest.approx(1.0)
    state = sim.inventory.admission_state_for_pool(node, pool)
    assert state.admission_capacity_t == pytest.approx(1.0)


def test_application_exposes_pool_capacity_and_actual_limiting_factor():
    app = build_game_application()
    sim = app._simulation
    node = ids.EARTH
    resource = ids.MINERAL_FEEDSTOCK
    pool = sim.inventory.storage_pool_for_resource(resource)
    current_physical = dict(sim.inventory.physical_storage_capacity_t)
    current_usable = dict(sim.inventory.usable_storage_capacity_t)
    occupied = sim.inventory.stored_in_pool(node, pool)
    current_usable[(node, pool)] = max(0.0, occupied - 1.0)
    sim.inventory.set_capacity_snapshot(
        current_physical, current_usable, {(node, pool): ("storage_power_limited",)}
    )

    view = app.query(GetOperationalNode(str(node)))
    row = next(item for item in view.inventory if item.resource_id == str(resource))
    storage = next(item for item in view.storage if item.storage_pool_key == pool)
    assert row.over_capacity == pytest.approx(1.0)
    assert row.admission_capacity == pytest.approx(0.0)
    assert tuple(factor.code for factor in row.limiting_factors) == ("storage_power_limited",)
    assert row.limiting_factors[0].severity == "limiting"
    assert row.limiting_factors[0].affected_action == "admit_storage"
    assert any(blocker.code == "storage_over_capacity" for blocker in row.admission_blockers)
    assert storage.unusable_occupied_t == pytest.approx(1.0)
    assert tuple(factor.code for factor in storage.limiting_factors) == ("storage_power_limited",)
    assert any(blocker.code == "storage_over_capacity" for blocker in storage.admission_blockers)
