"""Definition-derived upstream Resource constraints for selected activities.

This module does not infer transport origins or invent delivered Stock.
Registered Processes and selected upstream choices remain conditional and
share the same capacities as the primary balance projection.
"""
from __future__ import annotations

from collections import defaultdict

from space_idle.shared import DefinitionId


# Shared Definition-derived upstream accounting for all activity origins.
def aggregate_material(items):
    result = defaultdict(float)
    for name, value in items:
        result[str(name)] += value
    return {name: value for name, value in sorted(result.items()) if abs(value) > 1e-12}


def source_investment(sim, source_kind, source_id, level=1):
    if source_kind == 'facility':
        recipe = sim.projects.recipes.get(DefinitionId(source_id))
        components = list(recipe.resources) if recipe else []
        work = recipe.construction_work if recipe else None
        technologies = set(recipe.prerequisite_technologies) if recipe else set()
        for target_level in range(2, level + 1):
            upgrade = sim.projects.upgrade_recipes.get((DefinitionId(source_id), target_level))
            if upgrade is None:
                # A provider can advertise a Level without a physical way to
                # acquire it. Do not treat Level n as a free initial placement.
                return {}, None, sorted(str(t) for t in technologies), 'missing_registered_upgrade_recipe'
            components.extend(upgrade.resources)
            work = work + upgrade.construction_work if work is not None else None
            technologies.update(upgrade.prerequisite_technologies)
        return aggregate_material((r.resource_id, r.amount_t) for r in components), work, (
            sorted(str(v) for v in technologies)), (
            'construction_plus_upgrade_recipes' if level > 1 else
            'construction_recipe' if recipe else 'no_registered_construction_recipe')
    vehicle = next(v for v in sim.transport.vehicle_definitions() if str(v.id) == source_id)
    return dict((str(k), v) for k, v in vehicle.production.resources), None, (
        sorted(str(v) for v in vehicle.production.prerequisite_technologies)), 'vehicle_production_recipe'


def producer_catalog(sim):
    """Resolve every registered Process, Extraction and compatible equipment generically."""
    facilities = sorted(sim.facilities.definitions.values(), key=lambda f: str(f.id))
    production = defaultdict(list)
    for process in sim.industry.processes.values():
        equipment = [f for f in facilities if process.required_capabilities <= {c.id for c in f.capability_supplies}
                     and f.process_throughput_per_day > 0]
        for resource, amount in process.outputs_per_day.items():
            if amount > 0:
                production[str(resource)].append((process, amount, equipment))
    extraction = defaultdict(list)
    if sim.extraction is not None:
        for method in sim.extraction.specs.values():
            extraction[str(method.output_resource_id)].append({
                'method': str(method.id), 'resource_opportunity': str(method.resource_id),
                'required_capabilities': sorted(method.required_capabilities),
                'minimum_knowledge_level': (int(method.minimum_knowledge_level)
                                            if method.minimum_knowledge_level is not None else None),
                'status': 'site_knowledge_geology_and_shared_opportunity_required',
            })
    return production, extraction


def shared_upstream_capacity_bounds(selected_processes, idle_facility_rates, phase_days):
    """Necessary cumulative throughput bounds for analyst-selected upstream work.

    All processes within a compatible-Facility subset compete for the *same*
    unused process-run capacity. A subset bound is necessary, never an
    assignment or a promise of future production. Its one rate includes each
    installed Facility definition only once. Missing run quantities (cycles)
    cannot be silently interpreted as zero work.
    """
    tasks = []
    unresolved = []
    for entry in selected_processes:
        amount = entry.get("process_run_days_at_unit_throughput")
        if amount is None:
            unresolved.append(entry["process"])
            continue
        compatible = frozenset(entry["compatible_installed_facilities"])
        tasks.append((entry["process"], compatible, amount))
    groups = []
    for candidate_pool in sorted({compatible for _, compatible, _ in tasks},
                                 key=lambda pool: (len(pool), tuple(sorted(pool)))):
        affected = [(process, required) for process, compatible, required in tasks
                    if compatible <= candidate_pool]
        total = sum(amount for _, amount in affected)
        if total <= 1e-12:
            continue
        rate = sum(idle_facility_rates[facility] for facility in candidate_pool)
        groups.append({
            "compatible_facilities": sorted(candidate_pool),
            "competing_processes": sorted(process for process, _ in affected),
            "required_process_runs": total,
            "available_process_runs_per_day": rate,
            "conditional_shared_capacity_lower_bound_days": (total / rate if rate > 0 else None),
            "nominal_process_run_gap_in_phase": max(0.0, total - rate * phase_days),
            "status": "necessary_shared_idle_throughput_bound_not_an_allocation",
        })
    return {"constraints": groups, "unquantified_processes": sorted(unresolved)}

