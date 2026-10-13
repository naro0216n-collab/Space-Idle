"""One-period, node-local Resource/Service accounting from owned Content definitions.

This is a worksheet, not a hypothetical Game State, Allocation, future stock
forecast, stage scheduler or Player plan. Rates are conditional on the explicitly
supplied activities and may be mutually infeasible. Each row retains its owner.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from .catalog import describe_execution_requirement
from space_idle.research_models import ResearchProviderSourceKind
from .physical import physical_site_conditions, site_evidence, surface_region_evidence
from .world import physical_context_evidence
from space_idle.research_models import (
    ResearchTheoryStageSpec, ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)
from space_idle.simulation import Simulation


def quantity_ledger(sim: Simulation, *, period_days: float, activities: list[dict[str, Any]]) -> dict[str, Any]:
    """Accumulate explicit chosen activity coefficients without inferring eligibility.

    `count` is the number of new assets or chosen people, while `rate_per_day`
    is the hypothesized execution throughput. One-off inputs are shown *both*
    as investment and as average daily pressure during the selected interval.
    They are not consumed in daily installments by this function.
    """
    if not isinstance(period_days, (int, float)) or not isfinite(period_days) or period_days <= 0:
        raise ValueError('period_days must be finite and positive')
    if not isinstance(activities, list):
        raise TypeError('activities must be a list')
    rows: list[dict[str, Any]] = []
    by_resource: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_service: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    power: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    funds: dict[str, float] = defaultdict(float)
    research: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    habitation: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def number(item, key, *, whole=False):
        x = item[key]
        if (isinstance(x, bool) or not isinstance(x, (int, float))
                or not isfinite(x) or x < 0 or (whole and (not isinstance(x, int)))):
            raise ValueError(f'{key} must be a non-negative {"integer" if whole else "number"}')
        return x

    def level_of(item):
        level = item.get('level', 1)
        if type(level) is not int or level < 1:
            raise ValueError('level must be a positive integer')
        return level

    for index, item in enumerate(activities):
        if 'day' in item:
            raise ValueError('calendar-day environment sampling is not supported; use representative climate')
        kind, node = item['kind'], str(item['node'])
        if not node:
            raise ValueError('node label required')
        label = f'{kind}:{item.get("id", index)}'
        measurements: list[dict[str, Any]] = []

        def resource(rid, amount, direction: str, basis: str, *, at_node=None):
            if amount <= 0:
                return
            key = str(rid)
            if key not in sim.inventory.resource_definitions:
                raise ValueError(f'unknown Resource: {key}')
            resource_node = node if at_node is None else str(at_node)
            by_resource[(resource_node, key)][direction] += amount / period_days
            measurements.append({'measure': 'resource', 'node': resource_node, 'resource_id': key, 'direction': direction,
                                 'quantity_t_per_period': amount, 'mean_t_per_day': amount / period_days,
                                 'basis': basis})

        def service(type_name, amount, direction: str, scope='OPERATIONAL_NODE',
                    *, scope_id='organization', at_node=None):
            if amount <= 0:
                return
            node_or_scope = (str(node if at_node is None else at_node)
                             if scope == 'OPERATIONAL_NODE' else str(scope_id))
            by_service[(scope, node_or_scope, type_name)][direction] += amount / period_days
            measurements.append({'measure': 'service', 'service_type': type_name, 'scope': scope,
                                 'node_or_scope': node_or_scope, 'direction': direction,
                                 'quantity_per_period': amount, 'mean_per_day': amount / period_days})

        def funds_flow(amount, direction, basis):
            if amount <= 0:
                return
            funds[direction] += amount / period_days
            measurements.append({'measure': 'funds', 'node': node, 'direction': direction,
                                 'amount_musd': amount, 'mean_musd_per_day': amount / period_days,
                                 'basis': basis})

        if kind == 'market_trade':
            rid, provider_id = item['id'], item['provider_id']
            amount = number(item, 'quantity_t')
            direction = item['direction']
            provider = sim.market.provider_defs[provider_id]
            if direction == 'buy':
                price = provider.buy_price(rid)
                availability = provider.supply_def(rid)
                if price is None:
                    raise ValueError(f'Market has no buy offer for {rid}')
                funds_flow(amount * price, 'demand', 'External Market quoted buy price, no settlement')
            elif direction == 'sell':
                price = provider.sell_price(rid)
                availability = provider.demand_def(rid)
                if price is None:
                    raise ValueError(f'Market has no sell offer for {rid}')
                resource(rid, amount, 'demand', 'proposed Market sale, not settled')
                funds_flow(amount * price, 'supply', 'External Market quoted sell price, no settlement')
            else:
                raise ValueError('market_trade direction must be buy or sell')
            measurements.append({'measure': 'market_quote', 'provider_id': str(provider_id),
                                 'resource_id': str(rid), 'direction': direction,
                                 'quote_musd_per_t': price, 'quantity_t': amount,
                                 'delivery_lead_days': provider.lead_time_days,
                                 'authored_availability_t': None if availability is None else {
                                     'initial': availability.initial_t,
                                     'capacity': availability.capacity_t,
                                     'replenishment_per_day': availability.replenishment_t_per_day},
                                 'interpretation': 'no buy delivery credited; no sale proceeds assumed settled; '
                                                   'Market interface, competing orders and Funds not checked'})
        elif kind == 'process':
            pid, rate = item['id'], number(item, 'rate_per_day')
            spec = sim.industry.processes[pid]
            for rid, amount in spec.inputs_per_day.items():
                resource(rid, amount * rate * period_days, 'demand', 'Process input per execution')
            for rid, amount in spec.outputs_per_day.items():
                resource(rid, amount * rate * period_days, 'supply', 'Process output per execution, conditional')
            service(sim.industry.process_service_type(pid), rate * period_days, 'demand')
        elif kind == 'extraction':
            # The author supplies the rate; geology and installed equipment
            # are evidence alongside it, not an automatically fulfilled mine.
            fid, method_id = item['facility_id'], item['id']
            rate = number(item, 'rate_t_per_day')
            units = number(item, 'facility_units', whole=True)
            physical = site_evidence(sim, item['context_id'], fid, method_id=method_id,
                                     level=level_of(item))
            info = physical['extraction']
            resource(info['output_resource_id'], rate * period_days, 'supply',
                     'assumed Extraction output rate; physical opportunity refers to deposit Resource')
            nominal = info['nominal_capacity_t_per_day'] * units
            service(sim.extraction.service_type(sim.extraction.specs[method_id].resource_id),
                    nominal * period_days, 'demand')
            region = surface_region_evidence(
                sim, item.get('cell_ids', [item['context_id']]), method_id, fid,
                facility_units=units, level=level_of(item),
                anchor_cell_ids=item.get('anchor_cell_ids', ()))
            measurements.append({'measure': 'extraction_physical_opportunity',
                                 'equipment_units': units, 'per_facility': info,
                                 'region': region,
                                 'combined_nominal_capacity_t_per_day': nominal,
                                 'combined_physical_response_t_per_day': region['physical_diminishing_response_t_per_day'],
                                 'interpretation': 'assumed production is not proven by physical response; '
                                                   'Cell selection and anchors are assumptions, no founded territory; '
                                                   'extraction service demand is full nameplate request'})
        elif kind == 'spatial_development':
            rid, count = item['id'], number(item, 'count', whole=True)
            recipe = sim.projects.spatial_recipes[rid]
            for requirement in recipe.resources:
                resource(requirement.resource_id, requirement.amount_t * count, 'demand',
                         'Surface Location development investment once')
            service('construction_work', recipe.construction_work * count, 'demand')
            if 'target_cell_id' in item:
                measurements.append({'measure': 'development_target_world',
                    'context': physical_context_evidence(
                        sim, item['target_cell_id']),
                    **physical_site_conditions(sim, item['target_cell_id'], recipe.site_requirements),
                    'interpretation': 'candidate only; no surveyed Knowledge or adjacent owned territory is asserted'})
            measurements.append({'measure': 'spatial_development_site',
                                 'prerequisite_technologies': sorted(map(str, recipe.prerequisite_technologies)),
                                 'interpretation': 'not a developed Surface Cell; geometric and site conditions '
                                                   'must be checked separately'})
        elif kind == 'facility_construction':
            fid, count = item['id'], number(item, 'count', whole=True)
            recipe = sim.projects.recipes[fid]
            for requirement in recipe.resources:
                resource(requirement.resource_id, requirement.amount_t * count, 'demand', 'Construction investment once')
            service('construction_work', recipe.construction_work * count, 'demand')
        elif kind == 'facility_upgrade':
            fid, count = item['id'], number(item, 'count', whole=True)
            target_level = number(item, 'target_level', whole=True)
            recipe = sim.projects.upgrade_recipes[(fid, target_level)]
            for requirement in recipe.resources:
                resource(requirement.resource_id, requirement.amount_t * count, 'demand',
                         'Facility level transition investment once')
            service('construction_work', recipe.construction_work * count, 'demand')
            measurements.append({'measure': 'facility_upgrade_level', 'target_level': target_level,
                                 'prerequisite_technologies': sorted(map(str, recipe.prerequisite_technologies)),
                                 'interpretation': 'one specified level transition, not a free completed upgrade'})
        elif kind == 'vehicle_production':
            vid, count = item['id'], number(item, 'count', whole=True)
            spec = sim.transport.vehicle_defs[vid].production
            for rid, amount in spec.resources:
                resource(rid, amount * count, 'demand', 'Vehicle production investment once')
            if spec.service_type is not None:
                service(spec.service_type, spec.days * count, 'demand')
            measurements.append({'measure': 'production_nominal_days_per_unit', 'value': spec.days,
                                 'interpretation': 'not a delivery/completion schedule'})
        elif kind == 'facility_operation':
            fid, count = item['id'], number(item, 'count', whole=True)
            definition = sim.facilities.definitions[fid]
            context = item['context_id']
            site = site_evidence(sim, context, fid,
                level=level_of(item))
            gen = site['power']['generation_mw_per_facility']
            load = site['power']['active_load_mw_per_facility']
            measurements.append({'measure': 'site_environment',
                'installation': site['installation'], 'operation': site['operation'],
                'research_provider': site['research_provider'],
                'construction': site['construction'],
                'power_climate_coefficient': site['power'],
                'interpretation': 'not an installed Facility or a legality preflight'})
            power[node]['nominal_generation_mw'] += gen * count
            power[node]['nominal_active_load_mw'] += load * count
            measurements.append({'measure': 'power', 'generation_mw': gen * count,
                                 'active_load_mw': load * count, 'context_id': str(context),
                                 'basis': 'PowerService.nominal_for_definition_at_context; long-run climate coefficient, no fulfillment'})
            level = level_of(item)
            if definition.housing_at_level(level):
                habitation[node]['nominal_housing_people'] += definition.housing_at_level(level) * count
            if definition.life_support is not None:
                service('life_support', definition.life_support.capacity_at_level(level) * count
                        * period_days, 'supply')
                habitation[node]['nominal_life_support_person_days_per_day'] += (
                    definition.life_support.capacity_at_level(level) * count
                )
            for cap in definition.service_capacity_supplies:
                service(cap.service_type, cap.nominal_rate * count * period_days,
                        'supply', scope=cap.scope.value)
            construction_provider = sim.projects.construction_providers.get(fid)
            if construction_provider is not None:
                service('construction_work', construction_provider.work_per_day * count * period_days, 'supply')
            selected = item.get('selected_process_id')
            if selected is not None:
                service_type = sim.industry.process_service_type(selected)
                compatible = sim.industry.service_capacity_provider_definition_ids(service_type)
                if fid not in compatible:
                    raise ValueError(f'Process {selected} incompatible with Facility {fid}')
                service(service_type, count * definition.process_throughput_per_day * period_days, 'supply')
            if item.get('selected_extraction_method_id') is not None:
                physical = site_evidence(sim, context, fid,
                    method_id=item['selected_extraction_method_id'],
                    level=level)
                method = sim.extraction.specs[item['selected_extraction_method_id']]
                installed = sim.extraction.nominal_capacity_for_level(fid, level) * count
                service(sim.extraction.service_type(method.resource_id), installed * period_days, 'supply')
                measurements.append({'measure': 'site_extraction_physics',
                                     'per_facility': physical['extraction'], 'units': count,
                                     'nominal_installed_service_t_per_day': installed,
                                     'interpretation': 'selected method exposes its single nominal Extraction Service; '
                                                       'geology and Knowledge remain separate from actual Resource supply'})
            # Process capacity is shared over compatible Process choices; it is
            # not generated separately for every compatible Process.
            if definition.process_throughput_per_day:
                measurements.append({'measure': 'shared_process_executions_per_day',
                                     'quantity': count * definition.process_throughput_per_day})
            if definition.extraction_capacity_t_per_day:
                measurements.append({'measure': 'extraction_installed_nominal_t_per_day',
                                     'quantity': count * definition.extraction_capacity_t_per_day,
                                     'interpretation': 'before site opportunity, Knowledge and allocation'})
            recipe = sim.projects.recipes.get(fid)
            if recipe is not None:
                invested = defaultdict(float)
                for req in recipe.resources:
                    invested[req.resource_id] += req.amount_t * count
                # A hypothetical level > 1 includes actual registered transitions.
                # Missing transitions cannot be treated as free equipment.
                level = level_of(item)
                for next_level in range(2, level + 1):
                    upgrade = sim.projects.upgrade_recipes[(fid, next_level)]
                    for req in upgrade.resources:
                        invested[req.resource_id] += req.amount_t * count
                for rid, rate in sim.facilities.maintenance_requirements_for_investment(fid, invested).items():
                    resource(rid, rate * period_days, 'demand',
                             'MaintenanceService cumulative build and level-transition investment')
                measurements.append({'measure': 'facility_investment_for_maintenance',
                                     'level': level, 'resources_t': {str(k): v for k, v in sorted(invested.items())},
                                     'interpretation': 'assumed assets acquired; investment is not counted again as new construction'})
            provider = sim.research.facility_provider_for_definition(fid)
            if provider is not None:
                lev = provider.level_spec(level)
                research['organization']['rp_nominal_per_day'] += count * lev.generation_points_per_day
                research['organization']['rp_pool_capacity_nominal_points'] += count * lev.storage_capacity_points
                research['organization']['execution_nominal_per_day'] += count * lev.research_execution_per_day
                service('research_execution', lev.research_execution_per_day * count * period_days, 'supply', scope='ORGANIZATION')
                service('crew', provider.crew_person_days_per_research_point * count * lev.generation_points_per_day * period_days, 'demand')
                measurements.append({'measure': 'research_provider', 'rp_per_day': count * lev.generation_points_per_day,
                                     'execution_per_day': count * lev.research_execution_per_day,
                                     'storage_points': count * lev.storage_capacity_points})
        elif kind == 'survey_provider':
            provider_id, source_id = item['id'], item['source_id']
            units = number(item, 'units', whole=True)
            provider = sim.survey.provider(provider_id)
            mode = provider.observation_mode(item['mode_id'])
            if not sim.survey.source_supports_mode(provider, mode, source_id):
                raise ValueError(f'Survey source {source_id} incompatible with {provider_id}:{mode.id}')
            nominal = provider.capacity_units_per_source_per_day * units
            service(sim.survey.service_type_for_provider(provider_id, source_id),
                    nominal * period_days, 'supply')
            if 'context_id' in item:
                measurements.append({'measure': 'survey_observation_mode_site',
                    **physical_site_conditions(sim, item['context_id'], mode.site_requirements),
                    'interpretation': 'physical constraints only; source availability and reach not certified'})
            measurements.append({'measure': 'survey_provider_nominal',
                                 'source_kind': provider.source_kind.value,
                                 'units_assumed': units,
                                 'observation_mode_id': mode.id,
                                 'minimum_source_units': mode.minimum_source_units,
                                 'capacity_units_per_day': nominal,
                                 'survey_progress_units_per_day': nominal * mode.survey_rate,
                                 'maximum_knowledge_level': mode.max_knowledge_level.name,
                                 'prerequisite_technologies': sorted(map(str, mode.prerequisite_technologies)),
                                 'interpretation': 'not surveyed targets, feasible reach, '
                                                   'Power, eligibility, Fleet assignment or execution'})
        elif kind == 'survey_observation':
            # The author chooses an observation amount, not a Campaign or
            # Knowledge transition. The owner gives the capacity-to-progress
            # factor and the per-provider/source finite Service identity.
            provider_id, source_id = item['id'], item['source_id']
            mode_id = item['mode_id']
            assumed_progress = number(item, 'progress_units_per_day')
            provider = sim.survey.provider(provider_id)
            mode = provider.observation_mode(mode_id)
            if not sim.survey.source_supports_mode(provider, mode, source_id):
                raise ValueError(f'Survey source {source_id} incompatible with {provider_id}:{mode_id}')
            needed = assumed_progress / mode.survey_rate
            service(sim.survey.service_type_for_provider(provider_id, source_id),
                    needed * period_days, 'demand')
            measurements.append({'measure': 'assumed_survey_observation',
                'progress_units_per_day': assumed_progress,
                'service_units_per_day': needed,
                'mode_survey_rate': mode.survey_rate,
                'basis': 'SurveyService execution requirement / ObservationModeSpec.survey_rate',
                'interpretation': 'no target Knowledge progress, reachable target or completed Campaign'})
        elif kind == 'research_fleet_provider':
            provider_id, units = item['id'], number(item, 'units', whole=True)
            provider = sim.research.providers[provider_id]
            if provider.source_kind is not ResearchProviderSourceKind.FLEET:
                raise ValueError(f'Provider {provider_id} does not use Fleet')
            vehicle_id = item['vehicle_id']
            if vehicle_id not in {v.id for v in sim.research.compatible_vehicle_definitions(provider_id)}:
                raise ValueError(f'Vehicle {vehicle_id} is not an eligible Research Provider source')
            if level_of(item) != 1:
                raise ValueError('Fleet-backed Research Provider uses level 1 per unit')
            spec = provider.level_spec(1)
            research['organization']['rp_nominal_per_day'] += units * spec.generation_points_per_day
            research['organization']['rp_pool_capacity_nominal_points'] += units * spec.storage_capacity_points
            research['organization']['execution_nominal_per_day'] += units * spec.research_execution_per_day
            service('research_execution', spec.research_execution_per_day * units * period_days, 'supply', scope='ORGANIZATION')
            service('crew', provider.crew_person_days_per_research_point * units * spec.generation_points_per_day * period_days, 'demand')
            if 'context_id' in item:
                measurements.append({'measure': 'research_fleet_provider_site',
                    **physical_site_conditions(sim, item['context_id'], provider.site_requirements),
                    'interpretation': 'physical constraints only; capability supply and Fleet assignment not certified'})
            measurements.append({'measure': 'fleet_research_provider',
                'fleet_units_assumed_committed': units,
                'rp_per_day': units * spec.generation_points_per_day,
                'execution_per_day': units * spec.research_execution_per_day,
                'storage_points': units * spec.storage_capacity_points,
                'vehicle_id': str(vehicle_id),
                'interpretation': 'excludes Power, Crew, eligibility and competing Fleet commitments'})
        elif kind == 'construction_resource':
            rid, stock_t = item['id'], number(item, 'available_stock_t')
            provider = sim.projects.construction_resource_providers[rid]
            service('construction_work', stock_t * provider.work_per_t_per_day * period_days, 'supply')
            measurements.append({'measure': 'construction_resource_provider',
                'assumed_available_stock_t': stock_t,
                'nominal_work_per_day': stock_t * provider.work_per_t_per_day,
                'interpretation': 'available local Resource stock is explicitly assumed, not created'})
        elif kind == 'founding':
            recipe_id, count = item['id'], number(item, 'count', whole=True)
            recipe = sim.founding.deployment_recipes[recipe_id]
            for requirement in recipe.payload_resources:
                resource(requirement.resource_id, requirement.amount_t * count,
                         'demand', 'Founding payload including deployed hardware AND initial stock')
            if recipe.preparation_service_type is not None:
                service(recipe.preparation_service_type, recipe.preparation_work * count, 'demand')
            if 'target_context_id' in item:
                measurements.append({'measure': 'founding_target_world',
                    'context': physical_context_evidence(sim, item['target_context_id']),
                    **physical_site_conditions(sim, item['target_context_id'], recipe.target_requirements),
                    'interpretation': 'physical target only, no installed infrastructure, Survey or legal founding'})
            if 'staging_context_id' in item:
                measurements.append({'measure': 'founding_staging_world',
                    'context': physical_context_evidence(sim, item['staging_context_id']),
                    **physical_site_conditions(sim, item['staging_context_id'], recipe.staging_requirements)})
            measurements.append({'measure': 'founding_payload_mass_t', 'quantity': recipe.payload_t * count,
                                 'interpretation': 'staging demand only, not transported/settled Cargo'})
        elif kind == 'transport_cycle':
            vehicle_id, units = item['id'], number(item, 'units', whole=True)
            origin, destination = item['origin_context_id'], item['destination_context_id']
            destination_node = item['destination_node']
            resolver = sim.transport.movement_resolver()
            forward = [row for row in resolver.physical_context_plans(origin, destination)
                       if str(row.id) == item['forward_plan_id']]
            reverse_id = item.get('reverse_plan_id')
            reverse = [row for row in resolver.physical_context_plans(destination, origin)
                       if str(row.id) == reverse_id] if reverse_id is not None else []
            if len(forward) != 1 or (reverse_id is not None and len(reverse) != 1):
                raise ValueError('transport cycle requires registered physical Movement plan IDs')
            definition = sim.transport.vehicle_defs[vehicle_id]
            disposition = definition.movement_asset_disposition(forward[0]).value
            if disposition == 'destination' and not reverse:
                raise ValueError('reusable Transport cycle requires an explicit physical return')
            if disposition == 'origin' and reverse:
                raise ValueError('origin-returning Movement cannot also have a physical reverse')
            cycle = sim.transport.physical_cycle_coefficients(vehicle_id, tuple(forward), tuple(reverse),
                anchor_context_id=origin)
            from .physical import movement_evidence
            physics = movement_evidence(sim, origin, destination, vehicle_id)
            selected_forward = next(row for row in physics['forward']
                                    if row['movement_plan_id'] == str(forward[0].id))
            selected_reverse = (None if not reverse else next(row for row in physics['reverse']
                                    if row['movement_plan_id'] == str(reverse[0].id)))
            measurements.append({'measure': 'transport_cycle_physical_requirements',
                'forward': selected_forward, 'reverse': selected_reverse,
                'operation_support_requirements': physics['operation_support_requirements'],
                'resource_support_requirements': physics['resource_support_requirements'],
                'endurance_failures': list(definition.endurance_failures(cycle.forward_days + cycle.reverse_days)),
                'interpretation': 'selected Movement physics only; installed capabilities, actual refueling, '
                                  'Knowledge, Allocation, and Fleet exclusivity are not certified'})
            target_forward = number(item, 'target_forward_t_per_day') if 'target_forward_t_per_day' in item else None
            target_reverse = number(item, 'target_reverse_t_per_day') if 'target_reverse_t_per_day' in item else None
            if target_forward is not None or target_reverse is not None:
                from space_idle.transport.models import DirectionalCapacity
                requested = DirectionalCapacity(target_forward or 0.0, target_reverse or 0.0)
                required_units = sim.transport.required_units_for_capacity(requested, cycle.nominal_per_unit)
                measurements.append({'measure': 'transport_od_demand',
                                     'origin_node': node, 'destination_node': str(destination_node),
                                     'target_forward_t_per_day': requested.forward_t_per_day,
                                     'target_reverse_t_per_day': requested.reverse_t_per_day,
                                     'required_units_from_owner_physical_capacity': required_units,
                                     'assumed_fleet_units': units,
                                     'nominal_capacity_covers_target': units >= required_units,
                                     'basis': 'TransportDomain.required_units_for_capacity on physical cycle; '
                                              'not a Fleet reservation or a delivered Resource'})
            for context, rid, rate in cycle.resource_t_per_full_utilization_day:
                site_node = node if context == origin else destination_node if context == destination else None
                if site_node is None:
                    raise ValueError('intermediate Movement contexts require explicit node accounting')
                resource(rid, rate * units * period_days, 'demand',
                    'fully loaded physical Transport cycle; without actual Service availability', at_node=site_node)
            if definition.turnaround_service_type is not None:
                service(definition.turnaround_service_type,
                    cycle.servicing_units_per_full_utilization_day * units * period_days, 'demand')
            measurements.append({'measure': 'transport_cycle_nominal',
                'destination_node': destination_node,
                'fleet_units_assumed_committed': units,
                'fleet_cycle_days': cycle.cycle_days,
                'forward_t_per_day': cycle.nominal_per_unit.forward_t_per_day * units,
                'reverse_t_per_day': cycle.nominal_per_unit.reverse_t_per_day * units,
                'interpretation': 'full-cycle nominal loads; no Supply, installed infrastructure, Fleet acquisition or Cargo admission'})
        elif kind == 'movement':
            from .physical import movement_evidence
            count = number(item, 'count', whole=True)
            cargo = number(item, 'cargo_t')
            origin, destination, vehicle_id = item['origin_context_id'], item['destination_context_id'], item['id']
            evidence = movement_evidence(sim, origin, destination, vehicle_id, cargo_t=cargo)
            matches = [row for row in evidence['forward'] if row['movement_plan_id'] == item['movement_plan_id']]
            if not matches:
                raise ValueError(f'unknown physical Movement choice: {item["movement_plan_id"]}')
            leg = matches[0]
            if leg['cargo_exceeds_physical_capacity']:
                raise ValueError('Movement cargo exceeds vehicle physical payload capacity')
            propellant_resource = evidence['propellant_resource_id']
            if propellant_resource is not None:
                # This is consumption at the explicitly named origin only.
                resource(propellant_resource, leg['propellant_t_at_requested_cargo'] * count,
                         'demand', 'One-way Movement propellant (no Cargo settlement)')
            measurements.append({'measure': 'one_way_movement',
                'origin_context_id': str(origin), 'destination_context_id': str(destination),
                'vehicle_id': str(vehicle_id), 'movements': count,
                'cargo_t': cargo * count, 'fleet_days_in_transit': leg['transit_days'] * count,
                'vehicle_physical_failures': leg['vehicle_physical_failures'],
                'origin_environment_failures': leg['origin_environment_failures'],
                'destination_environment_failures': leg['destination_environment_failures'],
                'asset_disposition': leg['asset_disposition'],
                'interpretation': 'no founded endpoint, turnaround, return, refueling or Fleet assignment; do not book destination stock'})
        elif kind == 'life_support':
            fid, people = item['id'], number(item, 'people', whole=True)
            spec = sim.facilities.definitions[fid].life_support
            if spec is None:
                raise ValueError(f'Facility {fid} is not a Life Support provider')
            for rid, rate in spec.net_resources:
                resource(rid, rate * people * period_days, 'demand', 'Person-day Life Support use')
            habitation[node]['assumed_population_people'] += people
            service('life_support', people * period_days, 'demand')
            measurements.append({'measure': 'life_support_person_days_per_day_needed', 'quantity': people,
                                 'provider_person_days_per_day': spec.person_days_per_day})
        elif kind == 'research_stage':
            tid, stage_id = item['id'], item['stage_id']
            stage = sim.research.definitions[tid].stage_spec(stage_id)
            count = number(item, 'count', whole=True)
            if isinstance(stage, ResearchTheoryStageSpec):
                units = stage.research_point_cost * count
                research['organization']['rp_demand_per_day'] += units / period_days
                requirements = stage.execution_requirements
            elif isinstance(stage, (ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)):
                units = stage.required_work * count
                from .catalog import describe_site_requirements
                site = {'site': describe_site_requirements(stage.site_requirements)}
                if 'context_id' in item:
                    site = physical_site_conditions(sim, item['context_id'], stage.site_requirements)
                measurements.append({'measure': 'research_stage_site', **site,
                    'interpretation': 'specified context only; active Capabilities and Research Stage eligibility not certified'})
                if isinstance(stage, ResearchPrototypeStageSpec):
                    for rid, amount in stage.resources.items():
                        resource(rid, amount * count, 'demand', 'Prototype investment once')
                requirements = stage.execution_requirements
            else:
                units = 0
                requirements = ()
                measurements.append({'measure': 'knowledge_gate', 'requirements': dict(stage.requirements),
                                     'interpretation': 'not a timed progression'})
            for requirement in requirements:
                row = describe_execution_requirement(requirement)
                amount = units * requirement.amount_per_execution
                if row.get('kind') == 'service':
                    service(row['service_type'], amount, 'demand', scope=row['scope'],
                            scope_id=row['scope_id'], at_node=row['constraint_node_id'])
                elif row.get('kind') == 'resource':
                    resource(row['resource_id'], amount, 'demand',
                             'Research Stage execution requirement', at_node=row['constraint_node_id'])
                else:
                    measurements.append({'measure': 'execution_requirement', 'requirement': row,
                                         'total_units_over_period': amount})
            measurements.append({'measure': 'research_stage_work_or_rp', 'units': units,
                                 'stage_kind': stage.stage_type.value,
                                 'average_units_per_day': units / period_days})
        else:
            raise ValueError(f'unknown activity kind: {kind}')
        rows.append({'source': label, 'node': node, 'evidence': measurements})
    return {
        'period_days': period_days,
        'resource_by_node': [
            {'node': node, 'resource_id': rid, 'supply_t_per_day': values['supply'],
             'demand_t_per_day': values['demand'],
             'conditional_difference_t_per_day': values['supply'] - values['demand']}
            for (node, rid), values in sorted(by_resource.items())
        ],
        'service_by_scope': [
            {'scope': scope, 'node_or_scope': node, 'service_type': kind,
             'nominal_supply_per_day': values['supply'], 'demand_per_day': values['demand']}
            for (scope, node, kind), values in sorted(by_service.items())
        ],
        'power_by_node': [{'node': node, **values} for node, values in sorted(power.items())],
        'research_by_scope': [{'scope': scope, **values} for scope, values in sorted(research.items())],
        'funds_by_scope': ([] if not funds else [{
            'scope': 'ORGANIZATION',
            'quoted_receipts_musd_per_day': funds['supply'],
            'quoted_spending_musd_per_day': funds['demand'],
        }]),
        'habitation_by_node': [{'node': node, **values} for node, values in sorted(habitation.items())],
        'activity_evidence': rows,
        'limits': ('One-period stated activity loads only. Differences are conditional arithmetic, not feasible supply, '
                   'inventory forecasts, transport settlement, service allocation, construction progress or research completion. '
                   'Node labels are assumptions, not created Operational Nodes. No stock moves between nodes.'),
    }
