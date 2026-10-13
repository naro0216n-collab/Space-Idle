"""Read-only, cross-domain material-pressure view of the quantity ledger.

This is not a throughput solver. It connects the very same booked activity
inputs/outputs to upstream/downstream uses and typed registered definitions;
when a Resource is contested, *every* dependent activity is exposed, rather
than implicitly choosing an allocation or inventing production loss.
"""
from __future__ import annotations

from collections import defaultdict, deque


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


def registered_activity_coefficients(graph):
    """Source-preserving coefficient matrix for the entire registered activity catalog.

    Raw typed coefficients are intentionally not multiplied by imaginary
    Facilities, completed Projects or research decisions. Time bases may not
    be added across rows. Existing Definition Graph owns every relation.
    """
    methods = defaultdict(lambda: {"resource_inputs": [], "resource_outputs": [],
                                   "other_typed_coefficients": []})
    for relation in graph.relations:
        if relation.quantity is None:
            continue
        if relation.kind in {"consumes_resource", "invests_resource"} and relation.source.kind == "resource":
            method, group, counterpart = relation.target, "resource_inputs", relation.source
        elif relation.kind in {"produces_resource", "extracts_resource"} and relation.target.kind == "resource":
            method, group, counterpart = relation.source, "resource_outputs", relation.target
        elif relation.kind == "research_point_cost" and relation.target.kind == "research_stage":
            method, group, counterpart = relation.target, "other_typed_coefficients", relation.source
        elif relation.kind == "research_work" and relation.source.kind == "research_stage":
            method, group, counterpart = relation.source, "other_typed_coefficients", relation.target
        elif relation.source.kind in {"resource", "capacity_pool", "research_point_pool", "service_capacity"}:
            method, group, counterpart = relation.target, "other_typed_coefficients", relation.source
        else:
            method, group, counterpart = relation.source, "other_typed_coefficients", relation.target
        if method.kind in {"resource", "capacity_pool", "research_point_pool", "service_capacity",
                           "site_condition", "opportunity_factor", "body", "surface_cell",
                           "spatial_node", "research_point_pool"}:
            continue
        methods[(method.kind, method.id)][group].append({
            "relation": relation.kind, "other_kind": counterpart.kind,
            "other_id": counterpart.id, "quantity": relation.quantity,
            "unit": relation.unit, "time_basis": relation.time_basis,
            "condition": relation.condition, "provenance": relation.provenance,
        })
    return [
        {"method_kind": kind, "method_definition": definition,
         **{category: sorted(rows, key=lambda r: (r["relation"], r["other_kind"],
                                                   r["other_id"], r["provenance"]))
            for category, rows in categories.items()},
         "status": "registered_coefficient_not_scheduled_or_allocated"}
        for (kind, definition), categories in sorted(methods.items())
    ]
