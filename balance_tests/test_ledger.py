"""Registered Content activities share Node, Resource, time and owner in one worksheet."""
import math

from space_idle.content.base_catalog import build_base_catalog
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.composition.base_simulation import build_base_simulation
from content_balance.ledger import quantity_ledger


def _sim():
    scenario = build_standard_scenario_definition()
    return build_base_simulation(build_base_catalog(),
        population_rules=scenario.population_rules,
        external_population_sources=scenario.external_population_sources)


def test_material_ledger_preserves_node_time_and_shared_process_capacity():
    sim = _sim()
    process = next(spec for spec in sim.industry.processes.values()
        if spec.inputs_per_day and spec.outputs_per_day and
        sim.industry.service_capacity_provider_definition_ids(sim.industry.process_service_type(spec.id)))
    fid = next(iter(sim.industry.service_capacity_provider_definition_ids(
        sim.industry.process_service_type(process.id))))
    recipe = sim.projects.recipes[fid]
    site = next(iter(sim.graph.surface_cells))
    # Independent nodes cannot settle each other's stock, even when using the same Resource.
    result = quantity_ledger(sim, period_days=20.0, activities=[
        {'kind': 'process', 'node': 'producer', 'id': process.id, 'rate_per_day': 0.5},
        {'kind': 'facility_operation', 'node': 'producer', 'id': fid, 'count': 1,
         'context_id': site, 'selected_process_id': process.id},
        {'kind': 'facility_construction', 'node': 'consumer', 'id': fid, 'count': 2},
    ])
    service = next(row for row in result['service_by_scope']
                   if row['scope'] == 'OPERATIONAL_NODE' and row['service_type'] == sim.industry.process_service_type(process.id))
    assert service['demand_per_day'] == 0.5
    assert service['nominal_supply_per_day'] == sim.facilities.definitions[fid].process_throughput_per_day
    resource = next(iter(process.outputs_per_day))
    supply = next(row for row in result['resource_by_node']
                  if row['node'] == 'producer' and row['resource_id'] == resource)
    assert supply['supply_t_per_day'] == process.outputs_per_day[resource] * 0.5
    # Acquisition Resource is not a single-day rate, nor credited from another Node.
    req = recipe.resources[0]
    at_consumer = next(row for row in result['resource_by_node']
        if row['node'] == 'consumer' and row['resource_id'] == req.resource_id)
    assert math.isclose(at_consumer['demand_t_per_day'], req.amount_t * 2 / 20)
    assert sim.facilities.facilities == {}


def test_research_executions_keep_organization_scope_and_acquisition_distinct():
    sim = _sim()
    definition = next(d for d in sim.research.definitions.values()
        if any(getattr(stage, 'research_point_cost', None) for stage in d.stage_specs))
    stage = next(stage for stage in definition.stage_specs if hasattr(stage, 'research_point_cost'))
    result = quantity_ledger(sim, period_days=10, activities=[
        {'kind': 'research_stage', 'node': 'scientific-site', 'id': definition.id,
         'stage_id': stage.stage_id, 'count': 2},
    ])
    rp = result['research_by_scope'][0]['rp_demand_per_day']
    assert rp == stage.research_point_cost * 2 / 10
    assert any(row['scope'] == 'ORGANIZATION' and row['demand_per_day'] > 0
               for row in result['service_by_scope'])
    assert sim.research.active == {}


def test_ledger_does_not_invent_cargo_settlement_or_founding_facility_construction():
    sim = _sim()
    recipe = next(iter(sim.founding.deployment_recipes.values()))
    period = 6
    result = quantity_ledger(sim, period_days=period, activities=[
        {'kind': 'founding', 'node': 'staging', 'id': recipe.id, 'count': 1},
    ])
    for req in recipe.payload_resources:
        row = next(r for r in result['resource_by_node'] if r['resource_id'] == req.resource_id)
        assert math.isclose(row['demand_t_per_day'], req.amount_t / period)
        assert row['supply_t_per_day'] == 0
    assert result['activity_evidence'][0]['source'].startswith('founding:')
    assert sim.founding.active_projects == {} if hasattr(sim.founding, 'active_projects') else True


