from __future__ import annotations

import pytest

from space_idle import GetOperationalNode, build_game_application
from space_idle.catalog import ResourceDef
from space_idle.content import base_ids as ids
from space_idle.inventory import DEFAULT_STORAGE_POOL_KEY, InventoryBook
from space_idle.shared import DefinitionId, SpatialNodeId


def test_unrestricted_ordinary_inventory_and_shared_finite_special_storage():
    node = SpatialNodeId("node.test")
    a, b, special = (DefinitionId("resource.a"), DefinitionId("resource.b"),
                     DefinitionId("resource.special"))
    inventory = InventoryBook({
        a: ResourceDef(a, "A"), b: ResourceDef(b, "B"),
        special: ResourceDef(special, "Special", storage_pool_key="cryogenic"),
    })
    assert inventory.admit(node, a, 500.0).fully_admitted
    inventory.set_capacity_snapshot({(node, "cryogenic"): 10.0}, {(node, "cryogenic"): 10.0})
    assert inventory.admit(node, b, 1000.0).fully_admitted
    assert inventory.can_admit_resources(node, {a: 1000.0, b: 1000.0})
    assert inventory.admission_state(node, a).blockers == ()
    assert inventory.stored_in_pool(node, DEFAULT_STORAGE_POOL_KEY) == pytest.approx(1500.0)

    assert inventory.admit(node, special, 8.0).fully_admitted
    assert not inventory.can_admit_resources(node, {special: 3.0})
    inventory.set_capacity_snapshot(
        {(node, "cryogenic"): 10.0}, {(node, "cryogenic"): 5.0},
        {(node, "cryogenic"): ("storage_power_limited",)},
    )
    limited = inventory.admission_state(node, special)
    assert limited.over_capacity_t == pytest.approx(3.0)
    assert limited.admission_capacity_t == pytest.approx(0.0)
    assert "storage_over_capacity" in limited.blockers
    assert inventory.admit(node, special, 2.0).rejected_t == pytest.approx(2.0)
    assert inventory.admit(node, b, 2500.0).fully_admitted


def test_application_exposes_special_capacity_but_not_fictitious_ordinary_headroom():
    app = build_game_application()
    sim = app._simulation
    node = ids.EARTH
    pool = "cryogenic"
    physical = dict(sim.inventory.physical_storage_capacity_t)
    usable = dict(sim.inventory.usable_storage_capacity_t)
    occupied = sim.inventory.stored_in_pool(node, pool)
    usable[(node, pool)] = max(0.0, occupied - 1.0)
    sim.inventory.set_capacity_snapshot(
        physical, usable, {(node, pool): ("storage_power_limited",)}
    )
    # A Resource remains selectable even when current stock is zero.
    sim.inventory.stock.pop((node, ids.WATER), None)
    view = app.query(GetOperationalNode(str(node)))
    ordinary = next(row for row in view.inventory if row.resource_id == str(ids.WATER))
    assert ordinary.amount == pytest.approx(0.0)
    assert ordinary.physical_capacity is None
    assert ordinary.usable_capacity is None
    assert ordinary.admission_capacity is None
    assert not ordinary.admission_blockers
    assert not any(row.storage_pool_key == DEFAULT_STORAGE_POOL_KEY for row in view.storage)
    special = next(row for row in view.inventory if row.resource_id == str(ids.OXYGEN))
    assert special.over_capacity == pytest.approx(1.0)
    assert special.admission_capacity == pytest.approx(0.0)
    assert any(blocker.code == "storage_over_capacity" for blocker in special.admission_blockers)
    storage = next(row for row in view.storage if row.storage_pool_key == pool)
    assert storage.unusable_occupied_t == pytest.approx(1.0)


def test_unrestricted_capacity_is_not_written_to_stock_or_storage_snapshots():
    node = SpatialNodeId("node.unrestricted")
    resource = DefinitionId("resource.normal")
    inventory = InventoryBook({resource: ResourceDef(resource, "Normal")})
    with pytest.raises(ValueError, match="nonfinite"):
        inventory.add(node, resource, float("inf"))
    with pytest.raises(ValueError, match="nonfinite"):
        inventory.admit(node, resource, float("nan"))
    with pytest.raises(ValueError, match="ordinary Inventory"):
        inventory.set_capacity_snapshot({(node, DEFAULT_STORAGE_POOL_KEY): 3.0}, {})
    with pytest.raises(ValueError, match="finite and nonnegative"):
        inventory.set_capacity_snapshot({(node, "cryogenic"): float("inf")}, {})
    assert inventory.amount(node, resource) == 0.0
    inventory.add(node, resource, 1e308)
    with pytest.raises(ValueError, match="nonfinite inventory stock"):
        inventory.add(node, resource, 1e308)
    assert inventory.amount(node, resource) == 1e308
