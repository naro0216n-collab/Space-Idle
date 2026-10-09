from __future__ import annotations

from .domain import DomainExtension, StateCodec, decode_dict, decode_float, decode_int, decode_list, decode_str, require_fields
from .population import PopulationGroup, PopulationPosition
from .shared import EntityId, SpatialNodeId
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
        'external_remaining': dict(sorted(population.external_remaining.items())),
        'next_group_id': population._next_group_id,
    }


def restore_population_state(sim, state):
    row = require_fields(state, {'groups', 'targets', 'external_remaining', 'next_group_id'}, 'population state')
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
    service.external_remaining = {identifier: decode_int(value, 'external source remaining') for identifier, value in remaining.items()}
    service._next_group_id = decode_int(row['next_group_id'], 'next population group id')
    if service._next_group_id < 0:
        raise ValueError('negative population group counter')
    service._day_fulfillment = {}
    service.validate()


def validate_configuration(sim, ctx: ValidationContext) -> None:
    del ctx
    for definition in sim.facilities.definitions.values():
        if definition.life_support is not None:
            for resource_id, _ in definition.life_support.net_resources:
                if resource_id not in sim.inventory.resource_definitions:
                    raise ValueError(f'life support Resource not registered: {resource_id}')


def validate_runtime(sim) -> None:
    sim.population.validate()


DOMAIN_EXTENSION = DomainExtension(
    'population', state_codec=StateCodec('population', capture_population_state, restore_population_state),
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    allocation_pool_provider=lambda sim: sim.population,
    service_capacity_provider=lambda sim: sim.population,
)
