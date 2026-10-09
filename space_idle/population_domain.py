from __future__ import annotations

from .domain import DomainExtension, StateCodec, decode_dict, decode_float, decode_int, decode_list, decode_str, require_fields
from .population import PopulationGroup, PopulationPosition, PassengerTransferOrder, PassengerCapacitySource
from .shared import EntityId, SpatialNodeId, DefinitionId
from .validation_support import ValidationContext


def capture_population_state(sim):
    population = sim.population
    return {
        'groups': [
            {'id': str(group.id), 'count': group.count,
             'position': {'kind': group.position.kind, 'ref': group.position.ref},
             'activity_commitment_ref': group.activity_commitment_ref,
             'deprivation': group.deprivation,
             'mortality_remainder': group.mortality_remainder}
            for group in sorted(population.groups.values(), key=lambda group: str(group.id))
        ],
        'targets': [{'node_id': str(node), 'desired_count': count}
                    for node, count in sorted(population.targets.items(), key=lambda pair: str(pair[0]))],
        'transfer_orders': [
            {
                'id': str(order.id), 'origin_node_id': str(order.origin_node_id),
                'destination_node_id': str(order.destination_node_id),
                'requested_count': order.requested_count, 'activity_priority': int(order.activity_priority),
                'source_external_provider_id': order.source_external_provider_id,
                'capacity_source_constraint': None if order.capacity_source_constraint is None else {
                    'transport_allocation_ids': None if order.capacity_source_constraint.transport_allocation_ids is None else [str(value) for value in order.capacity_source_constraint.transport_allocation_ids],
                    'dedicated_vehicle_definition_id': None if order.capacity_source_constraint.dedicated_vehicle_definition_id is None else str(order.capacity_source_constraint.dedicated_vehicle_definition_id),
                    'dedicated_units': order.capacity_source_constraint.dedicated_units,
                    'movement_hard_constraint': None if order.capacity_source_constraint.movement_hard_constraint is None else list(order.capacity_source_constraint.movement_hard_constraint),
                },
                'delivered_count': order.delivered_count,
                'cancelled_count': order.cancelled_count,
                'deceased_count': order.deceased_count,
                'in_transit_group_refs': [str(value) for value in order.in_transit_group_refs],
            }
            for order in sorted(population.transfer_orders.values(), key=lambda value: str(value.id))
        ],
        'external_remaining': dict(sorted(population.external_remaining.items())),
        'external_acquisition_day': population.external_acquisition_day,
        'external_acquired_today': dict(sorted(population.external_acquired_today.items())),
        'next_group_id': population._next_group_id,
        'next_transfer_order_id': population._next_transfer_order_id,
    }


def restore_population_state(sim, state):
    row = require_fields(state, {'groups', 'targets', 'transfer_orders', 'external_remaining', 'external_acquisition_day', 'external_acquired_today', 'next_group_id', 'next_transfer_order_id'}, 'population state')
    service = sim.population
    groups = {}
    for raw in decode_list(row['groups'], 'population groups'):
        group_data = require_fields(raw, {'id', 'count', 'position', 'activity_commitment_ref', 'deprivation', 'mortality_remainder'}, 'population group')
        pos = require_fields(group_data['position'], {'kind', 'ref'}, 'population position')
        commitment = group_data['activity_commitment_ref']
        if commitment is not None:
            commitment = decode_str(commitment, 'population commitment')
        group = PopulationGroup(
            EntityId(decode_str(group_data['id'], 'group id')),
            decode_int(group_data['count'], 'population count'),
            PopulationPosition(decode_str(pos['kind'], 'position kind'), decode_str(pos['ref'], 'position ref')),
            commitment,
            decode_float(group_data['deprivation'], 'deprivation'),
            decode_float(group_data['mortality_remainder'], 'mortality remainder'),
        )
        if group.id in groups:
            raise ValueError('duplicate population group')
        groups[group.id] = group
    targets = {}
    for raw in decode_list(row['targets'], 'population targets'):
        target = require_fields(raw, {'node_id', 'desired_count'}, 'population target')
        node_id = SpatialNodeId(decode_str(target['node_id'], 'population target node'))
        if node_id in targets:
            raise ValueError('duplicate population target')
        targets[node_id] = decode_int(target['desired_count'], 'population target count')
    remaining = decode_dict(row['external_remaining'], 'external population remaining')
    service.groups = groups
    service.targets = targets
    orders = {}
    for raw in decode_list(row['transfer_orders'], 'passenger orders'):
        data = require_fields(raw, {
            'id', 'origin_node_id', 'destination_node_id', 'requested_count',
            'activity_priority', 'source_external_provider_id', 'capacity_source_constraint',
            'delivered_count', 'cancelled_count', 'deceased_count', 'in_transit_group_refs',
        }, 'passenger order')
        constraint = None
        if data['capacity_source_constraint'] is not None:
            source = require_fields(data['capacity_source_constraint'], {
                'transport_allocation_ids', 'dedicated_vehicle_definition_id',
                'dedicated_units', 'movement_hard_constraint',
            }, 'passenger capacity source')
            constraint = PassengerCapacitySource(
                None if source['transport_allocation_ids'] is None else tuple(EntityId(decode_str(item, 'service allocation id')) for item in decode_list(source['transport_allocation_ids'], 'service allocations')),
                None if source['dedicated_vehicle_definition_id'] is None else DefinitionId(decode_str(source['dedicated_vehicle_definition_id'], 'dedicated vehicle id')),
                None if source['dedicated_units'] is None else decode_int(source['dedicated_units'], 'dedicated units'),
                None if source['movement_hard_constraint'] is None else tuple(decode_str(item, 'movement plan id') for item in decode_list(source['movement_hard_constraint'], 'movement constraint')),
            )
        order = PassengerTransferOrder(
            EntityId(decode_str(data['id'], 'order id')),
            SpatialNodeId(decode_str(data['origin_node_id'], 'order origin')),
            SpatialNodeId(decode_str(data['destination_node_id'], 'order destination')),
            decode_int(data['requested_count'], 'order requested count'),
            decode_int(data['activity_priority'], 'order priority'),
            None if data['source_external_provider_id'] is None else decode_str(data['source_external_provider_id'], 'source provider'),
            constraint,
            decode_int(data['delivered_count'], 'order delivered'),
            decode_int(data['cancelled_count'], 'order cancelled'),
            decode_int(data['deceased_count'], 'order deceased'),
            [EntityId(decode_str(item, 'in transit group')) for item in decode_list(data['in_transit_group_refs'], 'in transit references')],
        )
        if order.id in orders:
            raise ValueError('duplicate passenger order id')
        orders[order.id] = order
    service.transfer_orders = orders
    service.external_remaining = {identifier: decode_int(value, 'external source remaining') for identifier, value in remaining.items()}
    service.external_acquisition_day = decode_int(row['external_acquisition_day'], 'external acquisition day')
    service.external_acquired_today = {
        identifier: decode_int(value, 'external acquired today')
        for identifier, value in decode_dict(row['external_acquired_today'], 'external acquired today').items()
    }
    service._next_group_id = decode_int(row['next_group_id'], 'next population group id')
    if service._next_group_id < 0:
        raise ValueError('negative population group counter')
    service._next_transfer_order_id = decode_int(row['next_transfer_order_id'], 'next passenger order id')
    service._day_fulfillment = {}
    service._dispatch_options.clear()
    service.validate()


