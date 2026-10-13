"""Read-only, cross-domain material-pressure view of the quantity ledger.

This is not a throughput solver. It connects the very same booked activity
inputs/outputs to upstream/downstream uses and typed registered definitions;
when a Resource is contested, *every* dependent activity is exposed, rather
than implicitly choosing an allocation or inventing production loss.
"""
from __future__ import annotations

from collections import defaultdict, deque

from space_idle.shared import DefinitionId


_DEMAND_DIMENSIONS = frozenset({
    "process_demand_t", "maintenance_demand_t", "construction_demand_t",
    "vehicle_build_demand_t", "fleet_turnaround_demand_t",
    "transport_service_demand_t", "research_material_demand_t",
    "science_material_demand_t", "founding_payload_demand_t",
    "passenger_provisions_demand_t", "life_support_demand_t", "shipped_t",
})
_SUPPLY_DIMENSIONS = frozenset({"production_t", "received_t"})


def registered_material_links(graph):
    """Typed graph links only; relation presence is not effective availability."""
    links = defaultdict(lambda: {"potential_producers": [], "registered_consumers": []})
    for relation in graph.relations:
        if relation.kind == "produces_resource" and relation.target.kind == "resource":
            resource, group, method = relation.target.id, "potential_producers", relation.source
        elif relation.kind in {"consumes_resource", "invests_resource"} and relation.source.kind == "resource":
            resource, group, method = relation.source.id, "registered_consumers", relation.target
        elif relation.kind == "extracts_resource" and relation.target.kind == "resource":
            resource, group, method = relation.target.id, "potential_producers", relation.source
        else:
            continue
        links[resource][group].append({
            "kind": method.kind, "definition": method.id,
            "quantity": relation.quantity, "unit": relation.unit,
            "time_basis": relation.time_basis, "condition": relation.condition,
            "provenance": relation.provenance,
        })
    return {key: {kind: sorted(rows, key=lambda row: (row["kind"], row["definition"], row["provenance"]))
                  for kind, rows in value.items()} for key, value in sorted(links.items())}


def _inter_node_capacity_bounds(phase):
    """Compare local Resource pressure to possible imports without routing cargo.

    Every candidate OD is independent. The upper bounds for distinct resources
    or distinct origin nodes MUST NOT be summed: both share the same Fleet,
    cargo handling and finite production conditions. These are not allocations.
    """
    duration = phase["days"]
    available_by_resource = defaultdict(list)
    missing_by_resource = defaultdict(list)
    for row in phase["resources"]:
        # No speculative arrivals or externally authored inflows can be
        # re-exported as a sourced surplus. Positive nominal production is
        # still only a conditional (not settled) Resource upper bound.
        local_balance = (row["notional_end_without_assumed_arrivals_t"]
                         - max(0.0, row["external_net_t"]))
        if local_balance > 1e-9:
            available_by_resource[row["resource"]].append((row["node"], local_balance))
        deficit = row["shortfall_without_assumed_arrivals_t"]
        if deficit > 1e-9:
            missing_by_resource[row["resource"]].append((row["node"], deficit))

    # A reverse leg consumes the same Fleet cycle; it is not an independent
    # second fleet. Other resources on the same OD share that capacity too.
    capacity = defaultdict(float)
    candidate_routes = set()
    blocked = defaultdict(set)
    for plan in phase["transport_services"]:
        legs = [(plan["origin"], plan["destination"], "forward_capacity_t_per_day")]
        if plan["reverse_path"]:
            legs.append((plan["destination"], plan["origin"], "reverse_capacity_t_per_day"))
        for origin, destination, metric in legs:
            key = (origin, destination)
            candidate_routes.add(key)
            if plan["blockers"] or plan[metric] is None:
                blocked[key].update(plan["blockers"] or ["route_capacity_unavailable"])
            else:
                capacity[key] += plan[metric]
    handling = {
        row["node"]: max(0.0, row["nominal_capacity_per_day"] - row["required_per_day"])
        for row in phase["service_constraints"] if row["service"] == "cargo_transfer"
    }
    candidates = []
    for resource in sorted(missing_by_resource):
        for destination, deficit in sorted(missing_by_resource[resource]):
            for origin, surplus in sorted(available_by_resource[resource]):
                if origin == destination:
                    continue
                key = origin, destination
                path_known = key in candidate_routes and not blocked[key]
                # Resource matching is possible even without a known path;
                # absence of transport or handling must not appear feasible.
                od_rate = capacity[key] if path_known else None
                handling_rate = (min(handling.get(origin, 0.0), handling.get(destination, 0.0))
                                 if path_known else None)
                per_resource_bound = min(surplus, deficit)
                # If several OD Fleet allocations share nodes, this remains
                # a per-candidate envelope, not an achievable simultaneous flow.
                combined_bound = (min(per_resource_bound, duration * od_rate,
                                      duration * handling_rate)
                                  if od_rate is not None else None)
                candidates.append({
                    "origin": origin, "destination": destination, "resource": resource,
                    "source_nominal_exportable_t": surplus,
                    "destination_unmet_without_arrivals_t": deficit,
                    "resource_overlap_upper_bound_t": per_resource_bound,
                    "od_capacity_t_per_day": od_rate,
                    "uncommitted_handling_t_per_day": handling_rate,
                    "transport_and_handling_upper_bound_t": combined_bound,
                    "blockers": sorted(blocked[key]) if key in candidate_routes else ["no_selected_transport_service"],
                    "status": "independent_conditional_bound_not_an_allocation",
                })
    return candidates


