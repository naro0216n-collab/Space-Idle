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


def _providers(defs, required_rp_per_day):
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
                                "units_for_stated_theory_rate_if_sole_provider":
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
    running_transport = {}
    running_population = {row["node"]: {"node": row["node"], "people": row["people"]}
                          for row in defs["owned"]["population"]}
    used_names = set()
    results = []
    for index, step in enumerate(milestones):
        _fields(step, {"name", "cumulative_hours"}, {"name", "cumulative_hours", "research_ids",
                 "research_time_share", "production_targets", "facility_targets", "vehicle_targets",
                 "transport_targets", "population_targets", "research_provider", "resource_supply_budgets"}, f"milestone {index}")
        name = step["name"]
        if not isinstance(name, str) or not name or name in used_names:
            raise ValueError("milestone names must be distinct nonempty strings")
        used_names.add(name)
        hours = _number(step["cumulative_hours"], "cumulative_hours", positive=True)
        if hours <= previous_hours:
            raise ValueError("cumulative_hours must increase strictly")
        interval_days = (hours - previous_hours) * 3600  # canonical 1 game-day / real-second
        previous_hours = hours
        share = _number(step.get("research_time_share", 1), "research_time_share", positive=True)
        if share > 1:
            raise ValueError("research_time_share must be <= 1")
        selected = step.get("research_ids", [])
        if not isinstance(selected, list) or any(not isinstance(rid, str) for rid in selected):
            raise ValueError("research_ids must be a list of IDs")
        closure = _closure(defs["research"], selected)
        pending = closure - already_researched
        already_researched.update(closure)
        rp_cost = sum(s.get("rp", 0.0) for rid in pending for s in defs["research"][rid]["stages"])
        prototype_materials = defaultdict(float)
        prototype_work = 0.0
        demonstration_work = 0.0
        experiential = []
        for rid in pending:
            for stage in defs["research"][rid]["stages"]:
                if stage["kind"] == "prototype":
                    prototype_work += stage["work"]
                    for resource, quantity in stage["resources_t"].items():
                        prototype_materials[resource] += quantity
                elif stage["kind"] == "demonstration":
                    demonstration_work += stage["work"]
                elif stage["kind"] == "operational_experience":
                    experiential.append(rid)
        required_rp = rp_cost / (interval_days * share)
        provider_options = _providers(defs, required_rp)
        facilities = dict(installed)
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
        required_facility = defaultdict(int)
        process_operating = defaultdict(float)
        process_outputs = defaultdict(float)
        unresolved = []
        for row in running_production.values():
            if row["node"] not in nodes:
                raise ValueError(f"unknown node: {row['node']}")
            _known(defs["resources"], row["resource"], "resource")
            amount = _number(row["tonnes_per_day"], "production rate", positive=True)
            options = _production_options(defs, row["resource"], amount)
            fid, method = row.get("facility"), row.get("method")
            chosen = next((item for item in options if item["facility"] == fid and item["method"] == method), None)
            if fid is not None or method is not None:
                if chosen is None:
                    raise ValueError(f"production provider cannot supply {row['resource']}: {fid}/{method}")
                required_facility[(row["node"], fid)] += chosen["minimum_nominal_units"]
                if chosen["kind"] == "process":
                    spec = defs["processes"][method]
                    throughput = amount / spec["outputs_per_unit_t"][row["resource"]]
                    for resource, rate in spec["inputs_per_unit_t"].items():
                        process_operating[(row["node"], resource)] += throughput * rate
                    for resource, rate in spec["outputs_per_unit_t"].items():
                        process_outputs[(row["node"], resource)] += throughput * rate
                else:
                    process_outputs[(row["node"], row["resource"])] += amount
                    unresolved.append(f"{name}: extraction at {row['node']} needs site geology, knowledge and Allocation")
            else:
                unresolved.append(f"{name}: production provider not selected for {row['node']}/{row['resource']}")
            if not options:
                unresolved.append(f"{name}: no registered production method for {row['resource']}")
            production.append({"node": row["node"], "resource": row["resource"],
                               "target_t_per_day": amount, "options": options,
                               "selected": chosen, "nominal_units_if_selected":
                                   None if chosen is None else chosen["minimum_nominal_units"]})
        for key, count in required_facility.items():
            facilities[key] = max(facilities.get(key, 0), count)
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
            goal_count = ceil(max(required_rp / provider["generation_points_per_day"],
                                  required_rp / provider["research_execution_per_day"]))
            key = provider_goal["node"], fid
            facilities[key] = max(facilities.get(key, 0), goal_count)
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
        route_fleet_requirements = defaultdict(int)
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
                        if isinstance(required, int) and required > 0:
                            route_fleet_requirements[(row["source"], row["vehicle"])] += required
                        else:
                            unresolved.append(f"{name}: no feasible fleet quantity from canonical route preview")
                    except (ValueError, RuntimeError, KeyError) as exc:
                        unresolved.append(f"{name}: transport preview unresolved: {exc}")
            else:
                unresolved.append(f"{name}: transport vehicle not selected")
            transport.append(result)
        for key, count in route_fleet_requirements.items():
            fleet_target[key] = max(fleet_target.get(key, 0), count)
        population_daily = defaultdict(float)
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
                    asset_key = row["node"], chosen
                    facilities[asset_key] = max(facilities.get(asset_key, 0), selected_provider_option["minimum_nominal_units"])
                    if kind == "life_support":
                        for resource, rate in defs["facilities"][chosen]["life_support_resources_per_person_day_t"].items():
                            population_daily[(row["node"], resource)] += people * rate
                elif people:
                    unresolved.append(f"{name}: {kind} provider not selected for {row['node']}")
            if people:
                unresolved.append(f"{name}: population growth, eligibility, arrival and common capacity allocation are not established")
            population.append(entry)

        capital = defaultdict(float)
        daily_input = defaultdict(float, process_operating)
        for key, value in population_daily.items():
            daily_input[key] += value
        nominal_output = defaultdict(float, process_outputs)
        work = defaultdict(float)
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
                unresolved.append(f"{name}: decommissioning does not refund investments")
            if added:
                recipe = facility["construction_resources_t"]
                if recipe is None:
                    unresolved.append(f"{name}: no construction Recipe for {fid}")
                else:
                    for resource, quantity in recipe.items():
                        capital[(node, resource)] += added * quantity
                    if not facility["self_deploying"]:
                        work[(node, "construction_work")] += added * (facility["construction_work"] or 0)
            for resource, quantity in (facility["maintenance_per_day_t"] or {}).items():
                daily_input[(node, resource)] += quantity * count
            for resource, quantity in facility["operating_per_day_t"].items():
                daily_input[(node, resource)] += quantity * count
        for (node, vid), count in sorted(fleet_target.items()):
            vehicle = defs["vehicles"][vid]
            added = max(0, count - fleet.get((node, vid), 0))
            for resource, quantity in vehicle["production_resources_t"].items():
                capital[(node, resource)] += added * quantity
            if vehicle["production_service_type"] and added:
                work[(node, vehicle["production_service_type"])] += added * vehicle["production_days"]
        for resource, quantity in prototype_materials.items():
            capital[("unallocated_research", resource)] += quantity
        work[("unallocated_research", "prototype_work")] += prototype_work
        work[("unallocated_research", "demonstration_work")] += demonstration_work
        generation = execution = pool = 0.0
        for (node, fid), count in facilities.items():
            provider = defs["facilities"][fid]["research_provider"]
            if provider:
                generation += count * provider["generation_points_per_day"]
                execution += count * provider["research_execution_per_day"]
                pool += count * provider["storage_capacity_points"]
        for (node, vid), count in fleet_target.items():
            for provider in defs["vehicles"][vid]["research_providers"]:
                generation += count * provider["generation_points_per_day"]
                execution += count * provider["research_execution_per_day"]
                pool += count * provider["storage_capacity_points"]
        nominal_rate = min(generation, execution)
        budget = nominal_rate * interval_days * share
        construction_supply = defaultdict(float)
        for (node, fid), count in facilities.items():
            construction_supply[node] += count * defs["facilities"][fid]["construction_work_per_day"]
        construction_bounds = [{"node": node, "required_work": amount,
                                "nominal_end_target_work_per_day": construction_supply.get(node, 0.0),
                                "days_lower_bound_at_end_target_capacity": (
                                    amount / construction_supply[node] if construction_supply.get(node, 0) > 0 else None)}
                               for (node, service), amount in sorted(work.items()) if service == "construction_work"]
        stated_supply = {}
        for row in step.get("resource_supply_budgets", []):
            _fields(row, {"node", "resource", "available_t_per_day"},
                    {"node", "resource", "available_t_per_day"}, "resource supply budget")
            if row["node"] not in nodes:
                raise ValueError(f"unknown budget node: {row['node']}")
            _known(defs["resources"], row["resource"], "budget resource")
            key = row["node"], row["resource"]
            if key in stated_supply:
                raise ValueError(f"duplicate resource budget: {key}")
            stated_supply[key] = _number(row["available_t_per_day"], "available_t_per_day")
        resource_budget = []
        for node, resource in sorted(set(capital) | set(daily_input) | set(nominal_output) | set(stated_supply)):
            acquisition = capital.get((node, resource), 0.0)
            daily_capital = acquisition / interval_days
            operation = daily_input.get((node, resource), 0.0)
            output = nominal_output.get((node, resource), 0.0)
            available = stated_supply.get((node, resource))
            total_required_rate = daily_capital + operation
            affordable_capital = None if available is None else (available - operation) * interval_days
            resource_budget.append({"node": node, "resource": resource,
                                    "authored_available_average_t_per_day": available,
                                    "required_average_total_t_per_day_at_end_target_operation": total_required_rate,
                                    "needed_supply_capacity_scale_if_budget_stated":
                                        (total_required_rate / available if available else None)
                                        if available is not None else None,
                                    "operating_input_alone_exceeds_stated_supply_budget":
                                        (operation > available) if available is not None else None,
                                    "affordable_capital_recipe_scale_if_budget_stated":
                                        (max(0.0, affordable_capital) / acquisition if acquisition else None)
                                        if available is not None else None,
                                    "capital_investment_t": acquisition,
                                    "average_capital_requirement_t_per_day_if_spread_over_interval": daily_capital,
                                    "end_target_operation_input_t_per_day": operation,
                                    "end_target_nominal_process_or_extraction_output_t_per_day": output,
                                    "end_target_output_less_average_capital_and_running_input_t_per_day": output - daily_capital - operation})
        if not selected and not any(step.get(field) for field in (
                "production_targets", "facility_targets", "vehicle_targets", "population_targets", "transport_targets", "research_provider")):
            unresolved.append(f"{name}: no new development outcome stated; only inherited targets are assessed" if index else
                              f"{name}: no development outcome specified; time target alone cannot determine Content values")
        # This is NOT cumulative production during growth: all operating rates are end targets.
        stage = {"name": name, "target_cumulative_hours": hours,
                 "interval_play_hours": interval_days / 3600, "interval_game_days_at_base_speed": interval_days,
                 "research": {"selected_ids": selected, "new_prerequisites_and_research": sorted(pending),
                              "theory_rp_cost_at_current_content": rp_cost,
                              "rp_cost_envelope_at_end_target_nominal_capacity": budget,
                              "theory_rp_cost_scale_to_fit_budget": budget / rp_cost if rp_cost else None,
                              "required_generation_and_execution_rp_per_day": required_rp,
                              "research_time_share": share, "nominal_end_target_generation_rp_per_day": generation,
                              "nominal_end_target_execution_rp_per_day": execution,
                              "nominal_end_target_pool_points": pool,
                              "generation_capacity_scale_to_meet_time": required_rp / generation if generation else None,
                              "execution_capacity_scale_to_meet_time": required_rp / execution if execution else None,
                              "prototype_resources_t": dict(sorted(prototype_materials.items())),
                              "prototype_work": prototype_work, "demonstration_work": demonstration_work,
                              "operational_experience_projects": sorted(experiential),
                              "single_provider_options": provider_options},
                 "production_targets": production,
                 "facility_end_targets": [{"node": node, "facility": fid, "count": count}
                                          for (node, fid), count in sorted(facilities.items())],
                 "fleet_end_targets": [{"node": node, "vehicle": vid, "count": count}
                                       for (node, vid), count in sorted(fleet_target.items())],
                 "capital_resources_t": _ledger(capital), "resource_time_budget": resource_budget, "construction_and_production_work": [
                     {"node": node, "service": svc, "quantity": amount}
                     for (node, svc), amount in sorted(work.items()) if amount],
                 "end_target_nominal_capacity": [{"node": node, "service": service, "quantity": value}
                                                  for (node, service), value in sorted(capacity.items()) if value],
                 "end_target_reference_power": [{"node": node, "nominal_reference_generation_mw": value[0],
                                                "nominal_load_mw": value[1], "site_adjustment_not_applied": True}
                                               for node, value in sorted(power.items())],
                 "end_target_nominal_inputs_t_per_day": _ledger(daily_input),
                 "end_target_nominal_process_outputs_t_per_day": _ledger(nominal_output),
                 "construction_work_time_lower_bounds": construction_bounds,
                 "required_average_work_per_day_by_service": [
                     {"node": node, "service": svc, "work_per_day_to_finish_in_interval": amount / interval_days}
                     for (node, svc), amount in sorted(work.items()) if amount],
                 "transport_targets": transport, "population_targets": population,
                 "unresolved_assumptions": sorted(set(unresolved)),
                 "interpretation": "Time-first design envelope, not growth simulation or achieved State. The target asset capacity is an end-state upper bound; build-up, competing allocation, geographic supply, and actual play decisions are not inferred."}
        results.append(stage)
        installed, fleet = facilities, fleet_target
    return {"kind": "balance_pacing", "identity": defs["identity"],
            "format": FORMAT, "prospective_locations": prospective,
            "milestones": results,
            "interpretation": "All milestones share one cumulative baseline. Game-days assume 1 game day per real second at base speed, not a promise of player completion times. All costs, facility performance, RP, transport, and milestone outcomes are editable design variables, not fixed balance contracts."}
