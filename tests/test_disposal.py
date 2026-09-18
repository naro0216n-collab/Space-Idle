from __future__ import annotations

import pytest

from space_idle.catalog import ResourceDef
from space_idle.disposal import salvage_admission_requirements, settle_salvage_recovery
from space_idle.execution_requirements import (
    ExecutionRequirementBundle,
    StockOrPoolAdmissionRequirement,
    admission_constraint,
    allocate_execution_requirements,
)
from space_idle.inventory import DEFAULT_STORAGE_POOL_KEY, InventoryBook
from space_idle.priority import ActivityPriority
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId


NODE = SpatialNodeId("test.node.disposal")
DEFAULT_SALVAGE = DefinitionId("test.resource.salvage.default")
CRYOGENIC_SALVAGE = DefinitionId("test.resource.salvage.cryogenic")
CONCURRENT_STOCK = DefinitionId("test.resource.concurrent.default")


def test_disposal_bundle_uses_one_fraction_across_pools_and_is_order_independent():
    inventory = InventoryBook(
        {
            DEFAULT_SALVAGE: ResourceDef(DEFAULT_SALVAGE, "Default salvage"),
            CRYOGENIC_SALVAGE: ResourceDef(
                CRYOGENIC_SALVAGE, "Cryogenic salvage", storage_pool_key="cryogenic"
            ),
            CONCURRENT_STOCK: ResourceDef(CONCURRENT_STOCK, "Concurrent stock"),
        }
    )
    inventory.set_capacity_snapshot(
        {
            (NODE, DEFAULT_STORAGE_POOL_KEY): 8.0,
            (NODE, "cryogenic"): 6.0,
        },
        {
            (NODE, DEFAULT_STORAGE_POOL_KEY): 8.0,
            (NODE, "cryogenic"): 6.0,
        },
    )

    potential = ((DEFAULT_SALVAGE, 10.0), (CRYOGENIC_SALVAGE, 6.0))
    requirements = salvage_admission_requirements(inventory, potential)
    assert requirements == (
        StockOrPoolAdmissionRequirement("cryogenic", 6.0),
        StockOrPoolAdmissionRequirement(DEFAULT_STORAGE_POOL_KEY, 10.0),
    )
    assert salvage_admission_requirements(inventory, reversed(potential)) == requirements

    salvage = ExecutionRequirementBundle(
        id=EntityId("test.disposal"),
        owner_kind="test_disposal",
        owner_id=EntityId("test.asset"),
        purpose="salvage_admission",
        operational_node_id=NODE,
        requested_execution=1.0,
        priority=ActivityPriority(3),
        requirements=requirements,
    )
    concurrent = ExecutionRequirementBundle(
        id=EntityId("test.concurrent"),
        owner_kind="test",
        owner_id=EntityId("test.concurrent.owner"),
        purpose="concurrent_admission",
        operational_node_id=NODE,
        requested_execution=1.0,
        priority=ActivityPriority(5),
        requirements=(StockOrPoolAdmissionRequirement(DEFAULT_STORAGE_POOL_KEY, 2.0),),
    )
    capacities = {
        admission_constraint(NODE, DEFAULT_STORAGE_POOL_KEY): 8.0,
        admission_constraint(NODE, "cryogenic"): 6.0,
    }
    forward = allocate_execution_requirements((salvage, concurrent), capacities)
    reverse = allocate_execution_requirements((concurrent, salvage), capacities)
    assert forward.fulfillment(salvage.id) == pytest.approx(0.6)
    assert reverse.fulfillment(salvage.id) == pytest.approx(0.6)

    assert inventory.admit(NODE, CONCURRENT_STOCK, 2.0).fully_admitted
    recovered = dict(
        settle_salvage_recovery(
            inventory,
            NODE,
            reversed(potential),
            forward.fulfillment(salvage.id),
        )
    )
    assert recovered[DEFAULT_SALVAGE] == pytest.approx(6.0)
    assert recovered[CRYOGENIC_SALVAGE] == pytest.approx(3.6)
    assert inventory.amount(NODE, DEFAULT_SALVAGE) == pytest.approx(6.0)
    assert inventory.amount(NODE, CRYOGENIC_SALVAGE) == pytest.approx(3.6)