def trace_material_system(phase, registered_links):
    """Join booked quantities and typed relations by Resource and physical Node.

    Only *selected* Process outputs can propagate a possible bottleneck.
    Construction, Vehicle, Research, etc. remain terminal consumers. Shared
    Inventory, priority, parallel processing and cargo are not allocated.
    """
    activities = defaultdict(lambda: {"supply": [], "demand": []})
    process_outputs = defaultdict(list)
    process_inputs = defaultdict(list)
    for row in phase["resource_contributions"]:
        node, resource = row["node"], row["resource"]
        dimension, amount = row["dimension"], row["amount_t"]
        kind, definition = row["origin_kind"], row["origin_definition"]
        item = {"activity_kind": kind, "definition": definition,
                "dimension": dimension, "quantity_basis": row["quantity_basis"],
                "amount_t": abs(amount)}
        if dimension in _DEMAND_DIMENSIONS or (dimension == "external_net_t" and amount < 0):
            if amount > 0 or dimension == "external_net_t" and amount < 0:
                activities[(node, resource)]["demand"].append(item)
            if kind == "process" and dimension == "process_demand_t" and amount > 0:
                process_inputs[(node, definition)].append((resource, amount))
        elif dimension in _SUPPLY_DIMENSIONS or (dimension == "external_net_t" and amount > 0):
            if amount > 0:
                activities[(node, resource)]["supply"].append(item)
            if kind == "process" and dimension == "production_t" and amount > 0:
                process_outputs[(node, definition)].append((resource, amount))
    for value in activities.values():
        for key in ("supply", "demand"):
            value[key].sort(key=lambda v: (v["activity_kind"], v["definition"], v["dimension"]))
    # Process endpoints are actual selected activities, not every recipe in the
    # catalog; Graph-only links remain separate evidence below.
    consumers_by_input = defaultdict(set)
    for (node, process), inputs in process_inputs.items():
        for resource, _ in inputs:
            consumers_by_input[(node, resource)].add(process)

    rows = []
    exposures = []
    for resource_row in phase["resources"]:
        node, resource = resource_row["node"], resource_row["resource"]
        upstream = activities[(node, resource)]
        # Trace every reachable *active* Process output without claiming its
        # production was actually curtailed. Cycles terminate by Resource ID.
        seen_resources = {resource}
        queue = deque([resource])
        exposed_processes = set()
        reachable_resources = set()
        downstream_activities = {}
        while queue:
            input_resource = queue.popleft()
            for demand in activities[(node, input_resource)]["demand"]:
                key = demand["activity_kind"], demand["definition"]
                downstream_activities[key] = True
            for process in sorted(consumers_by_input[(node, input_resource)]):
                exposed_processes.add(process)
                for output, _ in process_outputs.get((node, process), []):
                    reachable_resources.add(output)
                    if output not in seen_resources:
                        seen_resources.add(output)
                        queue.append(output)
        deficit = resource_row["shortfall_without_assumed_arrivals_t"]
        recurring = resource_row["nominal_recurring_net_t_per_day"]
        # A negative phase closing inventory is an unsatisfied request; a
        # negative recurring rate is longer-run pressure even with large Stock.
        condition = ("nominal_shortfall_without_assumed_arrivals" if deficit > 1e-9 else
                     "negative_nominal_recurring_rate" if recurring < -1e-9 else
                     "no_quantified_shortfall_in_selected_conditions")
        row = {
            "node": node, "resource": resource,
            "opening_stock_t": resource_row["start_t"],
            "nominal_production_t": resource_row["production_t"],
            "nominal_closing_stock_t": resource_row["notional_end_t"],
            "shortfall_without_assumed_arrivals_t": deficit,
            "recurring_net_t_per_day": recurring,
            "activity_supplies": upstream["supply"],
            "activity_demands": upstream["demand"],
            "registered_potential_producers": [
                {"kind": entry["kind"], "definition": entry["definition"]}
                for entry in registered_links.get(resource, {}).get("potential_producers", [])],
            "condition": condition,
            "status": "notional_balance_not_finite_allocation",
        }
        rows.append(row)
        if condition != "no_quantified_shortfall_in_selected_conditions":
            exposures.append({
                "node": node, "resource": resource, "condition": condition,
                "shortfall_without_assumed_arrivals_t": deficit,
                "recurring_net_t_per_day": recurring,
                "direct_demand_activities": upstream["demand"],
                "active_downstream_processes": sorted(exposed_processes),
                "potentially_affected_outputs": sorted(reachable_resources),
                "reachable_downstream_activity_references": [
                    {"kind": kind, "definition": definition}
                    for kind, definition in sorted(downstream_activities)
                ],
                "status": "possible_exposure_not_allocated_lost_output",
            })
    return {
        "material_balances": rows,
        "pressure_exposures": exposures,
        "service_pressures": [{
            "node": row["node"], "service": row["service"],
            "required_per_day": row["required_per_day"],
            "nominal_capacity_per_day": row["nominal_capacity_per_day"],
            "nominal_gap_per_day": row["nominal_gap_per_day"],
            "competing_activities": [
                {"kind": item["origin_kind"], "definition": item["origin_definition"],
                 "demand_per_day": item["rate_per_day"]}
                for item in phase["service_contributions"]
                if item["node"] == row["node"] and item["service"] == row["service"]
                and item["role"] == "demand"
            ],
            "status": "nominal_shared_service_not_allocated",
        } for row in phase["service_constraints"] if row["nominal_gap_per_day"] > 1e-9],
        "inter_node_resource_options": _inter_node_capacity_bounds(phase),
        "unresolved_transport_od": [
            {"origin": row["origin"], "destination": row["destination"],
             "requested_t_per_day": row["demand_t_per_day"],
             "nominal_capacity_t_per_day": row["nominal_capacity_t_per_day"],
             "status": row["status"], "blockers": row["blockers"]}
            for row in phase["od_transport_constraints"]
            if row["status"] != "conditional_nominal_capacity"
        ],
        "status": "resource_service_coupling_not_simulated_or_allocated",
    }


