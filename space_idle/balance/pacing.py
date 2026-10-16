"""Time-first cross-domain Content tuning, not a second game or a Build optimizer.

Each milestone specifies desired research and industrial outcomes before asset counts.
All coefficients come from the canonical Application's Definition projection.  The
output is a set of design envelopes, never a claim of future Game State.
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil, isfinite


FORMAT = "space-idle.pacing-targets.v1"


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if (value <= 0) if positive else (value < 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return float(value)


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _fields(obj, required, allowed, label):
    if not isinstance(obj, dict) or not set(required) <= set(obj) or set(obj) - set(allowed):
        raise ValueError(f"{label}: required {sorted(required)}, allowed {sorted(allowed)}")
    return obj


def _known(mapping, key, label):
    if key not in mapping:
        raise ValueError(f"unknown {label}: {key}")
    return mapping[key]


def _closure(research, selected):
    visited, active = set(), set()

    def visit(rid):
        item = _known(research, rid, "research")
        if rid in active:
            raise ValueError(f"research prerequisite cycle: {rid}")
        if rid in visited:
            return
        active.add(rid)
        for prerequisite in item["prerequisites"]:
            visit(prerequisite)
        active.remove(rid)
        visited.add(rid)

    for rid in selected:
        visit(rid)
    return visited


def _ledger(rows):
    return [{"node": node, "resource": res, "quantity_t": amount}
            for (node, res), amount in sorted(rows.items()) if amount]


def _providers(defs, required_rp_per_day, acquired_technologies, selected_technologies):
    options = []
    for kind, definitions, field in (("facility", defs["facilities"], "research_provider"),
                                      ("vehicle", defs["vehicles"], "research_providers")):
        for key, item in sorted(definitions.items()):
            providers = [item[field]] if kind == "facility" and item[field] else (
                item[field] if kind == "vehicle" else [])
            for provider in providers:
                gen, execution = provider["generation_points_per_day"], provider["research_execution_per_day"]
                if gen <= 0 or execution <= 0:
                    continue
                options.append({"kind": kind, "id": key, "tier": provider["tier"],
                                "rp_generation_per_day_per_unit": gen,
                                "rp_execution_per_day_per_unit": execution,
                                "pool_capacity_per_unit": provider["storage_capacity_points"],
                                "missing_at_start": sorted(set(item.get("prerequisites", ())) - acquired_technologies),
                                "outside_selected_research": sorted(set(item.get("prerequisites", ())) - selected_technologies),
                                "nominal_units_if_sole_provider_from_zero":
                                    ceil(max(required_rp_per_day / gen, required_rp_per_day / execution))})
    return options


def _production_options(defs, resource, rate):
    """Enumerate valid Content coefficients, not an optimal production choice."""
    result = []
    for pid, process in defs["processes"].items():
        output = process["outputs_per_unit_t"].get(resource, 0.0)
        if output <= 0:
            continue
        for fid in process["provider_facilities"]:
            spec = defs["facilities"][fid]
            unit_rate = output * spec["process_throughput_per_day"]
            if unit_rate > 0:
                result.append({"kind": "process", "method": pid, "facility": fid,
                               "output_t_per_day_per_unit": unit_rate,
                               "minimum_nominal_units": ceil(rate / unit_rate),
                               "required_technologies": sorted(set(process["prerequisites"] + spec["prerequisites"]))})
    for eid, extraction in defs["extraction"].items():
        if extraction["output_resource_id"] != resource:
            continue
        for fid in extraction["provider_facilities"]:
            spec = defs["facilities"][fid]
            unit_rate = spec["extraction_capacity_t_per_day"]
            if unit_rate > 0:
                result.append({"kind": "extraction", "method": eid, "facility": fid,
                               "output_t_per_day_per_unit": unit_rate,
                               "minimum_nominal_units": ceil(rate / unit_rate),
                               "required_technologies": sorted(set(extraction["prerequisites"] + spec["prerequisites"]))})
    return sorted(result, key=lambda item: (item["kind"], item["method"], item["facility"]))



def _selected_supply(defs, choices, demand, interval_days, nodes, known_nodes,
                     planned_technologies, starting_technologies):
    """Expand an authored process selection into a *conditional* demand envelope.

    The algorithm does not select supply methods, create assets or claim actual
    delivery. A process shared by several outputs is scaled once; its complete
    outputs and inputs are accounted together. Circular dependencies are flagged,
    never silently filled with hypothetical supply.
    """
    by_resource = {}
    groups = {}
    for row in choices:
        _fields(row, {"node", "resource", "facility", "method"},
                {"node", "resource", "facility", "method"}, "supply choice")
        node, resource, fid, method = (row[key] for key in ("node", "resource", "facility", "method"))
        if node not in nodes:
            raise ValueError(f"unknown supply node: {node}")
        _known(defs["resources"], resource, "supply resource")
        spec = _known(defs["facilities"], fid, "supply facility")
        if (node, resource) in by_resource:
            raise ValueError(f"duplicate supply choice: {node}/{resource}")
        if method in defs["processes"]:
            process = defs["processes"][method]
            kind = "process"
            output = process["outputs_per_unit_t"]
            inp = process["inputs_per_unit_t"]
            per_day = spec["process_throughput_per_day"]
        else:
            extraction = _known(defs["extraction"], method, "supply method")
            kind = "extraction"
            output = {extraction["output_resource_id"]: 1.0}
            inp = {}
            per_day = spec["extraction_capacity_t_per_day"]
            process = extraction
        if fid not in process["provider_facilities"] or output.get(resource, 0) <= 0 or per_day <= 0:
            raise ValueError(f"incompatible supply choice: {node}/{resource}/{method}/{fid}")
        key = (node, kind, method, fid)
        group = groups.setdefault(key, {"node": node, "kind": kind, "method": method,
            "facility": fid, "inputs": inp, "outputs": output, "unit_throughput_per_day": per_day,
            "activity_units_per_day": 0.0,
            "required_technologies": sorted(set(process["prerequisites"] + spec["prerequisites"]))})
        by_resource[(node, resource)] = (key, group)
    required = defaultdict(float, demand)
    supplied = defaultdict(float)
    issues = []
    active = set()
    # Finish each selected downstream demand before expanding its upstream inputs.
    def expand(key):
        outstanding = required[key] - supplied[key]
        if outstanding <= 1e-8 or key not in by_resource:
            return
        if key in active:
            issues.append({"code": "supply_cycle", "node": key[0], "resource": key[1],
                           "limits": ["supply", "capital", "time"]})
            return
        group_key, group = by_resource[key]
        if any(k in active for k, g in by_resource.items() if g[0] == group_key):
            issues.append({"code": "supply_cycle", "node": key[0], "resource": key[1],
                           "limits": ["supply", "capital", "time"]})
            return
        active.add(key)
        output_per_unit = group["outputs"][key[1]]
        activity = outstanding / output_per_unit
        group["activity_units_per_day"] += activity
        for resource, amount in group["outputs"].items():
            supplied[(key[0], resource)] += activity * amount
        for resource, amount in group["inputs"].items():
            upstream = (key[0], resource)
            required[upstream] += activity * amount
            expand(upstream)
        active.remove(key)
    for key in sorted(required):
        expand(key)
    activity_rows, reference_units = [], defaultdict(int)
    for key, group in sorted(groups.items()):
        activity = group["activity_units_per_day"]
        unit_rate = group["unit_throughput_per_day"]
        count = ceil((activity / unit_rate) - 1e-10) if activity > 0 else 0
        if count:
            reference_units[(group["node"], group["facility"])] += count
        prereqs = set(group["required_technologies"])
        row = {"node": group["node"], "kind": group["kind"],
               "method": group["method"], "facility": group["facility"],
               "conditional_activity_units_per_day": activity,
               "reference_nominal_facility_units": count,
               "inputs_t_per_day": {r: activity * q for r, q in group["inputs"].items()},
               "outputs_t_per_day": {r: activity * q for r, q in group["outputs"].items()},
               "missing_technologies_at_start": sorted(prereqs - starting_technologies),
               "outside_planned_technologies": sorted(prereqs - planned_technologies),
               "definition_source": group["method"], "condition": "selected_method_nominal_not_achieved"}
        activity_rows.append(row)
        if row["outside_planned_technologies"]:
            issues.append({"code": "unplanned_supply_technology", "node": group["node"],
                           "method": group["method"], "limits": ["supply", "time"]})
        if group["kind"] == "extraction":
            issues.append({"code": "geology_and_allocation_unverified", "node": group["node"],
                           "method": group["method"], "limits": ["supply", "time"]})
        if group["node"] not in known_nodes:
            issues.append({"code": "prospective_site_not_founded", "node": group["node"],
                           "method": group["method"], "limits": ["supply", "time"]})
    for key, qty in sorted(required.items()):
        if qty - supplied[key] > 1e-8:
            issues.append({"code": "supply_not_established", "node": key[0],
                           "resource": key[1], "quantity_t_per_day": qty - supplied[key],
                           "limits": ["supply", "capital", "time"]})
    return required, supplied, activity_rows, reference_units, issues


def tune(defs: dict, targets: dict, *, transport_preview=None) -> dict:
    """Evaluate authored real-play-time budgets and desired outcomes across milestones.

    Assets and research completed before a milestone carry into the next.  Research
    RP costs are *variables to tune*; present costs are not fixed requirements.
    Industrial rates are nominal alternatives, not achieved outputs or deliverable stock.
    """
    _fields(targets, {"format", "milestones"}, {"format", "milestones", "prospective_locations"}, "targets")
    if targets["format"] != FORMAT:
        raise ValueError("unsupported pacing target format")
    milestones = targets["milestones"]
    if not isinstance(milestones, list) or not milestones:
        raise ValueError("milestones must be a nonempty list")
    known_nodes = {row["id"] for row in defs["world"]["nodes"]}
    body_ids = {row["id"] for row in defs["world"]["bodies"]}
    prospective = {}
    for row in targets.get("prospective_locations", []):
        _fields(row, {"id", "body_id"}, {"id", "body_id"}, "prospective location")
        if row["id"] in known_nodes or row["id"] in prospective or row["body_id"] not in body_ids:
            raise ValueError("invalid prospective location")
        prospective[row["id"]] = row["body_id"]
    nodes = known_nodes | set(prospective)
    installed = {(r["node"], r["facility"]): r["count"] for r in defs["owned"]["facilities"]}
    fleet = {(r["node"], r["vehicle"]): r["count"] for r in defs["owned"]["fleet"]}
    completed = set(defs["owned"]["completed_technologies"])
    already_researched = set(completed)
    previous_hours = 0.0
    running_production = {}
    running_supply = {}
    running_transport = {}
    running_population = {row["node"]: {"node": row["node"], "people": row["people"]}
                          for row in defs["owned"]["population"]}
    used_names = set()
    results = []
    for index, step in enumerate(milestones):
        _fields(step, {"name", "cumulative_hours"}, {"name", "cumulative_hours", "research_ids",
                 "research_time_share", "production_targets", "facility_targets", "vehicle_targets",
                 "transport_targets", "population_targets", "research_provider", "resource_supply_assumptions",
                 "supply_choices"}, f"milestone {index}")
        name = step["name"]
        if not isinstance(name, str) or not name or name in used_names:
            raise ValueError("milestone names must be distinct nonempty strings")
        used_names.add(name)
        hours = _number(step["cumulative_hours"], "cumulative_hours", positive=True)
        if hours <= previous_hours:
            raise ValueError("cumulative_hours must increase strictly")
        interval_days = (hours - previous_hours) * 3600  # canonical 1 game-day / real-second
        previous_hours = hours
        share = (None if "research_time_share" not in step else
                 _number(step["research_time_share"], "research_time_share", positive=True))
        if share is not None and share > 1:
            raise ValueError("research_time_share must be <= 1")
        selected = step.get("research_ids", [])
        if not isinstance(selected, list) or any(not isinstance(rid, str) for rid in selected):
            raise ValueError("research_ids must be a list of IDs")
        closure = _closure(defs["research"], selected)
        already_researched_at_start = set(already_researched)
        pending = closure - already_researched
        already_researched.update(closure)
        rp_cost = sum(s.get("rp", 0.0) for rid in pending for s in defs["research"][rid]["stages"])
        prototype_materials = defaultdict(float)
        prototype_details = []
        prototype_work = 0.0
        demonstration_work = 0.0
        experiential = []
        research_requirements = []
        for rid in pending:
            for stage in defs["research"][rid]["stages"]:
                if stage.get("execution_requirements"):
                    research_requirements.append({"research": rid, "stage": stage["id"],
                                                  "requirements": stage["execution_requirements"]})
                if stage["kind"] == "prototype":
                    prototype_work += stage["work"]
                    prototype_details.append({"kind": "research_prototype_work", "id": rid,
                                              "stage_id": stage["id"], "node": "unallocated_research",
                                              "work": stage["work"]})
                    for resource, quantity in stage["resources_t"].items():
                        prototype_materials[resource] += quantity
                        prototype_details.append({"kind": "research_prototype_material", "id": rid,
                                                  "stage_id": stage["id"], "node": "unallocated_research",
                                                  "resource": resource, "quantity_t": quantity})
                elif stage["kind"] == "demonstration":
                    demonstration_work += stage["work"]
                    prototype_details.append({"kind": "research_demonstration_work", "id": rid,
                                              "stage_id": stage["id"], "node": "unallocated_research",
                                              "work": stage["work"]})
                elif stage["kind"] == "operational_experience":
                    experiential.append(rid)
        required_rp = rp_cost / interval_days
        conditional_rp = rp_cost / (interval_days * share) if share is not None else None
        provider_options = _providers(defs, conditional_rp if conditional_rp is not None else required_rp,
                                      already_researched_at_start, already_researched)
        facilities = dict(installed)
        starting_facilities = dict(installed)
        starting_fleet = dict(fleet)
        fleet_target = dict(fleet)
        seen_facilities = set()
        for row in step.get("facility_targets", []):
            _fields(row, {"node", "facility", "count"}, {"node", "facility", "count"}, "facility target")
            if row["node"] not in nodes:
                raise ValueError(f"unknown node: {row['node']}")
            _known(defs["facilities"], row["facility"], "facility")
            key = row["node"], row["facility"]
            if key in seen_facilities:
                raise ValueError(f"duplicate facility target: {key}")
            seen_facilities.add(key)
            facilities[key] = _count(row["count"], "facility count")
        seen_vehicles = set()
        for row in step.get("vehicle_targets", []):
            _fields(row, {"node", "vehicle", "count"}, {"node", "vehicle", "count"}, "vehicle target")
            if row["node"] not in nodes:
                raise ValueError(f"unknown node: {row['node']}")
            _known(defs["vehicles"], row["vehicle"], "vehicle")
            key = row["node"], row["vehicle"]
            if key in seen_vehicles:
                raise ValueError("duplicate vehicle target")
            seen_vehicles.add(key)
            fleet_target[key] = _count(row["count"], "vehicle count")
        seen_production = set()
        for row in step.get("production_targets", []):
            _fields(row, {"node", "resource", "tonnes_per_day"},
                    {"node", "resource", "tonnes_per_day", "facility", "method"}, "production target")
            key = row["node"], row["resource"]
            if key in seen_production:
                raise ValueError(f"duplicate production target: {key}")
            seen_production.add(key)
            running_production[key] = row
        production = []
        conditions = []
        for row in running_production.values():
            if row["node"] not in nodes:
                raise ValueError(f"unknown node: {row['node']}")
            _known(defs["resources"], row["resource"], "resource")
            amount = _number(row["tonnes_per_day"], "production rate", positive=True)
            options = _production_options(defs, row["resource"], amount)
            for option in options:
                prereqs = set(option["required_technologies"])
                option["missing_at_start"] = sorted(prereqs - already_researched_at_start)
                option["outside_selected_research"] = sorted(prereqs - already_researched)
            fid, method = row.get("facility"), row.get("method")
            chosen = next((item for item in options if item["facility"] == fid and item["method"] == method), None)
            if fid is not None or method is not None:
                if chosen is None:
                    raise ValueError(f"production provider cannot supply {row['resource']}: {fid}/{method}")
                if chosen["outside_selected_research"]:
                    conditions.append({"code": "production_goal_requires_unplanned_technology",
                                       "node": row["node"], "resource": row["resource"],
                                       "method": method, "facility": fid,
                                       "missing_technology_ids": chosen["outside_selected_research"],
                                       "limits": ["production_goal", "research", "time"]})
            else:
                conditions.append({"code": "production_goal_supply_method_unselected",
                                   "node": row["node"], "resource": row["resource"],
                                   "target_t_per_day": amount, "limits": ["production_goal"]})
            if not options:
                conditions.append({"code": "registered_production_method_missing",
                                   "node": row["node"], "resource": row["resource"],
                                   "target_t_per_day": amount, "limits": ["production_goal", "content"]})
            production.append({"node": row["node"], "resource": row["resource"],
                               "target_t_per_day": amount, "quantity_role": "authored_goal_not_verified_supply",
                               "options": options, "selected": chosen, "nominal_units_if_selected":
                                   None if chosen is None else chosen["minimum_nominal_units"]})
        provider_goal = step.get("research_provider")
        if provider_goal is not None:
            _fields(provider_goal, {"node", "facility"}, {"node", "facility"}, "research_provider")
            if provider_goal["node"] not in nodes:
                raise ValueError("unknown research provider node")
            fid = provider_goal["facility"]
            spec = _known(defs["facilities"], fid, "research provider facility")
            provider = spec["research_provider"]
            if not provider or provider["generation_points_per_day"] <= 0 or provider["research_execution_per_day"] <= 0:
                raise ValueError("selected facility is not an RP generation + execution provider")
            # A provider selection is a design reference, not an asset purchase.
            # Only explicit facility_targets contribute to the investment ledger.
            provider_goal = {**provider_goal,
                             "missing_at_start": sorted(set(spec["prerequisites"]) - already_researched_at_start),
                             "outside_selected_research": sorted(set(spec["prerequisites"]) - already_researched),
                             "nominal_units_if_sole_provider_from_zero": ceil(max(
                (conditional_rp if conditional_rp is not None else required_rp) / provider["generation_points_per_day"],
                (conditional_rp if conditional_rp is not None else required_rp) / provider["research_execution_per_day"]))}
            if provider_goal["outside_selected_research"]:
                conditions.append({"code": "research_provider_requires_unplanned_technology",
                                   "node": provider_goal["node"], "facility": fid,
                                   "missing_technology_ids": provider_goal["outside_selected_research"],
                                   "limits": ["research", "time"]})
        seen_transport = set()
        for row in step.get("transport_targets", []):
            _fields(row, {"source", "destination", "resource", "tonnes_per_day"},
                    {"source", "destination", "resource", "tonnes_per_day", "vehicle"}, "transport target")
            key = row["source"], row["destination"], row["resource"]
            if key in seen_transport:
                raise ValueError(f"duplicate transport target: {key}")
            seen_transport.add(key)
            running_transport[key] = row
        transport = []
        for row in running_transport.values():
            if row["source"] not in nodes or row["destination"] not in nodes:
                raise ValueError("unknown transport node")
            _known(defs["resources"], row["resource"], "transport resource")
            quantity = _number(row["tonnes_per_day"], "transport target", positive=True)
            result = {"source": row["source"], "destination": row["destination"],
                      "resource": row["resource"], "target_t_per_day": quantity,
                      "canonical_preview": None}
            if "vehicle" in row:
                vehicle = _known(defs["vehicles"], row["vehicle"], "transport vehicle")
                result["vehicle"] = row["vehicle"]
                result["minimum_departures_per_day_at_payload_limit"] = quantity / vehicle["payload_t"] if vehicle["payload_t"] > 0 else None
                if transport_preview and row["source"] in known_nodes and row["destination"] in known_nodes:
                    try:
                        result["canonical_preview"] = transport_preview(row["vehicle"], row["source"], row["destination"], quantity)
                        required = result["canonical_preview"].get("required_units")
                        result["reference_required_units_not_acquired"] = required
                        if not isinstance(required, int) or required <= 0:
                            conditions.append({"code": "transport_preview_no_feasible_units",
                                               "source": row["source"], "destination": row["destination"],
                                               "resource": row["resource"], "target_t_per_day": quantity,
                                               "limits": ["logistics", "time"]})
                    except (ValueError, RuntimeError, KeyError) as exc:
                        conditions.append({"code": "transport_preview_unresolved",
                                           "source": row["source"], "destination": row["destination"],
                                           "reason": str(exc), "limits": ["logistics", "time"]})
            else:
                conditions.append({"code": "transport_vehicle_unselected",
                                   "source": row["source"], "destination": row["destination"],
                                   "resource": row["resource"], "target_t_per_day": quantity,
                                   "limits": ["logistics"]})
            transport.append(result)
        # Desired cargo movements are a demand at origin, not a delivered
        # inventory credit at destination. Inbound is shown separately as a
        # conditional envelope so a route cannot manufacture supply.
        transport_outbound = defaultdict(float)
        transport_inbound = defaultdict(float)
        for row in transport:
            transport_outbound[(row["source"], row["resource"])] += row["target_t_per_day"]
            transport_inbound[(row["destination"], row["resource"])] += row["target_t_per_day"]
        population_daily = defaultdict(float)
        population_evidence = []
        seen_population = set()
        for row in step.get("population_targets", []):
            _fields(row, {"node", "people"}, {"node", "people", "housing_facility", "life_support_facility"}, "population target")
            if row["node"] in seen_population:
                raise ValueError("duplicate population target")
            seen_population.add(row["node"])
            running_population[row["node"]] = row
        population = []
        for row in running_population.values():
            if row["node"] not in nodes:
                raise ValueError("unknown population node")
            people = _count(row["people"], "people")
            entry = {"node": row["node"], "target_people": people}
            for kind, key, capacity_key in (("housing", "housing_facility", "housing_capacity"),
                                             ("life_support", "life_support_facility", "life_support_person_days_per_day")):
                options = [{"facility": fid, "person_capacity_per_unit": spec[capacity_key],
                            "minimum_nominal_units": ceil(people / spec[capacity_key])}
                           for fid, spec in sorted(defs["facilities"].items()) if (spec[capacity_key] or 0) > 0]
                chosen = row.get(key)
                entry[kind + "_options"] = options
                entry[kind + "_facility"] = chosen
                if chosen is not None:
                    selected_provider_option = next((opt for opt in options if opt["facility"] == chosen), None)
                    if selected_provider_option is None:
                        raise ValueError(f"{key} cannot support population: {chosen}")
                    entry[kind + "_nominal_units"] = selected_provider_option["minimum_nominal_units"]
                    if kind == "life_support":
                        for resource, rate in defs["facilities"][chosen]["life_support_resources_per_person_day_t"].items():
                            population_daily[(row["node"], resource)] += people * rate
                            population_evidence.append({"kind": "population_life_support", "id": chosen,
                                                        "node": row["node"], "resource": resource,
                                                        "people": people, "quantity_t_per_day": people * rate})
                elif people:
                    conditions.append({"code": "population_support_provider_unselected",
                                       "node": row["node"], "service": kind,
                                       "target_people": people, "limits": ["population", "capital", "time"]})
            if people:
                conditions.append({"code": "population_progression_unverified",
                                   "node": row["node"], "target_people": people,
                                   "limits": ["population", "time"]})
            population.append(entry)

        capital = defaultdict(float)
        daily_input = defaultdict(float)
        for key, value in population_daily.items():
            daily_input[key] += value
        nominal_output = defaultdict(float)
        work = defaultdict(float)
        quantity_evidence = prototype_details + population_evidence + [
            {"kind": "authored_transport_target", "id": (row["source"], row["destination"], row["resource"]),
             "source": row["source"], "destination": row["destination"],
             "resource": row["resource"], "target_t_per_day": row["target_t_per_day"],
             "delivery_is_unverified": True}
            for row in transport]
        # Quantity of the milestone asset inventory is a target, not a build schedule.
        capacity = defaultdict(float)
        power = defaultdict(lambda: [0.0, 0.0])
        for (node, fid), count in sorted(facilities.items()):
            facility = defs["facilities"][fid]
            capacity[(node, "construction_work_per_day")] += count * facility["construction_work_per_day"]
            capacity[(node, "housing_people")] += count * facility["housing_capacity"]
            capacity[(node, "life_support_person_days_per_day")] += count * (facility["life_support_person_days_per_day"] or 0)
            for service, rate in facility["services_per_day"].items():
                capacity[(node, f"service:{service}")] += count * rate
            power[node][0] += count * facility["power_reference_generation_mw"]
            power[node][1] += count * facility["power_load_mw"]
            added = max(0, count - installed.get((node, fid), 0))
            if count < installed.get((node, fid), 0):
                conditions.append({"code": "decommissioning_not_modeled",
                                   "node": node, "facility": fid, "limits": ["capital", "time"]})
            if added:
                recipe = facility["construction_resources_t"]
                if recipe is None:
                    conditions.append({"code": "facility_construction_recipe_missing",
                                       "node": node, "facility": fid,
                                       "limits": ["capital", "construction", "time"]})
                else:
                    for resource, quantity in recipe.items():
                        capital[(node, resource)] += added * quantity
                        quantity_evidence.append({"kind": "facility_acquisition", "id": fid, "node": node,
                                                  "resource": resource, "units": added, "quantity_t": added * quantity})
                    if not facility["self_deploying"]:
                        needed_work = added * (facility["construction_work"] or 0)
                        work[(node, "construction_work")] += needed_work
                        quantity_evidence.append({"kind": "facility_construction_work", "id": fid,
                                                  "node": node, "units": added, "work": needed_work})
            for resource, quantity in (facility["maintenance_per_day_t"] or {}).items():
                daily_input[(node, resource)] += quantity * count
                quantity_evidence.append({"kind": "facility_maintenance", "id": fid, "node": node,
                                          "resource": resource, "units": count, "quantity_t_per_day": quantity * count})
            for resource, quantity in facility["operating_per_day_t"].items():
                daily_input[(node, resource)] += quantity * count
                quantity_evidence.append({"kind": "facility_operation", "id": fid, "node": node,
                                          "resource": resource, "units": count, "quantity_t_per_day": quantity * count})
        for (node, vid), count in sorted(fleet_target.items()):
            vehicle = defs["vehicles"][vid]
            added = max(0, count - fleet.get((node, vid), 0))
            for resource, quantity in vehicle["production_resources_t"].items():
                capital[(node, resource)] += added * quantity
                if added:
                    quantity_evidence.append({"kind": "vehicle_acquisition", "id": vid, "node": node,
                                              "resource": resource, "units": added, "quantity_t": added * quantity})
            if vehicle["production_service_type"] and added:
                needed_work = added * vehicle["production_days"]
                work[(node, vehicle["production_service_type"])] += needed_work
                quantity_evidence.append({"kind": "vehicle_production_work", "id": vid,
                                          "node": node, "units": added,
                                          "service": vehicle["production_service_type"], "work": needed_work})
        for resource, quantity in prototype_materials.items():
            capital[("unallocated_research", resource)] += quantity

        work[("unallocated_research", "prototype_work")] += prototype_work
        work[("unallocated_research", "demonstration_work")] += demonstration_work
        def research_capacity(facility_counts, fleet_counts):
            generation = execution = pool = 0.0
            for (_, fid), count in facility_counts.items():
                provider = defs["facilities"][fid]["research_provider"]
                if provider:
                    generation += count * provider["generation_points_per_day"]
                    execution += count * provider["research_execution_per_day"]
                    pool += count * provider["storage_capacity_points"]
            for (_, vid), count in fleet_counts.items():
                for provider in defs["vehicles"][vid]["research_providers"]:
                    generation += count * provider["generation_points_per_day"]
                    execution += count * provider["research_execution_per_day"]
                    pool += count * provider["storage_capacity_points"]
            return {"generation_rp_per_day": generation,
                    "execution_rp_per_day": execution, "pool_capacity_rp": pool}

        starting_capacity = research_capacity(starting_facilities, starting_fleet)
        end_capacity = research_capacity(facilities, fleet_target)
        reference_rate = conditional_rp if conditional_rp is not None else required_rp
        if (reference_rate > end_capacity["generation_rp_per_day"] + 1e-9 or
                reference_rate > end_capacity["execution_rp_per_day"] + 1e-9):
            conditions.append({"code": "planned_end_research_rate_below_interval_reference",
                               "required_reference_rp_per_day": reference_rate,
                               "nominal_end_generation_rp_per_day": end_capacity["generation_rp_per_day"],
                               "nominal_end_execution_rp_per_day": end_capacity["execution_rp_per_day"],
                               "not_an_actual_timing_or_rp_stock_verdict": True,
                               "limits": ["research", "time"]})
        construction_supply = defaultdict(float)
        for (node, fid), count in facilities.items():
            construction_supply[node] += count * defs["facilities"][fid]["construction_work_per_day"]
        construction_bounds = [{"node": node, "required_work": amount,
                                "nominal_end_target_work_per_day": construction_supply.get(node, 0.0),
                                "days_lower_bound_at_end_target_capacity": (
                                    amount / construction_supply[node] if construction_supply.get(node, 0) > 0 else None)}
                               for (node, service), amount in sorted(work.items()) if service == "construction_work"]
        supply_assumptions = {}
        for assumption in step.get("resource_supply_assumptions", []):
            _fields(assumption, {"node", "resource", "average_t_per_day", "basis"},
                    {"node", "resource", "average_t_per_day", "basis"}, "supply assumption")
            node, resource = assumption["node"], assumption["resource"]
            if node not in nodes:
                raise ValueError(f"unknown supply assumption node: {node}")
            _known(defs["resources"], resource, "supply assumption resource")
            basis = assumption["basis"]
            if not isinstance(basis, str) or not basis.strip():
                raise ValueError("supply assumption basis must explain independent evidence or a design hypothesis")
            key = node, resource
            if key in supply_assumptions:
                raise ValueError(f"duplicate supply assumption: {key}")
            supply_assumptions[key] = {
                "average_t_per_day": _number(assumption["average_t_per_day"], "average_t_per_day"),
                "basis": basis.strip()}
        seen_supply = set()
        for choice in step.get("supply_choices", []):
            _fields(choice, {"node", "resource", "method", "facility"},
                    {"node", "resource", "method", "facility"}, "supply choice")
            key = (choice["node"], choice["resource"])
            if key in seen_supply:
                raise ValueError(f"duplicate supply choice: {key}")
            seen_supply.add(key)
            running_supply[key] = choice
        # Capital is a once-only stock requirement; operations are an end-point
        # rate. Spreading capital over the interval is a *scale*, not a schedule.
        reference_demand = defaultdict(float)
        for key, amount in capital.items():
            reference_demand[key] += amount / interval_days
        for key, amount in daily_input.items():
            reference_demand[key] += amount
        for key, amount in transport_outbound.items():
            reference_demand[key] += amount
        upstream_demand, selected_output, chosen_processes, reference_units, supply_issues = _selected_supply(
            defs, list(running_supply.values()), reference_demand, interval_days,
            nodes, known_nodes, already_researched, already_researched_at_start)
        nominal_output.update(selected_output)
        for row in chosen_processes:
            quantity_evidence.append({"kind": "selected_supply_process", "id": row["method"],
                                      "node": row["node"], "facility": row["facility"],
                                      "conditional_activity_units_per_day": row["conditional_activity_units_per_day"],
                                      "inputs_t_per_day": row["inputs_t_per_day"],
                                      "outputs_t_per_day": row["outputs_t_per_day"]})
        initial_stock = ({(r["node"], r["resource"]): r["available_t"]
                         for r in defs["owned"]["available_inventory"]} if index == 0 else {})
        resource_budget = []
        for node, resource in sorted(set(capital) | set(daily_input) | set(upstream_demand) |
                                     set(selected_output) | set(supply_assumptions) | set(initial_stock) |
                                     set(transport_outbound) | set(transport_inbound)):
            key = (node, resource)
            acquisition = capital.get(key, 0.0)
            operation = daily_input.get(key, 0.0)
            reference = reference_demand[key]
            all_demand = upstream_demand[key]
            output = selected_output[key]
            assumption = supply_assumptions.get(key)
            matches_target = (assumption is not None and any(
                r["node"] == node and r["resource"] == resource and
                abs(r["target_t_per_day"] - assumption["average_t_per_day"]) < 1e-8
                for r in production))
            if matches_target:
                conditions.append({"code": "supply_assumption_equals_production_goal",
                                   "node": node, "resource": resource,
                                   "assumed_t_per_day": assumption["average_t_per_day"],
                                   "limits": ["supply"]})
            resource_budget.append({
                "node": node, "resource": resource,
                "starting_available_stock_t_not_assumed_spent": initial_stock.get(key, 0.0),
                "authored_supply_assumption_t_per_day": None if assumption is None else assumption["average_t_per_day"],
                "supply_assumption_basis": None if assumption is None else assumption["basis"],
                "assumption_matches_conditional_production_target": matches_target,
                "capital_investment_t": acquisition,
                "average_capital_requirement_t_per_day_if_spread_over_interval": acquisition / interval_days,
                "end_target_operation_input_t_per_day": operation,
                "authored_transport_outbound_t_per_day": transport_outbound[key],
                "conditional_transport_inbound_t_per_day_not_delivered": transport_inbound[key],
                "conditional_reference_output_t_per_day": output,
                "direct_reference_requirement_t_per_day": reference,
                "upstream_intermediate_input_t_per_day": max(0.0, all_demand - reference),
                "combined_reference_demand_t_per_day": all_demand,
                "conditional_selected_method_output_t_per_day": output,
                "remaining_unestablished_supply_t_per_day": max(0.0, all_demand - output),
                "average_capital_plus_end_target_operation_input_t_per_day": reference,
                "quantity_status": "conditional_reference_not_delivery",
                "interpretation": "Capital is spread only to compare scales; outbound transport is an origin demand, inbound transport is not delivered supply, and conditional processes, start stock and authored supply assumptions do not establish delivery or a construction schedule."})
        for (node, fid), count in sorted(reference_units.items()):
            chosen = facilities.get((node, fid), 0)
            if count > chosen:
                supply_issues.append({"code": "planned_facility_capacity_below_reference",
                                      "node": node, "facility": fid, "nominal_reference_units": count,
                                      "explicit_planned_units": chosen,
                                      "limits": ["supply", "capital", "time"]})
        for row in population:
            node, people = row["node"], row["target_people"]
            for kind, field in (("housing", "housing_capacity"),
                                ("life_support", "life_support_person_days_per_day")):
                chosen = row.get(kind + "_facility")
                if chosen and people > facilities.get((node, chosen), 0) * (defs["facilities"][chosen][field] or 0):
                    supply_issues.append({"code": "planned_population_support_below_reference",
                                          "node": node, "facility": chosen, "service": kind,
                                          "limits": ["population", "capital", "time"]})
        for (node, service), amount in sorted(work.items()):
            rate = amount / interval_days
            if rate == 0:
                continue
            cap_key = "construction_work_per_day" if service == "construction_work" else f"service:{service}"
            available = capacity.get((node, cap_key), 0.0)
            if rate > available + 1e-9:
                supply_issues.append({"code": "planned_work_capacity_below_interval_average",
                                      "node": node, "service": service,
                                      "required_reference_per_day": rate, "planned_end_capacity_per_day": available,
                                      "limits": ["construction", "research", "time"]})
        for (node, fid), planned in sorted(facilities.items()):
            if planned > installed.get((node, fid), 0):
                missing = sorted(set(defs["facilities"][fid]["prerequisites"]) - already_researched)
                if missing:
                    supply_issues.append({"code": "facility_requires_unplanned_technology",
                                          "node": node, "facility": fid,
                                          "missing_technology_ids": missing,
                                          "limits": ["construction", "research", "time"]})
        for node, (generation, load) in sorted(power.items()):
            if load > generation + 1e-9:
                supply_issues.append({"code": "reference_power_load_exceeds_generation",
                                      "node": node, "nominal_generation_mw": generation,
                                      "nominal_load_mw": load, "limits": ["power", "supply", "research"]})
        # Global totals are economic *magnitudes*, not freely transferable supplies.
        totals = defaultdict(lambda: [0.0] * 7)
        for row in resource_budget:
            columns = totals[row["resource"]]
            columns[0] += row["capital_investment_t"]
            columns[1] += row["end_target_operation_input_t_per_day"]
            columns[2] += row["conditional_reference_output_t_per_day"]
            columns[3] += row["upstream_intermediate_input_t_per_day"]
            columns[4] += row["remaining_unestablished_supply_t_per_day"]
            columns[5] += row["authored_transport_outbound_t_per_day"]
            columns[6] += row["conditional_transport_inbound_t_per_day_not_delivered"]
        economy_resources = [{"resource": resource, "capital_investment_t": cols[0],
                              "end_target_operation_input_t_per_day": cols[1],
                              "conditional_reference_output_t_per_day": cols[2],
                              "conditional_upstream_input_t_per_day": cols[3],
                              "remaining_unestablished_supply_t_per_day": cols[4],
                              "authored_transport_outbound_t_per_day": cols[5],
                              "conditional_transport_inbound_t_per_day_not_delivered": cols[6],
                              "not_deliverable_global_supply": True}
                             for resource, cols in sorted(totals.items())]
        if not selected and not any(step.get(field) for field in (
                "production_targets", "facility_targets", "vehicle_targets", "population_targets", "transport_targets", "research_provider")):
            conditions.append({"code": "milestone_has_no_new_development_outcome",
                               "milestone": name, "inherited_previous_goals": bool(index),
                               "limits": ["development_goal", "balance_judgment"]})
        # This is NOT cumulative production during growth: all operating rates are end targets.
        stage = {"name": name, "target_cumulative_hours": hours,
                 "interval_play_hours": interval_days / 3600, "interval_game_days_at_base_speed": interval_days,
                 "research": {"selected_ids": selected, "new_prerequisites_and_research": sorted(pending),
                              "theory_rp_cost_at_current_content": rp_cost,
                              "required_average_rp_per_day_if_full_interval": required_rp,
                              "assumed_research_time_share": share,
                              "required_average_rp_per_day_if_share_assumed": conditional_rp,
                              "nominal_start_research_capacity": starting_capacity,
                              "nominal_end_target_research_capacity": end_capacity,
                              "selected_provider_reference": provider_goal,
                              "research_capacity_is_not_available_for_whole_interval": True,
                              "prototype_resources_t": dict(sorted(prototype_materials.items())),
                              "prototype_work": prototype_work, "demonstration_work": demonstration_work,
                              "operational_experience_projects": sorted(experiential),
                              "single_provider_options": provider_options,
                              "execution_requirements_by_stage": research_requirements,
                              "research_selection_is_planned_not_actual": True},
                 "production_targets": production,
                 "facility_end_targets": [{"node": node, "facility": fid, "count": count,
                                           "basis": ("explicit_target" if (node, fid) in seen_facilities else
                                                     "inherited_or_initial_asset")}
                                          for (node, fid), count in sorted(facilities.items())],
                 "fleet_end_targets": [{"node": node, "vehicle": vid, "count": count}
                                       for (node, vid), count in sorted(fleet_target.items())],
                 "capital_resources_t": _ledger(capital), "resource_time_budget": resource_budget,
                 "selected_supply_processes": chosen_processes,
                 "supply_choices": [running_supply[key] for key in sorted(running_supply)],
                 "reference_facility_units_not_acquired": [
                     {"node": n, "facility": f, "count": c} for (n, f), c in sorted(reference_units.items())],
                 "constraints": supply_issues + conditions,
                 "quantity_evidence": quantity_evidence,
                 "state_provenance": {"starting_assets": (
                     "actual_save_or_scenario" if index == 0 else "planned_previous_milestone_not_actual"),
                                      "ending_assets": "explicit_authored_targets_not_achieved_game_state",
                                      "reference_units": "conditional_not_acquired",
                                      "technologies": "selected_research_is_planned_not_proven_completed"},
                 "economy_resources_across_nodes": economy_resources,
                 "construction_and_production_work": [
                     {"node": node, "service": svc, "quantity": amount}
                     for (node, svc), amount in sorted(work.items()) if amount],
                 "end_target_nominal_capacity": [{"node": node, "service": service, "quantity": value}
                                                  for (node, service), value in sorted(capacity.items()) if value],
                 "end_target_reference_power": [{"node": node, "nominal_reference_generation_mw": value[0],
                                                "nominal_load_mw": value[1], "site_adjustment_not_applied": True}
                                               for node, value in sorted(power.items())],
                 "end_target_nominal_inputs_t_per_day": _ledger(daily_input),
                 "conditional_reference_process_outputs_t_per_day": _ledger(nominal_output),
                 "construction_work_time_lower_bounds": construction_bounds,
                 "required_average_work_per_day_by_service": [
                     {"node": node, "service": svc, "work_per_day_to_finish_in_interval": amount / interval_days}
                     for (node, svc), amount in sorted(work.items()) if amount],
                 "transport_targets": transport,
                 "transport_flow_envelope_not_proven_delivered": [
                     {"source": row["source"], "destination": row["destination"],
                      "resource": row["resource"], "target_t_per_day": row["target_t_per_day"]}
                     for row in transport],
                 "population_targets": population,

                 "interpretation": "Time-first design envelope, not growth simulation or achieved State. The target asset capacity is an end-state upper bound; build-up, competing allocation, geographic supply, and actual play decisions are not inferred."}
        results.append(stage)
        installed, fleet = facilities, fleet_target
    summary = []
    evidence = []
    for stage in results:
        name = stage["name"]
        constraint_kinds = defaultdict(int)
        for row in stage["constraints"]:
            constraint_kinds[row["code"]] += 1
        for row in stage["quantity_evidence"]:
            evidence.append({"milestone": name, **row})
        summary.append({
            "milestone": name, "target_cumulative_hours": stage["target_cumulative_hours"],
            "interval_game_days": stage["interval_game_days_at_base_speed"],
            "theory_rp_cost": stage["research"]["theory_rp_cost_at_current_content"],
            "average_required_rp_per_day": stage["research"]["required_average_rp_per_day_if_full_interval"],
            "start_nominal_research": stage["research"]["nominal_start_research_capacity"],
            "planned_end_nominal_research": stage["research"]["nominal_end_target_research_capacity"],
            "capital_resources_t": stage["capital_resources_t"],
            "reference_total_demands_by_resource": [
                {"node": r["node"], "resource": r["resource"],
                 "capital_t": r["capital_investment_t"],
                 "operating_t_per_day": r["end_target_operation_input_t_per_day"],
                 "transport_outbound_t_per_day": r["authored_transport_outbound_t_per_day"],
                 "conditional_transport_inbound_t_per_day": r["conditional_transport_inbound_t_per_day_not_delivered"],
                 "conditional_upstream_t_per_day": r["upstream_intermediate_input_t_per_day"]}
                for r in stage["resource_time_budget"]],
            "transport_routes": len(stage["transport_targets"]),
            "population_sites": len(stage["population_targets"]),
            "conditional_constraints_by_code": dict(sorted(constraint_kinds.items())),
            "details_ref": name, "evidence_ref": name})
    return {"kind": "balance_pacing", "identity": defs["identity"],
            "format": FORMAT, "prospective_locations": prospective,
            "summary": summary, "milestones": results, "evidence": evidence,
            "interpretation": "One cumulative design baseline; summary, stage quantities and ID-linked evidence. Reference process runs and target assets are conditional; no feasible construction timing, verified delivery, optimizer or achieved Game State is inferred."}