def test_extraction_physics_and_node_separation_are_conditional_and_domain_owned():
    sim = _sim()
    cell = next(cell for cell in sim.graph.surface_cells.values()
        if cell.resource_potential_by_resource)
    method = next(m for m in sim.extraction.specs.values()
        if cell.resource_potential_by_resource.get(m.resource_id, 0) > 0
        and any(m in sim.extraction.compatible_methods(fid) for fid in sim.facilities.definitions))
    fid = next(fid for fid in sim.facilities.definitions
        if method in sim.extraction.compatible_methods(fid))
    period = 12
    result = quantity_ledger(sim, period_days=period, activities=[
        {'kind': 'extraction', 'node': 'source', 'id': method.id,
         'facility_id': fid, 'facility_units': 2,
         'context_id': cell.id, 'rate_t_per_day': 0.3},
        {'kind': 'facility_construction', 'node': 'consumer', 'id': fid, 'count': 1},
    ])
    resource = next(row for row in result['resource_by_node']
        if row['node'] == 'source' and row['resource_id'] == str(method.resource_id))
    assert resource['supply_t_per_day'] == 0.3
    assert all(row['node'] != 'consumer' or row['supply_t_per_day'] == 0
               for row in result['resource_by_node'])
    service = next(row for row in result['service_by_scope']
        if row['service_type'] == sim.extraction.service_type(method.resource_id))
    assert service['demand_per_day'] == 2 * sim.extraction.nominal_capacity_for_level(fid, 1)
    evidence = result['activity_evidence'][0]['evidence'][-1]
    assert math.isclose(evidence['combined_physical_response_t_per_day'],
        sim.extraction.diminishing_response(2 * sim.extraction.nominal_capacity_for_level(fid, 1),
            evidence['per_facility']['physical_opportunity_before_knowledge']))
    assert sim.graph.locations == {}


def test_transport_cycle_rates_keep_each_context_and_do_not_deliver_stock():
    sim = _sim()
    nodes = tuple(sim.graph.nodes)
    origin, destination = nodes[0], nodes[1]
    plans = sim.transport.movement_resolver().physical_context_plans(origin, destination)
    reverse = sim.transport.movement_resolver().physical_context_plans(destination, origin)
    assert plans and reverse
    from space_idle.transport.models import OperationAssetDisposition
    vid = next(vid for vid, definition in sim.transport.vehicle_defs.items()
               if definition.movement_asset_disposition(plans[0]) is OperationAssetDisposition.DESTINATION
               and definition.propellant_resource_id is not None)
    result = quantity_ledger(sim, period_days=7, activities=[
        {'kind': 'transport_cycle', 'node': 'origin_stock', 'id': vid, 'units': 2,
         'origin_context_id': origin, 'destination_context_id': destination,
         'destination_node': 'destination_stock',
         'forward_plan_id': str(plans[0].id), 'reverse_plan_id': str(reverse[0].id)},
    ])
    expected = sim.transport.physical_cycle_coefficients(
        vid, (plans[0],), (reverse[0],), anchor_context_id=origin)
    assert result['activity_evidence'][0]['evidence'][-1]['fleet_cycle_days'] == expected.cycle_days
    for context, rid, rate in expected.resource_t_per_full_utilization_day:
        accounting_node = 'origin_stock' if context == origin else 'destination_stock'
        row = next(row for row in result['resource_by_node']
                   if row['node'] == accounting_node and row['resource_id'] == str(rid))
        assert math.isclose(row['demand_t_per_day'], rate * 2)
        assert row['supply_t_per_day'] == 0
    assert sim.transport.transport_allocations == {}


def test_execution_requirement_node_pin_and_organization_scope_are_not_merged():
    sim = _sim()
    from space_idle.execution_requirements import ResourceRequirement, ServiceCapacityRequirement
    from space_idle.service_capacity import ServiceCapacityScope
    from space_idle.research_models import ResearchTheoryStageSpec
    from dataclasses import replace
    original = next(d for d in sim.research.definitions.values()
        if any(isinstance(s, ResearchTheoryStageSpec) for s in d.stage_specs))
    stage = next(s for s in original.stage_specs if isinstance(s, ResearchTheoryStageSpec))
    resource_id = next(iter(sim.inventory.resource_definitions))
    altered = replace(stage, execution_requirements=(
        ResourceRequirement(resource_id, 0.25, constraint_node_id='pinned'),
        ServiceCapacityRequirement('research_execution', 1,
                                   scope=ServiceCapacityScope.ORGANIZATION, scope_id='laboratory_group'),
    ))
    sim.research.definitions[original.id] = replace(original, stage_specs=tuple(
        altered if s.stage_id == stage.stage_id else s for s in original.stage_specs))
    result = quantity_ledger(sim, period_days=10, activities=[
        {'kind': 'research_stage', 'node': 'initial', 'id': original.id,
         'stage_id': stage.stage_id, 'count': 1},
    ])
    assert any(row['node'] == 'pinned' and row['resource_id'] == str(resource_id)
               for row in result['resource_by_node'])
    assert any(row['scope'] == 'ORGANIZATION' and row['node_or_scope'] == 'laboratory_group'
               for row in result['service_by_scope'])


def test_market_quote_exposes_funds_and_arrival_without_free_delivery():
    sim = _sim()
    provider = next(p for p in sim.market.provider_defs.values() if p.buy_offers_musd_per_t)
    rid, price = provider.buy_offers_musd_per_t[0]
    result = quantity_ledger(sim, period_days=8, activities=[
        {'kind': 'market_trade', 'node': 'market_interface', 'id': rid,
         'provider_id': provider.id, 'direction': 'buy', 'quantity_t': 4},
    ])
    assert result['resource_by_node'] == []
    assert result['funds_by_node'][0]['quoted_spending_musd_per_day'] == price * 4 / 8
    assert result['activity_evidence'][0]['evidence'][-1]['delivery_lead_days'] == provider.lead_time_days
    assert sim.market.orders == {}


