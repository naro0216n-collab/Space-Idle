"""Cross-domain, unit-aware balance quantities for authored development scales.

Definition coefficients are projected by GameApplication; analysis only sums
stated quantities. Prospective nominal values never stand in for actual
Allocation, Technology eligibility, transport arrival, or completed builds.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite


def _nonnegative(value, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{description} must be finite and nonnegative")
    return float(value)


def _count(value, description: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{description} must be a nonnegative integer")
    return value


def _positive_days(value):
    if type(value) is not int or value <= 0:
        raise ValueError("period_days must be a positive integer")
    return value


def _known(mapping, key, kind):
    if key not in mapping:
        raise ValueError(f"unknown {kind}: {key}")
    return mapping[key]


def overview(defs: dict) -> dict:
    research = defs["research"]
    stages = defaultdict(lambda: {"count": 0, "theory_rp": 0.0, "prototype_work": 0.0,
                                  "demonstration_work": 0.0, "prototype_resources_t": defaultdict(float),
                                  "categories": defaultdict(int), "series": defaultdict(int)})
    for row in research.values():
        bucket = stages[str(row["stage"] if row["stage"] is not None else "unclassified")]
        bucket["count"] += 1
        bucket["categories"][row["category"] or "unclassified"] += 1
        bucket["series"][row["series"] or "unclassified"] += 1
        for stage in row["stages"]:
            if stage["kind"] == "theory": bucket["theory_rp"] += stage["rp"]
            if stage["kind"] == "prototype":
                bucket["prototype_work"] += stage["work"]
                for k, v in stage["resources_t"].items(): bucket["prototype_resources_t"][k] += v
            if stage["kind"] == "demonstration": bucket["demonstration_work"] += stage["work"]
    for row in stages.values():
        for k in ("categories", "series", "prototype_resources_t"):
            row[k] = dict(sorted(row[k].items()))
    resource_links = {}
    for resource in sorted(defs["resources"]):
        resource_links[resource] = {
            "input_processes": sorted(p for p, row in defs["processes"].items() if resource in row["inputs_per_unit_t"]),
            "output_processes": sorted(p for p, row in defs["processes"].items() if resource in row["outputs_per_unit_t"]),
            "facility_builds": sorted(f for f, row in defs["facilities"].items() if resource in (row["construction_resources_t"] or {})),
            "vehicle_builds": sorted(v for v, row in defs["vehicles"].items() if resource in row["production_resources_t"]),
            "research_prototypes": sorted(r for r, row in research.items() if any(resource in s.get("resources_t", {}) for s in row["stages"])),
        }
    return {
        "kind": "balance_overview", "identity": defs["identity"],
        "counts": {key: len(defs[key]) for key in ("research", "facilities", "vehicles", "processes", "extraction", "resources")},
        "research_by_stage": dict(sorted(stages.items(), key=lambda x: (not x[0].isdigit(), int(x[0]) if x[0].isdigit() else x[0]))),
        "facility_units": defs["facilities"], "vehicle_units": defs["vehicles"],
        "process_units": defs["processes"], "research_units": research, "extraction_units": defs["extraction"],
        "resource_links": resource_links, "world": defs["world"],
        "interpretation": "Definition-only structure. Registered Research totals are not mandatory completion costs; facility unit rates are not world-wide supply.",
    }


def _research_selection(defs: dict, ids: list[str]):
    research = defs["research"]
    selected = set()
    def include(key):
        item = _known(research, key, "research")
        if key in selected: return
        selected.add(key)
        for prior in item["prerequisites"]: include(prior)
    for rid in ids: include(rid)
    return sorted(selected)


def _add(ledger, node, resource, purpose, quantity, measure, source):
    if abs(quantity) <= 1e-12: return
    ledger[(node, resource, purpose, measure, source)] += quantity


def _rows(ledger):
    return [dict(zip(("node", "resource", "purpose", "measure", "source"), key), quantity=quantity)
            for key, quantity in sorted(ledger.items())]


def _summarize(rows):
    buckets = defaultdict(float)
    for row in rows:
        buckets[(row["node"], row["resource"], row["measure"])] += row["quantity"]
    return [{"node": n, "resource": r, "measure": m, "quantity": value}
            for (n, r, m), value in sorted(buckets.items())]


def evaluate(defs: dict, assessment: dict, *, current: dict | None = None, transport_preview=None, power_site=None) -> dict:
    """Prospective design ledger; no construction, allocation, or future Stock claims."""
    if not isinstance(assessment, dict) or set(assessment) - {"format", "periods", "prospective_locations"}:
        raise ValueError("unsupported assessment fields")
    if assessment.get("format") != "space-idle.balance-assessment.v1":
        raise ValueError("unsupported balance assessment format")
    periods = assessment.get("periods")
    if not isinstance(periods, list) or not periods:
        raise ValueError("assessment requires at least one authored period")
    established_nodes = {r["id"] for r in defs["world"]["nodes"]}
    node_ids = set(established_nodes)
    body_ids = {r["id"] for r in defs["world"]["bodies"]}
    hypothetical_nodes = {}
    for loc in assessment.get("prospective_locations", []):
        if not isinstance(loc, dict) or set(loc) != {"id", "body_id"}:
            raise ValueError("prospective_locations require id and body_id")
        node_id, body_id = loc["id"], loc["body_id"]
        if (not isinstance(node_id, str) or not node_id or node_id in node_ids
                or not isinstance(body_id, str) or body_id not in body_ids):
            raise ValueError(f"invalid prospective location: {loc}")
        hypothetical_nodes[node_id] = body_id
        node_ids.add(node_id)
    known = {kind: defs[kind] for kind in ("facilities", "vehicles", "processes", "research", "resources")}
    initial_facilities = {(r["node"], r["facility"]): r["count"] for r in defs["owned"]["facilities"]}
    initial_fleet = {(r["node"], r["vehicle"]): r["count"] for r in defs["owned"]["fleet"]}
    running_facilities = dict(initial_facilities)
    running_fleet = dict(initial_fleet)
    running_population = {row["node"]: row["people"] for row in defs["owned"]["population"]}
    running_life_support = {}
    original_installed = defs["owned"]["installed_facilities"]
    existing_maintenance = defaultdict(float)
    for item in defs["owned"]["actual_maintenance"]:
        existing_maintenance[(item["node"], item["facility"], item["resource"])] += item["quantity"]
    output = []
    names = set()
    for index, period in enumerate(periods):
        if not isinstance(period, dict) or set(period) - {"name", "period_days", "facilities", "vehicles", "research_ids", "transport_demands", "population"}:
            raise ValueError(f"period {index}: unsupported fields")
        name = period.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("period names must be unique nonempty strings")
        names.add(name)
        days = _positive_days(period.get("period_days"))
        investment = defaultdict(float)
        work = defaultdict(float)
        period_facility = dict(running_facilities)
        period_fleet = dict(running_fleet)
        period_population = dict(running_population)
        period_life_support = dict(running_life_support)
        selected_process = {}
        selected_extraction = {}
        utilization = {}
        caveats = ["Nominal constructed design: no assets are granted and no time progress is simulated."]
        if hypothetical_nodes:
            caveats.append("Prospective location labels represent design-only sites; Founding eligibility, environment, completed construction, and Cargo arrival are not established")
        for row in period.get("facilities", []):
            if not isinstance(row, dict) or set(row) - {"node", "facility", "count", "process", "extraction_method", "utilization"}:
                raise ValueError("invalid facility target")
            node, fid = row["node"], row["facility"]
            if node not in node_ids: raise ValueError(f"unknown node: {node}")
            definition = _known(known["facilities"], fid, "facility")
            count = _count(row["count"], "facility count")
            key = (node, fid)
            if key in selected_process: raise ValueError(f"duplicate facility target: {key}")
            period_facility[key] = count
            rate = _nonnegative(row.get("utilization", 1.0), "utilization")
            if rate > 1: raise ValueError("utilization cannot exceed one")
            utilization[key] = rate
            pid = row.get("process")
            if pid is not None:
                process = _known(known["processes"], pid, "process")
                if not set(process["required_capabilities"]) <= set(definition["capabilities"]):
                    raise ValueError(f"incompatible facility/process: {fid}/{pid}")
            selected_process[key] = pid
            method_id = row.get("extraction_method")
            if method_id is not None:
                method = _known(defs["extraction"], method_id, "extraction method")
                if fid not in method["provider_facilities"]:
                    raise ValueError(f"incompatible facility/extraction method: {fid}/{method_id}")
            selected_extraction[key] = method_id
        for row in period.get("vehicles", []):
            if not isinstance(row, dict) or set(row) != {"node", "vehicle", "count"}:
                raise ValueError("invalid vehicle target")
            node, vid = row["node"], row["vehicle"]
            if node not in node_ids: raise ValueError(f"unknown node: {node}")
            _known(known["vehicles"], vid, "vehicle")
            key = (node, vid)
            if key in investment: raise ValueError("duplicate vehicle target")
            new_count = _count(row["count"], "vehicle count")
            period_fleet[key] = new_count
            investment[key] += 0  # also records an explicit zero target
        capital = defaultdict(float)
        daily = defaultdict(float)
        finite = defaultdict(float)
        research_capacity = defaultdict(float)
        acquisition = []
        for (node, fid), count in sorted(period_facility.items()):
            definition = known["facilities"][fid]
            previous = running_facilities.get((node, fid), 0)
            added = max(0, count - previous)
            if count < previous: caveats.append(f"Facility reduction {node}/{fid}: no decommission refund or dismantling modeled")
            if added:
                acquisition.append({"node": node, "kind": "facility", "id": fid, "units": added})
                cost = definition["construction_resources_t"]
                if cost is None:
                    caveats.append(f"No construction Recipe for {fid}; acquisition demand unknown")
                else:
                    for resource, amount in cost.items():
                        _add(capital, node, resource, "facility_build", amount * added, "investment_t", fid)
                    if definition["self_deploying"]:
                        caveats.append(f"Self-deploying Facility {fid}: Resource investment is counted, local construction work is not")
                    else:
                        work[(node, "construction_work")] += (definition["construction_work"] or 0) * added
            # Installed and proposed asset nominal daily inputs are distinct from
            # actual allocations and do not create new in-game resources.
            rate = utilization.get((node, fid), 1.0)
            for resource, amount in definition["operating_per_day_t"].items():
                _add(daily, node, resource, "facility_operation", amount * count * rate, "demand_t_per_day", fid)
            for resource, amount in (definition["maintenance_per_day_t"] or {}).items():
                existing = min(count, running_facilities.get((node, fid), 0))
                # At the first authored period the exact installed investment is known.
                # For later periods, added units use the same canonical unit recipe.
                actual = existing_maintenance.get((node, fid, resource), 0.0) if index == 0 and existing == running_facilities.get((node, fid), 0) else amount * existing
                _add(daily, node, resource, "facility_maintenance", actual + amount * max(0, count-existing), "demand_t_per_day", fid)
            site_power = power_site(node, fid) if power_site and node in established_nodes else None
            if site_power is not None and site_power["status"] == "nominal_site_coefficient":
                finite[(node, "power", "nominal_load_mw", fid)] += site_power["load_mw"] * count * rate
                finite[(node, "power", "nominal_generation_mw", fid)] += site_power["generation_mw"] * count
            elif count:
                caveats.append(f"Power for {node}/{fid}: site coefficient unknown; no generation assumed")
            if definition["construction_work_per_day"] and count:
                finite[(node, "construction_work", "nominal_supply_per_day", fid)] += definition["construction_work_per_day"] * count * rate
            if definition["extraction_capacity_t_per_day"] and count:
                method_id = selected_extraction.get((node, fid))
                method = defs["extraction"].get(method_id) if method_id else None
                finite[(node, "extraction", "installed_nominal_capacity_t_per_day", fid)] += definition["extraction_capacity_t_per_day"] * count
                if method:
                    finite[(node, f"extraction_output:{method['output_resource_id']}", "installed_upper_bound_t_per_day", method_id)] += definition["extraction_capacity_t_per_day"] * count * rate
                caveats.append(f"Extraction at {node}/{fid}: geology, resource opportunity, knowledge and allocation limit actual output")
            for service, amount in definition["services_per_day"].items():
                finite[(node, service, "nominal_supply_per_day", fid)] += amount * count
            finite[(node, "housing", "nominal_supply", fid)] += definition["housing_capacity"] * count
            if definition["life_support_person_days_per_day"] is not None:
                finite[(node, "life_support", "nominal_supply_per_day", fid)] += definition["life_support_person_days_per_day"] * count
            p = definition["research_provider"]
            if p is not None:
                for field in ("generation_points_per_day", "research_execution_per_day", "storage_capacity_points"):
                    research_capacity[(node, field, fid)] += p[field] * count
            pid = selected_process.get((node, fid))
            if pid is None:
                matches = [r["process"] for r in original_installed
                           if r["node"] == node and r["facility"] == fid and r["process"]]
                if matches: caveats.append(f"Process mix for {node}/{fid} not specified; existing process selections are not assumed uniform")
            else:
                process = known["processes"][pid]
                throughput = definition["process_throughput_per_day"] * count * rate
                for resource, amount in process["inputs_per_unit_t"].items():
                    _add(daily, node, resource, "process_input", amount * throughput, "demand_t_per_day", pid)
                for resource, amount in process["outputs_per_unit_t"].items():
                    _add(daily, node, resource, "process_output", amount * throughput, "nominal_supply_t_per_day", pid)
        for (node, vid), count in sorted(period_fleet.items()):
            previous = running_fleet.get((node, vid), 0)
            added = max(0, count - previous)
            if count < previous: caveats.append(f"Fleet reduction {node}/{vid}: retirement effects unknown")
            if added:
                acquisition.append({"node": node, "kind": "vehicle", "id": vid, "units": added})
                for resource, amount in known["vehicles"][vid]["production_resources_t"].items():
                    _add(capital, node, resource, "vehicle_production", amount * added, "investment_t", vid)
                svc = known["vehicles"][vid]["production_service_type"]
                if svc: work[(node, f"vehicle_production:{svc}")] += known["vehicles"][vid]["production_days"] * added
            for provider in known["vehicles"][vid]["research_providers"]:
                for field in ("generation_points_per_day", "research_execution_per_day", "storage_capacity_points"):
                    research_capacity[(node, field, vid)] += provider[field] * count
        chosen_ids = period.get("research_ids", [])
        if not isinstance(chosen_ids, list) or any(not isinstance(k, str) for k in chosen_ids):
            raise ValueError("research_ids must be a list of IDs")
        closure = _research_selection(defs, chosen_ids)
        rp = 0.0
        for rid in closure:
            for stage in known["research"][rid]["stages"]:
                if stage["kind"] == "theory": rp += stage["rp"]
                if stage["kind"] == "prototype":
                    work[("unallocated", "research_prototype_work")] += stage["work"]
                    for resource, amount in stage["resources_t"].items():
                        _add(capital, "unallocated", resource, "research_prototype", amount, "investment_t", rid)
                if stage["kind"] == "demonstration":
                    work[("unallocated", "research_demonstration_work")] += stage["work"]
                if stage["kind"] == "operational_experience" and stage.get("experience"):
                    caveats.append(f"Operational Experience for {rid} requires activities; no duration is inferred")
        for item in period.get("population", []):
            if not isinstance(item, dict) or set(item) - {"node", "people", "life_support_facility"} or not {"node", "people"} <= set(item):
                raise ValueError("invalid population target")
            if item["node"] not in node_ids: raise ValueError("unknown population node")
            period_population[item["node"]] = _count(item["people"], "population")
            if "life_support_facility" in item:
                period_life_support[item["node"]] = item["life_support_facility"]
        for node, count in sorted(period_population.items()):
            finite[(node, "housing", "requested", "population")] += count
            finite[(node, "life_support", "requested_per_day", "population")] += count
            life_support_id = period_life_support.get(node)
            if life_support_id is not None:
                facility = _known(known["facilities"], life_support_id, "life_support_facility")
                if facility["life_support_person_days_per_day"] is None:
                    raise ValueError(f"facility has no life support: {life_support_id}")
                for resource, per_person in facility["life_support_resources_per_person_day_t"].items():
                    _add(daily, node, resource, "population_life_support", per_person * count,
                         "demand_t_per_day", life_support_id)
            else:
                if count: caveats.append(f"Population support Resource mix for {node} unknown without a chosen provider")
            if count: caveats.append(f"Population at {node}: provider allocation, arrival and housing eligibility not established")
        transport = []
        for item in period.get("transport_demands", []):
            if not isinstance(item, dict) or set(item) - {"source", "destination", "resource", "tonnes_per_day", "vehicle"}:
                raise ValueError("invalid transport demand")
            for field in ("source", "destination"):
                if item[field] not in node_ids: raise ValueError(f"unknown {field}: {item[field]}")
            _known(known["resources"], item["resource"], "resource")
            amount = _nonnegative(item["tonnes_per_day"], "transport demand")
            row = {**item, "capacity_status": "not_evaluated", "preview": None}
            if item.get("vehicle"):
                _known(known["vehicles"], item["vehicle"], "vehicle")
                if transport_preview is not None and item["source"] in established_nodes and item["destination"] in established_nodes:
                    try:
                        preview = transport_preview(item["vehicle"], item["source"], item["destination"], amount)
                        row["preview"] = preview
                        row["capacity_status"] = "canonical_preview_not_guaranteed"
                    except (ValueError, RuntimeError, KeyError) as error:
                        row["capacity_status"] = "unresolved"
                        row["reason"] = str(error)
            transport.append(row)
        time_bounds = []
        for (node, kind), amount in sorted(work.items()):
            if kind == "construction_work":
                available = sum(v for (n, s, m, _), v in finite.items()
                                if n == node and s == "construction_work" and m == "nominal_supply_per_day")
                time_bounds.append({"node": node, "work": amount, "nominal_work_per_day": available,
                                    "minimum_days_if_fully_allocated": None if available <= 0 else amount / available,
                                    "status": "nominal_lower_bound_not_schedule"})
        investments = _rows(capital)
        operation = _rows(daily)
        # Only independently comparable named measures are combined. Do not
        # count intermediate process outputs as an external Resource source.
        supply = defaultdict(float); demand = defaultdict(float)
        for row in operation:
            key = (row["node"], row["resource"])
            if row["measure"] == "nominal_supply_t_per_day": supply[key] += row["quantity"]
            else: demand[key] += row["quantity"]
        balances = [{"node": node, "resource": resource,
                     "nominal_process_supply_t_per_day": supply.get((node, resource), 0.0),
                     "stated_operation_demand_t_per_day": demand.get((node, resource), 0.0),
                     "local_nominal_gap_t_per_day": demand.get((node, resource), 0.0)-supply.get((node, resource), 0.0),
                     "note": "Partial nominal process balance, not net actual flow or transport-feasible supply"}
                    for node, resource in sorted(set(supply) | set(demand))]
        # Joint capital + recurring demand is the primary quantity question.
        # Nominal local Process output is only an upper-bound design coefficient;
        # it is not available Inventory or transport-feasible supply.
        capital_by_node = defaultdict(float)
        for row in investments:
            capital_by_node[(row["node"], row["resource"])] += row["quantity"]
        pressure = []
        for node, resource in sorted(set(capital_by_node) | set(supply) | set(demand)):
            acquired = capital_by_node.get((node, resource), 0.0)
            recurring = days * demand.get((node, resource), 0.0)
            nominal_output = days * supply.get((node, resource), 0.0)
            pressure.append({"node": node, "resource": resource, "period_days": days,
                             "capital_requirement_t": acquired, "operating_requirement_t": recurring,
                             "nominal_process_output_t": nominal_output,
                             "net_nominal_requirement_t": acquired + recurring - nominal_output,
                             "interpretation": "No Stock availability, equipment acquisition schedule, or Cargo delivery implied"})
        global_pressure = defaultdict(lambda: [0., 0., 0.])
        for row in pressure:
            values = global_pressure[row["resource"]]
            values[0] += row["capital_requirement_t"]
            values[1] += row["operating_requirement_t"]
            values[2] += row["nominal_process_output_t"]
        global_pressure_rows = [{"resource": r, "capital_requirement_t": values[0],
                                 "operating_requirement_t": values[1], "nominal_process_output_t": values[2],
                                 "net_nominal_requirement_t": values[0] + values[1] - values[2],
                                 "not_deliverable_global_supply": True}
                                for r, values in sorted(global_pressure.items())]
        capacity_levels = defaultdict(lambda: {"nominal_supply": 0.0, "stated_requirement": 0.0})
        for (node, service, measure, _), value in finite.items():
            if measure in ("nominal_supply_per_day", "nominal_supply", "nominal_generation_mw"):
                capacity_levels[(node, service)]["nominal_supply"] += value
            if measure in ("requested_per_day", "requested", "nominal_load_mw"):
                capacity_levels[(node, service)]["stated_requirement"] += value
        capacity_balance = [{"node": node, "service": service, **values,
                             "nominal_spare": values["nominal_supply"] - values["stated_requirement"],
                             "interpretation": "Named nominal capacities only; no finite Allocation or eligibility guarantee"}
                            for (node, service), values in sorted(capacity_levels.items())]
        provider_totals = defaultdict(float)
        for (node, measure, _), value in research_capacity.items():
            provider_totals[measure] += value
        if rp:
            caveats.append("Research Theory completion requires RP admission, Research execution allocation and prerequisite eligibility; nominal totals are not achieved work")
        output.append({
            "name": name, "period_days": days,
            "population_target": [{"node": node, "people": count} for node, count in sorted(period_population.items())],
            "initial_available_inventory_t": defs["owned"]["available_inventory"] if index == 0 else None,
            "research": {"requested_ids": chosen_ids, "prerequisite_closure": closure, "theory_rp_total": rp,
                         "required_average_rp_per_day_if_uniform": rp / days,
                         "average_is_not_completion_or_admission_guarantee": True},
            "facility_target": [{"node": node, "facility": fid, "count": value}
                                for (node, fid), value in sorted(period_facility.items())],
            "vehicle_target": [{"node": node, "vehicle": vid, "count": value}
                               for (node, vid), value in sorted(period_fleet.items())],
            "acquisitions": acquisition, "investment_entries": investments,
            "investment_by_resource": _summarize(investments),
            "operation_entries": operation, "operation_by_resource": _summarize(operation),
            "partial_local_nominal_balance": balances,
            "joint_resource_pressure_by_node": pressure,
            "joint_resource_pressure_overall_not_fungible": global_pressure_rows,
            "capacity_balance": capacity_balance,
            "research_nominal_capacity": dict(sorted(provider_totals.items())),
            "capacity_entries": [{"node": node, "service": service, "measure": measure,
                                  "source": src, "quantity": value}
                                 for (node, service, measure, src), value in sorted(finite.items()) if value],
            "research_provider_entries": [{"node": node, "measure": field, "source": src, "quantity": value}
                                          for (node, field, src), value in sorted(research_capacity.items()) if value],
            "time_lower_bounds": time_bounds,
            "work_entries": [{"node": node, "kind": kind, "quantity": value}
                             for (node, kind), value in sorted(work.items()) if value],
            "transport_demands": transport, "caveats": sorted(set(caveats)),
        })
        running_facilities, running_fleet = period_facility, period_fleet
        running_population, running_life_support = period_population, period_life_support
    return {"kind": "balance_evaluation", "identity": defs["identity"],
            "assessment": assessment, "prospective_locations": hypothetical_nodes, "periods": output,
            "current_state_evidence": current,
            "interpretation": "Capital demand is incremental against prior authored target; operation is nominal at each target. Neither implies acquisition history, allocation, sustained production, or cargo arrival."}


def inspect(report: dict, *, resource: str | None = None, facility: str | None = None,
            vehicle: str | None = None, research: str | None = None, node: str | None = None,
            period: str | None = None) -> dict:
    """Trace recorded contributors, not an independently recalculated economy."""
    kind = report.get("kind")
    filters = {"resource": resource, "facility": facility, "vehicle": vehicle, "research": research,
               "node": node, "period": period}
    if not any(value is not None for value in filters.values()):
        raise ValueError("inspect needs at least one scope")
    if kind == "balance_overview":
        if period is not None or node is not None: raise ValueError("overview has no period/node scope")
        return {"kind": "balance_inspect", "filters": filters,
                "resource": None if resource is None else report["resource_links"].get(resource),
                "facility": None if facility is None else report["facility_units"].get(facility),
                "vehicle": None if vehicle is None else report["vehicle_units"].get(vehicle),
                "research": None if research is None else report["research_units"].get(research)}
    if kind != "balance_evaluation": raise ValueError("unrecognized balance report")
    periods = []
    for row in report["periods"]:
        if period and row["name"] != period: continue
        def eligible(item):
            if node is not None and item.get("node") != node: return False
            if resource is not None and item.get("resource") != resource: return False
            if facility is not None and item.get("source", item.get("id")) != facility: return False
            if vehicle is not None and item.get("source", item.get("id")) != vehicle: return False
            if research is not None and item.get("source", item.get("id")) != research: return False
            return True
        relevant = {}
        for key in ("investment_entries", "operation_entries", "capacity_entries", "research_provider_entries", "acquisitions", "transport_demands", "partial_local_nominal_balance", "joint_resource_pressure_by_node", "capacity_balance"):
            relevant[key] = [item for item in row[key] if eligible(item)]
        if research is not None: relevant["research_in_prerequisite_closure"] = research in row["research"]["prerequisite_closure"]
        periods.append({"name": row["name"], **relevant})
    if period and not periods: raise ValueError(f"unknown period: {period}")
    return {"kind": "balance_inspect", "filters": filters, "periods": periods}