def network_overview(network):
    """Use bounded identities in the overview; keep all quantities in detail."""
    return {
        "material_pressure_count": len(network["pressure_exposures"]),
        "pressure_paths": [{
            "node": row["node"], "resource": row["resource"],
            "condition": row["condition"],
            "direct_activity_kinds": sorted({v["activity_kind"] for v in row["direct_demand_activities"]}),
            "active_downstream_process_count": len(row["active_downstream_processes"]),
            "reachable_downstream_activity_kinds": sorted({v["kind"] for v in row["reachable_downstream_activity_references"]}),
            "potentially_affected_outputs": row["potentially_affected_outputs"],
        } for row in network["pressure_exposures"]],
        "service_pressure_count": len(network["service_pressures"]),
        "inter_node_resource_options_count": len(network["inter_node_resource_options"]),
        "inter_node_routes_with_selected_capacity": sum(
            option["od_capacity_t_per_day"] is not None
            for option in network["inter_node_resource_options"]),
        "unresolved_od_count": len(network["unresolved_transport_od"]),
        "detail_section": "system_network",
        "status": network["status"],
    }


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
            equipment_rows.append({
                'facility': str(facility.id),
                'required_full_duty_facility_days': runs / facility.process_throughput_per_day,
                'capital_resource_per_facility_t': invested,
                'construction_work_per_facility': work,
                'required_technologies': technologies,
                'status': 'eligible_facility_day_option_not_allocated_or_built',
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
