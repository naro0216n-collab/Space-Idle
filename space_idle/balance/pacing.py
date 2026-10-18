"""Whole-horizon, authored development constraints, not a progression simulator.

Every numerical record belongs to one shared time/site/resource/capacity graph.
The model makes no implicit build, research, supply, transport or population choice.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite

FORMAT = "space-idle.development-structure.v2"
ACTIVITY_FIELDS = {
    "research": {"definition", "node"},
    "facility": {"definition", "node", "target_count"},
    "vehicle": {"definition", "node", "target_count"},
    "process": {"definition", "node", "facility", "rate_per_day"},
    "extraction": {"definition", "node", "facility", "rate_per_day"},
    "transport": {"source", "destination", "resource", "rate_per_day", "vehicle"},
    "population": {"node", "people", "housing_facility", "life_support_facility"},
}
REQUIRED_FIELDS = {
    "research": {"definition"},
    "facility": {"definition", "node", "target_count"},
    "vehicle": {"definition", "node", "target_count"},
    "process": {"definition", "node", "facility", "rate_per_day"},
    "extraction": {"definition", "node", "facility", "rate_per_day"},
    "transport": {"source", "destination", "resource", "rate_per_day"},
    "population": {"node", "people"},
}


def _shape(value, keys, required, label):
    if not isinstance(value, dict) or set(value) - keys or not required <= set(value):
        raise ValueError(f"{label}: expected fields {sorted(keys)}; required {sorted(required)}")
    return value


def _num(value, label, integer=False, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not isfinite(value) or (not isinstance(value, int) if integer else False) or
            value < 0 or (positive and value == 0)):
        raise ValueError(f"{label}: invalid nonnegative quantity")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty text required")
    return value


def _lookup(mapping, key, label):
    if key not in mapping:
        raise ValueError(f"unknown {label}: {key}")
    return mapping[key]


def _closure(definitions, identifiers):
    done, active = set(), set()
    def visit(identifier):
        definition = _lookup(definitions, identifier, "technology")
        if identifier in active:
            raise ValueError("cyclic technology prerequisites")
        if identifier in done:
            return
        active.add(identifier)
        for prerequisite in definition["prerequisites"]:
            visit(prerequisite)
        active.remove(identifier)
        done.add(identifier)
    for identifier in identifiers:
        visit(identifier)
    return done


def evaluate(defs: dict, design: dict, *, transport_preview=None) -> dict:
    """Evaluate ONE coupled design over all periods using canonical projected coefficients.

    Activity counts are explicit end-targets, rates are nominal end-period plans.
    State transitions, elapsed operation and fulfillment remain unknown until
    verified by the GameApplication. Nothing is optimized or auto-acquired.
    """
    _shape(design, {"format", "development", "periods", "prospective_locations"},
           {"format", "development", "periods"}, "design")
    if design["format"] != FORMAT:
        raise ValueError("unsupported development-structure format")
    development = _shape(design["development"], {"intent", "objectives"},
                         {"intent", "objectives"}, "development")
    _text(development["intent"], "whole-development intent")
    objectives = {}
    for row in development["objectives"]:
        _shape(row, {"id", "purpose", "role", "relationships"},
               {"id", "purpose", "role", "relationships"}, "objective")
        identifier = _text(row["id"], "objective id")
        if identifier in objectives:
            raise ValueError("duplicate objective id")
        _text(row["purpose"], "objective purpose")
        _text(row["role"], "engineering role")
        if not isinstance(row["relationships"], list) or not row["relationships"]:
            raise ValueError("objective must identify other development relationships")
        objectives[identifier] = row
    if not objectives:
        raise ValueError("development requires objectives")
    for obj in objectives.values():
        for other in obj["relationships"]:
            if other not in objectives or other == obj["id"]:
                raise ValueError(f"unresolved objective relationship: {other}")
    periods = design["periods"]
    if not isinstance(periods, list) or not periods:
        raise ValueError("development requires a nonempty period sequence")
    known_nodes = {row["id"] for row in defs["world"]["nodes"]}
    bodies = {row["id"] for row in defs["world"]["bodies"]}
    prospective = {}
    for row in design.get("prospective_locations", []):
        _shape(row, {"id", "body_id"}, {"id", "body_id"}, "prospective location")
        if row["id"] in known_nodes or row["id"] in prospective or row["body_id"] not in bodies:
            raise ValueError("invalid prospective location")
        prospective[row["id"]] = row["body_id"]
    all_nodes = known_nodes | set(prospective)

    facility_plan = {(r["node"], r["facility"]): r["count"] for r in defs["owned"]["facilities"]}
    actual_facilities = dict(facility_plan)
    fleet_plan = {(r["node"], r["vehicle"]): r["count"] for r in defs["owned"]["fleet"]}
    actual_fleet = dict(fleet_plan)
    starting_completed = set(defs["owned"]["completed_technologies"])
    planned_technologies = set(starting_completed)
    initial_stock = {(r["node"], r["resource"]): r["available_t"] for r in defs["owned"]["available_inventory"]}
    active_operations = {}  # explicit period-end plan, inherited across periods
    used_period_ids, used_activity_ids = set(), set()
    transactions, dependencies, issues, period_rows = [], [], [], []
    activity_objectives = {}
    asset_authorship = {}
    previous_hours = 0

    def transaction(period, activity, origin, destination, unit, amount, basis, *, definition=None):
        _num(amount, "transaction quantity")
        if not amount:
            return
        transactions.append({"id": f"q{len(transactions)}", "period": period, "activity": activity,
                             "source": origin, "sink": destination, "unit": unit,
                             "quantity": amount, "basis": basis, "definition": definition})

    def dependency(period, activity, key, relation, status, *, quantity=None):
        dependencies.append({"period": period, "activity": activity, "condition": key,
                             "relation": relation, "status": status, "quantity": quantity})

    def issue(period, activity, code, condition, meaning):
        issues.append({"period": period, "activity": activity, "code": code,
                       "condition": condition, "whole_horizon_implication": meaning})

    def facility_requirements(period, activity, node, fid, added):
        spec = defs["facilities"][fid]
        if added <= 0:
            return
        if spec["construction_resources_t"] is None:
            issue(period, activity, "construction_recipe_unprojected", fid, "Capital procurement cannot be connected")
        else:
            for resource, amount in spec["construction_resources_t"].items():
                transaction(period, activity, f"resource:{node}:{resource}", f"capital:{node}:{fid}", "tonnes", added * amount, "planned_capital", definition=fid)
        if not spec["self_deploying"]:
            if spec["construction_work"] is None:
                issue(period, activity, "construction_work_unprojected", fid, "Work requirement remains unknown")
            else:
                transaction(period, activity, f"capacity:{node}:construction_work", f"capital:{node}:{fid}", "work", added * spec["construction_work"], "planned_capital", definition=fid)

    for entry in periods:
        _shape(entry, {"id", "cumulative_hours", "purpose", "activities"},
               {"id", "cumulative_hours", "purpose", "activities"}, "period")
        period = _text(entry["id"], "period id")
        if period in used_period_ids:
            raise ValueError("duplicate period")
        used_period_ids.add(period)
        _text(entry["purpose"], "period purpose")
        hours = _num(entry["cumulative_hours"], "cumulative_hours", positive=True)
        if hours <= previous_hours:
            raise ValueError("cumulative_hours must increase")
        duration = (hours - previous_hours) * 3600
        previous_hours = hours
        if not isinstance(entry["activities"], list):
            raise ValueError("activities must be a list")
        objective_counts = defaultdict(int)
        introduced = []
        acquisitions = []
        for activity in entry["activities"]:
            _shape(activity, {"id", "objective", "kind"} | set().union(*ACTIVITY_FIELDS.values()),
                   {"id", "objective", "kind"}, "activity")
            aid = _text(activity["id"], "activity id")
            if aid in used_activity_ids:
                raise ValueError("activity IDs must be unique across the horizon")
            used_activity_ids.add(aid)
            objective = _lookup(objectives, activity["objective"], "objective")
            kind = activity["kind"]
            if kind not in ACTIVITY_FIELDS:
                raise ValueError("unknown activity type")
            _shape(activity, {"id", "objective", "kind"} | ACTIVITY_FIELDS[kind],
                   {"id", "objective", "kind"} | REQUIRED_FIELDS[kind], "activity")
            activity_objectives[aid] = objective["id"]
            objective_counts[objective["id"]] += 1
            introduced.append(aid)
            node = activity.get("node")
            if kind not in {"research", "transport"} and node not in all_nodes:
                raise ValueError(f"unknown node: {node}")
            target = activity.get("definition")
            if kind == "research":
                if node is not None and node not in all_nodes:
                    raise ValueError("invalid research site")
                needed = _closure(defs["research"], [target]) - planned_technologies
                planned_technologies.update(needed)
                for rid in sorted(needed):
                    definition = defs["research"][rid]
                    for prerequisite in definition["prerequisites"]:
                        dependency(period, aid, f"technology:{prerequisite}", "prerequisite",
                                   "actual_at_start" if prerequisite in starting_completed else "planned_not_verified")
                    for stage in definition["stages"]:
                        if stage["kind"] == "theory":
                            transaction(period, aid, "capacity:global:research_execution", f"technology:{rid}", "rp", stage["rp"], "planned_acquisition", definition=rid)
                        elif stage["kind"] == "prototype":
                            for resource, amount in stage["resources_t"].items():
                                if node is None:
                                    issue(period, aid, "research_site_unselected", rid, "Prototype material location and logistics remain undecided")
                                transaction(period, aid, f"resource:{node or 'unallocated'}:{resource}", f"technology:{rid}", "tonnes", amount, "planned_capital", definition=rid)
                            transaction(period, aid, f"capacity:{node or 'unallocated'}:prototype_work", f"technology:{rid}", "work", stage["work"], "planned_acquisition", definition=rid)
                        elif stage["kind"] == "demonstration":
                            transaction(period, aid, f"capacity:{node or 'unallocated'}:demonstration_work", f"technology:{rid}", "work", stage["work"], "planned_acquisition", definition=rid)
                        if stage["kind"] == "operational_experience" or stage["execution_requirements"]:
                            issue(period, aid, "research_stage_execution_unverified", rid, "Research stages require actual Application execution")
                if needed:
                    acquisitions.append(aid)
            elif kind in {"facility", "vehicle"}:
                field = "facilities" if kind == "facility" else "vehicles"
                spec = _lookup(defs[field], target, field)
                count = _num(activity.get("target_count"), "target_count", integer=True)
                index = (node, target)
                previous = (facility_plan if kind == "facility" else fleet_plan).get(index, 0)
                (facility_plan if kind == "facility" else fleet_plan)[index] = count
                asset_authorship[(kind, node, target)] = aid
                if count < previous:
                    issue(period, aid, "retirement_not_executed", target, "Reclaimed assets and materials not assumed")
                added = max(0, count - previous)
                if added:
                    acquisitions.append(aid)
                    if kind == "facility":
                        facility_requirements(period, aid, node, target, added)
                    else:
                        for resource, amount in spec["production_resources_t"].items():
                            transaction(period, aid, f"resource:{node}:{resource}", f"capital:{node}:{target}", "tonnes", added * amount, "planned_capital", definition=target)
                        if spec["production_service_type"]:
                            transaction(period, aid, f"capacity:{node}:{spec['production_service_type']}", f"capital:{node}:{target}", "work", added * spec["production_days"], "planned_capital", definition=target)
                if kind == "facility":
                    for prerequisite in spec["prerequisites"]:
                        dependency(period, aid, f"technology:{prerequisite}", "unlock",
                                   "actual_at_start" if prerequisite in starting_completed else "planned_not_verified" if prerequisite in planned_technologies else "unselected")
                dependency(period, aid, f"asset:{node}:{target}", "planned_target", "actual_at_start" if count == (actual_facilities if kind == "facility" else actual_fleet).get(index, 0) and previous == count else "planned_not_verified", quantity=count)
                if node in prospective:
                    issue(period, aid, "site_not_founded", node, "Founding, delivery and site eligibility are not established")
            elif kind in {"process", "extraction"}:
                table = "processes" if kind == "process" else "extraction"
                method = _lookup(defs[table], target, table)
                fid = _text(activity.get("facility"), "operating facility")
                _lookup(defs["facilities"], fid, "operating facility")
                if fid not in method["provider_facilities"]:
                    raise ValueError("facility cannot perform selected method")
                rate = _num(activity.get("rate_per_day"), "rate_per_day")
                active_operations[(kind, node, target, fid)] = (aid, activity)
                for tech in set(method["prerequisites"]) | set(defs["facilities"][fid]["prerequisites"]):
                    dependency(period, aid, f"technology:{tech}", "unlock",
                               "actual_at_start" if tech in starting_completed else
                               "planned_not_verified" if tech in planned_technologies else "unselected")
            elif kind == "transport":
                source, destination, resource = (activity.get(k) for k in ("source", "destination", "resource"))
                if source not in all_nodes or destination not in all_nodes or source == destination:
                    raise ValueError("invalid transport pair")
                _lookup(defs["resources"], resource, "resource")
                rate = _num(activity.get("rate_per_day"), "rate_per_day")
                active_operations[(kind, source, destination, resource)] = (aid, activity)
                if activity.get("vehicle") is not None:
                    _lookup(defs["vehicles"], activity["vehicle"], "vehicle")
            elif kind == "population":
                people = _num(activity.get("people"), "people", integer=True)
                active_operations[(kind, node)] = (aid, activity)
        # The *same* period ledger carries acquisitions, continuous operations,
        # shared capacities, transport and research. Neither reference stock nor
        # nominal process output becomes realized supply automatically.
        period_tx_start = next((i for i, t in enumerate(transactions) if t["period"] == period), len(transactions))
        process_capacity = defaultdict(float)
        required_fleet = defaultdict(int)
        fleet_commitment_known = set()
        for key, (aid, activity) in sorted(active_operations.items()):
            kind = key[0]
            if kind in {"process", "extraction"}:
                _, node, method_id, fid = key
                rate = activity["rate_per_day"]
                if not rate:
                    continue
                spec = defs["facilities"][fid]
                unit_capacity = (spec["process_throughput_per_day"] if kind == "process"
                                 else spec["extraction_capacity_t_per_day"])
                if not unit_capacity:
                    raise ValueError("selected facility has no nominal method capacity")
                process_capacity[(node, fid)] += rate / unit_capacity
                if kind == "process":
                    method = defs["processes"][method_id]
                    inp = method["inputs_per_unit_t"]
                    out = method["outputs_per_unit_t"]
                else:
                    method = defs["extraction"][method_id]
                    inp = {}
                    out = {method["output_resource_id"]: 1}
                    issue(period, aid, "extraction_site_unverified", node,
                          "Geology, site eligibility, Survey knowledge and allocation remain conditional")
                for resource, amount in inp.items():
                    transaction(period, aid, f"resource:{node}:{resource}", f"activity:{aid}",
                                "tonnes_per_day", amount * rate, "planned_continuous_input", definition=method_id)
                for resource, amount in out.items():
                    transaction(period, aid, f"activity:{aid}", f"resource:{node}:{resource}",
                                "tonnes_per_day", amount * rate, "conditional_nominal_output", definition=method_id)
                if node in prospective:
                    issue(period, aid, "site_not_founded", node, "Site founding and construction are not established")
            elif kind == "transport":
                _, source, destination, resource = key
                rate = activity["rate_per_day"]
                if not rate:
                    continue
                transaction(period, aid, f"resource:{source}:{resource}", f"route:{source}:{destination}:{resource}",
                            "tonnes_per_day", rate, "planned_continuous_input")
                transaction(period, aid, f"route:{source}:{destination}:{resource}", f"resource:{destination}:{resource}",
                            "tonnes_per_day", rate, "conditional_arrival_not_delivered")
                vehicle = activity.get("vehicle")
                if vehicle is None:
                    issue(period, aid, "transport_vehicle_unselected", f"{source}:{destination}",
                          "Fleet commitment, movement delay and delivered supply remain undecided")
                elif source in known_nodes and destination in known_nodes and transport_preview is not None:
                    try:
                        preview = transport_preview(vehicle, source, destination, rate)
                        units = preview.get("required_units")
                        if isinstance(units, int) and units > 0:
                            required_fleet[(source, vehicle)] += units
                            fleet_commitment_known.add((source, vehicle))
                        else:
                            issue(period, aid, "transport_preview_no_required_units", f"{source}:{destination}",
                                  "Fleet use cannot be related to the planned fleet without a valid Preview")
                        dependency(period, aid, f"fleet:{source}:{vehicle}", "canonical_transport_preview",
                                   "conditional_not_executed", quantity=preview)
                    except (ValueError, RuntimeError, KeyError) as exc:
                        issue(period, aid, "transport_preview_unresolved", str(exc),
                              "Route eligibility, round trip and vehicle commitment unverified")
                else:
                    issue(period, aid, "transport_preview_unavailable", f"{source}:{destination}",
                          "Route and travel time have not been confirmed by Application")
            elif kind == "population":
                _, node = key
                people = activity["people"]
                if node in prospective and people:
                    issue(period, aid, "site_not_founded", node,
                          "Population cannot exist in the proposed site until actual founding")
                dependency(period, aid, f"population:{node}", "population_end_goal",
                           "planned_not_verified", quantity=people)
                for field, attribute, capacity_key in (("housing_facility", "housing", "housing_capacity"),
                                                        ("life_support_facility", "life_support", "life_support_person_days_per_day")):
                    fid = activity.get(field)
                    if not fid:
                        if people:
                            issue(period, aid, f"{attribute}_method_unselected", node,
                                  "Population growth and sustained housing/supply remain undecided")
                        continue
                    spec = _lookup(defs["facilities"], fid, "population support facility")
                    capacity = spec[capacity_key]
                    if not capacity:
                        raise ValueError("population support facility cannot provide specified service")
                    for tech in spec["prerequisites"]:
                        dependency(period, aid, f"technology:{tech}", "population_provider_unlock",
                                   "actual_at_start" if tech in starting_completed else
                                   "planned_not_verified" if tech in planned_technologies else "unselected")
                    dependency(period, aid, f"capacity:{node}:{attribute}", "population_support",
                               "conditional_not_verified", quantity=people)
                    if people > facility_plan.get((node, fid), 0) * capacity:
                        issue(period, aid, "planned_population_capacity_inadequate", fid,
                              "Population and infrastructure plans are not aligned")
                    if attribute == "life_support":
                        for resource, amount in spec["life_support_resources_per_person_day_t"].items():
                            transaction(period, aid, f"resource:{node}:{resource}", f"population:{node}",
                                        "tonnes_per_day", people * amount, "planned_continuous_input", definition=fid)
                if people:
                    issue(period, aid, "population_transition_unverified", node,
                          "Passengers and natural increase require GameApplication validation")

        for (node, vehicle), needed in sorted(required_fleet.items()):
            planned = fleet_plan.get((node, vehicle), 0)
            dependency(period, f"fleet:{node}:{vehicle}", f"fleet:{node}:{vehicle}",
                       "concurrent_transport_commitment", "not_executed",
                       quantity={"nominal_required_units": needed, "planned_units": planned})
            if needed > planned:
                issue(period, f"fleet:{node}:{vehicle}", "transport_shared_fleet_insufficient", vehicle,
                      "Multiple routes contend for the same finite planned fleet")
        # Continuing operation of all planned assets participates in the SAME
        # demand and service ledger as new investments, never an independent KPI.
        generation = defaultdict(float)
        capability = defaultdict(float)
        research_capacity = {"rp_generation": 0., "research_execution": 0., "rp_pool": 0.}
        for (node, fid), count in sorted(facility_plan.items()):
            if not count:
                continue
            spec = defs["facilities"][fid]
            provenance = asset_authorship.get(("facility", node, fid), f"asset:{node}:{fid}")
            if spec["maintenance_per_day_t"] is None:
                issue(period, provenance, "maintenance_recipe_unprojected", fid,
                      "Continuing Resource requirement is not specified as a known zero")
            for resource, amount in (spec["maintenance_per_day_t"] or {}).items():
                transaction(period, provenance, f"resource:{node}:{resource}", f"asset:{node}:{fid}",
                            "tonnes_per_day", amount * count, "planned_continuous_input", definition=fid)
            for resource, amount in spec["operating_per_day_t"].items():
                transaction(period, provenance, f"resource:{node}:{resource}", f"asset:{node}:{fid}",
                            "tonnes_per_day", amount * count, "planned_continuous_input", definition=fid)
            generation[node] += count * spec["power_reference_generation_mw"]
            capability[(node, "power_load_mw")] += count * spec["power_load_mw"]
            capability[(node, "construction_work")] += count * spec["construction_work_per_day"]
            for service, amount in spec["services_per_day"].items():
                capability[(node, service)] += count * amount
            rp = spec["research_provider"]
            if rp:
                research_capacity["rp_generation"] += count * rp["generation_points_per_day"]
                research_capacity["research_execution"] += count * rp["research_execution_per_day"]
                research_capacity["rp_pool"] += count * rp["storage_capacity_points"]
        for (node, vid), count in sorted(fleet_plan.items()):
            for rp in defs["vehicles"][vid]["research_providers"]:
                research_capacity["rp_generation"] += count * rp["generation_points_per_day"]
                research_capacity["research_execution"] += count * rp["research_execution_per_day"]
                research_capacity["rp_pool"] += count * rp["storage_capacity_points"]
        for (node, fid), required_units in sorted(process_capacity.items()):
            available = facility_plan.get((node, fid), 0)
            if required_units > available + 1e-9:
                issue(period, f"asset:{node}:{fid}", "process_capacity_unproven", fid,
                      "Concurrent selected processes may exceed planned installed assets")
            dependency(period, f"asset:{node}:{fid}", f"capacity:{node}:{fid}", "concurrent_operation",
                       "conditional_nominal", quantity={"concurrent_nominal_units_required": required_units, "planned_end_units": available})
        for node, load in ((node, amount) for (node, kind), amount in capability.items() if kind == "power_load_mw"):
            if load > generation[node]:
                issue(period, f"capacity:{node}:power", "power_reference_insufficient", node,
                      "Power and process/research activity share a nominal capacity constraint")
        required_work = defaultdict(float)
        for txn in transactions[period_tx_start:]:
            if txn["unit"] == "work" and txn["source"].startswith("capacity:"):
                parts = txn["source"].split(":", 2)
                required_work[(parts[1], parts[2])] += txn["quantity"]
        for (node, service), amount in sorted(required_work.items()):
            nominal = capability.get((node, service), 0.)
            dependency(period, f"capacity:{node}:{service}", f"capacity:{node}:{service}",
                       "capital_work_over_interval", "planned_end_capacity_not_whole_interval",
                       quantity={"total_required_work": amount,
                                 "average_required_per_day": amount / duration,
                                 "planned_end_work_per_day": nominal})
            if amount / duration > nominal:
                issue(period, f"capacity:{node}:{service}", "work_nominal_rate_insufficient", service,
                      "Capital work competes with the installed work capacity over time")
        for (node, svc), amount in sorted(capability.items()):
            dependency(period, f"capacity:{node}:{svc}", f"capacity:{node}:{svc}", "planned_end_capacity",
                       "not_whole_interval", quantity=amount)
        for node, amount in sorted(generation.items()):
            dependency(period, f"capacity:{node}:power", f"capacity:{node}:power", "planned_end_generation",
                       "site_condition_unverified", quantity=amount)
        required_rp = sum(t["quantity"] for t in transactions[period_tx_start:]
                          if t["unit"] == "rp") / duration
        dependency(period, "global:research", "capacity:global:research_execution", "interval_average_rp",
                   "conditional_not_scheduled", quantity={"required_rp_per_day": required_rp,
                   "planned_end": research_capacity})
        if required_rp > min(research_capacity["rp_generation"], research_capacity["research_execution"]):
            issue(period, "global:research", "research_nominal_rate_insufficient", period,
                  "Generation and execution compete with acquisition and operation across the interval")
        # Joint resource constraints: co-products are produced in ONE process
        # transaction, never counted again by output-resource independent plans.
        ledgers = defaultdict(lambda: {"capital_t": 0., "operating_t_per_day": 0.,
                                       "conditional_output_t_per_day": 0.,
                                       "conditional_inbound_t_per_day": 0.})
        for txn in transactions[period_tx_start:]:
            origin, destination = txn["source"], txn["sink"]
            if origin.startswith("resource:"):
                tag, node, resource = origin.split(":", 2)
                if txn["unit"] == "tonnes":
                    ledgers[(node, resource)]["capital_t"] += txn["quantity"]
                elif txn["unit"] == "tonnes_per_day":
                    ledgers[(node, resource)]["operating_t_per_day"] += txn["quantity"]
            if destination.startswith("resource:") and txn["unit"] == "tonnes_per_day":
                tag, node, resource = destination.split(":", 2)
                field = ("conditional_inbound_t_per_day" if txn["basis"] == "conditional_arrival_not_delivered"
                         else "conditional_output_t_per_day")
                ledgers[(node, resource)][field] += txn["quantity"]
        for (node, resource), ledger in sorted(ledgers.items()):
            if ledger["capital_t"] or ledger["operating_t_per_day"]:
                status = "selected_conditional_supply" if ledger["conditional_output_t_per_day"] else "supply_method_unselected"
                dependency(period, f"resource:{node}:{resource}", f"resource:{node}:{resource}",
                           "shared_resource_balance", status, quantity={**ledger,
                           "starting_real_stock_t_only": initial_stock.get((node, resource), 0.) if len(period_rows) == 0 else None})
                if not ledger["conditional_output_t_per_day"]:
                    issue(period, f"resource:{node}:{resource}", "supply_method_unselected",
                          f"{node}:{resource}", "Capital, continuous operation and logistics compete for unresolved supply")
        period_rows.append({"id": period, "cumulative_hours": hours, "interval_game_days": duration,
                            "purpose": entry["purpose"], "activity_ids": introduced,
                            "objective_ids": sorted(objective_counts), "new_acquisitions": acquisitions,
                            "planned_end_research_capacity": research_capacity})

    # Connections are computed from the same ledger and dependency records;
    # reducing the displayed detail does not change the whole-horizon judgment.
    connections = defaultdict(lambda: {"periods": set(), "activities": set(), "objectives": set(), "evidence": []})
    for row in transactions:
        for endpoint in (row["source"], row["sink"]):
            if not (endpoint.startswith("resource:") or endpoint.startswith("capacity:") or
                    endpoint.startswith("technology:") or endpoint.startswith("capital:") or endpoint.startswith("route:")):
                continue
            record = connections[endpoint]
            record["periods"].add(row["period"])
            record["activities"].add(row["activity"])
            if row["activity"] in activity_objectives:
                record["objectives"].add(activity_objectives[row["activity"]])
            record["evidence"].append(row["id"])
    for row in dependencies:
        record = connections[row["condition"]]
        record["periods"].add(row["period"])
        record["activities"].add(row["activity"])
        if row["activity"] in activity_objectives:
            record["objectives"].add(activity_objectives[row["activity"]])
    coupled = [{"shared_constraint": key, "periods": sorted(record["periods"]),
                "objectives": sorted(record["objectives"]), "evidence_ids": record["evidence"],
                "relationship": "common_finite_resource_or_capability_not_verified_supply"}
               for key, record in sorted(connections.items())
               if len(record["objectives"]) > 1 or len(record["periods"]) > 1]
    quantified_uses = {activity_objectives[row["activity"]] for row in transactions
                       if row["activity"] in activity_objectives}
    quantified_uses.update(activity_objectives[row["activity"]] for row in dependencies
                           if row["activity"] in activity_objectives and row["quantity"] not in (None, 0))
    return {"kind": "whole_development_constraints", "format": FORMAT, "identity": defs["identity"],
            "development": development, "decision": {"scope": "entire_horizon", "verification": "not_verified",
            "objectives_with_no_quantified_connection": sorted(set(objectives) - quantified_uses),
            "cross_period_and_cross_objective_relations": coupled,
            "periods": [row["id"] for row in period_rows], "unresolved_conditions": issues,
            "objectives_relationships_without_quantified_shared_constraint": [
                {"from": objective, "to": other, "status": "authored_relation_not_physically_connected"}
                for objective, row in sorted(objectives.items()) for other in row["relationships"]
                if not any({objective, other} <= set(link["objectives"]) for link in coupled)],
            "interpretation": "Quantities are design commitments, not actual Game State or a feasibility verdict"},
            "technical_evidence": {"periods": period_rows, "transactions": transactions,
                                  "dependencies": dependencies, "conditions": issues, "shared_constraints": coupled,
                                  "prospective_locations": prospective},
            "interpretation": "One whole-horizon design; no local score, automatic edits or second Simulation"}

# Explicit public name emphasizes that no optimal pacing is inferred.
