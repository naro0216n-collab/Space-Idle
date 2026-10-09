from __future__ import annotations

from .app_contracts.passenger_views import (
    PassengerDispatchOptionRow, PassengerTransferPreviewView,
    PassengerTransferRow, PassengerTransfersView,
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
        housing = max(0, population.housing_capacity(destination, sim.day) - population.count_at(destination))
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
        population = self._simulation.population
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
                if source is None:
                    blockers = ('transport_service_required',)
                elif mode == 'dedicated':
                    option = population.dedicated_dispatch_option(
                        self._simulation.transport,
                        order.origin_node_id, order.destination_node_id, pending,
                        source.dedicated_vehicle_definition_id, source.dedicated_units,
                        self._simulation.day, source.movement_hard_constraint,
                    )
                    blockers = option.blockers
            rows.append(PassengerTransferRow(
                str(order.id), str(order.origin_node_id), str(order.destination_node_id),
                order.requested_count, pending, transit_count, order.delivered_count,
                order.cancelled_count, order.deceased_count, order.status(population.groups),
                order.source_external_provider_id, mode, int(order.activity_priority), blockers,
            ))
        return PassengerTransfersView(tuple(rows))
