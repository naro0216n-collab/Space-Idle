from __future__ import annotations

import pytest

from space_idle import GetBuildOptions, GetOperationalNode, build_game_application
from space_idle.catalog import ResourceDef
from space_idle.content import base_ids as ids
from space_idle.inventory import DEFAULT_STORAGE_POOL_KEY, InventoryBook
from space_idle.power import PowerSnapshot, PowerSpec
from space_idle.shared import DefinitionId, SpatialNodeId
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError


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


def test_special_storage_power_fulfillment_and_pause_preserve_only_physically_available_capacity():
    app = build_game_application()
    sim = app._simulation
    node = ids.LUNAR_ORBIT
    facility = next(
        row for row in sim.facilities.all_at(node)
        if row.definition_id == ids.ORBITAL_LOGISTICS_NODE
    )
    pool = sim.inventory.storage_pool_for_resource(ids.PROPELLANT)
    base_infrastructure = sim.storage.infrastructure_capacity_t[(node, pool)]
    capacity = sim.storage.providers[facility.definition_id].capacity_t_by_pool[pool]
    assert pool in sim.storage.providers[facility.definition_id].power_sensitive_pools
    assert sim.inventory.admission_state(node, ids.PROPELLANT).usable_capacity_t == pytest.approx(
        base_infrastructure + capacity
    )

    sim.facilities.pause(facility.id)
    sim.refresh_storage()
    paused = app.query(GetOperationalNode(str(node)))
    special = next(row for row in paused.storage if row.storage_pool_key == pool)
    assert special.physical_capacity_t == pytest.approx(base_infrastructure + capacity)
    assert special.usable_capacity_t == pytest.approx(base_infrastructure)
    facility_row = next(row for row in paused.facilities if row.id == str(facility.id))
    assert facility_row.power_active_load_mw == pytest.approx(sim.power.specs[facility.definition_id].load_mw)
    assert facility_row.power_standby_load_mw == pytest.approx(sim.power.specs[facility.definition_id].standby_load_mw)
    option = next(row for row in app.query(GetBuildOptions(str(node))).items
                  if row.facility_definition_id == str(facility.definition_id))
    assert option.power_nominal_standby_load_mw == pytest.approx(facility_row.power_standby_load_mw)
    assert next(row for row in paused.inventory if row.resource_id == str(ids.WATER)).admission_capacity is None

    # Pausing ordinary output does not withdraw cryogenic preservation when
    # its standby demand is supplied by another power asset.
    power_unit = sim.facilities.install(ids.ORBITAL_FISSION_POWER, node)
    sim.refresh_storage()
    assert sim.inventory.admission_state(node, ids.PROPELLANT).usable_capacity_t == pytest.approx(
        base_infrastructure + capacity
    )
    sim.facilities.pause(power_unit)
    sim.refresh_storage()
    assert sim.inventory.admission_state(node, ids.PROPELLANT).usable_capacity_t == pytest.approx(
        base_infrastructure
    )

    sim.facilities.resume(facility.id)
    sim.refresh_storage()
    assert sim.inventory.admission_state(node, ids.PROPELLANT).usable_capacity_t == pytest.approx(
        base_infrastructure + capacity
    )
    # Power availability is an admission constraint, not a modification to
    # physical storage hardware or existing Resource ownership.
    without_power = sim.power.snapshot(node, sim.facilities, sim.day)
    dark = PowerSnapshot(
        0.0, without_power.demand_mw, 0.0, {},
        without_power.maintenance_factor_by_facility,
    )
    sim.storage.refresh_node(node, sim.day, dark)
    admission = sim.inventory.admission_state(node, ids.PROPELLANT)
    assert admission.physical_capacity_t == pytest.approx(base_infrastructure + capacity)
    assert admission.usable_capacity_t == pytest.approx(base_infrastructure)


def test_power_sensitive_storage_requires_real_power_and_cryogenic_content_has_standby():
    app = build_game_application()
    sim = app._simulation
    for definition_id, spec in sim.storage.providers.items():
        if not spec.power_sensitive_pools:
            continue
        assert sim.power.specs[definition_id].load_mw > 0
        assert sim.power.specs[definition_id].standby_load_mw > 0
    validate_simulation_configuration(sim)

    provider_id = ids.ORBITAL_LOGISTICS_NODE
    original = sim.power.specs[provider_id]
    sim.power.specs[provider_id] = PowerSpec(
        original.generation, load_mw=0.0, standby_load_mw=0.0
    )
    with pytest.raises(ConfigurationError, match="active power demand"):
        validate_simulation_configuration(sim)
