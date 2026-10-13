"""Research-driven, definition-derived quantitative dependency view.

This is a goal lens of the existing balance analysis, not a second Simulation,
resource allocator, technology unlocker, or automatic Facility/Fleet selector.
It exposes alternative upstream requirements without silently choosing a method.
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil, isfinite

from space_idle.bootstrap import build_game_application_for_load
from space_idle.execution_requirements import ResourceRequirement, ServiceCapacityRequirement
from space_idle.power import FixedGeneration, SolarGeneration
from space_idle.shared import DefinitionId
from scripts.analysis_balance_network import aggregate_material, source_investment, producer_catalog, conditional_material_paths


def _research_stage_elapsed_capacity_floor(spec, execution_rate):
    """A single Stage's strictly serial progress given *one* provider option.

    RP may have been accumulated before the Theory Stage. We therefore only
    count its finite execution-service work here; the entire technology
    closure's RP supply is bounded separately. Across separate projects,
    Stage work can progress concurrently and must not be summed as days.
    """
    kind, rp, work, requirements = spec
    if kind == 'operational_experience':
        return 0.0  # Actual activity/Knowledge gates are a separate constraint.
    if kind != 'theory':
        return work
    execution_work = sum(
        req.amount_per_execution * rp
        for req in requirements
        if isinstance(req, ServiceCapacityRequirement)
        and req.service_type == 'research_execution'
        and req.scope.value == 'ORGANIZATION')
    if execution_work > 0 and execution_rate <= 0:
        return None
    return execution_work / execution_rate if execution_rate > 0 else 0.0


def _registered_branch_pacing(sim, research_ids, provider_choices):
    """Actual technology prerequisites -> capacity-time envelopes for each goal.

    This is never a fitted or preferred research route. Each goal includes
    only its authored transitive Technology prerequisites. Multiple projects
    may run concurrently; a single project traverses its Stage list in
    sequence. Source investment, Research Point admission, site eligibility,
    finite allocation, movement and operational experience remain distinct.
    """
    defs = sim.research.definitions
    closures = {}
    visiting = set()

    def closure(tech_id):
        if tech_id not in closures:
            if tech_id in visiting:
                raise ValueError('cyclic Technology prerequisite graph')
            visiting.add(tech_id)
            prereqs = set()
            for prerequisite in defs[DefinitionId(tech_id)].prerequisites:
                prereq_id = str(prerequisite)
                prereqs.add(prereq_id)
                prereqs.update(closure(prereq_id))
            visiting.remove(tech_id)
            closures[tech_id] = frozenset(prereqs | {tech_id})
        return closures[tech_id]

    def spec_parts(tech_id):
        for spec in defs[DefinitionId(tech_id)].stage_specs:
            yield (spec.stage_type.value, getattr(spec, 'research_point_cost', 0.0),
                   getattr(spec, 'required_work', 0.0), getattr(spec, 'execution_requirements', ()))

    def work_for(tech_id):
        return sum(sum(req.amount_per_execution * rp
                       for req in reqs
                       if isinstance(req, ServiceCapacityRequirement)
                       and req.scope.value == 'ORGANIZATION'
                       and req.service_type == 'research_execution')
                   for _, rp, _, reqs in spec_parts(tech_id))

    rp = {str(tech_id): sum(part[1] for part in spec_parts(str(tech_id))) for tech_id in defs}
    execution_work = {str(tech_id): work_for(str(tech_id)) for tech_id in defs}
    rows = []
    for tech_id in sorted(research_ids):
        lineage = closure(tech_id)
        accumulated_rp = sum(rp[key] for key in lineage)
        accumulated_execution = sum(execution_work[key] for key in lineage)
        experience = sorted(key for key in lineage
                            if any(spec.stage_type.value == 'operational_experience'
                                   for spec in defs[DefinitionId(key)].stage_specs))
        alternatives = []
        for choice in provider_choices:
            rate = choice['rp_generation_per_day']
            exec_rate = choice['research_execution_capacity_per_day']
            rp_days = accumulated_rp / rate if rate > 0 else (0.0 if not accumulated_rp else None)
            exec_days = (accumulated_execution / exec_rate if exec_rate > 0 else
                         (0.0 if not accumulated_execution else None))
            memo = {}

            def critical(key):
                if key not in memo:
                    stages = [_research_stage_elapsed_capacity_floor(part, exec_rate)
                              for part in spec_parts(key)]
                    serial = sum(stages) if all(value is not None for value in stages) else None
                    previous = [critical(str(pre)) for pre in defs[DefinitionId(key)].prerequisites]
                    memo[key] = (serial + max(previous, default=0.0)
                                 if serial is not None and all(value is not None for value in previous)
                                 else None)
                return memo[key]

            dag_days = critical(tech_id)
            limit = (max(rp_days, exec_days, dag_days)
                     if all(day is not None for day in (rp_days, exec_days, dag_days)) else None)
            alternatives.append({
                'provider': choice['provider'], 'source': choice['source'],
                'source_level': choice['provider_level'], 'source_units': choice['source_units'],
                'rp_flow_lower_bound_days': rp_days,
                'research_execution_flow_lower_bound_days': exec_days,
                'serial_technology_stage_path_lower_bound_days': dag_days,
                'conditional_capacity_lower_bound_days': limit,
                'source_technology_needed_within_path': sorted(lineage.intersection(
                    choice['prerequisite_technologies_for_source'])),
            })
        rows.append({
            'research': tech_id,
            'authored_prerequisite_closure': sorted(lineage),
            'branch_research_count': len(lineage),
            'branch_rp_demand': accumulated_rp,
            'branch_organization_research_execution_work': accumulated_execution,
            'experience_gates_on_branch': experience,
            'independent_source_time_comparisons': alternatives,
            'interpretation': 'conditional_branch_capacity_bound_not_a_gameplay_completion_day',
        })
    return rows


def research_goal_closure(definitions, research_ids, *, include_prerequisites=False):
    """Resolve the registered Technology DAG once for both goal and quantity views.

    The closure is a set of *requirements*, not a scheduled Research Project
    sequence or a claim of unlocked Technologies.
    """
    chosen = set(research_ids)
    if not chosen or len(chosen) != len(research_ids):
        raise ValueError('research IDs must be nonempty and unique')
    if not chosen <= {str(identifier) for identifier in definitions}:
        raise ValueError('unknown research ID')
    if include_prerequisites:
        todo = list(chosen)
        while todo:
            definition = definitions[DefinitionId(todo.pop())]
            for prerequisite in definition.prerequisites:
                if str(prerequisite) not in chosen:
                    chosen.add(str(prerequisite))
                    todo.append(str(prerequisite))
    return tuple(sorted(chosen))


def analyze_research_goal(*, progression_stage=None, research_ids=(), provider_units=1,
                          production_methods=None, include_prerequisites=False,
                          horizon_days=(), selected_science_campaigns=(), app=None):
    """Trace Research goal -> RP -> provider-days -> maintenance/capital -> raw inputs.

    Each Provider/source/level is a *choice*, never the recommended build. One
    option's demands must never be summed with a different option's demands.
    """
    if app is None:
        app = build_game_application_for_load()
    sim = app._simulation
    if (progression_stage is None) == (not research_ids):
        raise ValueError('select either a progression stage or research IDs')
    if progression_stage is not None and (type(progression_stage) is not int or progression_stage <= 0):
        raise ValueError('progression_stage must be positive integer')
    if type(provider_units) is not int or provider_units < 1:
        raise ValueError('provider_units must be positive integer')
    if any(type(day) not in (int, float) or not isfinite(day) or day <= 0 for day in horizon_days):
        raise ValueError('horizon days must be finite and positive')
    if len(set(horizon_days)) != len(horizon_days):
        raise ValueError('horizons must be distinct')
    defs = sim.research.definitions
    if progression_stage is not None:
        chosen = {str(x.id) for x in defs.values() if x.progression_stage == progression_stage}
        if not chosen:
            raise ValueError(f'no registered Research at progression stage {progression_stage}')
    else:
        if len(set(research_ids)) != len(research_ids) or not research_ids:
            raise ValueError('research IDs must be nonempty and unique')
        chosen = set(research_ids)
        if not chosen <= {str(x) for x in defs}:
            raise ValueError('unknown research ID')
    chosen = set(research_goal_closure(defs, tuple(sorted(chosen)),
                                       include_prerequisites=include_prerequisites))
    # The display generation is metadata, not an unlock rule or hidden build order.
    # Only actual prerequisite edges can add selected projects.
    external_prerequisites = sorted({str(pre) for identifier in chosen
                                     for pre in defs[DefinitionId(identifier)].prerequisites
                                     if str(pre) not in chosen})
    missions = sim.scientific_exploration.definitions
    if len(set(selected_science_campaigns)) != len(selected_science_campaigns):
        raise ValueError('duplicate Science Campaign selection')
    if set(selected_science_campaigns) - {str(k) for k in missions}:
        raise ValueError('unknown Scientific Exploration campaign')
    science_options = [{
        'campaign': str(c.id), 'finite_research_point_total': c.research_points_total,
        'on_site_science_activity_days': c.duration_days,
        'required_fleet_units': c.required_units,
        'required_crew': c.required_crew,
        'departure_consumable_resource_t': aggregate_material(c.consumable_resources),
        'prerequisite_technologies': sorted(map(str, c.prerequisite_technologies)),
        'selected_as_conditional_rp_source': str(c.id) in selected_science_campaigns,
        'status': 'finite_campaign_not_awarded_requires_movement_fleet_rp_admission',
    } for c in sorted(missions.values(), key=lambda c: str(c.id))]
    conditional_science_rp = sum(missions[DefinitionId(key)].research_points_total
                                 for key in selected_science_campaigns)
    research_requirements = defaultdict(float)
    service = defaultdict(float)
    experience = defaultdict(float)
    theory_rp = 0.0
    prototype_demonstration_work = 0.0
    experience_gates = []
    project_stages = defaultdict(list)
    stages = []
    for identifier in sorted(chosen):
        definition = defs[DefinitionId(identifier)]
        for spec in definition.stage_specs:
            rp = getattr(spec, 'research_point_cost', 0.0)
            work = getattr(spec, 'required_work', 0.0)
            theory_rp += rp
            if spec.stage_type.value in ('prototype', 'demonstration'):
                prototype_demonstration_work += work
            if spec.stage_type.value == 'operational_experience':
                experience_gates.append(identifier)
            project_stages[identifier].append((spec.stage_type.value, rp, work, getattr(spec, "execution_requirements", ())))
            material = aggregate_material((r, v) for r, v in getattr(spec, 'resources', {}).items())
            for r, value in material.items():
                research_requirements[r] += value
            for requirement in getattr(spec, 'execution_requirements', ()):
                progress = rp or work
                if isinstance(requirement, ServiceCapacityRequirement):
                    service[(requirement.scope.value, requirement.service_type)] += requirement.amount_per_execution * progress
                elif isinstance(requirement, ResourceRequirement):
                    research_requirements[str(requirement.resource_id)] += requirement.amount_per_execution * progress
            for category, amount in getattr(spec, 'requirements', {}).items():
                experience[category] += amount
            stages.append({'research': identifier, 'stage': spec.stage_id, 'stage_type': spec.stage_type.value,
                           'research_point_cost': rp, 'execution_work': work,
                           'direct_material_t': material,
                           'direct_prerequisites': sorted(str(p) for p in definition.prerequisites),
                           'status': 'registered_stage_not_executed'})
    services = [{'scope': scope, 'service': name, 'total_work': value}
                for (scope, name), value in sorted(service.items())]
    individual_research = []
    for identifier in sorted(chosen):
        definition = defs[DefinitionId(identifier)]
        own = [item for item in stages if item['research'] == identifier]
        individual_research.append({
            'research': identifier, 'progression_stage': definition.progression_stage,
            'category': definition.category, 'series': definition.series,
            'direct_prerequisites': sorted(map(str, definition.prerequisites)),
            'theory_rp': sum(item['research_point_cost'] for item in own),
            'site_stage_work': sum(item['execution_work'] for item in own),
            'stage_order': [{'stage_id': item['stage'], 'kind': item['stage_type'],
                             'theory_rp': item['research_point_cost'], 'work': item['execution_work']}
                            for item in own],
        })
    production, extraction = producer_catalog(sim)
    facilities = sorted(sim.facilities.definitions.values(), key=lambda f: str(f.id))
    vehicles = sorted(sim.transport.vehicle_definitions(), key=lambda v: str(v.id))
    providers = []
    remaining_conditional_rp = max(0.0, theory_rp - conditional_science_rp)
    for provider in sorted(sim.research.providers.values(), key=lambda p: str(p.id)):
        if provider.source_kind.value == 'facility':
            sources = [(f, str(f.id)) for f in facilities
                       if provider.accepts_source(cap.id for cap in f.capability_supplies)]
        else:
            sources = [(v, str(v.id)) for v in vehicles
                       if provider.accepts_source(v.performance.generic_capabilities)]
        for source_obj, source_id in sources:
            power_spec = sim.power.specs.get(source_obj.id) if provider.source_kind.value == 'facility' else None
            if provider.source_kind.value == 'facility':
                power_load = power_spec.load_mw if power_spec else None
                standby_load = power_spec.standby_load_mw if power_spec else None
                generation = (('fixed', power_spec.generation.mw) if power_spec and
                              isinstance(power_spec.generation, FixedGeneration) else
                              ('solar_world_dependent', power_spec.generation.rated_mw_at_reference_flux)
                              if power_spec and isinstance(power_spec.generation, SolarGeneration) else None)
            else:
                power_load = None
                standby_load = None
                generation = None
            for level in sorted(provider.levels, key=lambda level: level.level):
                invested, construction_work, technology, recipe_basis = source_investment(
                    sim, provider.source_kind.value, source_id, level.level)
                maintenance_rate = (aggregate_material(sim.facilities.maintenance_requirements_for_investment(
                    source_obj.id, {DefinitionId(r): amount for r, amount in invested.items()}).items())
                    if provider.source_kind.value == 'facility' and recipe_basis != 'missing_registered_upgrade_recipe'
                    else None)
                rp_rate = provider_units * level.generation_points_per_day
                execution_rate = provider_units * level.research_execution_per_day
                generation_days = remaining_conditional_rp / rp_rate if rp_rate > 0 else (0.0 if remaining_conditional_rp == 0 else None)
                research_execution = service.get(('ORGANIZATION', 'research_execution'), 0.0)
                execution_days = research_execution / execution_rate if execution_rate > 0 else (0.0 if research_execution == 0 else None)
                # Project Stages can progress in parallel across projects.
                # Global Stage work is a *quantity*, not a serial duration.
                # A research source incurs Maintenance through the larger
                # RP-generation, research-execution or project-DAG obligation.
                duration_floor = (max(generation_days, execution_days)
                                  if generation_days is not None and execution_days is not None else None)
                # The serial Stage order imposes an independent project lower
                # bound; prerequisite DAG is accounted for below.
                project_durations = {}
                for identifier in chosen:
                    parts = [_research_stage_elapsed_capacity_floor(s, execution_rate)
                             for s in project_stages[identifier]]
                    project_durations[identifier] = sum(parts) if all(p is not None for p in parts) else None
                critical_path = {}
                def path_days(identifier):
                    if identifier in critical_path:
                        return critical_path[identifier]
                    previous = [path_days(str(p)) for p in defs[DefinitionId(identifier)].prerequisites
                                if str(p) in chosen]
                    own = project_durations[identifier]
                    critical_path[identifier] = (own + max(previous, default=0.0)
                                                 if own is not None and all(p is not None for p in previous)
                                                 else None)
                    return critical_path[identifier]
                paths = [path_days(identifier) for identifier in sorted(chosen)]
                serial_dag_floor = max(paths, default=0.0) if all(p is not None for p in paths) else None
                if duration_floor is not None:
                    duration_floor = max(duration_floor, serial_dag_floor) if serial_dag_floor is not None else None
                # Fixed, per-provider construction versus operating bill is
                # separated. None is unknown, never a free 0-cost Fleet.
                resource_rate = (aggregate_material((k, v * provider_units) for k, v in maintenance_rate.items())
                                 if maintenance_rate is not None else None)
                maintenance_total = (aggregate_material((k, v * duration_floor) for k, v in resource_rate.items())
                                     if resource_rate is not None and duration_floor is not None else None)
                fixed_capital = aggregate_material((k, v * provider_units) for k, v in invested.items())
                footprint = aggregate_material(list(research_requirements.items()) + list(fixed_capital.items())
                                       + list((maintenance_total or {}).items()))
                horizon_sensitivity = []
                for days in sorted(horizon_days):
                    min_units_rp = ceil(remaining_conditional_rp / (days * level.generation_points_per_day)) if level.generation_points_per_day > 0 else (0 if remaining_conditional_rp == 0 else None)
                    min_units_execution = (ceil(research_execution / (days * level.research_execution_per_day))
                                           if level.research_execution_per_day > 0 else (0 if research_execution == 0 else None))
                    min_units = (max(1, min_units_rp, min_units_execution)
                                 if min_units_rp is not None and min_units_execution is not None else None)
                    if min_units is None:
                        horizon_sensitivity.append({'days': days, 'minimum_provider_units_capacity_only': None,
                                                    'status': 'no_positive_rp_or_execution_capacity'})
                        continue
                    candidate_maintenance = (aggregate_material((r, amount * min_units * days)
                                                       for r, amount in (maintenance_rate or {}).items())
                                             if maintenance_rate is not None else None)
                    candidate_capital = aggregate_material((r, amount * min_units) for r, amount in invested.items())
                    horizon_sensitivity.append({
                        'days': days,
                        'minimum_units_for_rp_rate': min_units_rp,
                        'minimum_units_for_research_execution_rate': min_units_execution,
                        'minimum_provider_units_capacity_only': min_units,
                        'source_construction_resource_t': candidate_capital,
                        'source_construction_work': construction_work * min_units if construction_work is not None else None,
                        'source_maintenance_t_during_window': candidate_maintenance,
                        'source_power_load_mw_at_capacity': power_load * min_units if power_load is not None else None,
                        'stage_serial_path_exceeds_window': serial_dag_floor > days if serial_dag_floor is not None else None,
                        'technology_and_placement_unassessed': True,
                        'status': 'necessary_nominal_capacity_not_a_completion_schedule',
                    })
                selected_tech = {str(k) for k in chosen}
                blockers = sorted(selected_tech.intersection(technology))
                providers.append({
                    'provider': str(provider.id), 'tier': provider.tier,
                    'source_kind': provider.source_kind.value, 'source': source_id,
                    'source_units': provider_units, 'provider_level': level.level,
                    'rp_generation_per_day': rp_rate,
                    'nominal_rp_remaining_if_all_selected_science_settles': remaining_conditional_rp,
                    'rp_storage_capacity': level.storage_capacity_points * provider_units,
                    'research_execution_capacity_per_day': execution_rate,
                    'rp_generation_lower_bound_days': generation_days,
                    'research_execution_lower_bound_days': execution_days,
                    'shared_concurrent_capacity_lower_bound_days': max(generation_days or 0, execution_days or 0)
                    if generation_days is not None and execution_days is not None else None,
                    'selected_project_serial_stage_lower_bound_days': serial_dag_floor,
                    'individual_project_stage_lower_bound_days': dict(sorted(project_durations.items())),
                    'operating_lower_bound_days_excluding_unassessed_dependencies': duration_floor,
                    'maintenance_cost_basis_days': duration_floor,
                    'horizon_sensitivity': horizon_sensitivity,
                    'source_prerequisites_within_research_goal': blockers,
                    'construction_resource_t': fixed_capital,
                    'construction_work': construction_work * provider_units if construction_work is not None else None,
                    'source_maintenance_resource_per_day_t': resource_rate,
                    'maintenance_for_goal_rp_generation_t': maintenance_total,
                    'direct_research_material_t': aggregate_material(research_requirements.items()),
                    'combined_direct_resource_burden_t': footprint,
                    'source_power_load_mw': power_load,
                    'source_standby_power_mw': standby_load,
                    'source_generation_model_and_rating': generation,
                    'power_load_mw_days_during_nominal_operating_lower_bound': (
                        power_load * provider_units * duration_floor
                        if power_load is not None and duration_floor is not None else None),
                    'crew_person_days_per_rp': provider.crew_person_days_per_research_point,
                    'crew_person_days_for_goal': theory_rp * provider.crew_person_days_per_research_point,
                    'prerequisite_technologies_for_source': technology,
                    'source_recipe_basis': recipe_basis,
                    'vehicle_assembly_service_type': (source_obj.production.service_type
                                                      if provider.source_kind.value == 'fleet' else None),
                    'vehicle_assembly_service_days': (source_obj.production.days
                                                      if provider.source_kind.value == 'fleet' else None),
                    'physical_upgrade_recipe_required': level.level > 1,
                    'investment_obtained': recipe_basis not in ('missing_registered_upgrade_recipe', 'no_registered_construction_recipe'),
                    'upstream_material_dependencies': conditional_material_paths(footprint, sim, production, extraction,
                                                                      production_methods or {}),
                    'status': 'conditional_independent_provider_choice_no_tech_site_allocation_or_shipping',
                })
    return {
        'model': 'research_driven_system_dependency_v1',
        'content_id': app.content_id, 'world_definition_id': app.world_definition_id,
        'goal': {'progression_stage': progression_stage, 'research_ids': sorted(chosen),
                 'includes_recursive_prerequisites': include_prerequisites,
                 'research_definition_count': len(chosen),
                 'theory_research_point_demand': theory_rp,
                 'conditionally_credited_science_rp': conditional_science_rp,
                 'remaining_nominal_rp_from_provider_if_science_settles': remaining_conditional_rp,
                 'registered_science_campaign_options': science_options,
                 'serial_site_stage_work': prototype_demonstration_work,
                 'experience_gated_research_ids': sorted(set(experience_gates)),
                 'external_direct_prerequisites_not_in_selection': external_prerequisites,
                 'research_stage_direct_material_t': aggregate_material(research_requirements.items()),
                 'research_stage_service_work': services,
                 'experience_requirements': dict(sorted(experience.items())),
                 'direct_registered_unlocks': [],
                 'registered_stages': stages,
                 'individual_research': individual_research},
        'provider_choices': providers,
        'model_limitations': [
            'research_progression_stage_is_content_metadata_not_an_automatic_play_sequence',
            'each_provider_choice_is_independent_and_not_an_optimal_or_guaranteed_configuration',
            'one_time_investment_and_ongoing_maintenance_are_separate',
            'provider_time_is_a_resource_and_service_lower_bound_not_an_actual_game_completion_day',
            'chosen_horizons_are_sensitivity_inputs_not_ideal_research_days',
            'some_provider_sources_may_be_locked_by_research_within_the_goal',
            'selected_science_rp_is_not_received_until_actual_eligible_fleet_movement_science_and_admission_settle',
            'science_activity_duration_excludes_travel_fleet_turnaround_and_return',
            'operating_cost_lower_bound_assumes_facility_is_maintained_for_the_capacity_lower_bound',
            'research_stage_service_work_can_use_other_shared_capacities_not_in_provider_execution',
            'RP_storage_admission_stage_order_preconditions_crew_power_site_supply_and_travel_are_not_solved',
            'selected_Process_material_chains_are_conditional_and_do_not_settle_power_fleet_or_inventory',
            'real_site_resource_opportunity_is_not_inferred_from_a_goal',
        ],
    }


def evaluate_research_generations(*, app=None, horizon_days=(), production_methods=None):
    """One content-wide research-to-industry lens; not independent fixed-case fixtures.

    Display stages group research demands but never impose a research order.
    Provider tiers are physical equipment maturity and MUST NOT be conflated
    with research progression stages. Every listed facility/source is a
    counterfactual alternative; choices are not installed cumulatively.
    """
    if app is None:
        app = build_game_application_for_load()
    sim = app._simulation
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    graph = build_definition_dependency_graph(sim, app._catalog)
    unlocks = defaultdict(list)
    for relation in graph.relations:
        if relation.kind == 'unlocks_method' and relation.source.kind == 'technology':
            unlocks[relation.source.id].append({'kind': relation.target.kind, 'definition': relation.target.id})
    generations = []
    for stage in sorted({d.progression_stage for d in sim.research.definitions.values()
                         if d.progression_stage is not None}):
        analysis = analyze_research_goal(
            progression_stage=stage, provider_units=1, horizon_days=horizon_days,
            production_methods=production_methods or {}, app=app)
        ids = analysis['goal']['research_ids']
        analysis['goal']['direct_registered_unlocks'] = [
            {'research': research_id, 'methods': sorted(unlocks.get(research_id, []),
                                                        key=lambda row: (row['kind'], row['definition']))}
            for research_id in ids if unlocks.get(research_id)]
        analysis['goal']['authored_technology_branch_pacing'] = _registered_branch_pacing(
            sim, ids, analysis['provider_choices'])
        analysis['goal']['category_distribution'] = {
            category: sum((sim.research.definitions[DefinitionId(i)].category or 'uncategorized') == category
                          for i in ids)
            for category in sorted({sim.research.definitions[DefinitionId(i)].category or 'uncategorized'
                                    for i in ids})}
        generations.append(analysis)
    return {
        'model': 'registered_research_generation_economics_v1',
        'content_id': app.content_id,
        'world_definition_id': app.world_definition_id,
        'time_unit': 'game_days_for_nominal_capacity_comparison_not_completion_predictions',
        'generation_axis': 'research_display_progression_stage_not_unlock_order',
        'provider_axis': 'independent_capability_compatible_physical_sources_not_a_selected_build',
        'horizon_days': sorted(horizon_days),
        'generations': generations,
        'adjustment_cycle': {
            'observe': ('Compare RP cost and typed Stage work with provider capacity; '
                        'identify which shared RP, execution, prototype or experience gate affects elapsed time'),
            'connect': ('Trace each viable technology-source acquisition, recurring maintenance, power, '
                        'crew, upstream Process/Extraction and OD delivery through one quantity model'),
            'vary': ('Compare different provider generations/levels, existing-versus-new construction, '
                     'run durations, duty and the associated upstream production/transport allocations'),
            'evaluate_player_experience': ('Assess whether time spent on research overlaps meaningful infrastructure '
                                           'investment, branch choice, geographic specialization and subsequent technological output; '
                                           'do not optimize for a fixed day-count or one forced build order'),
            'adjust_and_repeat': ('Change connected Definition coefficients or content roles only after cross-domain comparison; '
                                  'rerun these generation lenses and the same active economic compositions'),
        },
    }



def _summarize_branch_pacing_by_source(rows, horizons=()):
    """Stage/lineage pacing distribution without emitting every cartesian option.

    The detailed view retains the per-Technology prerequisite closure and
    every independent source alternative. The summary reports descriptive
    distributions, not a target day count or a preferred provider.
    """
    by_source = defaultdict(list)
    for row in rows:
        for option in row['independent_source_time_comparisons']:
            key = (option['provider'], option['source'], option['source_level'],
                   option['source_units'])
            if option['conditional_capacity_lower_bound_days'] is not None:
                by_source[key].append((option['conditional_capacity_lower_bound_days'],
                                       row['research'], option))
    out = []
    for (provider, source, level, units), values in sorted(by_source.items()):
        ordered = sorted(values, key=lambda item: (item[0], item[1]))
        count = len(ordered)
        if not count:
            continue
        # Ordered-position quantiles require no statistical model and remain
        # meaningful without a scenario, recommended completion day or score.
        quantile = lambda numerator: ordered[(count - 1) * numerator // 4][0]
        pressure = defaultdict(int)
        for duration, tech, option in ordered:
            components = {
                'rp_generation': option['rp_flow_lower_bound_days'],
                'research_execution': option['research_execution_flow_lower_bound_days'],
                'technology_stage_serial_path': option['serial_technology_stage_path_lower_bound_days'],
            }
            for name, amount in components.items():
                if amount is not None and abs(amount - duration) <= 1e-9:
                    pressure[name] += 1
        out.append({
            'provider': provider, 'source': source, 'level': level,
            'source_units': units, 'authored_technology_branches_compared': count,
            'conditional_prerequisite_branch_lower_bound_days': {
                'minimum': ordered[0][0], 'lower_quartile': quantile(1),
                'median': quantile(2), 'upper_quartile': quantile(3),
                'maximum': ordered[-1][0],
            },
            'technology_with_longest_conditional_branch': ordered[-1][1],
            'branches_requiring_provider_source_technology_within_their_own_path': sum(
                bool(item['source_technology_needed_within_path']) for _, _, item in ordered),
            'selected_horizon_feasibility_filters_not_completion_claims': [
                {
                    'days': days,
                    'branches_excluded_by_nominal_time_lower_bound': sum(
                        duration > days for duration, _, _ in ordered),
                    'branches_not_excluded_by_time_lower_bound': sum(
                        duration <= days for duration, _, _ in ordered),
                    'other_eligibility_and_supply_constraints_unchecked': True,
                } for days in sorted(horizons)],
            'binding_components_may_tie': dict(sorted(pressure.items())),
            'status': 'descriptive_research_waiting_exposure_not_target_days_or_a_schedule',
        })
    return out


def summarize_research_generations(report):
    """Compact overview retains actual time/resource dimensions and alternatives."""
    result = []
    for analysis in report['generations']:
        goal = analysis['goal']
        options = []
        for row in analysis['provider_choices']:
            options.append({
                'provider': row['provider'], 'source': row['source'], 'source_kind': row['source_kind'],
                'provider_tier': row['tier'], 'provider_level': row['provider_level'],
                'source_units': row['source_units'],
                'rp_generation_per_day': row['rp_generation_per_day'],
                'research_execution_per_day': row['research_execution_capacity_per_day'],
                'rp_storage_capacity': row['rp_storage_capacity'],
                'rp_generation_lower_bound_days': row['rp_generation_lower_bound_days'],
                'execution_lower_bound_days': row['research_execution_lower_bound_days'],
                'serial_stage_lower_bound_days': row['selected_project_serial_stage_lower_bound_days'],
                'individual_research_stage_lower_bound_days': row['individual_project_stage_lower_bound_days'],
                'conditional_operating_lower_bound_days': row['operating_lower_bound_days_excluding_unassessed_dependencies'],
                'source_construction_resource_t': row['construction_resource_t'],
                'source_construction_work': row['construction_work'],
                'source_maintenance_t_per_day': row['source_maintenance_resource_per_day_t'],
                'source_maintenance_t_during_conditional_lower_bound': row['maintenance_for_goal_rp_generation_t'],
                'source_power_mw_per_unit': row['source_power_load_mw'],
                'crew_person_days_for_goal': row['crew_person_days_for_goal'],
                'required_source_technologies': row['prerequisite_technologies_for_source'],
                'source_technologies_within_research_goal': row['source_prerequisites_within_research_goal'],
                'horizon_sensitivity': row['horizon_sensitivity'],
                'upstream_primary_requirements_t': row['upstream_material_dependencies']['gross_resource_requirements_t'],
                'selected_upstream_processes': [p['process'] for p in row['upstream_material_dependencies']['selected_processes']],
            })
        unlock_by_research = {item['research']: item['methods'] for item in goal['direct_registered_unlocks']}
        result.append({
            'research_progression_stage': goal['progression_stage'],
            'registered_research_count': goal['research_definition_count'],
            'research_point_requirement': goal['theory_research_point_demand'],
            'science_alternatives': goal['registered_science_campaign_options'],
            'remaining_provider_rp_if_selected_science_settles': goal['remaining_nominal_rp_from_provider_if_science_settles'],
            'prototype_and_demonstration_work': goal['serial_site_stage_work'],
            'experience_gates': goal['experience_gated_research_ids'],
            'research_stage_material_t': goal['research_stage_direct_material_t'],
            'research_service_work': goal['research_stage_service_work'],
            'authored_technology_branch_pacing_by_source': _summarize_branch_pacing_by_source(
                goal.get('authored_technology_branch_pacing', []), report['horizon_days']),
            'research_items': [{**row, 'unlock_methods': unlock_by_research.get(row['research'], [])}
                               for row in goal['individual_research']],
            'prerequisites_outside_generation': goal['external_direct_prerequisites_not_in_selection'],
            'technology_method_unlocks': goal['direct_registered_unlocks'],
            'provider_options_not_additive': options,
        })
    return {
        'model': 'registered_research_generation_economics_summary_v1',
        'content_id': report['content_id'],
        'generation_axis': report['generation_axis'],
        'horizon_days': report['horizon_days'],
        'generations': result,
        'adjustment_cycle': report['adjustment_cycle'],
        'caveats': ['Research time is a conditional capacity lower bound, not a fixed completion estimate',
                    'Provider options are independent and may require their own target research to be unlocked',
                    'RP storage admission, Prototype sites, Experience, logistics and shared finite allocation matter',
                    'Process/extraction paths are conditional input requirements not actual produced/transported goods'],
    }


def relate_research_goal_to_economy(goal_analysis, comparison):
    """Join one goal to selected production/Research capacity without allocating it.

    No cross-node Resource netting, no implicit delivery or additional Provider
    construction. The same existing balance report supplies all dimensions.
    """
    goal = goal_analysis['goal']
    demand_rp = goal['theory_research_point_demand']
    demanded_exec = sum(row['total_work'] for row in goal['research_stage_service_work']
                        if row['scope'] == 'ORGANIZATION' and row['service'] == 'research_execution')
    if 'cases' in comparison:
        cases = comparison['cases']
    else:
        cases = [{'name': 'explicit_composition', 'projection': comparison}]
    contexts = []
    for case in cases:
        for phase in case['projection']['phases']:
            duration = phase['days']
            r = phase['research_point_balance']
            generated = r['nominal_generation_points'] / duration
            # Selected Research Stages may already be physically booked in the
            # economy projection (including an explicitly authored goal). Do
            # not count them as a competing unrelated project, then charge the
            # exact same goal a second time in this independent capacity bound.
            goal_ids = set(goal['research_ids'])
            booked = [stage for stage in phase['research_stages'] if stage['research'] in goal_ids]
            already_booked_rp = sum(stage['point_cost'] for stage in booked)
            already_booked_execution = sum(
                req['total_required'] for stage in booked
                for req in stage['execution_requirements']
                if req['kind'] == 'service' and req['scope'] == 'ORGANIZATION'
                and req['name'] == 'research_execution')
            unrelated_rp = max(0.0, r['research_stage_demand_points'] - already_booked_rp)
            unrelated_execution = max(0.0, r['total_research_execution_work'] - already_booked_execution)
            occupied_rp = unrelated_rp / duration
            available_generation = max(0.0, generated - occupied_rp)
            available_execution = max(0.0, r['nominal_execution_per_day'] -
                                      unrelated_execution / duration)
            # Opening RP is organization stock; claim it once, after reserving
            # unrelated Research demand. Storage admission is still not solved.
            goal_initial_rp_upper_bound = max(0.0, r['start_points'] - unrelated_rp)
            unfinanced_goal_rp = max(0.0, demand_rp - goal_initial_rp_upper_bound)
            rp_days = (unfinanced_goal_rp / available_generation if available_generation > 0
                       else 0.0 if unfinanced_goal_rp == 0 else None)
            exec_days = (demanded_exec / available_execution if available_execution > 0
                         else 0.0 if demanded_exec == 0 else None)
            resources = {}
            related_resource_ids = set(goal['research_stage_direct_material_t'])
            for option in goal_analysis['provider_choices']:
                related_resource_ids.update(option['upstream_material_dependencies']['gross_resource_requirements_t'])
            for row in phase['resources']:
                resource = row['resource']
                if resource not in related_resource_ids:
                    continue
                resources.setdefault(resource, []).append({
                    'node': row['node'], 'initial_stock_t': row['start_t'],
                    'nominal_recurring_net_t_per_day': row['nominal_recurring_net_t_per_day'],
                    'conditional_shortfall_without_unconfirmed_cargo_t': row['shortfall_without_assumed_arrivals_t'],
                    'received_unconfirmed_cargo_t': row['cumulative_unverified_incoming_cargo_t'],
                })
            construction_remaining = {
                row['node']: max(0.0, row['nominal_capacity_per_day'] - row['required_per_day'])
                for row in phase['service_constraints'] if row['service'] == 'construction_work'
            }
            power_context = {row['node']: row for row in phase['constraints']}
            capital_node_options = []
            for option in goal_analysis['provider_choices']:
                for node in sorted(set(construction_remaining) | set(power_context)):
                    work_rate = construction_remaining.get(node, 0.0)
                    cost = option['construction_work']
                    capital_days = (cost / work_rate if cost is not None and work_rate > 0 else
                                    0.0 if cost == 0 else None)
                    operation_days = option['operating_lower_bound_days_excluding_unassessed_dependencies']
                    # Sequential new-source acquisition precedes use of its
                    # additional RP/Service; no self-construction is credited.
                    combined_days = (capital_days + operation_days if capital_days is not None
                                     and operation_days is not None else None)
                    power = power_context.get(node)
                    new_load = option['source_power_load_mw']
                    generation_spec = option['source_generation_model_and_rating']
                    additional_supply = (generation_spec[1] if generation_spec and generation_spec[0] == 'fixed'
                                         else 0.0 if generation_spec is None else None)
                    power_gap = (max(0.0, power['power_demand_nominal_mw']
                                     + new_load * option['source_units']
                                     - power['power_generation_nominal_mw']
                                     - additional_supply * option['source_units'])
                                 if power is not None and new_load is not None
                                 and additional_supply is not None else None)
                    # Initial on-hand Resource at a candidate site is observed
                    # separately; no surplus at a *different* Node is counted.
                    initial_by_resource = {resource: next((v['initial_stock_t'] for v in rows
                                                           if v['node'] == node), 0.0)
                                           for resource, rows in resources.items()}
                    immediate_stock_gaps = {
                        resource: max(0.0, amount - max(0.0, initial_by_resource.get(resource, 0.0)))
                        for resource, amount in option['construction_resource_t'].items()
                        if amount > max(0.0, initial_by_resource.get(resource, 0.0)) + 1e-12}
                    capital_node_options.append({
                        'provider': option['provider'], 'source': option['source'],
                        'source_level': option['provider_level'], 'possible_node_without_site_validation': node,
                        'available_construction_work_after_other_demand_per_day': work_rate,
                        'new_source_construction_lower_bound_days': capital_days,
                        'nominal_new_source_acquisition_plus_research_lower_bound_days': combined_days,
                        'power_gap_if_additional_source_operates_mw': power_gap,
                        'immediate_construction_stock_gaps_t': immediate_stock_gaps,
                        'status': 'conditional_site_and_technology_unverified_no_transport_or_resource_allocation',
                    })
            contexts.append({
                'case': case['name'], 'phase': phase['name'], 'phase_days': duration,
                'new_source_acquisition_site_time_comparisons': capital_node_options,
                'current_nominal_rp_generation_per_day': generated,
                'current_other_research_rp_claim_per_day': occupied_rp,
                'goal_stage_demand_already_booked_in_ledger': bool(booked),
                'goal_stage_rp_booked_in_ledger': already_booked_rp,
                'goal_research_execution_work_booked_in_ledger': already_booked_execution,
                'opening_rp_conditionally_available_for_goal': goal_initial_rp_upper_bound,
                'goal_rp_remaining_after_opening_stock': unfinanced_goal_rp,
                'residual_nominal_rp_rate_per_day': available_generation,
                'current_nominal_research_execution_per_day': r['nominal_execution_per_day'],
                'residual_nominal_research_execution_per_day': available_execution,
                'goal_rp_supply_lower_bound_days_from_residual_capacity': rp_days,
                'goal_research_execution_lower_bound_days_from_residual_capacity': exec_days,
                'gross_capacity_lower_bound_days': (max(rp_days, exec_days)
                                                    if rp_days is not None and exec_days is not None else None),
                'already_present_research_rp_stock': r['start_points'],
                'current_rp_storage_capacity': r['nominal_storage_capacity_points'],
                'related_resource_context_by_node': {k: v for k, v in sorted(resources.items())},
                'independent_provider_acquisition_and_upkeep_options': [
                    {
                        'provider': option['provider'], 'source': option['source'],
                        'level': option['provider_level'],
                        'new_investment_t': option['construction_resource_t'],
                        'maintenance_resource_per_day_t': option['source_maintenance_resource_per_day_t'],
                        'conditional_upstream_gross_resource_bill_t': option['upstream_material_dependencies']['gross_resource_requirements_t'],
                        'upstream_processes_selected': [p['process'] for p in option['upstream_material_dependencies']['selected_processes']],
                        'required_source_technologies': option['prerequisite_technologies_for_source'],
                        'status': 'candidate_acquisition_not_an_installed_facility_or_auto_shipping',
                    } for option in goal_analysis['provider_choices']],
                'pre_investment_construction_by_node': phase['investment_constraints'],
                'local_service_gaps': [v for v in phase['service_constraints'] if v['nominal_gap_per_day'] > 0],
                'power_gaps': [{k: row[k] for k in ('node', 'power_gap_mw')}
                               for row in phase['constraints'] if row['power_gap_mw'] > 0],
                'unresolved_transport': [{k: entry[k] for k in (
                    'origin', 'destination', 'nominal_capacity_t_per_day', 'status', 'blockers')}
                    for entry in phase['od_transport_constraints']
                    if entry['nominal_capacity_t_per_day'] is None or entry['blockers']],
                'status': 'independent_selected_economy_and_goal_join_no_provider_allocation',
            })
    return {
        'model': 'research_goal_vs_selected_economic_compositions_v1',
        'goal_research_ids': goal['research_ids'],
        'research_point_requirement': demand_rp,
        'research_execution_work_requirement': demanded_exec,
        'contexts': contexts,
        'caveats': [
            'Remaining RP and execution rates reserve unrelated selected research demand once; no dynamic allocation performed',
            'Goal acquisition and maintenance are shown separately and are not already commissioned in selected economy',
            'Each Resource and Facility capacity is local; cross-node balances never compensate without selected OD delivery',
            'Capacity lower bounds do not incorporate technology prerequisite sequencing, storage headroom or Construction lead-in',
        ],
    }


def compare_research_generation_reports(before, after):
    """Content tuning feedback in physical dimensions, never a scalar score."""
    if before.get('model') != after.get('model') or before.get('model') != 'registered_research_generation_economics_summary_v1':
        raise ValueError('compare two generation summary reports from the same evaluation contract')
    first = {row['research_progression_stage']: row for row in before['generations']}
    second = {row['research_progression_stage']: row for row in after['generations']}
    result = []
    for generation in sorted(set(first) | set(second)):
        left, right = first.get(generation), second.get(generation)
        if left is None or right is None:
            result.append({'generation': generation, 'change': 'added' if left is None else 'removed'})
            continue
        def index(data):
            return {(row['provider'], row['source'], row['provider_level']): row
                    for row in data['provider_options_not_additive']}
        a, b = index(left), index(right)
        comparisons = []
        quantities = (
            'rp_generation_per_day', 'research_execution_per_day', 'rp_storage_capacity',
            'rp_generation_lower_bound_days', 'execution_lower_bound_days',
            'serial_stage_lower_bound_days', 'conditional_operating_lower_bound_days',
            'source_construction_resource_t', 'source_construction_work',
            'source_maintenance_t_per_day', 'source_maintenance_t_during_conditional_lower_bound',
            'source_power_mw_per_unit', 'crew_person_days_for_goal',
            'upstream_primary_requirements_t', 'horizon_sensitivity',
        )
        for key in sorted(set(a) | set(b)):
            old, new = a.get(key), b.get(key)
            if old == new:
                continue
            if old is None or new is None:
                comparisons.append({'provider': key, 'change': 'added' if old is None else 'removed'})
                continue
            changes = {field: {'before': old[field], 'after': new[field]}
                       for field in quantities if old[field] != new[field]}
            if changes:
                comparisons.append({'provider': key, 'changes': changes})
        research_a = {v['research']: v for v in left['research_items']}
        research_b = {v['research']: v for v in right['research_items']}
        research_changes = []
        for tech in sorted(set(research_a) | set(research_b)):
            old, new = research_a.get(tech), research_b.get(tech)
            if old != new:
                research_changes.append({'research': tech, 'before': old, 'after': new})
        result.append({
            'generation': generation,
            'registered_research_change': right['registered_research_count'] - left['registered_research_count'],
            'research_point_requirement_change': right['research_point_requirement'] - left['research_point_requirement'],
            'prototype_and_demonstration_work_change': right['prototype_and_demonstration_work'] - left['prototype_and_demonstration_work'],
            'research_material_changes': {
                key: {'before': left['research_stage_material_t'].get(key, 0),
                      'after': right['research_stage_material_t'].get(key, 0)}
                for key in sorted(set(left['research_stage_material_t']) | set(right['research_stage_material_t']))
                if left['research_stage_material_t'].get(key, 0) != right['research_stage_material_t'].get(key, 0)
            },
            'changed_research_definitions': research_changes,
            'changed_provider_economics': comparisons,
            'changed_branch_waiting_exposure': (
                {'before': left['authored_technology_branch_pacing_by_source'],
                 'after': right['authored_technology_branch_pacing_by_source']}
                if left['authored_technology_branch_pacing_by_source'] != right['authored_technology_branch_pacing_by_source']
                else None),
        })
    return {
        'model': 'research_generation_content_tuning_delta_v1',
        'before_content_id': before['content_id'],
        'after_content_id': after['content_id'],
        'generation_changes': result,
        'interpretation': ('Inspect changed waiting/capacity stages, Stage work, source capital/maintenance, '
                           'upstream Resource methods and technology unlock before accepting any change. '
                           'A faster Theory in isolation is not a better play experience if it blocks '
                           'investment, logistics or geographically distinct production.'),
        'no_automatic_balance_verdict': True,
    }


def summarize_research_goal(report):
    """Single-goal counterpart of the same research-generation quantity summary."""
    wrapped = {
        'content_id': report['content_id'],
        'generation_axis': 'selected_research_or_display_stage',
        'horizon_days': [row['days'] for row in report['provider_choices'][0]['horizon_sensitivity']] if report['provider_choices'] else [],
        'generations': [report],
        'adjustment_cycle': {},
    }
    result = summarize_research_generations(wrapped)
    return {
        'model': 'research_goal_system_economics_summary_v1',
        'content_id': report['content_id'],
        'goal': result['generations'][0],
        'caveats': result['caveats'],
    }


def research_generations_portfolio_overview(report):
    """Bounded overview for a multi-plan report, not a second analysis model."""
    generations = []
    for item in report['generations']:
        goal = item['goal']
        generations.append({
            'display_research_stage': goal['progression_stage'],
            'research_count': goal['research_definition_count'],
            'total_catalog_theory_rp_not_a_required_playthrough': goal['theory_research_point_demand'],
            'site_stage_work': goal['serial_site_stage_work'],
            'authored_branch_pacing_by_source': _summarize_branch_pacing_by_source(
                goal.get('authored_technology_branch_pacing', []), report['horizon_days']),
            'outside_generation_prerequisite_count': len(goal['external_direct_prerequisites_not_in_selection']),
            'experience_gate_count': len(goal['experience_gated_research_ids']),
            'independent_source_options': [{
                'source': option['source'], 'provider': option['provider'],
                'tier': option['tier'], 'level': option['provider_level'],
                'rp_per_day': option['rp_generation_per_day'],
                'execution_per_day': option['research_execution_capacity_per_day'],
                'generation_days_lower_bound': option['rp_generation_lower_bound_days'],
                'execution_days_lower_bound': option['research_execution_lower_bound_days'],
                'operating_days_lower_bound': option['operating_lower_bound_days_excluding_unassessed_dependencies'],
                'capital_work': option['construction_work'],
                'maintenance_resource_per_day_t': option['source_maintenance_resource_per_day_t'],
                'capital_resource_t': option['construction_resource_t'],
                'source_tech_inside_goal': option['source_prerequisites_within_research_goal'],
            } for option in item['provider_choices']],
        })
    return {
        'model': 'registered_research_generation_portfolio_overview_v1',
        'research_display_stages': generations,
        'note': 'Alternatives are not additive; individual Technology paths and full upstream bills require --research-generations or --research-id',
        'balance_purpose': 'Compare time spent acquiring, maintaining, executing and unlocking Research across industrial and spatial investments',
    }


def summarize_research_economy_context(report):
    """Avoid repeating the per-provider bill in every scenario/phase overview."""
    return {
        **report,
        'contexts': [
            {k: v for k, v in context.items() if k != 'independent_provider_acquisition_and_upkeep_options'}
            for context in report['contexts']
        ],
        'full_provider_bill_available_in_detailed_report': True,
    }


def research_goal_impact(before, after, *, summary=False):
    """Research Goal sensitivity from registered Stage and Provider quantities.

    This reports only same-identity changes. There is no implied physical
    comparison of unrelated Provider sources and no scalar balance score.
    """
    def comparable_changes(left, right, fields, identity):
        original = {identity(v): v for v in left}
        edited = {identity(v): v for v in right}
        changes = []
        for key in sorted(set(original) | set(edited)):
            a, b = original.get(key), edited.get(key)
            if a is None or b is None:
                changes.append({'identity': key, 'before': a, 'after': b,
                                'condition': 'candidate_membership_changed'})
                continue
            delta = {field: b[field] - a[field] for field in fields
                     if isinstance(a.get(field), (float, int)) and isinstance(b.get(field), (float, int))
                     and abs(a[field] - b[field]) > 1e-12}
            condition = {field: {'before': a.get(field), 'after': b.get(field)}
                         for field in fields if a.get(field) != b.get(field)
                         and (a.get(field) is None or b.get(field) is None)}
            if delta or condition:
                changes.append({'identity': key, 'delta': delta,
                                'unassessed_condition_change': condition})
        return changes

    g0, g1 = before['goal'], after['goal']
    if g0['research_ids'] != g1['research_ids']:
        raise ValueError('Research Content comparison changed the goal membership')
    stage_changes = comparable_changes(g0['registered_stages'], g1['registered_stages'],
        ('research_point_cost', 'execution_work'),
        lambda row: (row['research'], row['stage']))
    provider_changes = comparable_changes(before['provider_choices'], after['provider_choices'],
        ('rp_generation_per_day', 'research_execution_capacity_per_day',
         'operating_lower_bound_days_excluding_unassessed_dependencies',
         'construction_work', 'source_power_load_mw',
         'power_load_mw_days_during_nominal_operating_lower_bound'),
        lambda row: (row['provider'], row['source'], row['provider_level']))
    def resource_deltas(a, b):
        return {name: b.get(name, 0.0) - a.get(name, 0.0)
                for name in sorted(set(a) | set(b))
                if abs(b.get(name, 0.0) - a.get(name, 0.0)) > 1e-12}
    material = resource_deltas(g0['research_stage_direct_material_t'],
                               g1['research_stage_direct_material_t'])
    for record in provider_changes:
        key = record['identity']
        first = next((v for v in before['provider_choices'] if
                     (v['provider'], v['source'], v['provider_level']) == key), None)
        second = next((v for v in after['provider_choices'] if
                      (v['provider'], v['source'], v['provider_level']) == key), None)
        if first and second:
            record['construction_resource_delta_t'] = resource_deltas(
                first['construction_resource_t'], second['construction_resource_t'])
            record['maintenance_resource_rate_delta_t_per_day'] = resource_deltas(
                first['source_maintenance_resource_per_day_t'] or {},
                second['source_maintenance_resource_per_day_t'] or {})
    return {
        'model': 'research_goal_registered_definition_impact_v1',
        'research_ids': g0['research_ids'],
        'research_point_demand_delta': (g1['theory_research_point_demand']
                                        - g0['theory_research_point_demand']),
        'research_stage_material_delta_t': material,
        'stage_changes': stage_changes,
        'provider_changes': provider_changes,
        'baseline': summarize_research_goal(before) if summary else before,
        'edited_content': summarize_research_goal(after) if summary else after,
        'caveat': 'Stage and Provider options remain uncommitted; physical demand is booked only in selected economic compositions',
    }
