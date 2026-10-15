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
    assert result['funds_by_scope'][0]['quoted_spending_musd_per_day'] == price * 4 / 8
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


def test_extraction_equipment_and_activity_share_one_owned_service_not_free_output():
    sim = _sim()
    cell = next(cell for cell in sim.graph.surface_cells.values() if cell.resource_potential_by_resource)
    method = next(m for m in sim.extraction.specs.values()
        if cell.resource_potential_by_resource.get(m.resource_id, 0) > 0
        and any(m in sim.extraction.compatible_methods(fid) for fid in sim.facilities.definitions))
    fid = next(fid for fid in sim.facilities.definitions if method in sim.extraction.compatible_methods(fid))
    result = quantity_ledger(sim, period_days=21, activities=[
        {'kind': 'facility_operation', 'node': 'mine', 'id': fid, 'context_id': cell.id,
         'count': 3, 'selected_extraction_method_id': method.id},
        {'kind': 'extraction', 'node': 'mine', 'id': method.id, 'facility_id': fid,
         'facility_units': 3, 'context_id': cell.id, 'rate_t_per_day': 0.15},
    ])
    nominal = 3 * sim.extraction.nominal_capacity_for_level(fid, 1)
    row = next(row for row in result['service_by_scope']
               if row['service_type'] == sim.extraction.service_type(method.resource_id))
    assert row['scope'] == 'OPERATIONAL_NODE' and row['node_or_scope'] == 'mine'
    assert math.isclose(row['nominal_supply_per_day'], nominal)
    assert math.isclose(row['demand_per_day'], nominal)
    produced = next(row for row in result['resource_by_node']
                    if row['node'] == 'mine' and row['resource_id'] == str(method.resource_id))
    assert produced['supply_t_per_day'] == 0.15
    assert sim.facilities.facilities == {}
    assert sim.graph.locations == {}


def test_research_pool_storage_capacity_is_visible_alongside_rp_and_execution():
    sim = _sim()
    facility_id = next(fid for fid in sim.facilities.definitions
        if sim.research.facility_provider_for_definition(fid) is not None)
    provider = sim.research.facility_provider_for_definition(facility_id)
    physical_context = next(iter(sim.graph.surface_cells))
    level = provider.levels[0].level
    result = quantity_ledger(sim, period_days=16, activities=[
        {'kind': 'facility_operation', 'node': 'lab', 'id': facility_id, 'count': 3,
         'context_id': physical_context, 'level': level},
    ])
    fields = result['research_by_scope'][0]
    spec = provider.level_spec(level)
    assert fields['rp_pool_capacity_nominal_points'] == 3 * spec.storage_capacity_points
    assert fields['rp_nominal_per_day'] == 3 * spec.generation_points_per_day
    assert fields['execution_nominal_per_day'] == 3 * spec.research_execution_per_day
    assert sim.research.active == {}


def test_transport_cycle_reports_selected_leg_physics_not_a_free_operational_service():
    sim = _sim()
    origin, dest = tuple(sim.graph.nodes)[:2]
    fwd = sim.transport.movement_resolver().physical_context_plans(origin, dest)[0]
    back = sim.transport.movement_resolver().physical_context_plans(dest, origin)[0]
    from space_idle.transport.models import OperationAssetDisposition
    vehicle_id = next(vid for vid, v in sim.transport.vehicle_defs.items()
                      if v.movement_asset_disposition(fwd) is OperationAssetDisposition.DESTINATION)
    result = quantity_ledger(sim, period_days=9, activities=[
        {'kind': 'transport_cycle', 'node': 'departure', 'destination_node': 'arrival',
         'id': vehicle_id, 'units': 1, 'origin_context_id': origin,
         'destination_context_id': dest, 'forward_plan_id': str(fwd.id), 'reverse_plan_id': str(back.id)},
    ])
    conditions = next(row for row in result['activity_evidence'][0]['evidence']
                      if row['measure'] == 'transport_cycle_physical_requirements')
    assert conditions['forward']['movement_plan_id'] == str(fwd.id)
    assert conditions['forward']['vehicle_physical_failures'] == list(
        sim.transport.performance_movement_failures(fwd, sim.transport.vehicle_defs[vehicle_id].performance,
                                                     include_operation_support=False))
    assert conditions['reverse']['movement_plan_id'] == str(back.id)
    assert sim.transport.transport_allocations == {}