def test_survey_provider_and_location_development_are_inputs_not_advancement():
    sim = _sim()
    provider = next(iter(sim.survey.providers.values()))
    mode = provider.observation_modes[0]
    source_id = next(iter(sim.survey.compatible_mode_source_definition_ids(provider, mode)))
    spatial = next(iter(sim.projects.spatial_recipes.values()))
    period = 5
    result = quantity_ledger(sim, period_days=period, activities=[
        {'kind': 'survey_provider', 'node': 'provider_site', 'id': provider.id,
         'source_id': source_id, 'mode_id': mode.id, 'units': 2},
        {'kind': 'spatial_development', 'node': 'new_cell', 'id': spatial.id, 'count': 3},
    ])
    svc = sim.survey.service_type_for_provider(provider.id, source_id)
    assert any(row['service_type'] == svc
        and row['nominal_supply_per_day'] == 2 * provider.capacity_units_per_source_per_day
        for row in result['service_by_scope'])
    for req in spatial.resources:
        row = next(x for x in result['resource_by_node']
                   if x['node'] == 'new_cell' and x['resource_id'] == str(req.resource_id))
        assert math.isclose(row['demand_t_per_day'], req.amount_t * 3 / period)
        assert row['supply_t_per_day'] == 0
    assert sim.survey.campaigns == {}
    assert sim.graph.locations == {}


def test_upgrade_investment_is_separate_from_cumulative_operating_maintenance():
    sim = _sim()
    (fid, level), upgrade = next(iter(sim.projects.upgrade_recipes.items()))
    construction = sim.projects.recipes[fid]
    cell = next(iter(sim.graph.surface_cells))
    result = quantity_ledger(sim, period_days=25, activities=[
        {'kind': 'facility_upgrade', 'node': 'industrial', 'id': fid,
         'target_level': level, 'count': 2},
        {'kind': 'facility_operation', 'node': 'research', 'id': fid,
         'count': 2, 'level': level, 'context_id': cell},
    ])
    spent = {str(row.resource_id): row.amount_t * 2 for row in upgrade.resources}
    for rid, amount in spent.items():
        row = next(row for row in result['resource_by_node']
                   if row['node'] == 'industrial' and row['resource_id'] == rid)
        assert math.isclose(row['demand_t_per_day'], amount / 25)
        assert row['supply_t_per_day'] == 0
    investments = {str(req.resource_id): req.amount_t * 2 for req in construction.resources}
    for next_level in range(2, level + 1):
        for req in sim.projects.upgrade_recipes[(fid, next_level)].resources:
            investments[str(req.resource_id)] = investments.get(str(req.resource_id), 0) + 2 * req.amount_t
    upkeep = sim.facilities.maintenance_requirements_for_investment(fid, investments)
    for rid, rate in upkeep.items():
        row = next(row for row in result['resource_by_node']
                   if row['node'] == 'research' and row['resource_id'] == str(rid))
        assert math.isclose(row['demand_t_per_day'], rate)
    assert sim.projects.projects == {}
    assert sim.facilities.facilities == {}


def test_transport_demand_couples_owner_required_fleet_to_explicit_od_without_cargo_settlement():
    sim = _sim()
    origin, destination = tuple(sim.graph.nodes)[:2]
    forward = sim.transport.movement_resolver().physical_context_plans(origin, destination)
    reverse = sim.transport.movement_resolver().physical_context_plans(destination, origin)
    from space_idle.transport.models import OperationAssetDisposition, DirectionalCapacity
    vid = next(vid for vid, definition in sim.transport.vehicle_defs.items()
        if definition.movement_asset_disposition(forward[0]) is OperationAssetDisposition.DESTINATION)
    cycle = sim.transport.physical_cycle_coefficients(vid, (forward[0],), (reverse[0],),
                                                      anchor_context_id=origin)
    demand = DirectionalCapacity(cycle.nominal_per_unit.forward_t_per_day * 2.1,
                                 cycle.nominal_per_unit.reverse_t_per_day * 0.7)
    result = quantity_ledger(sim, period_days=28, activities=[
        {'kind': 'transport_cycle', 'node': 'one', 'destination_node': 'two', 'id': vid,
         'units': 2, 'origin_context_id': origin, 'destination_context_id': destination,
         'forward_plan_id': str(forward[0].id), 'reverse_plan_id': str(reverse[0].id),
         'target_forward_t_per_day': demand.forward_t_per_day,
         'target_reverse_t_per_day': demand.reverse_t_per_day},
    ])
    measurement = next(row for row in result['activity_evidence'][0]['evidence']
                       if row['measure'] == 'transport_od_demand')
    assert measurement['required_units_from_owner_physical_capacity'] == sim.transport.required_units_for_capacity(
        demand, cycle.nominal_per_unit)
    assert not measurement['nominal_capacity_covers_target']
    assert measurement['origin_node'] == 'one' and measurement['destination_node'] == 'two'
    assert all(row['supply_t_per_day'] == 0 for row in result['resource_by_node'])
    assert sim.transport.transport_allocations == {}
