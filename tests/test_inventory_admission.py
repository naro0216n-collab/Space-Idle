from __future__ import annotations

import pytest

from space_idle import GetOperationalNode, build_game_application
from space_idle.content import base_ids as ids
from space_idle.inventory import InventoryBook
from space_idle.shared import DefinitionId, SpatialNodeId


def test_inventory_admission_preserves_stock_when_usable_capacity_falls_and_recovers():
    node = SpatialNodeId("node.test")
    a = DefinitionId("resource.a")
    b = DefinitionId("resource.b")
    inventory = InventoryBook()
    inventory.register_storage_class(a, "bulk")
    inventory.register_storage_class(b, "bulk")
    no_storage_node = SpatialNodeId("node.no-storage")
    assert inventory.admission_state(no_storage_node, a).admission_capacity_t == pytest.approx(0.0)
    assert inventory.admit(no_storage_node, a, 1.0).admitted_t == pytest.approx(0.0)
    inventory.set_capacity_snapshot({(node, "bulk"): 10.0}, {(node, "bulk"): 10.0})

    admitted = inventory.admit(node, a, 8.0)
    assert admitted.fully_admitted
    assert inventory.amount(node, a) == pytest.approx(8.0)

    inventory.set_capacity_snapshot({(node, "bulk"): 10.0}, {(node, "bulk"): 5.0})
    constrained = inventory.admission_state(node, a)
    assert inventory.amount(node, a) == pytest.approx(8.0)
    assert constrained.physical_capacity_t == pytest.approx(10.0)
    assert constrained.usable_capacity_t == pytest.approx(5.0)
    assert constrained.over_capacity_t == pytest.approx(3.0)
    assert constrained.admission_capacity_t == pytest.approx(0.0)
    assert constrained.conditioning_required
    assert "storage_over_capacity" in constrained.blockers

    blocked = inventory.admit(node, b, 2.0)
    assert blocked.admitted_t == pytest.approx(0.0)
    assert blocked.rejected_t == pytest.approx(2.0)

    inventory.set_capacity_snapshot({(node, "bulk"): 10.0}, {(node, "bulk"): 10.0})
    recovered = inventory.admit(node, b, 2.0)
    assert recovered.fully_admitted
    assert inventory.stored_in_class(node, "bulk") == pytest.approx(10.0)


def test_execution_bundles_share_one_storage_class_admission_capacity():
    app = build_game_application()
    sim = app._simulation
    node = ids.EARTH
    bulk_capacity = sim.inventory.usable_storage_capacity_t[(node, "bulk")]
    sim.inventory.admit(node, ids.AGGREGATE, bulk_capacity - 1.0)

    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[node]
    rows = sim.extraction.snapshots(
        node, sim.facilities, sim.inventory, power, sim.day, decision.allocations.execution
    )
    bulk_output = sum(
        row.output_t_per_day
        for row in rows
        if sim.inventory.resource_storage_class.get(row.output_resource_id) == "bulk"
    )
    assert bulk_output == pytest.approx(1.0)
    state = sim.inventory.admission_state_for_class(node, "bulk")
    assert state.admission_capacity_t == pytest.approx(1.0)


def test_application_exposes_inventory_admission_and_over_capacity_state():
    app = build_game_application()
    sim = app._simulation
    node = ids.EARTH
    resource = ids.AGGREGATE
    current_physical = dict(sim.inventory.physical_storage_capacity_t)
    current_usable = dict(sim.inventory.usable_storage_capacity_t)
    sim.inventory.admit(node, resource, 2.0)
    current_usable[(node, "bulk")] = 1.0
    sim.inventory.set_capacity_snapshot(current_physical, current_usable)

    view = app.query(GetOperationalNode(str(node)))
    row = next(item for item in view.inventory if item.resource_id == str(resource))
    storage = next(item for item in view.storage if item.storage_class == "bulk")
    assert row.over_capacity == pytest.approx(1.0)
    assert row.admission_capacity == pytest.approx(0.0)
    assert row.conditioning_required
    assert "storage_over_capacity" in row.admission_blockers
    assert storage.unusable_occupied_t == pytest.approx(1.0)
    assert "storage_over_capacity" in storage.admission_blockers