def test_one_period_demands_keep_owned_resource_service_habitation_and_organization_scopes():
    """Concurrent hypotheses may share rates, but not free stock or allocation."""
    from dataclasses import replace

    sim = _sim()
    cell = next(cell for cell in sim.graph.surface_cells.values() if cell.resource_potential_by_resource)
    method = next(m for m in sim.extraction.specs.values()
                  if cell.resource_potential_by_resource.get(m.resource_id, 0) > 0
                  and any(m in sim.extraction.compatible_methods(fid) for fid in sim.facilities.definitions))
    source_facility = next(fid for fid in sim.facilities.definitions
                           if method in sim.extraction.compatible_methods(fid))
    # A future Extraction Process need not yield the same Resource as its
    # surveyed deposit. Both identifiers must follow the owned Definition.
    refined = next(r for r in sim.inventory.resource_definitions if r != method.resource_id)
    sim.extraction.specs[method.id] = replace(method, output_resource_id=refined)
    sim.extraction.refresh_definition_compatibility()

    housing_facility = next(fid for fid, d in sim.facilities.definitions.items()
                            if d.life_support is not None and d.housing_capacity)
    life = sim.facilities.definitions[housing_facility].life_support
    market = next(p for p in sim.market.provider_defs.values() if p.buy_offers_musd_per_t)
    market_resource, market_price = market.buy_offers_musd_per_t[0]
    survey = next(iter(sim.survey.providers.values()))
    mode = survey.observation_modes[0]
    survey_source = next(iter(sim.survey.compatible_mode_source_definition_ids(survey, mode)))

    result = quantity_ledger(sim, period_days=30, activities=[
        {'kind': 'facility_operation', 'node': 'mine', 'id': source_facility,
         'count': 2, 'context_id': cell.id, 'selected_extraction_method_id': method.id},
        {'kind': 'extraction', 'node': 'mine', 'id': method.id,
         'facility_id': source_facility, 'facility_units': 2,
         'context_id': cell.id, 'rate_t_per_day': 0.25},
        {'kind': 'facility_operation', 'node': 'colony', 'id': housing_facility,
         'count': 2, 'level': 1, 'context_id': cell.id},
        {'kind': 'life_support', 'node': 'colony', 'id': housing_facility, 'people': 4},
        {'kind': 'survey_provider', 'node': 'colony', 'id': survey.id, 'units': 2,
         'source_id': survey_source, 'mode_id': mode.id},
        {'kind': 'survey_observation', 'node': 'colony', 'id': survey.id,
         'source_id': survey_source, 'mode_id': mode.id,
         'progress_units_per_day': 0.25 * mode.survey_rate},
        {'kind': 'market_trade', 'node': 'mine', 'id': market_resource,
         'provider_id': market.id, 'direction': 'buy', 'quantity_t': 3},
        {'kind': 'market_trade', 'node': 'colony', 'id': market_resource,
         'provider_id': market.id, 'direction': 'buy', 'quantity_t': 2},
    ])
    mine = [row for row in result['resource_by_node'] if row['node'] == 'mine']
    assert next(r for r in mine if r['resource_id'] == str(refined))['supply_t_per_day'] == 0.25
    assert all(r['resource_id'] != str(method.resource_id) or r['supply_t_per_day'] == 0
               for r in mine)
    housing = result['habitation_by_node'][0]
    assert housing['node'] == 'colony' and housing['assumed_population_people'] == 4
    assert housing['nominal_housing_people'] == 2 * sim.facilities.definitions[housing_facility].housing_capacity
    life_row = next(r for r in result['service_by_scope'] if r['service_type'] == 'life_support')
    assert life_row['node_or_scope'] == 'colony'
    assert math.isclose(life_row['nominal_supply_per_day'], life.capacity_at_level(1) * 2)
    assert life_row['demand_per_day'] == 4
    survey_row = next(r for r in result['service_by_scope'] if r['service_type'] ==
                      sim.survey.service_type_for_provider(survey.id, survey_source))
    assert survey_row['demand_per_day'] == 0.25
    assert survey_row['nominal_supply_per_day'] == 2 * survey.capacity_units_per_source_per_day
    assert len(result['funds_by_scope']) == 1
    funding = result['funds_by_scope'][0]
    assert funding['scope'] == 'ORGANIZATION' and funding['quoted_receipts_musd_per_day'] == 0
    assert math.isclose(funding['quoted_spending_musd_per_day'], (3 + 2) * market_price / 30)
    assert sim.facilities.facilities == {}
    assert sim.survey.campaigns == {}
    assert sim.market.orders == {}