def conditional_material_paths(resources, sim, production, extraction, selected_methods):
    """Build a selected-input chain and evidence for every unchosen alternative.

    Quantities in each option are defined by a registered Process output ratio.
    No alternative quantities are added. Selected paths are recursively expanded
    only when the selected production graph is acyclic. Coproduction/shared
    Facility scheduling and eligible extraction remain separate constraints.
    """
    if not isinstance(selected_methods, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                     for k, v in selected_methods.items()):
        raise ValueError('production_methods must map Resource IDs to Process IDs')
    known_methods = {str(p.id) for p in sim.industry.processes.values()}
    for resource, method in selected_methods.items():
        if method not in known_methods or method not in {str(p.id) for p, _, _ in production.get(resource, ())}:
            raise ValueError(f'Process {method} does not produce {resource}')
    required = defaultdict(float, resources)
    # One selected Process per produced Resource. If a Process is selected for
    # two of its outputs, both output demands must share its production runs;
    # do not treat that as two independent factories.
    used_processes = defaultdict(list)
    for resource, method in selected_methods.items():
        used_processes[method].append(resource)
    graph = defaultdict(set)
    for resource, method in selected_methods.items():
        process = sim.industry.processes[DefinitionId(method)]
        graph[resource].update(str(k) for k, v in process.inputs_per_day.items() if v > 0)
    visit, ordered, active, cycles = {}, [], [], []
    def walk(resource):
        if visit.get(resource) == 1:
            cycles.append(active[active.index(resource):] + [resource])
            return
        if visit.get(resource) == 2:
            return
        visit[resource] = 1
        active.append(resource)
        for dependency in sorted(graph[resource]):
            walk(dependency)
        active.pop()
        visit[resource] = 2
        ordered.append(resource)
    for resource in sorted(set(resources) | set(selected_methods)):
        walk(resource)
    if cycles:
        # Keep the *one* physical run variable per registered Process, even if
        # multiple selected Resource outputs require it. Do not recursively
        # invent gross tonnage or declare a cycle infeasible merely because a
        # sequential expansion cannot solve simultaneous consumption.
        selected_process_ids = sorted(set(selected_methods.values()))
        processes = [sim.industry.processes[DefinitionId(key)] for key in selected_process_ids]
        coefficient_resources = sorted(set(resources) |
            {str(k) for process in processes
             for k in (*process.inputs_per_day, *process.outputs_per_day)})
        equations = []
        for resource in coefficient_resources:
            produces = {str(process.id): float(process.outputs_per_day.get(DefinitionId(resource), 0.0))
                        for process in processes if process.outputs_per_day.get(DefinitionId(resource), 0.0) > 0}
            consumes = {str(process.id): float(process.inputs_per_day.get(DefinitionId(resource), 0.0))
                        for process in processes if process.inputs_per_day.get(DefinitionId(resource), 0.0) > 0}
            equations.append({
                'resource': resource, 'direct_requirement_t': float(resources.get(resource, 0.0)),
                'selected_process_output_t_per_run': produces,
                'selected_process_input_t_per_run': consumes,
                'relation': 'sum_selected_output_minus_input_plus_external_supply >= direct_requirement',
                'external_supply': 'requires_explicit_stock_extraction_process_or_OD_choice',
            })
        alternatives = []
        for resource, quantity in sorted(resources.items()):
            alternatives.append({'resource': resource, 'gross_requirement_t': quantity,
                'selected_process': selected_methods.get(resource),
                'registered_extraction_options': sorted(extraction.get(resource, ()), key=lambda r: r['method']),
                'status': 'cyclic_chain_requires_simultaneous_nonnegative_run_and_external_supply_solution'})
        return {
            'gross_resource_requirements_t': aggregate_material(resources.items()),
            'material_bill_complete': False,
            'selected_processes': [{'process': str(process.id),
                'input_coefficients_t_per_run': aggregate_material(process.inputs_per_day.items()),
                'output_coefficients_t_per_run': aggregate_material(process.outputs_per_day.items()),
                'status': 'symbolic_shared_process_run_not_a_scheduled_or_available_capacity'}
                for process in processes],
            'resource_supply_options': alternatives,
            'cyclic_selected_resource_paths': cycles,
            'conditional_simultaneous_resource_constraints': equations,
            'unresolved_constraints': [
                'nonnegative_shared_process_runs_and_external_supply_have_not_been_selected',
                'compatible_installed_facility_throughput_and_technology_not_allocated',
                'power_resource_maintenance_and_inter_node_transport_not_allocated'],
            'non_additivity': 'One selected Process has one shared run count for all co-products',
            'status': 'cyclic_selected_process_system_not_yet_quantitatively_closed',
        }
    # Process outputs can form a joint product. Resolve at most once, after
    # all its output Resource needs are known (within the chosen acyclic graph).
    resolved = set()
    processes = []
    for resource in reversed(ordered):
        method = selected_methods.get(resource)
        if method is None or method in resolved:
            continue
        process = sim.industry.processes[DefinitionId(method)]
        chosen_outputs = used_processes[method]
        # For independent selected outputs the maximum run amount covers both
        # as a *conditional* envelope, without multiplying shared throughput.
        runs = max((required[output] / process.outputs_per_day[DefinitionId(output)]
                    for output in chosen_outputs if required[output] > 0), default=0)
        resolved.add(method)
        inputs = aggregate_material((k, amount * runs) for k, amount in process.inputs_per_day.items())
        outputs = aggregate_material((k, amount * runs) for k, amount in process.outputs_per_day.items())
        for k, amount in inputs.items():
            required[k] += amount
        equipment_rows = []
        for facility in sorted((f for f in sim.facilities.definitions.values()
                                if process.required_capabilities <= {c.id for c in f.capability_supplies}
                                and f.process_throughput_per_day > 0), key=lambda f: str(f.id)):
            invested, work, technologies, source = source_investment(sim, 'facility', str(facility.id))
            # Quantity of processing work is in full-utilization Facility-days;
            # daily simultaneous capacity is not implied.
            # Equipment alternatives must expose their actual acquisition and
            # recurring burdens, not merely faster output. The Facility Domain
            # owns Maintenance scaling; Power supplies the installed nameplate.
            maintenance = sim.facilities.maintenance_requirements_for_investment(
                facility.id, {DefinitionId(resource): quantity
                              for resource, quantity in invested.items()}) if work is not None else {}
            power = sim.power.specs.get(facility.id)
            equipment_rows.append({
                'facility': str(facility.id),
                'required_full_duty_facility_days': runs / facility.process_throughput_per_day,
                'capital_resource_per_facility_t': invested,
                'construction_work_per_facility': work,
                'maintenance_resource_per_day_for_one_acquired_facility_t':
                    aggregate_material(maintenance.items()),
                'power_rated_active_load_mw_per_facility': power.load_mw if power else None,
                'power_rated_standby_load_mw_per_facility': power.standby_load_mw if power else None,
                'required_technologies': technologies,
                'status': 'conditional_equipment_option_not_selected_or_acquired',
            })
        processes.append({
            'process': method, 'selected_output_demands_t': {k: required[k] for k in sorted(chosen_outputs)},
            'process_run_days_at_unit_throughput': runs,
            'input_resource_t': inputs, 'co_products_t': outputs,
            'equipment_options': equipment_rows,
            'required_technologies': sorted(str(v) for v in process.prerequisite_technologies),
            'status': 'conditional_selected_process_not_commissioned_or_allocated',
        })
    alternatives = []
    for resource, quantity in sorted(required.items()):
        if quantity <= 1e-12:
            continue
        rows = []
        for process, amount, equipment in sorted(production.get(resource, ()), key=lambda row: str(row[0].id)):
            runs = quantity / amount
            rows.append({
                'process': str(process.id), 'output_t_per_process_day': amount,
                'required_process_days_at_unit_throughput': runs,
                'inputs_for_resource_amount_t': aggregate_material((k, v * runs)
                                                           for k, v in process.inputs_per_day.items()),
                'compatible_facilities': [str(f.id) for f in equipment],
                'technology_prerequisites': sorted(str(v) for v in process.prerequisite_technologies),
            })
        alternatives.append({
            'resource': resource, 'gross_requirement_t': quantity,
            'selected_process': selected_methods.get(resource),
            'registered_process_options': rows,
            'registered_extraction_options': sorted(extraction.get(resource, ()), key=lambda r: r['method']),
            'status': ('selected_process_input_expanded_conditionally' if resource in selected_methods else
                       'supply_route_unselected_no_upstream_quantity_claim'),
        })
    return {'gross_resource_requirements_t': aggregate_material(required.items()),
            'material_bill_complete': True,
            'selected_processes': processes, 'resource_supply_options': alternatives,
            'non_additivity': 'Process alternatives, coproduction and equipment choices are not additive',
            'status': 'conditional_definition_material_bill_not_allocated_or_delivered'}
