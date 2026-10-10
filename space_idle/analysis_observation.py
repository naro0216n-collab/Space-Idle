"""Opt-in read-only observations of domain-owned stocks and finite capacity.

Unlike Definition dependencies, these values describe an actual canonical-day
State. No forecast, allocation or flow is inferred from a stock observation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite

from .shared import DefinitionId, SpatialNodeId
from .logistics_models import CargoPositionSnapshot
from .simulation import Simulation


@dataclass(frozen=True, order=True)
class StateMetric:
    kind: str
    subject_id: str
    context_id: str
    quantity: float
    unit: str
    provenance: str

    def __post_init__(self) -> None:
        if not self.kind or not self.subject_id or not self.context_id or not self.unit or not self.provenance:
            raise ValueError("state metric requires source, scope, unit and provenance")
        if not isfinite(self.quantity) or self.quantity < -1e-9:
            raise ValueError("state metric must be finite and nonnegative")


@dataclass(frozen=True)
class StateObservation:
    day: int
    scenario_id: str
    metrics: tuple[StateMetric, ...]
    operational_node_ids: tuple[str, ...] | None = None
    resource_ids: tuple[str, ...] | None = None
    cargo_positions: tuple[CargoPositionSnapshot, ...] = ()

    def to_json_data(self) -> dict:
        return {
            "day": self.day,
            "scenario_id": self.scenario_id,
            "scope": {
                "operational_node_ids": (None if self.operational_node_ids is None
                                         else list(self.operational_node_ids)),
                "resource_ids": (None if self.resource_ids is None
                                 else list(self.resource_ids)),
            },
            "cargo_positions": [{k: str(v) if v is not None and not isinstance(v, (int, float, bool)) else v
                                 for k, v in asdict(row).items()} for row in self.cargo_positions],
            "metrics": [
                {
                    "kind": value.kind, "subject_id": value.subject_id,
                    "context_id": value.context_id, "quantity": value.quantity,
                    "unit": value.unit, "provenance": value.provenance,
                }
                for value in self.metrics
            ],
        }


def observe_state(
    sim: Simulation, *,
    operational_node_ids: frozenset[SpatialNodeId] | None = None,
    resource_ids: frozenset[DefinitionId] | None = None,
) -> StateObservation:
    """Read only requested contexts, never deriving or advancing a tick.

    Stored/available/reserved and physical/usable capacities are distinct;
    quantities are owned by their native Inventory, Market, Fleet, and Research
    domains. The result is a snapshot, not a second authoritative State.
    """
    rows: list[StateMetric] = []

    def in_scope(node_id: SpatialNodeId, resource_id: DefinitionId | None = None) -> bool:
        return ((operational_node_ids is None or node_id in operational_node_ids)
                and (resource_id is None or resource_ids is None or resource_id in resource_ids))

    def emit(kind: str, owner: object, context: object, amount: float, unit: str, provenance: str) -> None:
        rows.append(StateMetric(kind, str(owner), str(context), amount, unit, provenance))

    inventory = sim.inventory
    # Include reservation-only keys as well as ordinary stocks. Reservation
    # invariants are owned by Inventory, not revalidated by the analyzer.
    stock_keys = set(inventory.stock)
    stock_keys.update((node_id, resource_id) for _owner, node_id, resource_id in inventory.reserved)
    for node_id, resource_id in sorted(stock_keys):
        if not in_scope(node_id, resource_id):
            continue
        emit("inventory_stock", resource_id, node_id,
             inventory.amount(node_id, resource_id), "t", "inventory.stock")
        emit("inventory_reserved", resource_id, node_id,
             inventory.reserved_total(node_id, resource_id), "t", "inventory.reserved")
        emit("inventory_available", resource_id, node_id,
             inventory.available(node_id, resource_id), "t", "inventory.available")
    if resource_ids is None:
        # Pool utilization is not reducible to an individual Resource. Include
        # occupied pools even when no Storage provider has installed capacity.
        storage_keys = set(inventory.physical_storage_capacity_t)
        storage_keys.update(inventory.usable_storage_capacity_t)
        storage_keys.update((node_id, inventory.storage_pool_for_resource(resource_id))
                            for node_id, resource_id in inventory.stock)
        storage_keys.update((node_id, inventory.storage_pool_for_resource(resource_id))
                            for _owner, node_id, resource_id in inventory.external_occupancy)
        for node_id, pool in sorted(storage_keys):
            if not in_scope(node_id):
                continue
            admission = inventory.admission_state_for_pool(node_id, pool)
            emit("storage_pool_occupied", pool, node_id,
                 admission.occupied_t, "t", "inventory.admission_state_for_pool")
            emit("storage_pool_admission_available", pool, node_id,
                 admission.admission_capacity_t, "t", "inventory.admission_state_for_pool")
            emit("storage_pool_over_capacity", pool, node_id,
                 admission.over_capacity_t, "t", "inventory.admission_state_for_pool")
        for (node_id, pool), amount in inventory.physical_storage_capacity_t.items():
            if in_scope(node_id):
                emit("physical_storage_capacity", pool, node_id, amount, "t",
                     "inventory.physical_storage_capacity_t")
        for (node_id, pool), amount in inventory.usable_storage_capacity_t.items():
            if in_scope(node_id):
                emit("usable_storage_capacity", pool, node_id, amount, "t",
                     "inventory.usable_storage_capacity_t")

    if resource_ids is None:
        for vehicle_id, node_id in sim.transport.fleet_pool_keys():
            if in_scope(node_id):
                pool = sim.transport.fleet_pool_snapshot(vehicle_id, node_id)
                # An empty FleetPool key is not owned physical stock and need
                # not survive Save/Load. Observe only actual units, rather
                # than making a stale zero-valued key a semantic difference.
                if pool.total_units == 0:
                    continue
                emit("fleet_total", vehicle_id, node_id, pool.total_units, "units", "transport.fleet_pool_snapshot")
                emit("fleet_free", vehicle_id, node_id,
                     pool.free_units, "units", "transport.fleet_pool_snapshot")

    # Detached Fleet commitments are physical assets, not Operational Node
    # Inventory or FleetPool stock. Their onboard Resources belong to Transport
    # while in flight or at a non-operational target. Keep the distinction even
    # in a partial observation; never label the target as an owned Node.
    for commitment in sim.transport.fleet_commitment_snapshots():
        # A Node filter includes commitments physically stationed at that Node.
        # A moving unit or a unit at an unestablished target belongs to no
        # operational Node, even when its origin/destination lies in scope.
        if (operational_node_ids is not None and
                commitment.operational_node_id not in operational_node_ids):
            continue
        if commitment.physical_target is not None:
            endpoint = commitment.physical_target
            context = f"physical_target:{endpoint.locator_kind}:{endpoint.locator_id}"
        elif commitment.movement_execution_id is not None:
            context = f"movement:{commitment.movement_execution_id}"
        else:
            context = str(commitment.operational_node_id)
        if resource_ids is None:
            emit("fleet_committed", commitment.vehicle_definition_id, context,
                 commitment.quantity, "units", f"transport.fleet_commitment:{commitment.id}")
            if commitment.operational_node_id is None:
                emit("fleet_detached", commitment.vehicle_definition_id, context,
                     commitment.quantity, "units", f"transport.fleet_commitment:{commitment.id}")
        for resource_id, amount in commitment.onboard_resources:
            if resource_ids is None or resource_id in resource_ids:
                emit("fleet_onboard_resource", resource_id, context,
                     amount, "t", f"transport.fleet_commitment:{commitment.id}")

    # Movement payloads and aggregate passenger-service provisions remain
    # Transport-owned physical Stock until a real arrival/admission. Neither
    # their origin nor intended destination is an Operational Node holding
    # that Resource in the meantime. A Node-scoped observation therefore
    # deliberately excludes them rather than inventing local Inventory.
    if operational_node_ids is None:
        for execution in sim.transport.movement_execution_snapshots():
            for payload in execution.payload_resources:
                if resource_ids is None or payload.resource_id in resource_ids:
                    emit("movement_payload_resource", payload.resource_id,
                         f"movement:{execution.id}", payload.amount_t, "t",
                         f"transport.movement_execution:{execution.id}:payload_resources")
        for transit in sorted(sim.transport.passenger_service_transits.values(),
                              key=lambda row: str(row.id)):
            for resource_id, amount in sorted(transit.onboard_resources.items()):
                if resource_ids is None or resource_id in resource_ids:
                    emit("passenger_service_onboard_resource", resource_id,
                         f"passenger_transit:{transit.id}", amount, "t",
                         f"transport.passenger_service_transit:{transit.id}:onboard_resources")

    # Provider stock belongs to the external Market, not the local Inventory.
    # A scoped observation includes only providers with an enabled Interface
    # at the requested Node. Provider availability is still a shared stock,
    # NOT per-interface or guaranteed delivery to that Node.
    providers_in_scope = (set(sim.market.provider_states) if operational_node_ids is None else {
        interface.provider_id for interface in sim.market.interfaces.values()
        if interface.enabled and interface.operational_node_id in operational_node_ids
    })
    for provider_id in sorted(providers_in_scope):
        state = sim.market.provider_states.get(provider_id)
        if state is None:
            continue
        for resource_id in sorted(state.supply_available_t):
            if resource_ids is not None and resource_id not in resource_ids:
                continue
            emit("external_market_supply_remaining", resource_id, provider_id,
                 state.supply_available_t[resource_id], "t", "market.provider_states.supply_available_t")
            emit("external_market_supply_available", resource_id, provider_id,
                 sim.market.available_provider_supply_t(provider_id, resource_id),
                 "t", "market.available_provider_supply_t")
        for resource_id in sorted(state.demand_available_t):
            if resource_ids is None or resource_id in resource_ids:
                emit("external_market_demand_available", resource_id, provider_id,
                     sim.market.available_provider_demand_t(provider_id, resource_id),
                     "t", "market.available_provider_demand_t")

    if operational_node_ids is None and resource_ids is None:
        emit("funds_balance", "funds", "organization", sim.market.funds.balance,
             "MUSD", "market.funds.balance")
        emit("funds_reserved", "funds", "organization", sim.market.reserved_funds_musd,
             "MUSD", "market.buy_commitments")
        if sim.research is not None:
            emit("research_points_stored", "research_points", "organization",
                 sim.research.stored_points, "research_points", "research.stored_points")

    # A destination is not physical ownership. Observe active Cargo through its
    # owner Domain's public projection; do not add unarrived Cargo to Inventory.
    cargo = tuple(row for row in sim.logistics.cargo_position_snapshot()
                  if (resource_ids is None or row.resource_id in resource_ids)
                  and (operational_node_ids is None
                       or row.current_node_id in operational_node_ids
                       or row.leg_source_id in operational_node_ids
                       or row.leg_destination_id in operational_node_ids))
    return StateObservation(
        sim.day, sim.scenario_id, tuple(sorted(rows)),
        None if operational_node_ids is None else tuple(sorted(map(str, operational_node_ids))),
        None if resource_ids is None else tuple(sorted(map(str, resource_ids))), cargo,
    )