def test_balance_worksheet_rejects_calendar_day_as_environment_input():
    import pytest
    sim = _sim()
    facility_id = next(iter(sim.facilities.definitions))
    with pytest.raises(ValueError, match='calendar-day environment sampling'):
        quantity_ledger(sim, period_days=5, activities=[
            {'kind': 'facility_operation', 'node': 'assumed-node', 'id': facility_id,
             'count': 1, 'context_id': next(iter(sim.graph.surface_cells)), 'day': 9},
        ])


def test_od_resource_manifest_binds_source_demand_to_owner_fleet_coefficient_without_delivery():
    sim = _sim()
    origin, destination = tuple(sim.graph.nodes)[:2]
    resolver = sim.transport.movement_resolver()
    forward = resolver.physical_context_plans(origin, destination)[0]
    reverse = resolver.physical_context_plans(destination, origin)[0]
    from space_idle.transport.models import OperationAssetDisposition, DirectionalCapacity
    vid = next(vid for vid, definition in sim.transport.vehicle_defs.items()
               if definition.movement_asset_disposition(forward) is OperationAssetDisposition.DESTINATION)
    resources = list(sim.inventory.resource_definitions)
    assert len(resources) >= 2
    manifest = {resources[0]: 0.3, resources[1]: 0.2}
    activities = [{'kind': 'transport_cycle', 'node': 'origin', 'destination_node': 'destination',
                   'id': vid, 'units': 1, 'origin_context_id': origin, 'destination_context_id': destination,
                   'forward_plan_id': str(forward.id), 'reverse_plan_id': str(reverse.id),
                   'forward_cargo_t_per_day': manifest}]
    from pytest import raises
    result = quantity_ledger(sim, period_days=40, activities=activities)
    row = next(x for x in result['activity_evidence'][0]['evidence']
               if x['measure'] == 'transport_od_demand')
    assert row['target_forward_t_per_day'] == 0.5
    assert row['target_reverse_t_per_day'] == 0
    expected = sim.transport.physical_cycle_coefficients(vid, (forward,), (reverse,), anchor_context_id=origin)
    assert row['required_units_from_owner_physical_capacity'] == sim.transport.required_units_for_capacity(
        DirectionalCapacity(0.5, 0), expected.nominal_per_unit)
    for rid, rate in manifest.items():
        local = next(x for x in result['resource_by_node'] if x['node'] == 'origin' and x['resource_id'] == str(rid))
        assert local['demand_t_per_day'] >= rate
    assert all(x['supply_t_per_day'] == 0 for x in result['resource_by_node'])
    assert sim.transport.transport_allocations == {}
    assert sim.graph.operational_node_states == {}
    bad = dict(activities[0], target_forward_t_per_day=0.6)
    with raises(ValueError, match='target mass'):
        quantity_ledger(sim, period_days=40, activities=[bad])
    with raises(ValueError, match='finite'):
        quantity_ledger(sim, period_days=40, activities=[dict(activities[0], forward_cargo_t_per_day={resources[0]: float('nan')})])
