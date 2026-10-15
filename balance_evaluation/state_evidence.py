"""Common, read-only projection of *actual* game Domain-owned state.

Nominal coefficients and factual inventory are intentionally separate.  A
snapshot is not a planner: it cannot declare unbuilt Facilities or arrival.
"""
from __future__ import annotations

from collections import defaultdict

from content_balance.ledger import quantity_ledger
from space_idle.facilities import FacilityLifecycle


def state_activities(sim):
    """Describe registered physical assets without stage-specific branches."""
    activities = []
    for facility in sorted(sim.facilities.facilities.values(), key=lambda f: str(f.id)):
        if facility.paused or facility.lifecycle != FacilityLifecycle.NORMAL:
            continue
        location = sim.graph.locations.get(facility.operational_node_id)
        context = (facility.site_cell_id or (location.core_cell_id if location else facility.operational_node_id))
        activities.append({
            'kind': 'facility_operation', 'node': str(facility.operational_node_id),
            'id': str(facility.definition_id), 'context_id': str(context),
            'count': 1, 'level': facility.level,
            'invested_resources': {str(k): v for k, v in facility.invested_resources.items()},
            **({'selected_process_id': str(facility.selected_process_id)}
               if facility.selected_process_id is not None else {}),
            **({'selected_extraction_method_id': str(facility.selected_extraction_method_id)}
               if facility.selected_extraction_method_id is not None else {}),
        })
    # Existing research Fleet assignments, not assumed uncommitted Fleet.
    for assignment in sorted(sim.research.provider_assignments.values(), key=lambda a: str(a.id)):
        if assignment.paused:
            continue
        quantity = sim.transport.fleet_commitments[assignment.fleet_commitment_ref].quantity
        if quantity:
            activities.append({'kind': 'research_fleet_provider',
                               'node': str(assignment.operational_node_id),
                               'id': str(assignment.provider_definition_id),
                               'vehicle_id': str(assignment.vehicle_definition_id),
                               'units': quantity, 'context_id': str(assignment.operational_node_id)})
    return activities


def evaluate_state(app, *, period_days: float) -> dict:
    sim = app._simulation
    activities = state_activities(sim)
    ledger = quantity_ledger(sim, period_days=period_days, activities=activities)
    stocks = [
        {'node': str(node), 'resource_id': str(resource), 'stock_t': amount,
         'reserved_t': sim.inventory.reserved_total(node, resource),
         'available_t': sim.inventory.available(node, resource)}
        for (node, resource), amount in sorted(sim.inventory.stock.items())
    ]
    facilities = defaultdict(int)
    for row in sim.facilities.facilities.values():
        facilities[(str(row.operational_node_id), str(row.definition_id))] += row.level
    return {
        'game_day': sim.day,
        'installed_facilities': [
            {'node': node, 'facility_definition_id': definition, 'installed_units': units}
            for (node, definition), units in sorted(facilities.items())],
        'inventory_stock': stocks,
        'completed_technologies': sorted(map(str, sim.technology.completed)),
        'research_points_stored': sim.research.stored_points,
        'active_research': [
            {'research_id': str(project.definition_id),
             'stage_id': project.current_stage_id,
             'progress': project.stage_progress, 'paused': project.paused}
            for project in sorted(sim.research.active.values(), key=lambda r: str(r.definition_id))
        ],
        'fleet_by_node': [
            {'node': str(pool.operational_node_id), 'vehicle_id': str(pool.vehicle_definition_id),
             'total_units': pool.total_units}
            for pool in sorted(sim.transport.fleet_pools.values(),
                               key=lambda row: (str(row.operational_node_id), str(row.vehicle_definition_id)))
        ],
        'population_by_position': [
            {'position_kind': group.position.kind, 'position_ref': str(group.position.ref),
             'people': group.count}
            for group in sorted(sim.population.groups.values(), key=lambda r: str(r.id))
        ],
        'nominal_capacity_from_installed_assets': {
            'research': ledger['research_by_scope'],
            'power': ledger['power_by_node'],
            'service': ledger['service_by_scope'],
            'habitation': ledger['habitation_by_node'],
        },
        'asset_evidence': ledger['activity_evidence'],
        'interpretation': ('Read-only nominal capacity and actual State from game Save. '
                           'Nominal does not mean effective production, allocation, completed research, '
                           'transport delivery or reachability. No future acquisition is credited.'),
    }
