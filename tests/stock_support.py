"""Physical stock setup for tests of non-Storage domain contracts.

Tests of Fleet, Founding, Population, and movement explicitly begin with
pre-existing stored materials, not with a promise that the standard Scenario
has enough cold space for arbitrary fixture quantities. Use the Storage owner
rather than assigning Inventory.stock directly or bypassing Admission.
"""

from space_idle.inventory import DEFAULT_STORAGE_POOL_KEY


def add_preexisting_stock(sim, node_id, resource_id, amount):
    pool = sim.inventory.storage_pool_for_resource(resource_id)
    if pool != DEFAULT_STORAGE_POOL_KEY:
        state = sim.inventory.admission_state_for_pool(node_id, pool)
        shortfall = max(0.0, amount - state.admission_capacity_t)
        if shortfall > 1e-9:
            existing = sim.storage.infrastructure_capacity_t.get((node_id, pool), 0.0)
            sim.storage.set_infrastructure_capacity(node_id, pool, existing + shortfall)
            sim.refresh_storage()
    sim.inventory.add(node_id, resource_id, amount)
