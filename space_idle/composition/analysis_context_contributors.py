"""Static World, Movement, Founding and Population Definition contributors.

These use registered owner Definitions, not fixed planet, recipe or vehicle IDs.
A Movement profile is never misreported as a resolved origin/destination route.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import json

from ..analysis_graph import DependencyFragment, DependencyNode, DependencyRelation
from ..site import SiteRequirements
from ..simulation import Simulation


def _node(kind: str, key: object) -> DependencyNode:
    return DependencyNode(kind, str(key))


def _field_data(value: object) -> object:
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if is_dataclass(value) and not isinstance(value, type):
        return {row.name: _field_data(getattr(value, row.name)) for row in fields(value)}
    if isinstance(value, dict):
        return {str(key): _field_data(element) for key, element in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset, tuple, list)):
        items = [_field_data(element) for element in value]
        return sorted(items, key=str) if isinstance(value, (set, frozenset)) else items
    if hasattr(value, 'value') and hasattr(type(value), '__members__'):
        return value.value
    return value


def _site(owner: DependencyNode, scope: str, req: SiteRequirements,
          nodes: list[DependencyNode], relations: list[DependencyRelation]) -> None:
    """Keep AND requirements and physical parameter types without executing eligibility."""
    for capacity in req.capability_requirements:
        relations.append(DependencyRelation(
            'requires_site_capability', _node('capability', capacity.capability_id), owner,
            f'{owner.kind}:{owner.id}:{scope}:capability:{capacity.capability_id}',
            condition=f'required_state:{capacity.required_state.value}',
        ))
    for classification in req.spatial_classification_requirements:
        relations.append(DependencyRelation(
            'requires_site_classification', _node('spatial_classification', classification.classification.value), owner,
            f'{owner.kind}:{owner.id}:{scope}:classification:{classification.code}',
            condition=f'site_role:{scope}',
        ))
    for condition in req.environment:
        subject = _node('site_condition', f'{owner.kind}:{owner.id}/{scope}/{condition.code}')
        nodes.append(subject)
        relations.append(DependencyRelation(
            'requires_site_environment', subject, owner,
            f'{owner.kind}:{owner.id}:{scope}:environment:{condition.code}',
            condition=json.dumps(_field_data(condition), sort_keys=True, ensure_ascii=False),
        ))


def world(sim: Simulation) -> DependencyFragment:
    graph = sim.graph
    nodes = [_node('star_system', key) for key in graph.star_systems]
    nodes.extend(_node('body', key) for key in graph.bodies)
    nodes.extend(_node('surface_cell', key) for key in graph.surface_cells)
    nodes.extend(_node('spatial_node', key) for key in graph.nodes)
    nodes.extend(_node('spatial_classification', category) for category in ('SURFACE', 'ORBITAL', 'NON_SURFACE'))
    relations = []
    for body in graph.bodies.values():
        b = _node('body', body.id)
        relations.append(DependencyRelation(
            'within_star_system', _node('star_system', body.star_system_id), b,
            f'world:body:{body.id}:star_system_id',
        ))
        if body.parent_body_id is not None:
            relations.append(DependencyRelation(
                'body_orbits_parent', _node('body', body.parent_body_id), b,
                f'world:body:{body.id}:parent_body_id',
            ))
    for cell in graph.surface_cells.values():
        target = _node('surface_cell', cell.id)
        relations.append(DependencyRelation('body_has_cell', _node('body', cell.body_id), target,
                                            f'world:surface_cell:{cell.id}:body_id'))
        for rid, potential in cell.resource_potential_by_resource.items():
            relations.append(DependencyRelation(
                'static_resource_potential', target, _node('resource', rid),
                f'world:surface_cell:{cell.id}:potential:{rid}', potential, 'potential_index',
                'per_static_surface_cell', condition='not_recoverable_inventory_or_survey_knowledge',
            ))
        for neighbor in sorted(cell.neighbor_ids):
            if str(cell.id) < str(neighbor):
                relations.append(DependencyRelation('surface_adjacency', target,
                                                    _node('surface_cell', neighbor),
                                                    f'world:surface_cell:{cell.id}:neighbor:{neighbor}',
                                                    condition='undirected_adjacency'))
    for position in graph.nodes.values():
        owner = _node('spatial_node', position.id)
        relations.append(DependencyRelation('within_star_system',
                                            _node('star_system', position.star_system_id), owner,
                                            f'world:spatial_node:{position.id}:star_system_id'))
        if position.body_id is not None:
            relations.append(DependencyRelation('node_orbits_body', _node('body', position.body_id), owner,
                                                f'world:spatial_node:{position.id}:body_id',
                                                condition=f'physical_kind:{position.kind.value}'))
        if position.parent_id is not None:
            relations.append(DependencyRelation('spatial_parent', _node('spatial_node', position.parent_id), owner,
                                                f'world:spatial_node:{position.id}:parent_id'))
    return DependencyFragment(tuple(nodes), tuple(relations))


WORLD_RELATIONS = frozenset({
    'within_star_system', 'body_orbits_parent', 'body_has_cell', 'static_resource_potential',
    'surface_adjacency', 'node_orbits_body', 'spatial_parent',
})


def movement(sim: Simulation) -> DependencyFragment:
    transport = sim.transport
    nodes = []
    relations = []
    operations = set()
    for rule in transport.surface_movement_rules:
        method = _node('surface_movement_rule', rule.id)
        nodes.append(method)
        operations.add(rule.operation.operation_type)
        relations.extend((
            DependencyRelation('requires_operation', _node('transport_operation', rule.operation.operation_type),
                               method, f'movement:{rule.id}:operation',
                               condition=f'delta_v_km_s:{rule.operation.delta_v_km_s}'),
            DependencyRelation('requires_gateway_capability', _node('capability', rule.gateway_capability_id),
                               method, f'movement:{rule.id}:gateway_capability_id'),
            DependencyRelation('minimum_transit_duration', method,
                               _node('movement_parameter', 'duration_floor'),
                               f'movement:{rule.id}:transit_days', rule.transit_days,
                               'days', 'per_operation_profile'),
        ))
    for rule in transport.surface_access_movement_rules:
        method = _node('surface_access_movement_rule', rule.id)
        nodes.append(method)
        relations.append(DependencyRelation('requires_body_context', _node('body', rule.body_id), method,
                                            f'movement:{rule.id}:body_id'))
        relations.append(DependencyRelation('requires_gateway_capability',
                                            _node('capability', rule.gateway_capability_id), method,
                                            f'movement:{rule.id}:gateway_capability_id'))
        for scope, choices in (('ascent', rule.ascent_operations), ('descent', rule.descent_operations)):
            for op in choices:
                operations.add(op.operation_type)
                relations.append(DependencyRelation(
                    'requires_operation', _node('transport_operation', op.operation_type), method,
                    f'movement:{rule.id}:{scope}:operations:{op.operation_type}',
                    condition=f'operation_scope:{scope};delta_v_km_s:{op.delta_v_km_s}',
                ))
        for scope, requirement in (('surface', rule.surface_requirements), ('space', rule.space_requirements)):
            _site(method, scope, requirement, nodes, relations)
        relations.append(DependencyRelation('minimum_transit_duration', method,
                                            _node('movement_parameter', 'duration_floor'),
                                            f'movement:{rule.id}:transit_days', rule.transit_days,
                                            'days', 'per_operation_profile'))
    for rule in transport.spaceflight_movement_rules:
        method = _node('spaceflight_movement_rule', rule.id)
        nodes.append(method)
        operations.add(rule.operation_type)
        relations.extend((
            DependencyRelation('requires_operation', _node('transport_operation', rule.operation_type),
                               method, f'movement:{rule.id}:operation_type',
                               condition='eligibility_requires_actual_vehicle_and_route'),
            DependencyRelation('characteristic_speed', method, _node('movement_parameter', 'speed'),
                               f'movement:{rule.id}:characteristic_speed_km_per_day',
                               rule.characteristic_speed_km_per_day, 'km/day', 'per_movement_profile'),
            DependencyRelation('minimum_transit_duration', method,
                               _node('movement_parameter', 'duration_floor'),
                               f'movement:{rule.id}:minimum_transit_days', rule.minimum_transit_days,
                               'days', 'per_operation_profile'),
        ))
        for scope, requirement in (('origin', rule.origin_requirements), ('destination', rule.destination_requirements)):
            _site(method, scope, requirement, nodes, relations)
    nodes.extend(_node('transport_operation', name) for name in sorted(operations))
    nodes.extend((_node('movement_parameter', 'speed'), _node('movement_parameter', 'duration_floor')))
    return DependencyFragment(tuple(nodes), tuple(relations))


MOVEMENT_RELATIONS = frozenset({
    'requires_operation', 'requires_gateway_capability', 'requires_body_context',
    'requires_site_capability', 'requires_site_classification', 'requires_site_environment',
    'minimum_transit_duration', 'characteristic_speed',
})


def founding(sim: Simulation) -> DependencyFragment:
    nodes = []
    relations = []
    if sim.founding is None:
        return DependencyFragment((), ())
    for recipe in sim.founding.deployment_recipes.values():
        method = _node('founding_method', recipe.id)
        nodes.append(method)
        for deployment in recipe.deployed_facilities:
            relations.append(DependencyRelation(
                'deploys_facility', method, _node('facility', deployment.facility_def_id),
                f'founding:{recipe.id}:deployed_facilities',
            ))
        for resource_id, amount in recipe.investment_totals().items():
            relations.append(DependencyRelation(
                'invests_resource', _node('resource', resource_id), method,
                f'founding:{recipe.id}:invested:{resource_id}',
                amount, 't', 'per_founding_project',
            ))
        for requirement in recipe.initial_inventory:
            relations.append(DependencyRelation('funds_initial_inventory',
                                                _node('resource', requirement.resource_id), method,
                                                f'founding:{recipe.id}:initial_inventory:{requirement.resource_id}',
                                                requirement.amount_t, 't', 'per_founding_project'))
        relations.extend((
            DependencyRelation('requires_service_capacity',
                               _node('service_capacity', recipe.preparation_service_type), method,
                               f'founding:{recipe.id}:preparation_service_type'),
            DependencyRelation('requires_fleet_units', _node('capacity_pool', 'fleet_units'), method,
                               f'founding:{recipe.id}:required_units', recipe.required_units,
                               'units', 'per_founding_project',
                               condition='compatible_vehicle_and_actual_movement_are_required'),
            DependencyRelation('preparation_work', method, _node('founding_parameter', 'work'),
                               f'founding:{recipe.id}:preparation_work', recipe.preparation_work,
                               'work_units', 'per_founding_project'),
        ))
        for requirement in recipe.knowledge_requirements:
            relations.append(DependencyRelation('requires_knowledge',
                                                _node('resource', requirement.subject_resource_id), method,
                                                f'founding:{recipe.id}:knowledge:{requirement.subject_resource_id}',
                                                condition=f'minimum_level:{requirement.minimum_level.value};target_cell_required'))
        for scope, requirement in (('staging', recipe.staging_requirements), ('target', recipe.target_requirements)):
            _site(method, scope, requirement, nodes, relations)
    nodes.append(_node('founding_parameter', 'work'))
    return DependencyFragment(tuple(nodes), tuple(relations))


FOUNDING_RELATIONS = frozenset({
    'deploys_facility', 'invests_resource', 'funds_initial_inventory', 'requires_service_capacity',
    'requires_fleet_units', 'preparation_work', 'requires_knowledge',
    'requires_site_capability', 'requires_site_classification', 'requires_site_environment',
})


def population(sim: Simulation) -> DependencyFragment:
    if sim.population is None:
        return DependencyFragment((), ())
    nodes = []
    relations = []
    for definition in sim.population.external_definitions.values():
        method = _node('external_population_source', definition.id)
        nodes.append(method)
        relations.append(DependencyRelation(
            'external_population_supply', method, _node('capacity_pool', 'population'),
            f'population:{definition.id}:max_acquisition_per_day',
            definition.max_acquisition_per_day, 'people/day', 'per_enabled_external_source',
            condition=f'operational_node:{definition.operational_node_id}',
        ))
        relations.append(DependencyRelation(
            'external_population_endowment', method, _node('capacity_pool', 'population'),
            f'population:{definition.id}:initial_people',
            definition.initial_people, 'people', 'per_new_game_source',
        ))
        for technology in definition.required_technology_ids:
            relations.append(DependencyRelation('unlocks_method', _node('technology', technology), method,
                                                f'population:{definition.id}:required_technology_ids'))
    return DependencyFragment(tuple(nodes), tuple(relations))


POPULATION_RELATIONS = frozenset({
    'external_population_supply', 'external_population_endowment', 'unlocks_method',
})
