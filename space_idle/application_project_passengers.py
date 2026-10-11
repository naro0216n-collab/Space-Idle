from __future__ import annotations

from .app_contracts.passenger_views import (
    PassengerDispatchOptionRow, PassengerTransferPreviewView,
    PassengerCargoHoldView, PassengerTransferRow, PassengerTransfersView,
)
from .shared import SpatialNodeId


class PassengerProjectorMixin:
    """Expose Population-owned decisions without reconstructing rules in UI."""

    def _passenger_transfer_preview_view(self, query):
        sim = self._simulation
        population = sim.population
        origin = SpatialNodeId(query.origin_node_id)
        destination = SpatialNodeId(query.destination_node_id)
        if not population.graph.has_operational_node(origin) or not population.graph.has_operational_node(destination):
            raise ValueError('passenger transfer endpoints must be established')
        if query.source_external_provider_id is None:
            available = population.free_count_at(origin)
        else:
            source = population.external_definitions.get(query.source_external_provider_id)
            if source is None or source.operational_node_id != origin:
                raise ValueError('external source is not at origin')
            available = population.external_available(query.source_external_provider_id, sim.day)
        housing = max(0, population.housing_capacity(destination, sim.day) - population.count_at(destination)
                      - population._inbound_by_node().get(destination, 0))
        receive = population._supportable_admission(destination, min(query.requested_count, housing), sim.day)
        options = population.transfer_preview(origin, destination, query.requested_count, sim.day)
        external_sources = tuple(
            (source_id, population.external_remaining[source_id],
             source.max_acquisition_per_day, population.external_available(source_id, sim.day))
            for source_id, source in sorted(population.external_definitions.items())
            if source.operational_node_id == origin
        )
        target = population.targets.get(origin)
        after = (None if target is None else max(
            0, target - population.count_at(origin)
            + (min(query.requested_count, available) if query.source_external_provider_id is None else 0)
        ))
        return PassengerTransferPreviewView(
            str(origin), str(destination), query.requested_count, available, housing, receive,
            tuple(PassengerDispatchOptionRow(
                option.mode, str(option.vehicle_definition_id),
                tuple(str(value) for value in option.allocation_ids),
                tuple(str(value) for value in option.movement_path), option.units,
                option.latency_days, min(option.possible_people, available, receive),
                max(0, query.requested_count - min(option.possible_people, available, receive)),
                option.payload_per_person_t * min(option.possible_people, available, receive),
                tuple((str(node), str(resource), amount) for node, resource, amount in option.resources_for_dispatch),
                option.blockers + (('no_source_people',) if available == 0 else ())
                + (('destination_life_support_or_housing',) if receive == 0 else ()),
            ) for option in options), external_sources, after,
        )

    def _passenger_transfers_view(self, query):
        sim = self._simulation
        population = sim.population
        transport = sim.transport
        # Physical stock belongs to Transport; this is a read projection over
        # its existing immutable snapshots, not an Application-owned manifest.
        movements = {item.owner_id: item for item in transport.movement_execution_snapshots()
                     if item.kind.value == 'passenger_transfer'}
        commitments = {item.owner_activity_ref.activity_id: item
                       for item in transport.fleet_commitment_snapshots()
                       if item.owner_activity_ref.activity_type == 'passenger_transfer'}
        service_transits = {}
        for transit in transport.passenger_service_transits.values():
            if transit.order_id is not None:
                service_transits.setdefault(transit.order_id, []).append(transit)
        if query.operational_node_id is not None:
            self._require_operational_node(query.operational_node_id)
        rows = []
        for order in sorted(population.transfer_orders.values(), key=lambda row: str(row.id)):
            if (query.operational_node_id is not None and query.operational_node_id not in
                    (str(order.origin_node_id), str(order.destination_node_id))):
                continue
            transit_count = order.transit_count(population.groups)
            pending = order.pending_count(population.groups)
            source = order.capacity_source_constraint
            mode = None if source is None else ('dedicated' if source.dedicated_vehicle_definition_id is not None else 'service')
            blockers = ()
            if pending and not transit_count:
                blockers = population.transfer_order_blockers(order, self._simulation.day)
            holds = []
            movement = movements.get(order.id)
            if movement is not None and movement.payload_resources:
                holds.append(PassengerCargoHoldView(
                    f'movement:{movement.id}', None,
                    tuple((str(row.resource_id), row.amount_t) for row in movement.payload_resources), (),
                ))
            commitment = commitments.get(order.id)
            if commitment is not None and commitment.onboard_resources:
                recovery_node = commitment.operational_node_id
                resources = dict(commitment.onboard_resources)
                holds.append(PassengerCargoHoldView(
                    f'fleet_commitment:{commitment.id}',
                    None if recovery_node is None else str(recovery_node),
                    tuple((str(resource), amount) for resource, amount in commitment.onboard_resources),
                    ('storage_admission_unavailable',) if recovery_node is not None
                    and not sim.inventory.can_admit_resources(recovery_node, resources) else (),
                ))
            for transit in sorted(service_transits.get(order.id, ()), key=lambda row: str(row.id)):
                if not transit.onboard_resources:
                    continue
                # Arrival waiting remains physically in Transport custody even
                # if passengers have already disembarked. It is never a local
                # Inventory quantity until finite storage admission succeeds.
                recovery_node = transit.legs[-1].destination_id if transit.arrival_day <= sim.day else None
                holds.append(PassengerCargoHoldView(
                    f'passenger_transit:{transit.id}',
                    None if recovery_node is None else str(recovery_node),
                    tuple((str(resource), amount) for resource, amount in
                          sorted(transit.onboard_resources.items())),
                    ('storage_admission_unavailable',) if recovery_node is not None
                    and not sim.inventory.can_admit_resources(recovery_node, transit.onboard_resources) else (),
                ))
            rows.append(PassengerTransferRow(
                str(order.id), str(order.origin_node_id), str(order.destination_node_id),
                order.requested_count, pending, transit_count, order.delivered_count,
                order.cancelled_count, order.deceased_count, order.status(population.groups),
                order.source_external_provider_id, mode, int(order.activity_priority), blockers,
                tuple(holds),
            ))
        return PassengerTransfersView(tuple(rows))
