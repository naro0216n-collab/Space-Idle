"""Read-only World geography and representative physical/climate coefficients.

World parameters, Cell topology, resolved Environment, and physical transport
contexts share one authored source. Missing Facets remain unknown, not zero.
The snapshot makes no founded Location, Survey Knowledge or allocation claim.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from space_idle.spatial import great_circle_distance_km
from space_idle.simulation import Simulation


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _value(val) for key, val in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, (frozenset, set)):
        return sorted((_value(item) for item in value), key=str)
    return value


def context_environment(sim: Simulation, context_id: str) -> dict[str, Any]:
    """Every registered typed representative climate/environment facet from its owner."""
    graph = sim.graph
    if context_id not in graph.surface_cells and context_id not in graph.nodes:
        raise KeyError(f'unknown physical context: {context_id}')
    resolver = sim.facilities.environment
    result: dict[str, Any] = {}
    for facet_type in sorted(resolver.static.facet_types(), key=lambda t: (t.facet_key, t.__name__)):
        facet = resolver.get(context_id, facet_type)
        result[facet_type.facet_key] = {
            'scope': facet_type.environment_scope.value,
            'values': None if facet is None else _value(facet),
            'basis': 'EnvironmentResolver.get: static World plus ordered physical overlays',
        }
    return result


def physical_context_evidence(sim: Simulation, context_id: str) -> dict[str, Any]:
    graph = sim.graph
    if context_id in graph.surface_cells:
        cell = graph.surface_cells[context_id]
        body = graph.bodies[cell.body_id]
        neighbors = {str(neighbor): great_circle_distance_km(
            cell.centroid, graph.surface_cells[neighbor].centroid, body.mean_radius_km
        ) for neighbor in sorted(cell.neighbor_ids, key=str)}
        return {
            'id': str(cell.id), 'kind': 'surface_cell', 'name': cell.display_name,
            'body_id': str(cell.body_id), 'area_km2': cell.area_km2,
            'centroid': _value(cell.centroid),
            'neighbor_ids': sorted(map(str, cell.neighbor_ids)),
            'neighbor_separation_km': neighbors,
            'geology': _value(cell.static_geology), 'terrain': _value(cell.terrain),
            'resource_potential_by_resource': _value(cell.resource_potential_by_resource),
            'environment': context_environment(sim, context_id),
        }
    if context_id in graph.nodes:
        node = graph.nodes[context_id]
        return {
            'id': str(node.id), 'kind': node.kind.value, 'name': node.display_name,
            'body_id': None if node.body_id is None else str(node.body_id),
            'star_system_id': str(node.star_system_id),
            'parent_id': None if node.parent_id is None else str(node.parent_id),
            'inherits_parent_environment': node.inherits_parent_environment,
            'body_center_orbit_radius_km': node.body_center_orbit_radius_km,
            'system_local_transport_geometry': _value(node.system_local_transport_geometry),
            'environment': context_environment(sim, context_id),
        }
    raise KeyError(f'unknown physical context: {context_id}')


def world_evidence(sim: Simulation) -> dict[str, Any]:
    """All bodies, cells, space contexts and current World facets; no inferred assets."""
    graph = sim.graph
    by_body = defaultdict(list)
    for cell in graph.surface_cells.values():
        by_body[cell.body_id].append(cell)
    nodes_by_body = defaultdict(list)
    for node in graph.nodes.values():
        nodes_by_body[node.body_id].append(node)
    bodies = []
    for bid, body in sorted(graph.bodies.items()):
        cells = [physical_context_evidence(sim, cell.id)
                 for cell in sorted(by_body[bid], key=lambda c: str(c.id))]
        potentials = defaultdict(list)
        for cell in cells:
            for rid, amount in cell['resource_potential_by_resource'].items():
                potentials[rid].append(amount)
        bodies.append({
            'id': str(bid), 'name': body.display_name,
            'body_parameters': {
                'star_system_id': str(body.star_system_id),
                'parent_body_id': None if body.parent_body_id is None else str(body.parent_body_id),
                'physical_surface': body.physical_surface.value,
                'mean_radius_km': body.mean_radius_km,
                'reference_gravity_m_s2': body.reference_gravity_m_s2,
                'standard_gravitational_parameter_km3_s2': body.standard_gravitational_parameter_km3_s2,
                'representative_gravity_m_s2': body.representative_gravity_m_s2,
                'heliocentric_semimajor_axis_au': body.heliocentric_semimajor_axis_au,
                'parent_orbit_semimajor_axis_km': body.parent_orbit_semimajor_axis_km,
                'representative_solar_flux_w_m2': graph.representative_solar_flux_w_m2(bid),
                'system_local_transport_geometry': _value(body.system_local_transport_geometry),
            },
            'body_environment_baseline': {
                facet_type.facet_key: {
                    'scope': facet_type.environment_scope.value,
                    'values': _value(facet),
                    'basis': 'StaticFacetStore.body_facets, before overlays',
                }
                for (body_id, facet_type), facet in sorted(
                    sim.environment.static.body_facets.items(),
                    key=lambda pair: (str(pair[0][0]), pair[0][1].facet_key)
                ) if body_id == bid
            },
            'surface_cells': cells, 'surface_cell_count': len(cells),
            'non_surface_contexts': [physical_context_evidence(sim, n.id)
                                     for n in sorted(nodes_by_body[bid], key=lambda n: str(n.id))],
            'potential_by_resource': {rid: {'positive_cells': sum(x > 0 for x in vals),
                                          'min': min(vals), 'max': max(vals)}
                                      for rid, vals in sorted(potentials.items())},
        })
    free_nodes = [physical_context_evidence(sim, node.id)
                  for node in sorted(nodes_by_body[None], key=lambda n: str(n.id))]
    return {
        'star_systems': [_value(system) for _, system in sorted(graph.star_systems.items())],
        'bodies': bodies, 'unbound_non_surface_contexts': free_nodes,
        'interpretation': ('World Definition, geography and representative climate/environment conditions; '
                           'missing facet means unknown, no founded State, surveyed potential or guaranteed industry'),
    }