def validate_configuration(sim, ctx: ValidationContext) -> None:
    del ctx
    for source in sim.population.external_definitions.values():
        for technology in source.required_technology_ids:
            if technology not in sim.research.definitions:
                raise ValueError(f'external population source technology not defined: {technology}')
    for definition in sim.facilities.definitions.values():
        if definition.life_support is not None:
            for resource_id, _ in definition.life_support.net_resources:
                if resource_id not in sim.inventory.resource_definitions:
                    raise ValueError(f'life support Resource not registered: {resource_id}')
    for vehicle in sim.transport.vehicle_definitions():
        for resource_id, _ in vehicle.passengers.net_resources_per_person_day:
            if resource_id not in sim.inventory.resource_definitions:
                raise ValueError(f'onboard life support Resource not registered: {resource_id}')


def validate_runtime(sim) -> None:
    """Match Population-owned headcounts to Transport-owned physical obligations.

    Each owner validates its own State independently; this cross-domain check
    confirms that an Order cannot refer to a person absent from its vessel,
    including after a Save/Load reconstruction.
    """
    sim.population.validate()
    population = sim.population
    transport = sim.transport
    service_manifest: dict[EntityId, tuple[EntityId, EntityId | None]] = {}
    for transit_id, transit in transport.passenger_service_transits.items():
        for group_id in transit.passenger_group_refs:
            if group_id in service_manifest:
                raise ValueError(f'Population group has duplicate vessel membership: {group_id}')
            service_manifest[group_id] = (transit_id, transit.order_id)

    dedicated_members: set[EntityId] = set()
    for order in population.transfer_orders.values():
        constraint = order.capacity_source_constraint
        dedicated = constraint is not None and constraint.dedicated_vehicle_definition_id is not None
        if dedicated and order.in_transit_group_refs:
            execution_id = population._passenger_execution_id(order.id)
            execution = transport.movement_execution_snapshot(execution_id)
            if execution is None or execution.kind.value != 'passenger_transfer':
                raise ValueError(f'Passenger Order has no active physical Movement: {order.id}')
        for group_id in order.in_transit_group_refs:
            group = population.groups[group_id]
            if dedicated:
                if group_id in service_manifest or group_id in dedicated_members:
                    raise ValueError(f'Passenger is committed to multiple vehicles: {group_id}')
                if group.position.ref != str(execution_id):
                    raise ValueError(f'Passenger Movement position mismatch: {group_id}')
                dedicated_members.add(group_id)
            elif service_manifest.get(group_id, (None, None))[1] != order.id:
                raise ValueError(f'Passenger Order lacks matching Transport manifest: {order.id}/{group_id}')

    for group_id, (transit_id, owner_id) in service_manifest.items():
        if owner_id is None:
            if group_id in dedicated_members:
                raise ValueError(f'Automatic and dedicated passenger ownership overlap: {group_id}')
        elif group_id not in population.transfer_orders[owner_id].in_transit_group_refs:
            raise ValueError(f'Passenger manifest lacks matching Order: {transit_id}/{group_id}')

    for group_id, group in population.groups.items():
        if group.position.kind != 'transport_execution':
            continue
        if group_id not in service_manifest and group_id not in dedicated_members:
            # Other finite Activity types may move people only with a real
            # Movement and an exclusive Activity commitment.
            if (group.activity_commitment_ref is None or
                    transport.movement_execution_snapshot(EntityId(group.position.ref)) is None):
                raise ValueError(f'Population in transit lacks physical owner: {group_id}')


DOMAIN_EXTENSION = DomainExtension(
    'population', state_codec=StateCodec('population', capture_population_state, restore_population_state),
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    allocation_pool_provider=lambda sim: sim.population,
    service_capacity_provider=lambda sim: sim.population,
)
