"""Read-only physical Context measurements use owning Domains, not Game State."""
from dataclasses import replace

from space_idle.content.base_catalog import build_base_catalog
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.composition.base_simulation import build_base_simulation
from content_balance.physical import movement_evidence, site_evidence


def _assembled():
    scenario = build_standard_scenario_definition()
    return build_base_simulation(
        build_base_catalog(), population_rules=scenario.population_rules,
        external_population_sources=scenario.external_population_sources,
    )


def test_site_measurement_uses_local_environment_and_owner_extraction_physics():
    sim = _assembled()
    cell = next(cell for cell in sim.graph.surface_cells.values()
                if cell.resource_potential_by_resource)
    method = next(m for m in sim.extraction.specs.values()
                  if cell.resource_potential_by_resource.get(m.resource_id, 0.0) > 0
                  and any(m in sim.extraction.compatible_methods(fid)
                          for fid in sim.facilities.definitions))
    fid = next(fid for fid in sim.facilities.definitions
               if method in sim.extraction.compatible_methods(fid))
    before = site_evidence(sim, cell.id, fid, method_id=method.id)
    physical = before['extraction']
    assert physical['nominal_capacity_t_per_day'] == sim.extraction.nominal_capacity_for_level(fid, 1)
    assert physical['diminishing_response_t_per_day'] == sim.extraction.diminishing_response(
        physical['nominal_capacity_t_per_day'], physical['physical_opportunity_before_knowledge'])
    assert before['power']['generation_mw_per_facility'] == sim.power.nominal_for_definition_at_context(fid, cell.id, 0)[0]
    sim.graph.surface_cells[cell.id] = replace(cell, resource_potential_by_resource={
        **cell.resource_potential_by_resource, method.resource_id:
        cell.resource_potential_by_resource[method.resource_id] * 1.4,
    })
    changed = site_evidence(sim, cell.id, fid, method_id=method.id)
    assert changed['extraction']['physical_opportunity_before_knowledge'] >= physical['physical_opportunity_before_knowledge']
    assert sim.graph.locations == {}
    assert sim.facilities.facilities == {}


def test_movement_physics_reuses_world_and_vehicle_contracts_without_endpoints():
    sim = _assembled()
    nodes = tuple(sim.graph.nodes)
    vehicle_id = next(iter(sim.transport.vehicle_defs))
    result = movement_evidence(sim, nodes[0], nodes[1], vehicle_id, cargo_t=0.2)
    resolver = sim.transport.movement_resolver()
    plans = resolver.physical_context_plans(nodes[0], nodes[1])
    assert plans
    assert [row['movement_plan_id'] for row in result['forward']] == [str(p.id) for p in plans]
    for row, plan in zip(result['forward'], plans):
        definition = sim.transport.vehicle_defs[vehicle_id]
        assert row['propellant_t_at_requested_cargo'] == definition.propellant_t(plan, 0.2)
        assert row['transit_days'] == sim.transport.performance_movement_transit_days(plan, definition.performance)
        assert row['vehicle_physical_failures'] == list(sim.transport.performance_movement_failures(
            plan, definition.performance, include_operation_support=False))
    assert result['reverse']
    assert result['physical_cycle_options']
    cycle = result['physical_cycle_options'][0]
    forward = plans[0]
    backward = resolver.physical_context_plans(nodes[1], nodes[0])[0]
    expected = sim.transport.physical_cycle_coefficients(
        vehicle_id, (forward,), (backward,), anchor_context_id=nodes[0])
    assert cycle['cycle_days'] == expected.cycle_days
    assert cycle['forward_t_per_day_per_nominal_unit'] == expected.nominal_per_unit.forward_t_per_day
    assert sim.graph.operational_node_states == {}
    assert sim.transport.transport_allocations == {}
    assert sim.transport.fleet_pools == {}


def test_window_power_coefficients_sample_owner_per_day_without_running_game():
    sim = _assembled()
    from space_idle.power import SolarGeneration
    fid = next(fid for fid, spec in sim.power.specs.items()
               if isinstance(spec.generation, SolarGeneration))
    context = next(iter(sim.graph.nodes))
    window = 12.5
    result = site_evidence(sim, context, fid, day=9, window_days=window)
    values = [sim.power.nominal_for_definition_at_context(fid, context, 9 + i)[0]
              for i in range(13)]
    expected = (sum(values[:12]) + 0.5 * values[12]) / window
    assert abs(result['power']['mean_generation_mw_per_facility'] - expected) < 1e-9
    assert result['power']['minimum_generation_mw_per_facility'] == min(values)
    assert result['power']['maximum_generation_mw_per_facility'] == max(values)
    assert result['power']['generation_mw_per_facility'] == values[0]
    assert sim.graph.locations == {}
    assert sim.facilities.facilities == {}
