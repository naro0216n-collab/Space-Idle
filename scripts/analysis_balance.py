#!/usr/bin/env python3
"""Opt-in quantitative Content comparison; never executes Player Commands or ticks.

Plan phases supply *hypothetical* installed asset counts, selected processes,
operation duty, purchases and flows. Gross requirements and nominal capacities
are computed from registered Definitions. A negative projected stock or a capacity
excess is a planning gap, NOT a successful actual Game State transition. No
resource is generated to repair an infeasible plan.

Usage: python scripts/analysis_balance.py plan.json > report.json
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import json
from math import isfinite
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from space_idle.bootstrap import build_game_application_for_load
from space_idle.power import FixedGeneration, SolarGeneration
from space_idle.shared import DefinitionId


def _number(value, name, *, strictly_positive=False):
    if type(value) not in (int, float) or not isfinite(value) or value < 0 or (strictly_positive and value <= 0):
        raise ValueError(f"{name} must be {'positive' if strictly_positive else 'nonnegative'} and finite")
    return float(value)


def _integer(value, name, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(f"{name} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def _identifier(value, choices, field):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"unknown {field}: {value!r}")
    return value


def _keys(row, allowed, required, context):
    if not isinstance(row, dict) or set(row) - set(allowed) or not set(required) <= set(row):
        raise ValueError(f"invalid {context} fields")


def _accumulate(mapping, key, amount):
    mapping[key] += amount


def _asset_rows(rows, sim, nodes, *, label):
    """One method per Facility block; sum units by definition for construction."""
    result = []
    for row in rows:
        _keys(row, {"node", "facility", "units", "process", "extraction", "duty", "extraction_yield_fraction", "supported_person_days_per_day"},
              {"node", "facility", "units"}, label)
        node = _identifier(row["node"], nodes, "node")
        name = _identifier(row["facility"], sim.facilities.definitions, "facility")
        units = _integer(row["units"], "facility units", positive=True)
        duty = _number(row.get("duty", 1.0), "duty")
        if duty > 1:
            raise ValueError("duty cannot exceed 1")
        definition = sim.facilities.definitions[DefinitionId(name)]
        capabilities = {cap.id for cap in definition.capability_supplies}
        process_id = row.get("process")
        extraction_id = row.get("extraction")
        if extraction_id is None and "extraction_yield_fraction" in row:
            raise ValueError("extraction yield requires an extraction method")
        yield_factor = _number(row.get("extraction_yield_fraction", 0), "extraction_yield_fraction")
        if yield_factor > 1:
            raise ValueError("extraction_yield_fraction cannot exceed 1")
        people = _number(row.get("supported_person_days_per_day", 0), "supported_person_days_per_day")
        support = definition.life_support
        if people > 0 and support is None:
            raise ValueError(f"facility {name} has no Life Support capability")
        if support is not None and people > units * support.person_days_per_day:
            raise ValueError("assigned Life Support exceeds nominal person-days")
        if process_id and extraction_id:
            raise ValueError("one Facility block cannot run a Process and Extraction simultaneously")
        if process_id is not None:
            proc_id = _identifier(process_id, sim.industry.processes, "process")
            if not sim.industry.processes[DefinitionId(proc_id)].required_capabilities <= capabilities:
                raise ValueError(f"process {proc_id} incompatible with facility {name}")
        if extraction_id is not None:
            if sim.extraction is None:
                raise ValueError("no extraction service")
            method_id = _identifier(extraction_id, sim.extraction.specs, "extraction method")
            if not sim.extraction.specs[DefinitionId(method_id)].required_capabilities <= capabilities:
                raise ValueError(f"extraction {method_id} incompatible with facility {name}")
        result.append((node, name, units, process_id, extraction_id, duty, yield_factor, people))
    return sorted(result)


def _fleet_rows(rows, vehicles, nodes, *, label, allow_turnarounds):
    """Fleet holdings are quantities, not synthetic per-unit Vehicle entities."""
    result = {}
    for row in rows:
        allowed = {"node", "vehicle", "units"}
        if allow_turnarounds:
            allowed.add("turnarounds_per_unit_per_day")
        _keys(row, allowed, {"node", "vehicle", "units"}, label)
        node = _identifier(row["node"], nodes, "node")
        vehicle = _identifier(row["vehicle"], vehicles, "vehicle")
        key = (node, vehicle)
        if key in result:
            raise ValueError(f"duplicate Fleet holdings at {key}")
        units = _integer(row["units"], "Fleet units")
        cycles = _number(row.get("turnarounds_per_unit_per_day", 0), "Fleet turnaround frequency")
        result[key] = (units, cycles)
    return result


def _aggregate_by_dimension(rows, dimension, fields):
    """Combine like quantities without netting away shortages at different nodes."""
    grouped = defaultdict(lambda: defaultdict(float))
    for row in rows:
        for field in fields:
            grouped[row[dimension]][field] += row[field]
    return [dict({dimension: name}, **{field: values[field] for field in fields})
            for name, values in sorted(grouped.items())]


def evaluate(plan: dict, *, app=None) -> dict:
    """Compute a multi-phase, multi-node notional balance from actual Definitions.

    No finite allocation, location eligibility or automatic scheduling is solved.
    Scenario authors must explicitly provide solar yield and all outside inflows.
    This is a quantity *demand* model, not a second Game Simulation.
    """
    _keys(plan, {"initial_stock", "initial_facilities", "initial_fleet", "initial_research_points", "phases", "solar_yield"}, {"phases"}, "plan")
    if app is None:
        app = build_game_application_for_load()
    sim, catalog = app._simulation, app._catalog
    nodes = {str(node) for node in sim.spatial.graph.operational_nodes} if hasattr(sim, "spatial") else set()
    # Non-surface nodes and future planned sites may be compared as authored
    # contexts: balance rows are not an eligibility or founding validation.
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("facilities", ()))
    nodes.update(str(row["node"]) for row in plan.get("initial_facilities", ()))
    nodes.update(str(row["node"]) for row in plan.get("initial_stock", ()))
    nodes.update(str(row["node"]) for row in plan.get("initial_fleet", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("fleet", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("vehicle_builds", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("external_rates", ()))
    known_resource = {str(r) for r in catalog.resources}
    stocks = defaultdict(float)
    for row in plan.get("initial_stock", ()):
        _keys(row, {"node", "resource", "amount_t"}, {"node", "resource", "amount_t"}, "initial_stock")
        key = row["node"], _identifier(row["resource"], known_resource, "Resource")
        if key in stocks:
            raise ValueError(f"duplicate initial stock {key}")
        stocks[key] = _number(row["amount_t"], "initial stock")
    solar_yield = {}
    for node, factor in plan.get("solar_yield", {}).items():
        solar_yield[node] = _number(factor, "solar yield")

    initial = _asset_rows(plan.get("initial_facilities", ()), sim, nodes, label="initial facility")
    previous = defaultdict(int)
    for node, name, units, _p, _e, _d, _y, _people in initial:
        previous[(node, name)] += units
    vehicles = {str(vehicle.id): vehicle for vehicle in sim.transport.vehicle_definitions()}
    previous_fleet = {key: units for key, (units, _cycles) in _fleet_rows(
        plan.get("initial_fleet", ()), vehicles, nodes,
        label="initial Fleet", allow_turnarounds=False,
    ).items()}
    stored_research_points = _number(plan.get("initial_research_points", 0), "initial_research_points")
    report = []
    seen_research_stages = set()
    for phase in plan["phases"]:
        _keys(phase, {"name", "days", "facilities", "external_rates", "transfers", "vehicle_builds", "fleet", "research_stages", "research_provider_allocations"},
              {"name", "days", "facilities"}, "phase")
        days = _integer(phase["days"], "phase days", positive=True)
        assets = _asset_rows(phase["facilities"], sim, nodes, label="facility")
        current = defaultdict(int)
        produced = defaultdict(float)
        process_inputs = defaultdict(float)
        extraction_nominal = defaultdict(float)
        extraction_assumed = defaultdict(float)
        maintenance = defaultdict(float)
        construction = defaultdict(float)
        vehicle_inputs = defaultdict(float)
        vehicle_turnaround_inputs = defaultdict(float)
        fleet_report = []
        research_inputs = defaultdict(float)
        life_support_inputs = defaultdict(float)
        life_support_supplied = defaultdict(float)
        life_support_committed = defaultdict(float)
        research_points = 0.0
        research_work = 0.0
        external = defaultdict(float)
        shipped = defaultdict(float)
        received = defaultdict(float)
        work = defaultdict(float)
        power_supply = defaultdict(float)
        power_load = defaultdict(float)
        services = defaultdict(float)
        storage = defaultdict(float)
        # Everything here is a request or nominal nameplate, never settled flow.
        for node, name, units, process_id, extraction_id, duty, yield_factor, people in assets:
            current[(node, name)] += units
            facility = sim.facilities.definitions[DefinitionId(name)]
            mult = units * duty
            if facility.life_support is not None:
                life_support_supplied[node] += facility.life_support.person_days_per_day * mult
                life_support_committed[node] += people
                for resource_id, amount in facility.life_support.net_resources:
                    life_support_inputs[(node, str(resource_id))] += amount * people * days
            if process_id:
                proc = sim.industry.processes[DefinitionId(process_id)]
                for res, quantity in proc.inputs_per_day.items():
                    _accumulate(process_inputs, (node, str(res)), quantity * mult * facility.process_throughput_per_day * days)
                for res, quantity in proc.outputs_per_day.items():
                    _accumulate(produced, (node, str(res)), quantity * mult * facility.process_throughput_per_day * days)
            if extraction_id:
                method = sim.extraction.specs[DefinitionId(extraction_id)]
                _accumulate(extraction_nominal, (node, str(method.output_resource_id)),
                            mult * facility.extraction_capacity_t_per_day * days)
                _accumulate(extraction_assumed, (node, str(method.output_resource_id)),
                            mult * facility.extraction_capacity_t_per_day * days * yield_factor)
                _accumulate(produced, (node, str(method.output_resource_id)),
                            mult * facility.extraction_capacity_t_per_day * days * yield_factor)
            for supply in facility.service_capacity_supplies:
                _accumulate(services, (node, supply.service_type), supply.nominal_rate * mult)
            if facility.id in sim.projects.construction_providers:
                _accumulate(services, (node, "construction_work"),
                            sim.projects.construction_providers[facility.id].work_per_day * mult)
            spec = sim.power.specs.get(facility.id)
            if spec:
                power_load[node] += (spec.load_mw * duty + spec.standby_load_mw * (1 - duty)) * units
                if isinstance(spec.generation, FixedGeneration):
                    power_supply[node] += spec.generation.mw * mult
                elif isinstance(spec.generation, SolarGeneration):
                    if node not in solar_yield:
                        raise ValueError(f"solar_yield for {node} required to compare {name}")
                    power_supply[node] += spec.generation.rated_mw_at_reference_flux * solar_yield[node] * mult
            storage_spec = sim.storage.providers.get(facility.id)
            if storage_spec:
                for pool, amount in storage_spec.capacity_t_by_pool.items():
                    storage[(node, pool)] += amount * units
            recipe = sim.projects.recipes.get(facility.id)
            if recipe:
                for req in recipe.resources:
                    maintenance[(node, str(req.resource_id))] += (req.amount_t * facility.maintenance_fraction_per_year / 365.0
                                                                  * units * days)
        for key in set(current) | set(previous):
            units = current[key]
            if units < previous[key]:
                raise ValueError(f"Facility removal at {key} requires an explicit retirement model")
            delta = units - previous[key]
            if not delta:
                continue
            recipe = sim.projects.recipes.get(DefinitionId(key[1]))
            if recipe is None:
                raise ValueError(f"no construction recipe for {key[1]}")
            for req in recipe.resources:
                construction[(key[0], str(req.resource_id))] += req.amount_t * delta
            work[key[0]] += recipe.construction_work * delta
        facility_units_added = sum(max(0, current[k] - previous[k]) for k in current)
        previous = current
        # RP is an organization-owned numerical dimension, never an Inventory
        # Resource. A research source must be assigned to a real authored
        # Facility group; Fleet providers are deliberately not modeled yet.
        research_generation_per_day = 0.0
        research_storage_nominal = 0.0
        research_execution_per_day = 0.0
        research_crew_demand_per_day = 0.0
        assigned_source_units = defaultdict(int)
        for row in phase.get("research_provider_allocations", ()):
            _keys(row, {"node", "provider", "source_facility", "units", "level", "duty"},
                  {"node", "provider", "source_facility", "units"}, "research provider")
            name = _identifier(row["provider"], sim.research.providers, "research provider")
            provider = sim.research.providers[DefinitionId(name)]
            if provider.source_kind.value != "facility":
                raise ValueError("Fleet-backed research providers require separate Fleet assumptions")
            facility_name = _identifier(row["source_facility"], sim.facilities.definitions, "research source Facility")
            facility = sim.facilities.definitions[DefinitionId(facility_name)]
            if not provider.required_source_capabilities <= {c.id for c in facility.capability_supplies}:
                raise ValueError("research provider not compatible with source Facility")
            units = _integer(row["units"], "research source units", positive=True)
            key = (row["node"], facility_name)
            assigned_source_units[key] += units
            if assigned_source_units[key] > current[key]:
                raise ValueError(f"research provider requires more installed Facilities: {key}")
            level = _integer(row.get("level", 1), "research provider level", positive=True)
            level_spec = next((candidate for candidate in provider.levels if candidate.level == level), None)
            if level_spec is None:
                raise ValueError(f"unknown research provider level: {name}/{level}")
            duty = _number(row.get("duty", 1), "research provider duty")
            if duty > 1:
                raise ValueError("research provider duty cannot exceed 1")
            research_generation_per_day += units * duty * level_spec.generation_points_per_day
            research_execution_per_day += units * duty * level_spec.research_execution_per_day
            research_storage_nominal += units * level_spec.storage_capacity_points
            research_crew_demand_per_day += (units * duty * level_spec.generation_points_per_day
                                              * provider.crew_person_days_per_research_point)
        # Asset counts, unlike production work orders, persist across phases.
        # An explicit Fleet composition describes the *whole* current holding;
        # otherwise build orders accumulate on the existing holding.
        if "fleet" in phase and phase.get("vehicle_builds"):
            raise ValueError("fleet holdings and vehicle_builds cannot both specify acquisitions")
        fleet_spec = _fleet_rows(phase.get("fleet", ()), vehicles, nodes,
                                 label="Fleet", allow_turnarounds=True) if "fleet" in phase else None
        builds = defaultdict(int)
        if fleet_spec is not None:
            current_fleet = {key: units for key, (units, _cycles) in fleet_spec.items()}
            for key in set(previous_fleet) | set(current_fleet):
                delta = current_fleet.get(key, 0) - previous_fleet.get(key, 0)
                if delta < 0:
                    raise ValueError(f"Fleet removal at {key} requires explicit retirement/relocation assumptions")
                builds[key] = delta
        else:
            current_fleet = dict(previous_fleet)
            for row in phase.get("vehicle_builds", ()):
                _keys(row, {"node", "vehicle", "units"}, {"node", "vehicle", "units"}, "vehicle build")
                key = (_identifier(row["node"], nodes, "node"),
                       _identifier(row["vehicle"], vehicles, "vehicle"))
                builds[key] += _integer(row["units"], "vehicle units", positive=True)
                current_fleet[key] = current_fleet.get(key, 0) + row["units"]
        for (node, vehicle_id), added in sorted(builds.items()):
            vehicle = vehicles[vehicle_id]
            for res, amount in vehicle.production.resources:
                vehicle_inputs[(node, str(res))] += amount * added
            if vehicle.production.service_type:
                services[(node, f"required:{vehicle.production.service_type}")] += added * vehicle.production.days / days
        for (node, vehicle_id), units in sorted(current_fleet.items()):
            if units == 0:
                continue
            vehicle = vehicles[vehicle_id]
            cycles_per_unit = fleet_spec.get((node, vehicle_id), (units, 0))[1] if fleet_spec is not None else 0
            cycles = units * cycles_per_unit * days
            for resource, amount in vehicle.maintenance.resources:
                vehicle_turnaround_inputs[(node, str(resource))] += amount * cycles
            if vehicle.maintenance.service_type:
                services[(node, f"required:{vehicle.maintenance.service_type}")] += (
                    cycles * vehicle.maintenance.turnaround_days / days
                )
            fleet_report.append({"node": node, "vehicle": vehicle_id,
                                 "units": units, "units_built": builds.get((node, vehicle_id), 0),
                                 "assumed_turnarounds": cycles})
        previous_fleet = current_fleet
        for row in phase.get("research_stages", ()):
            _keys(row, {"node", "research", "stage"}, {"node", "research", "stage"}, "research stage")
            rid = _identifier(row["research"], sim.research.definitions, "research")
            definition = sim.research.definitions[DefinitionId(rid)]
            try:
                spec = definition.stage_spec(row["stage"])
            except KeyError as exc:
                raise ValueError(f"unknown Research Stage: {rid}/{row['stage']}") from exc
            key = (rid, spec.stage_id)
            if key in seen_research_stages:
                raise ValueError(f"duplicate Research Stage across phases: {rid}/{spec.stage_id}")
            seen_research_stages.add(key)
            if hasattr(spec, "resources"):
                for res, amount in spec.resources.items():
                    research_inputs[(row["node"], str(res))] += amount
            research_points += getattr(spec, "research_point_cost", 0.0)
            research_work += getattr(spec, "required_work", 0.0)
        for row in phase.get("external_rates", ()):
            _keys(row, {"node", "resource", "net_t_per_day"}, {"node", "resource", "net_t_per_day"}, "external rate")
            _identifier(row["resource"], known_resource, "Resource")
            rate = row["net_t_per_day"]
            if type(rate) not in (int, float) or not isfinite(rate):
                raise ValueError("external rate must be finite")
            external[(row["node"], row["resource"])] += rate * days
        # Transfers are an authored delivered-volume assumption, NOT routing or
        # Fleet dispatch. Origin debit and destination credit use the same mass;
        # per-day cargo handling demand is separately exposed for each end.
        for row in phase.get("transfers", ()):
            _keys(row, {"origin", "destination", "resource", "t_per_day"},
                  {"origin", "destination", "resource", "t_per_day"}, "transfer")
            origin, dest = row["origin"], row["destination"]
            if origin == dest:
                raise ValueError("transfer requires two distinct nodes")
            res = _identifier(row["resource"], known_resource, "Resource")
            amount = _number(row["t_per_day"], "transfer rate") * days
            shipped[(origin, res)] += amount
            received[(dest, res)] += amount
            services[(origin, "required:cargo_transfer")] += amount / days
            services[(dest, "required:cargo_transfer")] += amount / days
        end = {}
        keys = set(stocks) | set(produced) | set(process_inputs) | set(maintenance) | set(construction) | set(vehicle_inputs) | set(vehicle_turnaround_inputs) | set(research_inputs) | set(life_support_inputs) | set(external) | set(shipped) | set(received)
        breakdown = []
        for key in sorted(keys):
            start = stocks[key]
            delta = (produced[key] - process_inputs[key] - maintenance[key] - construction[key]
                     - vehicle_inputs[key] - vehicle_turnaround_inputs[key] - research_inputs[key] - life_support_inputs[key] + external[key] - shipped[key] + received[key])
            end[key] = start + delta
            breakdown.append({
                "node": key[0], "resource": key[1], "start_t": start,
                "production_t": produced[key], "process_demand_t": process_inputs[key],
                "maintenance_demand_t": maintenance[key], "construction_demand_t": construction[key],
                "vehicle_build_demand_t": vehicle_inputs[key], "fleet_turnaround_demand_t": vehicle_turnaround_inputs[key], "research_material_demand_t": research_inputs[key],
                "life_support_demand_t": life_support_inputs[key],
                "external_net_t": external[key],
                "shipped_t": shipped[key], "received_t": received[key],
                "net_t": delta, "notional_end_t": end[key],
                "shortfall_t": max(0.0, -end[key]),
            })
        stocks = defaultdict(float, end)
        start_rp = stored_research_points
        generated_rp = research_generation_per_day * days
        stored_research_points += generated_rp - research_points
        research_metrics = {
            "start_points": start_rp, "nominal_generation_points": generated_rp,
            "research_stage_demand_points": research_points,
            "notional_end_points": stored_research_points,
            "point_shortfall": max(0.0, -stored_research_points),
            "nominal_storage_capacity_points": research_storage_nominal,
            "storage_excess_points": max(0.0, stored_research_points - research_storage_nominal),
            "nominal_execution_per_day": research_execution_per_day,
            "crew_requirement_person_days_per_day": research_crew_demand_per_day,
        }
        constraints = []
        for node in sorted(set(power_supply) | set(power_load) | set(work) | set(life_support_supplied) | {n for n, _ in services}):
            construction_supply = services[(node, "construction_work")] * days
            constraints.append({
                "node": node, "power_generation_nominal_mw": power_supply[node],
                "power_demand_nominal_mw": power_load[node],
                "power_gap_mw": max(0.0, power_load[node] - power_supply[node]),
                "construction_work_required": work[node],
                "construction_work_nominal_capacity": construction_supply,
                "construction_work_gap": max(0.0, work[node] - construction_supply),
                "life_support_nominal_person_days_per_day": life_support_supplied[node],
                "life_support_assigned_person_days_per_day": life_support_committed[node],
                "life_support_gap_person_days_per_day": max(0.0, life_support_committed[node] - life_support_supplied[node]),
                "cargo_transfer_demand_t_per_day": services[(node, "required:cargo_transfer")],
                "cargo_transfer_nominal_capacity_t_per_day": services[(node, "cargo_transfer")],
                "cargo_transfer_gap_t_per_day": max(0.0, services[(node, "required:cargo_transfer")] - services[(node, "cargo_transfer")]),
            })
        # Demand and nominal supply for every typed Service are exposed side by
        # side. Never treat a missing provider as satisfied or turn this
        # comparison into a second priority allocator.
        service_keys = {(node, name.removeprefix("required:"))
                        for (node, name) in services}
        service_keys.update((node, "construction_work") for node in work)
        service_constraints = []
        for node, service in sorted(service_keys):
            required_per_day = services[(node, f"required:{service}")]
            if service == "construction_work":
                required_per_day += work[node] / days
            nominal = services[(node, service)]
            service_constraints.append({
                "node": node, "service": service,
                "required_per_day": required_per_day,
                "nominal_capacity_per_day": nominal,
                "nominal_gap_per_day": max(0.0, required_per_day - nominal),
            })
        storage_constraints = []
        pool_keys = set(storage)
        pool_keys.update((n, catalog.resources[DefinitionId(r)].storage_pool_key)
                         for (n, r) in end if catalog.resources[DefinitionId(r)].storage_pool_key is not None)
        for node, pool in sorted(pool_keys):
            cap = storage[(node, pool)]
            occupied = sum(max(0.0, amount) for (n, r), amount in end.items()
                           if n == node and catalog.resources[DefinitionId(r)].storage_pool_key == pool)
            storage_constraints.append({"node": node, "pool": pool, "physical_capacity_t": cap,
                                        "notional_occupied_t": occupied,
                                        "capacity_excess_t": max(0.0, occupied - cap)})
        system_resources = _aggregate_by_dimension(breakdown, "resource", (
            "production_t", "process_demand_t", "maintenance_demand_t",
            "construction_demand_t", "vehicle_build_demand_t", "fleet_turnaround_demand_t",
            "research_material_demand_t", "life_support_demand_t", "external_net_t",
            "shipped_t", "received_t", "net_t", "notional_end_t", "shortfall_t",
        ))
        system_services = _aggregate_by_dimension(service_constraints, "service", (
            "required_per_day", "nominal_capacity_per_day", "nominal_gap_per_day",
        ))
        report.append({"name": phase["name"], "days": days, "resources": breakdown,
                       "system_resources": system_resources, "system_services": system_services,
                       "fleet": fleet_report,
                       "scale": {"facility_units": sum(current.values()),
                                 "facility_units_added": facility_units_added,
                                 "fleet_units": sum(current_fleet.values()),
                                 "fleet_units_built": sum(builds.values())},
                       "constraints": constraints, "service_constraints": service_constraints,
                       "storage": storage_constraints,
                       "extraction_projections_t": [dict(node=node, resource=res, nominal_t=q,
                                                         assumed_t=extraction_assumed[(node, res)])
                                                    for (node, res), q in sorted(extraction_nominal.items())],
                       "research_point_demand": research_points,
                       "research_point_balance": research_metrics,
                       "research_work_demand": research_work,
                       "nominal_services_per_day": [dict(node=n, service=s, capacity=q)
                                                     for (n, s), q in sorted(services.items())
                                                     if not s.startswith("required:")]})
    return {"model": "definition_quantity_projection_v1", "content_id": app.content_id,
            "world_definition_id": app.world_definition_id,
            "assumptions": [
                "Requested production, maintenance, construction and transport are not settled Game flow.",
                "Facility changes take effect at phase start; construction work is a separate nominal demand, not scheduled completion.",
                "Negative projected stock records unsatisfied notional demand; no automatic procurement or allocation occurs.",
                "Power and finite service are nominal capacities, not eligibility or maintenance-adjusted availability.",
                "Extraction yield is an explicitly authored fraction of installed capacity, not geology/knowledge/eligibility validation.",
                "Research stages contribute authored RP, work and physical inputs. RP supply requires an authored compatible Facility provider assignment, without technology/site/crew availability validation.",
                "Life Support resource demand uses explicitly assigned person-days and registered per-person rates, not population planning.",
                "Authored transfer arrivals omit travel time and Fleet operation requirements; capacities are compared only.",
                "Fleet holdings are assumed at phase start; new units incur production inputs and work, not scheduled completion.",
                "Fleet turnaround frequency is an explicit activity assumption; no movements, propellant consumption or utilization are inferred.",
                "System totals preserve resource and Service types and sum local shortfalls without transferring excess capacity between nodes.",
                "Solar yield is an authored site flux/availability ratio to reference flux, not a dynamically resolved environment.",
                "Maintenance approximates invested material using base construction recipe; upgrade and salvage are not simulated.",
            ], "phases": report}


def _apply_case_updates(base: dict, updates: list) -> dict:
    """Edit declared quantities, never synthesize a build order or choose an asset."""
    if not isinstance(updates, list):
        raise ValueError("case updates must be a list")
    plan = deepcopy(base)
    # Independently authored phase lists must remain independent even when a
    # Python caller reused the same list object when composing the input.
    for phase in plan["phases"]:
        for collection in ("facilities", "fleet"):
            if collection in phase:
                phase[collection] = [dict(row) for row in phase[collection]]
    seen = set()
    for change in updates:
        _keys(change, {"phase", "collection", "node", "id", "units", "duty",
                       "turnarounds_per_unit_per_day"},
              {"phase", "collection", "node", "id"}, "case update")
        name = change["collection"]
        if name not in ("facilities", "fleet"):
            raise ValueError(f"case updates cannot edit {name!r}")
        if (name == "facilities" and "turnarounds_per_unit_per_day" in change) or (name == "fleet" and "duty" in change):
            raise ValueError("case update attributes do not belong to selected asset kind")
        if not {"units", "duty", "turnarounds_per_unit_per_day"} & set(change):
            raise ValueError("case update must change at least one quantity")
        identity = (change["phase"], name, change["node"], change["id"])
        if identity in seen:
            raise ValueError(f"duplicate case update: {identity}")
        seen.add(identity)
        matched_phases = [row for row in plan["phases"] if row["name"] == change["phase"]]
        if len(matched_phases) != 1:
            raise ValueError(f"case update requires a unique phase: {change['phase']}")
        phase = matched_phases[0]
        key = "facility" if name == "facilities" else "vehicle"
        rows = phase.setdefault(name, [])
        matched = [row for row in rows if row["node"] == change["node"] and row[key] == change["id"]]
        if len(matched) != 1:
            raise ValueError(f"case update requires one existing {name} row: {identity}")
        for field in ("units", "duty", "turnarounds_per_unit_per_day"):
            if field in change:
                matched[0][field] = change[field]
    return plan


def compare_cases(payload: dict, *, app=None) -> dict:
    """Compute several explicitly authored asset compositions with one Content set.

    Comparison never selects a best plan, and reports physical dimensions
    separately rather than summing unlike Resource kinds into a score.
    """
    _keys(payload, {"cases", "base_plan"}, {"cases"}, "case comparison")
    cases = payload["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("comparison requires cases")
    if app is None:
        app = build_game_application_for_load()
    results = []
    names = set()
    for case in cases:
        _keys(case, {"name", "plan", "updates"}, {"name"}, "case")
        if ("plan" in case and ("updates" in case or "base_plan" in payload)) or ("plan" not in case and "base_plan" not in payload):
            raise ValueError("case requires a plan or a shared base_plan with updates, not both")
        if not isinstance(case["name"], str) or not case["name"] or case["name"] in names:
            raise ValueError("case names must be unique and nonempty")
        names.add(case["name"])
        case_plan = (case["plan"] if "plan" in case else
                     _apply_case_updates(payload["base_plan"], case.get("updates", [])))
        results.append({"name": case["name"], "projection": evaluate(case_plan, app=app)})
    differences = []
    baseline = results[0]["projection"]["phases"]
    for alternative in results[1:]:
        alternative_phases = alternative["projection"]["phases"]
        for index, (left, right) in enumerate(zip(baseline, alternative_phases)):
            if left["name"] != right["name"] or left["days"] != right["days"]:
                continue  # Different time bases cannot be compared as like quantities.
            left_rp, right_rp = left["research_point_balance"], right["research_point_balance"]
            rp_delta = {key: right_rp[key] - left_rp[key] for key in left_rp
                        if abs(right_rp[key] - left_rp[key]) > 1e-12}
            if rp_delta:
                differences.append({"case": alternative["name"], "phase": left["name"],
                                    "section": "research_point_balance", "identity": {"pool": "organization"},
                                    "delta_from_baseline": rp_delta})
            for section, key_fields, metrics in (
                ("service_constraints", ("node", "service"),
                 ("required_per_day", "nominal_capacity_per_day", "nominal_gap_per_day")),
                ("system_resources", ("resource",), ("production_t", "process_demand_t",
                      "maintenance_demand_t", "construction_demand_t", "vehicle_build_demand_t",
                      "fleet_turnaround_demand_t", "notional_end_t", "shortfall_t")),
                ("system_services", ("service",), ("required_per_day", "nominal_capacity_per_day",
                       "nominal_gap_per_day")),
                ("resources", ("node", "resource"), ("production_t", "process_demand_t",
                       "maintenance_demand_t", "construction_demand_t", "vehicle_build_demand_t", "fleet_turnaround_demand_t",
                       "research_material_demand_t", "life_support_demand_t", "notional_end_t", "shortfall_t")),
                ("constraints", ("node",), ("power_generation_nominal_mw", "power_demand_nominal_mw",
                       "power_gap_mw", "life_support_nominal_person_days_per_day", "life_support_assigned_person_days_per_day",
                       "life_support_gap_person_days_per_day", "construction_work_required", "construction_work_nominal_capacity",
                       "construction_work_gap", "cargo_transfer_demand_t_per_day", "cargo_transfer_gap_t_per_day")),
                ("fleet", ("node", "vehicle"), ("units", "units_built", "assumed_turnarounds")),
                ("storage", ("node", "pool"), ("physical_capacity_t", "notional_occupied_t",
                       "capacity_excess_t")),
            ):
                def indexed(items):
                    return {tuple(row[key] for key in key_fields): row for row in items}
                l, r = indexed(left[section]), indexed(right[section])
                for key in sorted(set(l) | set(r)):
                    delta = {metric: r.get(key, {}).get(metric, 0.0) - l.get(key, {}).get(metric, 0.0)
                             for metric in metrics}
                    delta = {metric: value for metric, value in delta.items() if abs(value) > 1e-12}
                    if delta:
                        differences.append({"case": alternative["name"], "phase": left["name"],
                                            "section": section, "identity": dict(zip(key_fields, key)),
                                            "delta_from_baseline": delta})
    return {"model": "definition_quantity_comparison_v1", "baseline_case": results[0]["name"],
            "cases": results, "differences": differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON phases specifying Facility counts, duties and material movement")
    args = parser.parse_args()
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    result = compare_cases(payload) if "cases" in payload else evaluate(payload)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    print()


if __name__ == "__main__":
    main()
