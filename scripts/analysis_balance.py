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
from collections import Counter, defaultdict
from copy import deepcopy
import json
from math import isfinite
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from space_idle.bootstrap import build_game_application_for_load
from space_idle.power import FixedGeneration, SolarGeneration
from space_idle.transport import MovementEndpoint
from space_idle.spatial import IlluminationField
from space_idle.shared import DefinitionId, SurfaceCellId, SpatialNodeId
from space_idle.exploration_models import KnowledgeLevel
from space_idle.analysis_graph import DependencyNode
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.execution_requirements import (
    ServiceCapacityRequirement, ResourceRequirement, PoolRequirement,
    PoolAdmissionRequirement, StockOrPoolAdmissionRequirement,
)


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


def _extraction_contexts(rows, sim, nodes, known_resource):
    """Read selected World cells without adding hypothetical Game State.

    Knowledge values here are *scenario claims*, never resolved Survey State.
    A context does not establish Location founding, accessible service or method
    Technology. In particular, no non-surface World node can acquire ore.
    """
    contexts = {}
    graph = sim.extraction.graph
    for row in rows:
        _keys(row, {"node", "developed_cells", "knowledge", "day"},
              {"node", "developed_cells"}, "extraction context")
        node = _identifier(row["node"], nodes, "node")
        if node in contexts:
            raise ValueError(f"duplicate extraction context: {node}")
        if node in {str(key) for key in graph.nodes}:
            raise ValueError(f"non-surface World node cannot contain developed Cells: {node}")
        cells = row["developed_cells"]
        if not isinstance(cells, list) or not cells or len(set(cells)) != len(cells):
            raise ValueError("developed_cells must be nonempty and unique")
        cell_defs = []
        for cell in cells:
            cell_id = _identifier(cell, graph.surface_cells, "Surface Cell")
            cell_defs.append(graph.surface_cells[SurfaceCellId(cell_id)])
        if len({cell.body_id for cell in cell_defs}) != 1:
            raise ValueError("extraction site cannot combine cells from different bodies")
        knowledge = {}
        for value in row.get("knowledge", ()):
            _keys(value, {"cell", "resource", "level"}, {"cell", "resource", "level"}, "survey knowledge")
            if value["cell"] not in cells:
                raise ValueError("knowledge cell must be within selected developed Cells")
            resource = _identifier(value["resource"], known_resource, "Resource")
            if type(value["level"]) is not int:
                raise ValueError("knowledge level must be an integer")
            try:
                level = KnowledgeLevel(value["level"])
            except ValueError as exc:
                raise ValueError("unknown survey knowledge level") from exc
            key = (value["cell"], resource)
            if key in knowledge:
                raise ValueError(f"duplicate Knowledge assumption: {key}")
            knowledge[key] = level
        day = _integer(row.get("day", 0), "World opportunity reference day")
        contexts[node] = {"cells": tuple(cells), "knowledge": knowledge,
                          "body": str(cell_defs[0].body_id), "day": day}
    return contexts


def _graph_evidence(graph_nodes, relation_index, roots) -> dict:
    """Expose the existing typed Graph's conditions and provenance, not extra quantities.

    This lookup is explanatory: a relation is never converted to consumed or
    delivered Resource by the existence of an edge alone.
    """
    nodes = frozenset(DependencyNode(kind, identifier) for kind, identifier in roots)
    included = [root for root in sorted(nodes) if root in graph_nodes]
    relevant = sorted({relation for node in nodes for relation in relation_index.get(node, ())},
                      key=lambda rel: (rel.kind, rel.provenance, rel.source, rel.target))
    return {
        "roots": [{"kind": node.kind, "id": node.id} for node in included],
        "relations": [{"kind": relation.kind,
                       "source": f"{relation.source.kind}:{relation.source.id}",
                       "target": f"{relation.target.kind}:{relation.target.id}",
                       "provenance": relation.provenance, "quantity": relation.quantity,
                       "unit": relation.unit, "time_basis": relation.time_basis,
                       "condition": relation.condition}
                      for relation in relevant],
        "status": "typed_definition_dependencies_not_executed",
    }


def evaluate(plan: dict, *, app=None, _definition_graph=None) -> dict:
    """Compute a multi-phase, multi-node notional balance from actual Definitions.

    No finite allocation, location eligibility or automatic scheduling is solved.
    Unresolved solar factors and all outside inflows require explicit assumptions.
    A selected World site uses the Power owner's context formula instead.
    This is a quantity *demand* model, not a second Game Simulation.
    """
    _keys(plan, {"initial_stock", "initial_facilities", "initial_fleet", "initial_research_points", "phases", "solar_yield", "solar_sites"}, {"phases"}, "plan")
    if app is None:
        app = build_game_application_for_load()
    sim, catalog = app._simulation, app._catalog
    graph = (_definition_graph if _definition_graph is not None else
             build_definition_dependency_graph(sim, catalog))
    graph_nodes = frozenset(graph.nodes)
    relation_index = defaultdict(list)
    for relation in graph.relations:
        relation_index[relation.source].append(relation)
        if relation.target != relation.source:
            relation_index[relation.target].append(relation)
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
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("extraction_sites", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("research_provider_allocations", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("spatial_projects", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("upgrade_projects", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("survey_activities", ()))
    nodes.update(str(row["staging_node"]) for phase in plan["phases"] for row in phase.get("founding_projects", ()))
    nodes.update(str(row["node"]) for phase in plan["phases"] for row in phase.get("market_buys", ()))
    nodes.update(str(row["origin"]) for phase in plan["phases"] for row in phase.get("passenger_transfers", ()))
    nodes.update(str(row["destination"]) for phase in plan["phases"] for row in phase.get("passenger_transfers", ()))
    nodes.update(str(row["origin"]) for phase in plan["phases"] for row in phase.get("transport_allocations", ()))
    nodes.update(str(row["destination"]) for phase in plan["phases"] for row in phase.get("transport_allocations", ()))
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
        solar_yield[_identifier(node, nodes, "solar factor Node")] = _number(factor, "solar yield")
    # A World site is an authored prospective placement, not an actually
    # founded Node or installed Facility. The Power Domain owns the mapping
    # from actual Illumination at that World context to rated generation.
    solar_sites = {}
    available_contexts = ({str(cell) for cell in sim.power.environment.graph.surface_cells}
                          | {str(node) for node in sim.power.environment.graph.nodes})
    for row in plan.get("solar_sites", ()):
        _keys(row, {"node", "facility", "context", "day"},
              {"node", "facility", "context"}, "solar site")
        node = _identifier(row["node"], nodes, "solar site Node")
        facility_id = _identifier(row["facility"], sim.facilities.definitions, "solar site Facility")
        if not isinstance(getattr(sim.power.specs.get(DefinitionId(facility_id)), "generation", None),
                          SolarGeneration):
            raise ValueError("solar World site requires a solar generating Facility")
        context = _identifier(row["context"], available_contexts, "World solar context")
        if node in solar_yield:
            raise ValueError("World solar site conflicts with authored node solar yield")
        key = (node, facility_id)
        if key in solar_sites:
            raise ValueError(f"duplicate solar World site: {key}")
        solar_sites[key] = context, _integer(row.get("day", 0), "solar World reference day")

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
    # Cumulative authored receipts are conditional upon actual Cargo settlement.
    # This is an algebraic lower Stock-bound, not a second logistics scheduler.
    unverified_cargo_receipts = defaultdict(float)
    report = []
    seen_research_stages = set()
    seen_science_campaigns = set()
    seen_phase_names = set()
    previous_assets = initial
    for phase in plan["phases"]:
        _keys(phase, {"name", "days", "facilities", "external_rates", "transfers", "vehicle_builds", "fleet", "research_stages", "research_provider_allocations", "extraction_sites", "transport_allocations", "spatial_projects", "upgrade_projects", "science_campaigns", "survey_activities", "founding_projects", "passenger_transfers", "market_buys", "assumed_funds_musd"},
              {"name", "days", "facilities"}, "phase")
        if not isinstance(phase["name"], str) or not phase["name"] or phase["name"] in seen_phase_names:
            raise ValueError("phase names must be unique and nonempty")
        seen_phase_names.add(phase["name"])
        days = _integer(phase["days"], "phase days", positive=True)
        assets = _asset_rows(phase["facilities"], sim, nodes, label="facility")
        extraction_contexts = _extraction_contexts(phase.get("extraction_sites", ()),
                                                    sim, nodes, known_resource)
        current = defaultdict(int)
        produced = defaultdict(float)
        process_inputs = defaultdict(float)
        extraction_nominal = defaultdict(float)
        extraction_assumed = defaultdict(float)
        maintenance = defaultdict(float)
        construction = defaultdict(float)
        vehicle_inputs = defaultdict(float)
        vehicle_turnaround_inputs = defaultdict(float)
        transport_service_inputs = defaultdict(float)
        fleet_report = []
        research_inputs = defaultdict(float)
        research_service_work = defaultdict(float)
        theory_execution_work = 0.0
        science_inputs = defaultdict(float)
        founding_inputs = defaultdict(float)
        passenger_provisions = defaultdict(float)
        founding_activity_details = []
        passenger_activity_details = []
        market_activity_details = []
        science_reward_conditional = 0.0
        science_activity_details = []
        survey_activity_details = []
        spatial_activity_details = []
        upgrade_activity_details = []
        life_support_inputs = defaultdict(float)
        life_support_supplied = defaultdict(float)
        life_support_committed = defaultdict(float)
        housing_nominal = defaultdict(int)
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
        activity_sources = []
        # Definition-derived resource flows and explicitly authored assumptions
        # share this single accounting path; the ledger is only provenance.
        resource_origins = defaultdict(float)
        service_origins = defaultdict(float)
        def book(mapping, dimension, node, resource, amount, origin_kind, origin_id, basis="definition_x_composition"):
            mapping[(node, str(resource))] += amount
            resource_origins[(node, str(resource), dimension, origin_kind, str(origin_id), basis)] += amount
        def book_service(node, service, rate, role, origin_kind, origin_id, basis="definition_x_composition"):
            services[(node, f"required:{service}" if role == "demand" else service)] += rate
            service_origins[(node, service, role, origin_kind, str(origin_id), basis)] += rate
        def book_construction_work(node, required_work, origin_kind, origin_id):
            work[node] += required_work
            service_origins[(node, "construction_work", "demand", origin_kind, str(origin_id),
                             "definition_x_selected_investment")] += required_work / days
        unassessed = set()
        stage_details = []
        transfer_details = []
        transport_services = []
        transport_supply_by_od = defaultdict(float)
        extraction_groups = defaultdict(list)
        extraction_context_report = []
        power_world_context_report = []
        # Everything here is a request or nominal nameplate, never settled flow.
        for node, name, units, process_id, extraction_id, duty, yield_factor, people in assets:
            current[(node, name)] += units
            facility = sim.facilities.definitions[DefinitionId(name)]
            mult = units * duty
            activity_sources.append({
                "kind": "facility", "node": node, "definition": name,
                "units": units, "duty": duty, "process": process_id, "extraction": extraction_id,
                "quantity_source": "definition_x_selected_composition",
                "graph_evidence": _graph_evidence(
                    graph_nodes, relation_index, (("facility", name),)
                    + ((("process", process_id),) if process_id else ())
                    + ((("extraction_method", extraction_id),) if extraction_id else ()),
                ),
            })
            if (process_id or extraction_id) and duty > 0:
                unassessed.add("shared_power_service_and_resource_allocation")
            # Housing is a physical installed capacity; it is not an
            # operating-process rate and cannot be multiplied by duty.
            housing_nominal[node] += facility.housing_capacity * units
            if facility.life_support is not None:
                life_support_supplied[node] += facility.life_support.person_days_per_day * mult
                life_support_committed[node] += people
                for resource_id, amount in facility.life_support.net_resources:
                    book(life_support_inputs, "life_support_demand_t", node, resource_id,
                         amount * people * days, "facility_life_support", name)
            if process_id:
                proc = sim.industry.processes[DefinitionId(process_id)]
                for res, quantity in proc.inputs_per_day.items():
                    book(process_inputs, "process_demand_t", node, res,
                         quantity * mult * facility.process_throughput_per_day * days,
                         "process", process_id)
                for res, quantity in proc.outputs_per_day.items():
                    book(produced, "production_t", node, res,
                         quantity * mult * facility.process_throughput_per_day * days,
                         "process", process_id)
            if extraction_id:
                method = sim.extraction.specs[DefinitionId(extraction_id)]
                nominal = mult * facility.extraction_capacity_t_per_day
                key = (node, str(method.output_resource_id))
                extraction_nominal[key] += nominal * days
                extraction_groups[(node, str(method.resource_id))].append((method, nominal))
                if node not in extraction_contexts:
                    # Legacy explicit yield remains a conditional sensitivity
                    # input; absence never manufactures proven production.
                    if "extraction_yield_fraction" not in next(row for row in phase["facilities"]
                            if row["node"] == node and row["facility"] == name
                            and row.get("extraction") == extraction_id):
                        unassessed.add("extraction_opportunity_geology_and_knowledge")
                    else:
                        unassessed.add("extraction_yield_is_authored_not_world_derived")
                    extracted = nominal * days * yield_factor
                    extraction_assumed[key] += extracted
                    book(produced, "production_t", node, method.output_resource_id, extracted,
                         "extraction_method", extraction_id, "authored_extraction_yield")
                elif yield_factor != 0 or any(
                    row["node"] == node and row["facility"] == name and
                    row.get("extraction") == extraction_id and "extraction_yield_fraction" in row
                    for row in phase["facilities"]
                ):
                    raise ValueError("World extraction context and authored yield cannot both govern one asset")
            for supply in facility.service_capacity_supplies:
                book_service(node, supply.service_type, supply.nominal_rate * mult, "nominal_supply", "facility", name)
            if facility.id in sim.projects.construction_providers:
                book_service(node, "construction_work",
                             sim.projects.construction_providers[facility.id].work_per_day * mult,
                             "nominal_supply", "construction_provider", name)
            spec = sim.power.specs.get(facility.id)
            if spec:
                power_load[node] += (spec.load_mw * duty + spec.standby_load_mw * (1 - duty)) * units
                if isinstance(spec.generation, FixedGeneration):
                    power_supply[node] += spec.generation.mw * mult
                elif isinstance(spec.generation, SolarGeneration):
                    selected_site = solar_sites.get((node, name))
                    if selected_site is not None:
                        context, reference_day = selected_site
                        # A missing environmental field is unknown, not zero
                        # generation. The Power owner calculates the quantity;
                        # the evaluator only guards scenario interpretation.
                        if sim.power.environment.get(context, IlluminationField, reference_day) is None:
                            raise ValueError(f"World solar illumination unassessed for {context}")
                        extraction_context = extraction_contexts.get(node)
                        if extraction_context is not None:
                            graph = sim.power.environment.graph
                            solar_body = graph.context_body_id(context)
                            if str(solar_body) != extraction_context["body"]:
                                raise ValueError("solar World site and extraction context refer to different bodies at one node")
                            if context not in extraction_context["cells"]:
                                unassessed.add("intra_location_power_distribution_between_cells_unassessed")
                        per_unit_mw, _load = sim.power.nominal_for_definition_at_context(
                            DefinitionId(name), context, reference_day,
                        )
                        power_supply[node] += per_unit_mw * mult
                        power_world_context_report.append({
                            "node": node, "facility": name, "world_context": context,
                            "world_reference_day": reference_day,
                            "nominal_unallocated_generation_mw": per_unit_mw * mult,
                            "basis": "power_domain_world_environment_x_selected_facility_and_duty",
                            "status": "prospective_site_placement_and_operation_unassessed",
                        })
                        unassessed.add("world_solar_site_placement_and_ongoing_conditions_unassessed")
                    else:
                        if node not in solar_yield:
                            raise ValueError(f"solar_yield or solar_sites for {node}/{name} required")
                        power_supply[node] += spec.generation.rated_mw_at_reference_flux * solar_yield[node] * mult
                        unassessed.add("solar_yield_is_authored_not_world_derived")
            storage_spec = sim.storage.providers.get(facility.id)
            if storage_spec:
                for pool, amount in storage_spec.capacity_t_by_pool.items():
                    storage[(node, pool)] += amount * units
            recipe = sim.projects.recipes.get(facility.id)
            if recipe:
                # The Domain owns the invested-resource maintenance contract.
                # Base recipe investment is an explicit assumption for the
                # already-installed assets, not an inspected Facility State.
                base_investment = {req.resource_id: req.amount_t * units for req in recipe.resources}
                for resource_id, rate in sim.facilities.maintenance_requirements_for_investment(
                    facility.id, base_investment,
                ).items():
                    book(maintenance, "maintenance_demand_t", node, resource_id,
                         rate * days, "facility_maintenance", name,
                         "base_construction_recipe_assumed_investment")
        for (node, resource), group in sorted(extraction_groups.items()):
            context = extraction_contexts.get(node)
            if context is None:
                continue
            methods = tuple(method for method, nominal in group if nominal > 0)
            knowledge = context["knowledge"]
            def eligible(method, cell):
                required = method.minimum_knowledge_level
                return required is None or knowledge.get((str(cell), str(method.resource_id)), KnowledgeLevel.UNKNOWN) >= required
            opportunity = sim.extraction.opportunity_for_cells(
                DefinitionId(resource), methods, context["cells"], context["day"], eligible=eligible,
            )
            # One geological opportunity is shared by every Method extracting
            # this raw Resource. Split its single diminishing response across
            # output Resource kinds rather than crediting the first Method's
            # output to every selected Method (future Methods may differ).
            by_output = defaultdict(float)
            output_methods = defaultdict(set)
            for method, nominal in group:
                method_opportunity = sim.extraction.opportunity_for_cells(
                    DefinitionId(resource), (method,), context["cells"], context["day"], eligible=eligible,
                )
                adjusted = (nominal * min(1.0, method_opportunity / opportunity)
                            if opportunity > 1e-12 else 0.0)
                by_output[str(method.output_resource_id)] += adjusted
                output_methods[str(method.output_resource_id)].add(str(method.id))
            adjusted_capacity = sum(by_output.values())
            total_output = sim.extraction.diminishing_response(adjusted_capacity, opportunity) * days
            for output_resource, output_capacity in sorted(by_output.items()):
                output = (total_output * output_capacity / adjusted_capacity
                          if adjusted_capacity > 1e-12 else 0.0)
                key = node, output_resource
                extraction_assumed[key] += output
                book(produced, "production_t", node, output_resource, output,
                     "extraction_opportunity", ",".join(sorted(output_methods[output_resource])),
                     "world_definition_x_authored_knowledge")
                extraction_context_report.append({
                    "node": node, "resource": resource, "output_resource": output_resource,
                    "contributing_methods": sorted(output_methods[output_resource]),
                    "world_body": context["body"], "world_cells": list(context["cells"]),
                    "knowledge_source": "authored_knowledge_levels_not_survey_state",
                    "world_reference_day": context["day"],
                    "effective_opportunity": opportunity,
                    "shared_adjusted_installed_capacity_t_per_day": adjusted_capacity,
                    "adjusted_installed_capacity_t_per_day": output_capacity,
                    "diminishing_output_t_per_day": output / days,
                    "marginal_efficiency": sim.extraction.marginal_response(adjusted_capacity, opportunity),
                    "status": "conditional_world_definition_upper_bound_not_allocated",
                })
            unassessed.add("extraction_site_technology_service_and_stock_allocation")
            if any(method.minimum_knowledge_level is not None for method, _ in group):
                unassessed.add("survey_knowledge_levels_are_authored_assumptions")
        for key in set(current) | set(previous):
            units = current[key]
            if units < previous[key]:
                raise ValueError(f"Facility removal at {key} requires an explicit retirement model")
            delta = units - previous[key]
            if delta > 0:
                unassessed.add("new_facilities_operate_before_construction_completion")
            if not delta:
                continue
            recipe = sim.projects.recipes.get(DefinitionId(key[1]))
            if recipe is None:
                raise ValueError(f"no construction recipe for {key[1]}")
            for req in recipe.resources:
                book(construction, "construction_demand_t", key[0], req.resource_id,
                     req.amount_t * delta, "facility_construction", key[1])
            book_construction_work(key[0], recipe.construction_work * delta,
                                   "facility_construction", key[1])
        # Explicit Spatial Development demand is a registered one-time
        # project recipe; it never constructs Cells or awards territory.
        for row in phase.get("spatial_projects", ()):
            _keys(row, {"node", "recipe", "units"}, {"node", "recipe", "units"}, "spatial project")
            node = _identifier(row["node"], nodes, "node")
            rid = _identifier(row["recipe"], sim.projects.spatial_recipes, "Spatial Development recipe")
            units = _integer(row["units"], "Spatial Development projects", positive=True)
            recipe = sim.projects.spatial_recipes[DefinitionId(rid)]
            for req in recipe.resources:
                book(construction, "construction_demand_t", node, req.resource_id,
                     req.amount_t * units, "spatial_development", rid)
            book_construction_work(node, recipe.construction_work * units,
                                   "spatial_development", rid)
            spatial_activity_details.append({
                "node": node, "recipe": rid, "units": units,
                "required_construction_work": recipe.construction_work * units,
                "resources_t": {str(req.resource_id): req.amount_t * units for req in recipe.resources},
                "prerequisite_technologies": sorted(map(str, recipe.prerequisite_technologies)),
                "knowledge_requirements": [{"resource": str(req.subject_resource_id),
                                            "minimum_level": int(req.minimum_level)}
                                           for req in recipe.knowledge_requirements],
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                                                  (("spatial_development_method", rid),)),
                "status": "project_and_cell_eligibility_unassessed",
            })
            unassessed.add("spatial_target_site_cell_knowledge_and_finite_construction_allocation")
        # Upgrade recipes represent a separately acquired Level transition.
        # Requested upgrades do not alter installed Levels or production here:
        # their completion/order must still be checked by the owning Domain.
        upgraded = defaultdict(int)
        for row in phase.get("upgrade_projects", ()):
            _keys(row, {"node", "facility", "target_level", "units"},
                  {"node", "facility", "target_level", "units"}, "Facility Upgrade")
            node = _identifier(row["node"], nodes, "upgrade node")
            facility_id = _identifier(row["facility"], sim.facilities.definitions, "upgrade Facility")
            target_level = _integer(row["target_level"], "upgrade target_level", positive=True)
            units = _integer(row["units"], "upgrade units", positive=True)
            recipe = sim.projects.upgrade_recipes.get((DefinitionId(facility_id), target_level))
            if recipe is None:
                raise ValueError(f"unregistered Facility Upgrade recipe: {facility_id}/{target_level}")
            upgraded[(node, facility_id)] += units
            if upgraded[(node, facility_id)] > current[(node, facility_id)]:
                raise ValueError("upgrade projects exceed selected installed Facility units")
            for req in recipe.resources:
                book(construction, "construction_demand_t", node, req.resource_id,
                     req.amount_t * units, "facility_upgrade", f"{facility_id}/level:{target_level}")
            book_construction_work(node, recipe.construction_work * units,
                                   "facility_upgrade", f"{facility_id}/level:{target_level}")
            # Upgrade completion is not simulated: this is *potential* later
            # maintenance on the increment of invested materials, not demand
            # booked into the investment phase before construction succeeds.
            upgrade_investment = {req.resource_id: req.amount_t * units for req in recipe.resources}
            post_upgrade_maintenance = sim.facilities.maintenance_requirements_for_investment(
                DefinitionId(facility_id), upgrade_investment,
            )
            # Registered Provider levels are capabilities *after* a valid
            # upgrade, not free capacity in the investment phase. Report
            # their differences alongside material/work/maintenance burdens.
            facility_def = sim.facilities.definitions[DefinitionId(facility_id)]
            compatible_provider_changes = []
            for provider in sim.research.providers.values():
                if provider.source_kind.value != "facility" or not provider.accepts_source(
                    cap.id for cap in facility_def.capability_supplies
                ):
                    continue
                previous_level = next((level for level in provider.levels
                                       if level.level == target_level - 1), None)
                next_level = next((level for level in provider.levels
                                   if level.level == target_level), None)
                if previous_level is None or next_level is None:
                    continue
                compatible_provider_changes.append({
                    "provider": str(provider.id), "assumed_current_level": target_level - 1,
                    "generation_points_per_day_before": previous_level.generation_points_per_day * units,
                    "generation_points_per_day_after": next_level.generation_points_per_day * units,
                    "research_execution_per_day_before": previous_level.research_execution_per_day * units,
                    "research_execution_per_day_after": next_level.research_execution_per_day * units,
                    "storage_capacity_points_before": previous_level.storage_capacity_points * units,
                    "storage_capacity_points_after": next_level.storage_capacity_points * units,
                    "status": "conditional_post_upgrade_provider_capacity_not_allocated",
                })
            upgrade_activity_details.append({
                "node": node, "facility": facility_id, "target_level": target_level,
                "conditional_research_provider_changes": compatible_provider_changes,
                "units": units, "required_construction_work": recipe.construction_work * units,
                "resources_t": {str(req.resource_id): req.amount_t * units for req in recipe.resources},
                "conditional_additional_maintenance_t_per_day": {
                    str(resource): rate for resource, rate in sorted(post_upgrade_maintenance.items())
                },
                "prerequisite_technologies": sorted(map(str, recipe.prerequisite_technologies)),
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                    (("facility_upgrade_method", f"{facility_id}/level:{target_level}"),)),
                "status": "level_transition_site_and_construction_completion_unassessed",
            })
            unassessed.add("facility_upgrade_level_eligibility_and_sequencing")
        facility_units_added = sum(max(0, current[k] - previous[k]) for k in current)
        previous = current
        # The existing (pre-investment) capacity is the only defensible bound
        # for the investment work: new providers cannot construct themselves.
        existing_construction = defaultdict(float)
        for node, name, units, _p, _e, duty, _y, _people in previous_assets:
            provider = sim.projects.construction_providers.get(DefinitionId(name))
            if provider:
                existing_construction[node] += provider.work_per_day * units * duty
        investment_constraints = [{
            "node": node, "required_work": amount,
            "pre_investment_work_per_day": existing_construction[node],
            "pre_investment_work_lower_bound_days": (
                amount / existing_construction[node] if existing_construction[node] > 0 else None
            ),
            "status": "conditional_lower_bound" if existing_construction[node] > 0 else "unassessed_no_initial_capacity",
        } for node, amount in sorted(work.items()) if amount > 0]
        if investment_constraints:
            unassessed.add("construction_material_delivery_and_ordering")
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
                book(vehicle_inputs, "vehicle_build_demand_t", node, res,
                     amount * added, "vehicle_manufacture", vehicle_id)
            if vehicle.production.service_type:
                book_service(node, vehicle.production.service_type, added * vehicle.production.days / days,
                             "demand", "vehicle_manufacture", vehicle_id)
        for (node, vehicle_id), units in sorted(current_fleet.items()):
            if units == 0:
                continue
            vehicle = vehicles[vehicle_id]
            cycles_per_unit = fleet_spec.get((node, vehicle_id), (units, 0))[1] if fleet_spec is not None else 0
            cycles = units * cycles_per_unit * days
            for resource, amount in vehicle.maintenance.resources:
                book(vehicle_turnaround_inputs, "fleet_turnaround_demand_t", node, resource,
                     amount * cycles, "fleet_turnaround", vehicle_id, "definition_x_authored_turnarounds")
            if vehicle.maintenance.service_type:
                book_service(node, vehicle.maintenance.service_type,
                             cycles * vehicle.maintenance.turnaround_days / days,
                             "demand", "fleet_turnaround", vehicle_id, "definition_x_authored_turnarounds")
            activity_sources.append({"kind": "fleet", "node": node, "definition": vehicle_id,
                                     "units": units, "turnarounds_per_unit_per_day": cycles_per_unit,
                                     "quantity_source": "definition_x_selected_composition",
                                     "graph_evidence": _graph_evidence(graph_nodes, relation_index, (("vehicle", vehicle_id),
                                         ("vehicle_operation_method", vehicle_id)))})
            if cycles_per_unit:
                unassessed.add("fleet_turnarounds_without_movement_or_route_validation")
            fleet_report.append({"node": node, "vehicle": vehicle_id,
                                 "units": units, "units_built": builds.get((node, vehicle_id), 0),
                                 "assumed_turnarounds": cycles})
        committed_fleet = defaultdict(int)
        # RP is an organization-owned quantity. Each Provider must reference an
        # explicitly held compatible Facility or Fleet source. Fleet Providers
        # reserve those units across research, Survey, Transport and science.
        research_generation_per_day = 0.0
        research_storage_nominal = 0.0
        research_execution_per_day = 0.0
        research_crew_demand_per_day = 0.0
        assigned_source_units = defaultdict(int)
        for row in phase.get("research_provider_allocations", ()):
            _keys(row, {"node", "provider", "source_facility", "source_vehicle", "units", "level", "duty"},
                  {"node", "provider", "units"}, "research provider")
            name = _identifier(row["provider"], sim.research.providers, "research provider")
            provider = sim.research.providers[DefinitionId(name)]
            node = _identifier(row["node"], nodes, "research source Node")
            if ("source_facility" in row) == ("source_vehicle" in row):
                raise ValueError("research provider requires exactly one typed source")
            units = _integer(row["units"], "research source units", positive=True)
            if provider.source_kind.value == "facility":
                if "source_facility" not in row:
                    raise ValueError("Facility Research Provider requires a source Facility")
                source = _identifier(row["source_facility"], sim.facilities.definitions, "research source Facility")
                facility = sim.facilities.definitions[DefinitionId(source)]
                if not provider.accepts_source(cap.id for cap in facility.capability_supplies):
                    raise ValueError("research provider not compatible with source Facility")
                assigned_source_units[(node, source)] += units
                if assigned_source_units[(node, source)] > current[(node, source)]:
                    raise ValueError("research provider requires more installed Facilities")
            else:
                if "source_vehicle" not in row:
                    raise ValueError("Fleet Research Provider requires a source Vehicle")
                source = _identifier(row["source_vehicle"], vehicles, "research source Vehicle")
                if not provider.accepts_source(vehicles[source].performance.generic_capabilities):
                    raise ValueError("research provider not compatible with source Vehicle")
                committed_fleet[(node, source)] += units
                if committed_fleet[(node, source)] > current_fleet.get((node, source), 0):
                    raise ValueError("research provider reuses Fleet holdings")
                if fleet_spec is not None and fleet_spec.get((node, source), (0, 0))[1] > 0:
                    raise ValueError("Fleet Research Provider overlaps authored turnarounds")
            level = _integer(row.get("level", 1), "research provider level", positive=True)
            level_spec = next((candidate for candidate in provider.levels if candidate.level == level), None)
            if level_spec is None:
                raise ValueError(f"unknown research provider level: {name}/{level}")
            if provider.source_kind.value == "fleet" and level != 1:
                raise ValueError("Fleet-backed research source has no Facility-style Level upgrade")
            if provider.source_kind.value == "facility" and level > 1:
                unassessed.add("research_source_facility_level_and_upgrade_investment_unassessed")
            duty = _number(row.get("duty", 1), "research provider duty")
            if duty > 1:
                raise ValueError("research provider duty cannot exceed 1")
            activity_sources.append({"kind": "research_provider", "node": row["node"],
                                     "definition": name, "source_kind": provider.source_kind.value,
                                     "source_definition": source,
                                     "level": level, "units": units, "duty": duty,
                                     "quantity_source": "definition_x_selected_allocation",
                                     "graph_evidence": _graph_evidence(graph_nodes, relation_index, (("research_provider", name),))})
            unassessed.add("research_source_site_technology_crew_power_and_finite_allocation")
            if provider.source_kind.value == "facility" and any(
                n == node and f == source and (proc or extraction)
                for n, f, _u, proc, extraction, _d, _y, _people in assets):
                unassessed.add("research_and_industry_share_facility_sources")
            research_generation_per_day += units * duty * level_spec.generation_points_per_day
            research_execution_per_day += units * duty * level_spec.research_execution_per_day
            research_storage_nominal += units * level_spec.storage_capacity_points
            research_crew_demand_per_day += (units * duty * level_spec.generation_points_per_day
                                              * provider.crew_person_days_per_research_point)
        # Selected Fleet is reserved once across authored OD services. The
        # Transport owner's read-only preview supplies paths, cycle, payload,
        # propellant, servicing, infrastructure and blockers. This tool does
        # not settle dispatch or turn any preview into an Allocation State.
        for row in phase.get("transport_allocations", ()):
            _keys(row, {"origin", "destination", "vehicle", "units", "duty", "day"},
                  {"origin", "destination", "vehicle", "units"}, "transport allocation")
            origin = _identifier(row["origin"], nodes, "origin")
            destination = _identifier(row["destination"], nodes, "destination")
            if origin == destination:
                raise ValueError("transport allocation requires distinct endpoints")
            vehicle_id = _identifier(row["vehicle"], vehicles, "Vehicle")
            units = _integer(row["units"], "transport Fleet units", positive=True)
            duty = _number(row.get("duty", 1.0), "transport operating duty")
            if duty > 1:
                raise ValueError("transport operating duty cannot exceed 1")
            day = _integer(row.get("day", 0), "transport World reference day")
            committed_fleet[(origin, vehicle_id)] += units
            available = current_fleet.get((origin, vehicle_id), 0)
            if committed_fleet[(origin, vehicle_id)] > available:
                raise ValueError(f"transport allocations reuse Fleet holdings: {(origin, vehicle_id)}")
            if fleet_spec is not None and fleet_spec.get((origin, vehicle_id), (0, 0))[1] > 0:
                raise ValueError("transport service cycles and authored Fleet turnarounds overlap")
            try:
                plan_preview = sim.transport.transport_service_plan_for(
                    DefinitionId(vehicle_id), SpatialNodeId(origin), SpatialNodeId(destination), day=day,
                )
            except (KeyError, ValueError) as exc:
                plan_preview = None
                blockers = [f"transport_plan_not_available:{type(exc).__name__}:{exc}"]
            else:
                blockers = list(plan_preview.blockers)
            if plan_preview is None or plan_preview.cycle_days <= 0 or not plan_preview.forward_path:
                unassessed.add("transport_route_or_cycle_not_derivable")
                forward_capacity = reverse_capacity = None
            else:
                capacity = sim.transport.capacity_for_service_units(plan_preview.nominal_per_unit, units)
                forward_capacity = capacity.forward_t_per_day * duty
                reverse_capacity = capacity.reverse_t_per_day * duty
                transport_supply_by_od[(origin, destination)] += forward_capacity
                if plan_preview.reverse_path:
                    transport_supply_by_od[(destination, origin)] += reverse_capacity
                # Registered full-cycle resource inputs are a declared
                # nameplate-utilization condition, not delivered Cargo flow.
                for location, resource, quantity in plan_preview.resource_t_per_full_utilization_day:
                    book(transport_service_inputs, "transport_service_demand_t", str(location), resource,
                         quantity * units * duty * days, "transport_service", vehicle_id,
                         "transport_domain_plan_x_selected_fleet")
                maintenance_spec = vehicles[vehicle_id].maintenance
                if maintenance_spec.service_type:
                    book_service(origin, maintenance_spec.service_type,
                                 units * duty * plan_preview.turnaround_days / plan_preview.cycle_days,
                                 "demand", "transport_service", vehicle_id,
                                 "transport_domain_plan_x_selected_fleet")
            transport_services.append({
                "origin": origin, "destination": destination, "vehicle": vehicle_id,
                "fleet_units": units, "duty": duty, "world_reference_day": day,
                "forward_capacity_t_per_day": forward_capacity,
                "reverse_capacity_t_per_day": reverse_capacity,
                "forward_latency_days": (plan_preview.forward_latency_days if plan_preview and plan_preview.forward_path else None),
                "reverse_latency_days": plan_preview.reverse_latency_days if plan_preview else None,
                "cycle_days": (plan_preview.cycle_days if plan_preview and plan_preview.cycle_days > 0 else None),
                "forward_path": list(map(str, plan_preview.forward_path)) if plan_preview else [],
                "reverse_path": list(map(str, plan_preview.reverse_path)) if plan_preview else [],
                "infrastructure_requirements": [list(map(str, requirement))
                                                for requirement in plan_preview.infrastructure_requirements] if plan_preview else [],
                "blockers": blockers,
                "quantity_source": "transport_domain_plan_x_selected_fleet",
                "status": "conditional_capacity_upper_bound" if not blockers and forward_capacity is not None
                          else "blockers_or_route_unassessed",
            })
            unassessed.add("transport_fleet_activation_eligible_infrastructure_finite_allocation")
        if committed_fleet:
            unassessed.add("transport_cycle_capacity_not_settled_cargo")
        previous_fleet = current_fleet
        # Scientific Exploration is a conditional *activity* with registered
        # inputs and potential RP outcome. No travel, Crew provisions, RP award,
        # or Mission state transition is simulated by this comparison.
        for row in phase.get("science_campaigns", ()):
            _keys(row, {"campaign", "vehicle"}, {"campaign"}, "scientific exploration")
            campaign_id = _identifier(row["campaign"], sim.scientific_exploration.definitions,
                                      "Scientific Exploration campaign")
            if campaign_id in seen_science_campaigns:
                raise ValueError(f"duplicate Scientific Exploration across phases: {campaign_id}")
            seen_science_campaigns.add(campaign_id)
            campaign = sim.scientific_exploration.definitions[DefinitionId(campaign_id)]
            origin = str(campaign.origin_id)
            assigned_vehicle = row.get("vehicle")
            if assigned_vehicle is not None:
                vehicle_id = _identifier(assigned_vehicle, vehicles, "Scientific Exploration Vehicle")
                committed_fleet[(origin, vehicle_id)] += campaign.required_units
                if committed_fleet[(origin, vehicle_id)] > current_fleet.get((origin, vehicle_id), 0):
                    raise ValueError("Scientific Exploration reuses Fleet holdings committed to other activities")
            # Mission requirements and onboard survival are distinct registered
            # inputs.  The owning Scientific Exploration Domain provisions the
            # *entire* on-site activity when the target has no established Node.
            # Transit/return days cannot be derived without a real Movement
            # path, so only that known on-site floor is counted here.
            crew_seat_gap = None
            crew_site_days = None
            crew_site_provisions = None
            crew_minimum_loaded_mass = None
            if campaign.required_crew and assigned_vehicle is not None:
                accommodation = vehicles[vehicle_id].passengers
                if accommodation.seats == 0:
                    raise ValueError("crewed Scientific Exploration requires passenger-rated Vehicle")
                crew_seat_gap = max(0, campaign.required_crew -
                                    accommodation.supportable_seats(campaign.required_units))
                if isinstance(campaign.destination, MovementEndpoint):
                    crew_site_days = campaign.duration_days
                    crew_site_provisions = accommodation.required_provisions(
                        campaign.required_crew, crew_site_days)
                    for resource, amount in crew_site_provisions.items():
                        book(science_inputs, "science_material_demand_t", origin, resource,
                             amount, "scientific_exploration_crew_site_provisions", campaign_id,
                             "vehicle_passenger_accommodation_x_registered_site_activity_lower_bound")
                    crew_minimum_loaded_mass = (
                        campaign.minimum_payload_t * campaign.required_units
                        + accommodation.loaded_payload_mass(campaign.required_crew, crew_site_provisions))
                unassessed.add("scientific_crew_transit_and_return_provisions_not_assessed")
            elif campaign.required_crew:
                unassessed.add("scientific_crew_vehicle_not_selected")
            for resource, quantity in campaign.consumable_resources:
                book(science_inputs, "science_material_demand_t", origin, resource,
                     quantity, "scientific_exploration", campaign_id)
            science_reward_conditional += campaign.research_points_total
            science_activity_details.append({
                "campaign": campaign_id, "origin": origin,
                "destination": str(campaign.destination_id),
                "selected_vehicle": assigned_vehicle,
                "required_fleet_units": campaign.required_units,
                "required_crew": campaign.required_crew,
                "crew_seat_gap_people": crew_seat_gap,
                "crew_registered_site_days_lower_bound": crew_site_days,
                "crew_site_provisions_lower_bound_t": (
                    {str(resource): amount for resource, amount in sorted(crew_site_provisions.items())}
                    if crew_site_provisions is not None else None),
                "crew_minimum_loaded_payload_lower_bound_t": crew_minimum_loaded_mass,
                "duration_days": campaign.duration_days,
                "conditional_rp_reward": campaign.research_points_total,
                "consumable_resources_t": {str(r): q for r, q in campaign.consumable_resources},
                "prerequisite_technologies": sorted(map(str, campaign.prerequisite_technologies)),
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                                                  (("scientific_exploration", campaign_id),)),
                "status": "mission_fleet_eligibility_provisions_and_completion_unassessed",
            })
            unassessed.add("scientific_exploration_fleet_path_crew_provision_site_and_execution")
        # Survey quantities are from registered Provider/Mode/Target Definitions.
        # Explicit assumed starting progress is required for a time bound;
        # missing Survey State is never interpreted as unmeasured zero.
        for row in phase.get("survey_activities", ()):
            _keys(row, {"node", "provider", "source", "mode", "units", "cell", "resource", "starting_progress"},
                  {"node", "provider", "source", "mode", "units", "cell", "resource"}, "Survey activity")
            node = _identifier(row["node"], nodes, "node")
            provider_id = _identifier(row["provider"], sim.survey.providers, "Survey Provider")
            provider = sim.survey.providers[DefinitionId(provider_id)]
            try:
                mode = provider.observation_mode(row["mode"])
            except KeyError as exc:
                raise ValueError(f"unknown Survey observation mode: {provider_id}/{row['mode']}") from exc
            source_kind = provider.source_kind.value
            source_pool = sim.facilities.definitions if source_kind == "facility" else vehicles
            source = _identifier(row["source"], source_pool, "Survey source")
            if not sim.survey.source_supports_mode(provider, mode, DefinitionId(source)):
                raise ValueError("Survey Mode incompatible with selected source")
            units = _integer(row["units"], "Survey units", positive=True)
            if units < mode.minimum_source_units:
                raise ValueError("Survey Mode minimum source units not met")
            if source_kind == "facility":
                assigned_source_units[(node, source)] += units
                if assigned_source_units[(node, source)] > current[(node, source)]:
                    raise ValueError("Survey and Research reuse Facility source units")
            else:
                committed_fleet[(node, source)] += units
                if committed_fleet[(node, source)] > current_fleet.get((node, source), 0):
                    raise ValueError("Survey reuses Fleet held for transport or science")
            cell_id = _identifier(row["cell"], sim.extraction.graph.surface_cells, "Survey Cell")
            resource = _identifier(row["resource"], known_resource, "Survey Resource")
            target = sim.survey.targets.get((SurfaceCellId(cell_id), DefinitionId(resource)))
            if target is None:
                raise ValueError("Survey target is not a registered Cell/Resource pair")
            threshold = target.thresholds[int(mode.max_knowledge_level) - 1]
            start = (_number(row["starting_progress"], "authored Survey starting progress")
                     if "starting_progress" in row else None)
            remaining = max(0.0, threshold - start) if start is not None else None
            nominal_rate = units * provider.capacity_units_per_source_per_day * mode.survey_rate
            survey_activity_details.append({
                "node": node, "provider": provider_id, "source": source, "source_kind": source_kind,
                "units": units, "mode": mode.id, "target_cell": cell_id, "target_resource": resource,
                "max_knowledge_level": int(mode.max_knowledge_level),
                "assumed_start_progress": start, "target_progress_threshold": threshold,
                "remaining_progress": remaining, "nominal_progress_per_day": nominal_rate,
                "conditional_minimum_days": (remaining / nominal_rate if remaining is not None and nominal_rate > 0 else None),
                "survey_source_service": sim.survey.service_type_for_provider(DefinitionId(provider_id), DefinitionId(source)),
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                                                  (("survey_provider", provider_id),)),
                "status": "survey_reach_technology_site_power_and_allocation_unassessed",
            })
            unassessed.add("survey_reach_technology_site_and_finite_allocation")
            if start is None:
                unassessed.add("survey_starting_progress_not_assumed")
            if source_kind == "facility":
                unassessed.add("survey_and_other_facility_services_compete_for_power_crew")
        # Founding pays for the registered deployment package and preparation.
        # The payload is not credited to an unestablished destination Node.
        # Target and Movement eligibility stay with the owning Domains.
        for row in phase.get("founding_projects", ()):
            _keys(row, {"staging_node", "recipe", "target_cell", "target_node", "vehicle"},
                  {"staging_node", "recipe"}, "founding project")
            if ("target_cell" in row) == ("target_node" in row):
                raise ValueError("founding project requires one explicit target Cell or World Node")
            origin = _identifier(row["staging_node"], nodes, "founding staging node")
            recipe_id = _identifier(row["recipe"], sim.founding.deployment_recipes, "Founding recipe")
            recipe = sim.founding.deployment_recipes[DefinitionId(recipe_id)]
            if "target_cell" in row:
                destination = _identifier(row["target_cell"], sim.extraction.graph.surface_cells, "founding target Cell")
                target_kind = "surface_cell"
            else:
                destination = _identifier(row["target_node"], sim.extraction.graph.nodes, "founding target World Node")
                target_kind = "non_surface_node"
            vehicle_id = None
            if "vehicle" in row:
                vehicle_id = _identifier(row["vehicle"], vehicles, "Founding Vehicle")
                committed_fleet[(origin, vehicle_id)] += recipe.required_units
                if committed_fleet[(origin, vehicle_id)] > current_fleet.get((origin, vehicle_id), 0):
                    raise ValueError("Founding reuses Fleet holdings committed to other activities")
            resources = {str(r.resource_id): r.amount_t for r in recipe.payload_resources}
            for resource, amount in resources.items():
                book(founding_inputs, "founding_payload_demand_t", origin, resource,
                     amount, "founding_method", recipe_id)
            book_service(origin, recipe.preparation_service_type, recipe.preparation_work / days,
                         "demand", "founding_method", recipe_id)
            founding_activity_details.append({
                "staging_node": origin, "recipe": recipe_id,
                "target": destination, "target_kind": target_kind,
                "vehicle": vehicle_id, "required_vehicle_units": recipe.required_units,
                "preparation_service": recipe.preparation_service_type,
                "preparation_work": recipe.preparation_work,
                "payload_resource_t": resources, "payload_t": recipe.payload_t,
                "deployed_facilities": [str(deployment.facility_def_id) for deployment in recipe.deployed_facilities],
                "initial_inventory_t": {str(r): quantity for r, quantity in recipe.initial_inventory_totals().items()},
                "knowledge_requirements": [
                    {"resource": str(req.subject_resource_id), "minimum_level": int(req.minimum_level)}
                    for req in recipe.knowledge_requirements
                ],
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                                                  (("founding_method", recipe_id),)),
                "status": "target_site_preparation_fleet_movement_and_arrival_unassessed",
            })
            unassessed.add("founding_target_site_knowledge_movement_payload_and_settlement")
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
                    book(research_inputs, "research_material_demand_t", row["node"], res,
                         amount, "research_stage", f"{rid}/{spec.stage_id}")
            research_points += getattr(spec, "research_point_cost", 0.0)
            research_work += getattr(spec, "required_work", 0.0)
            requirements = []
            # The Research owner's execution bundle applies each typed finite
            # Requirement per unit of stage progress: RP for Theory, work for
            # Prototype/Demonstration. Do not silently discard these demands.
            progress_amount = (getattr(spec, "research_point_cost", 0.0)
                               or getattr(spec, "required_work", 0.0))
            for requirement in getattr(spec, "execution_requirements", ()):
                if isinstance(requirement, ServiceCapacityRequirement):
                    scope = ("organization" if requirement.scope.value == "ORGANIZATION"
                             else f"node:{requirement.constraint_node_id or row['node']}")
                    if (scope, requirement.service_type) == ("organization", "research_execution") and spec.stage_type.value == "theory":
                        theory_execution_work += requirement.amount_per_execution * progress_amount
                    research_service_work[(scope, requirement.service_type)] += (
                        requirement.amount_per_execution * progress_amount)
                    if requirement.scope.value != "ORGANIZATION":
                        # Ledger and physical Service Capacity are keyed by
                        # the actual Node, not the human-readable scope label.
                        book_service(str(requirement.constraint_node(row["node"])), requirement.service_type,
                                     requirement.amount_per_execution * progress_amount / days,
                                     "demand", "research_stage", f"{rid}/{spec.stage_id}")
                    requirements.append({"kind": "service", "name": requirement.service_type,
                                         "amount_per_execution": requirement.amount_per_execution,
                                         "scope": requirement.scope.value,
                                         "total_required": requirement.amount_per_execution * progress_amount})
                elif isinstance(requirement, ResourceRequirement):
                    node = str(requirement.constraint_node_id or row["node"])
                    book(research_inputs, "research_material_demand_t", node, requirement.resource_id,
                         requirement.amount_per_execution * progress_amount,
                         "research_stage_execution", f"{rid}/{spec.stage_id}")
                    requirements.append({"kind": "resource", "name": str(requirement.resource_id),
                                         "amount_per_execution": requirement.amount_per_execution,
                                         "total_required_t": requirement.amount_per_execution * progress_amount,
                                         "node": node})
                elif isinstance(requirement, (PoolRequirement, PoolAdmissionRequirement,
                                              StockOrPoolAdmissionRequirement)):
                    requirements.append({"kind": type(requirement).__name__,
                                         "name": requirement.pool_id,
                                         "amount_per_execution": requirement.amount_per_execution})
            stage_details.append({
                "node": row["node"], "research": rid, "stage": spec.stage_id,
                "stage_type": spec.stage_type.value,
                "direct_prerequisites": sorted(str(r) for r in definition.prerequisites),
                "point_cost": getattr(spec, "research_point_cost", 0.0),
                "work": getattr(spec, "required_work", 0.0),
                "experience_requirements": dict(sorted(getattr(spec, "requirements", {}).items())),
                "resource_requirements_t": {str(r): amount for r, amount in
                                            sorted(getattr(spec, "resources", {}).items(), key=lambda pair: str(pair[0]))},
                "execution_requirements": requirements,
                "source": f"research:{rid}/stage:{spec.stage_id}",
                "graph_evidence": _graph_evidence(graph_nodes, relation_index, (("research_stage", f"{rid}/{spec.stage_id}"),
                                                        ("technology", rid))),
                "status": "not_scheduled_or_eligibility_checked",
            })
            unassessed.add("research_stage_order_prerequisites_site_and_execution_allocation")
            if spec.stage_type.value == "operational_experience":
                unassessed.add("operational_experience_not_generated_by_elapsed_time")
        # A selected one-shot dedicated passenger trip consumes real Vehicle
        # accommodation provisions, not a fictional Population-as-Cargo item.
        # Fleet is reserved against every other selected activity once. Travel
        # duration is authored because no Movement/Cargo timeline is executed.
        for row in phase.get("passenger_transfers", ()):
            _keys(row, {"origin", "destination", "vehicle", "units", "people", "assumed_onboard_days"},
                  {"origin", "destination", "vehicle", "units", "people", "assumed_onboard_days"},
                  "passenger transfer")
            origin = _identifier(row["origin"], nodes, "passenger origin")
            destination = _identifier(row["destination"], nodes, "passenger destination")
            if origin == destination:
                raise ValueError("passenger transfer requires distinct nodes")
            vehicle_id = _identifier(row["vehicle"], vehicles, "passenger Vehicle")
            vehicle = vehicles[vehicle_id]
            accommodation = vehicle.passengers
            if accommodation.seats == 0:
                raise ValueError("dedicated passenger transfer requires passenger-rated Vehicle")
            units = _integer(row["units"], "passenger Fleet units", positive=True)
            people = _integer(row["people"], "passenger count", positive=True)
            onboard_days = _number(row["assumed_onboard_days"], "assumed onboard days", strictly_positive=True)
            committed_fleet[(origin, vehicle_id)] += units
            if committed_fleet[(origin, vehicle_id)] > current_fleet.get((origin, vehicle_id), 0):
                raise ValueError("passenger transfer reuses Fleet holdings committed to other activities")
            if fleet_spec is not None and fleet_spec.get((origin, vehicle_id), (0, 0))[1] > 0:
                raise ValueError("dedicated passenger transfer cannot overlap authored Fleet turnarounds")
            provisions = accommodation.required_provisions(people, onboard_days)
            loaded_mass = accommodation.loaded_payload_mass(people, provisions)
            for resource, quantity in provisions.items():
                book(passenger_provisions, "passenger_provisions_demand_t", origin, resource,
                     quantity, "passenger_transfer", f"{vehicle_id}:{origin}->{destination}",
                     "vehicle_passenger_accommodation_x_authored_people_and_duration")
            seats = accommodation.supportable_seats(units)
            payload_envelope = vehicle.performance.payload_t * units
            passenger_activity_details.append({
                "origin": origin, "destination": destination, "vehicle": vehicle_id,
                "reserved_fleet_units": units, "requested_people": people,
                "nominal_supportable_seats": seats,
                "nominal_seat_gap_people": max(0, people - seats),
                "assumed_onboard_days": onboard_days,
                "person_mass_t": people * accommodation.person_mass_t,
                "onboard_provisions_t": {str(resource): quantity for resource, quantity in sorted(provisions.items())},
                "total_departure_payload_t": loaded_mass,
                "vehicle_nameplate_payload_upper_bound_t": payload_envelope,
                "nameplate_payload_gap_t": max(0.0, loaded_mass - payload_envelope),
                "vehicle_endurance_days": vehicle.performance.endurance_days,
                "assumed_duration_exceeds_vehicle_endurance": (
                    vehicle.performance.endurance_days is not None
                    and onboard_days > vehicle.performance.endurance_days
                ),
                "onboard_power_supply_mw": accommodation.onboard_power_mw * units,
                "onboard_power_requirement_mw": accommodation.power_mw_per_person * people,
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                                                  (("vehicle", vehicle_id),)),
                "status": "dedicated_departure_conditions_only_no_route_population_or_arrival_settlement",
            })
            unassessed.add("passenger_dedicated_movement_propellant_route_departure_and_arrival_unassessed")
            unassessed.add("passenger_origin_population_and_destination_housing_life_support_unassessed")
            if onboard_days > days:
                unassessed.add("passenger_onboard_duration_extends_beyond_comparison_phase")
        # Market Definition supply is an upper bound on a shared provider's
        # notional window, not a free Resource inflow. Purchases only affect
        # stock if authored separately as explicit external settlement claims.
        market_requests = defaultdict(float)
        market_price = {}
        for row in phase.get("market_buys", ()):
            _keys(row, {"node", "provider", "resource", "requested_t"},
                  {"node", "provider", "resource", "requested_t"}, "market buy")
            node = _identifier(row["node"], nodes, "market interface node")
            provider_id = _identifier(row["provider"], sim.market.provider_defs, "Market Provider")
            resource = _identifier(row["resource"], known_resource, "Market Resource")
            quantity = _number(row["requested_t"], "Market request")
            market_requests[(provider_id, resource)] += quantity
            market_price[(provider_id, resource)] = sim.market.provider_defs[DefinitionId(provider_id)].buy_price(DefinitionId(resource))
            market_activity_details.append({
                "node": node, "provider": provider_id, "resource": resource,
                "requested_t": quantity, "status": "market_interface_and_purchase_not_settled",
                "graph_evidence": _graph_evidence(graph_nodes, relation_index,
                                                  (("market_provider", provider_id),)),
            })
            unassessed.add("market_interface_provider_state_funds_and_delivery")
        market_provider_constraints = []
        for (provider_id, resource), quantity in sorted(market_requests.items()):
            provider = sim.market.provider_defs[DefinitionId(provider_id)]
            supply = provider.supply_def(DefinitionId(resource))
            price = market_price[(provider_id, resource)]
            # Supply is the provider-wide potential, not repeated per Node.
            conditional_supply = (supply.initial_t + supply.replenishment_t_per_day * days
                                  if supply else None)
            arrival_window = max(0, days - provider.lead_time_days)
            conditional_deliverable = (None if supply is None else
                                       supply.initial_t + supply.replenishment_t_per_day * arrival_window
                                       if arrival_window > 0 else 0.0)
            market_provider_constraints.append({
                "provider": provider_id, "resource": resource,
                "total_requested_t": quantity,
                "unit_price_musd_per_t": price,
                "nominal_cost_musd": (price * quantity if price is not None else None),
                "provider_definition_initial_supply_t": supply.initial_t if supply else None,
                "provider_definition_stock_capacity_t": supply.capacity_t if supply else None,
                "provider_definition_replenishment_t_per_day": supply.replenishment_t_per_day if supply else None,
                "conditional_total_supply_upper_bound_t": conditional_supply,
                "conditional_arrival_window_upper_bound_t": conditional_deliverable,
                "theoretical_shortfall_t": (max(0.0, quantity - conditional_deliverable)
                                            if supply and price is not None else None),
                "lead_time_days": provider.lead_time_days,
                "status": "conditional_provider_definition_not_market_state_or_delivery"
                          if supply and price is not None else "no_registered_buy_offer_or_supply",
            })
        assumed_funds = (_number(phase["assumed_funds_musd"], "authored phase funds")
                         if "assumed_funds_musd" in phase else None)
        nominal_market_cost = (sum(row["nominal_cost_musd"] for row in market_provider_constraints)
                               if all(row["nominal_cost_musd"] is not None for row in market_provider_constraints)
                               else None)
        market_funds = {"assumed_funds_musd": assumed_funds,
                        "nominal_request_cost_musd": nominal_market_cost,
                        "conditional_funds_gap_musd": (max(0.0, nominal_market_cost - assumed_funds)
                                                       if assumed_funds is not None and nominal_market_cost is not None else None),
                        "status": "phase_condition_not_actual_market_state"}
        for row in phase.get("external_rates", ()):
            _keys(row, {"node", "resource", "net_t_per_day"}, {"node", "resource", "net_t_per_day"}, "external rate")
            _identifier(row["resource"], known_resource, "Resource")
            rate = row["net_t_per_day"]
            if type(rate) not in (int, float) or not isfinite(rate):
                raise ValueError("external rate must be finite")
            book(external, "external_net_t", row["node"], row["resource"],
                 rate * days, "external_rate", "analyst_assumption", "authored_external_net_rate")
            unassessed.add("external_market_supply_funds_and_lead_time")
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
            book(shipped, "shipped_t", origin, res, amount, "authored_transfer", f"{origin}->{dest}", "authored_delivery_assumption")
            book(received, "received_t", dest, res, amount, "authored_transfer", f"{origin}->{dest}", "authored_delivery_assumption")
            book_service(origin, "cargo_transfer", amount / days, "demand", "authored_transfer",
                         f"{origin}->{dest}", "authored_delivery_assumption")
            book_service(dest, "cargo_transfer", amount / days, "demand", "authored_transfer",
                         f"{origin}->{dest}", "authored_delivery_assumption")
            # A physical OD capacity is shared across all Resource demands.
            # The per-resource row never claims that entire capacity as its own.
            transfer_details.append({"origin": origin, "destination": dest,
                                     "resource": res, "required_t": amount,
                                     "required_t_per_day": amount / days,
                                     "source": "authored_delivery_assumption",
                                     "status": "cargo_arrival_unassessed"})
            unassessed.add("transport_fleet_cycle_propellant_latency_and_arrival")
        od_demands = defaultdict(float)
        for row in transfer_details:
            od_demands[(row["origin"], row["destination"])] += row["required_t_per_day"]
        od_transport_constraints = []
        for (origin, destination), required in sorted(od_demands.items()):
            matched = [allocation for allocation in transport_services
                       if (allocation["origin"], allocation["destination"]) == (origin, destination)
                       or ((allocation["destination"], allocation["origin"]) == (origin, destination)
                           and allocation["reverse_path"])]
            defined = bool(matched) and all(
                (allocation["forward_capacity_t_per_day"] is not None
                 if allocation["origin"] == origin else allocation["reverse_capacity_t_per_day"] is not None)
                for allocation in matched
            )
            blocked = any(allocation["blockers"] for allocation in matched)
            capacity = transport_supply_by_od[(origin, destination)] if defined else None
            od_transport_constraints.append({
                "origin": origin, "destination": destination,
                "demand_t_per_day": required, "nominal_capacity_t_per_day": capacity,
                "nominal_gap_t_per_day": (max(0.0, required - capacity) if capacity is not None else None),
                "status": ("fleet_route_unassessed" if not defined else
                           "blocked_nominal_capacity_only" if blocked else
                           "conditional_capacity_not_cargo_settlement"),
                "blockers": sorted({blocker for allocation in matched for blocker in allocation["blockers"]}),
            })
        end = {}
        keys = set(stocks) | set(produced) | set(process_inputs) | set(maintenance) | set(construction) | set(vehicle_inputs) | set(vehicle_turnaround_inputs) | set(transport_service_inputs) | set(research_inputs) | set(science_inputs) | set(founding_inputs) | set(passenger_provisions) | set(life_support_inputs) | set(external) | set(shipped) | set(received)
        breakdown = []
        for key in sorted(keys):
            start = stocks[key]
            delta = (produced[key] - process_inputs[key] - maintenance[key] - construction[key]
                     - vehicle_inputs[key] - vehicle_turnaround_inputs[key] - transport_service_inputs[key] - research_inputs[key] - science_inputs[key] - founding_inputs[key] - passenger_provisions[key] - life_support_inputs[key] + external[key] - shipped[key] + received[key])
            end[key] = start + delta
            unverified_cargo_receipts[key] += received[key]
            without_assumed_arrivals = end[key] - unverified_cargo_receipts[key]
            # Separate the phase's acquisition/project burden from its
            # nominal recurring load. Both are already booked in the single
            # Resource ledger; this classification does not make either flow
            # executable or change projected stock.
            investment_t = (construction[key] + vehicle_inputs[key] + research_inputs[key]
                            + science_inputs[key] + founding_inputs[key] + passenger_provisions[key])
            recurring_delta = delta + investment_t
            recurring_rate = recurring_delta / days
            # This is a conditional stationary-rate exhaustion scale, not a
            # forecast completion/depletion date. In particular, prior
            # negative notional stock is never treated as usable inventory.
            opening_after_investment = start - investment_t
            exhaustion = (opening_after_investment / -recurring_rate
                          if opening_after_investment >= 0 and recurring_rate < -1e-12
                          else None)
            breakdown.append({
                "node": key[0], "resource": key[1], "start_t": start,
                "production_t": produced[key], "process_demand_t": process_inputs[key],
                "maintenance_demand_t": maintenance[key], "construction_demand_t": construction[key],
                "vehicle_build_demand_t": vehicle_inputs[key], "fleet_turnaround_demand_t": vehicle_turnaround_inputs[key],
                "transport_service_demand_t": transport_service_inputs[key],
                "research_material_demand_t": research_inputs[key],
                "science_material_demand_t": science_inputs[key],
                "founding_payload_demand_t": founding_inputs[key],
                "passenger_provisions_demand_t": passenger_provisions[key],
                "life_support_demand_t": life_support_inputs[key],
                "external_net_t": external[key],
                "shipped_t": shipped[key], "received_t": received[key],
                "cumulative_unverified_incoming_cargo_t": unverified_cargo_receipts[key],
                "notional_end_without_assumed_arrivals_t": without_assumed_arrivals,
                "shortfall_without_assumed_arrivals_t": max(0.0, -without_assumed_arrivals),
                "net_t": delta, "notional_end_t": end[key],
                "shortfall_t": max(0.0, -end[key]),
                "one_time_investment_and_activity_demand_t": investment_t,
                "nominal_recurring_net_t_per_day": recurring_rate,
                "conditional_stock_exhaustion_days_after_investment": exhaustion,
                "opening_investment_stock_shortfall_t": max(0.0, investment_t - max(0.0, start)),
            })
        stocks = defaultdict(float, end)
        start_rp = stored_research_points
        generated_rp = research_generation_per_day * days
        stored_research_points += generated_rp - research_points
        # A rate comparison is a physical lower bound only, not a simulated
        # Research execution date. RP admission, stage order and daily settlement
        # are deliberately not replicated here.
        theory_days_by_execution = (theory_execution_work / research_execution_per_day
                                    if research_execution_per_day > 0 else
                                    0.0 if theory_execution_work == 0 else None)
        theory_days_by_generation = (
            max(0.0, research_points - max(0.0, start_rp)) / research_generation_per_day
            if research_generation_per_day > 0 else
            (0.0 if research_points <= max(0.0, start_rp) else None)
        )
        organization_research_execution_work = research_service_work.get(("organization", "research_execution"), 0.0)
        research_services = []
        for (scope, service), amount in sorted(research_service_work.items()):
            capacity = (research_execution_per_day if (scope, service) ==
                        ("organization", "research_execution") else None)
            research_services.append({
                "scope": scope, "service": service, "total_required": amount,
                "nominal_capacity_per_day": capacity,
                "conditional_lower_bound_days": (amount / capacity if capacity and capacity > 0 else
                                                  0.0 if amount == 0 else None),
                "status": "conditional_shared_organization_capacity" if capacity is not None
                          else "service_capacity_not_assessed",
            })
            if capacity is None:
                unassessed.add("research_execution_service_capacity_not_assessed")
        research_metrics = {
            "execution_capacity_lower_bound_days": theory_days_by_execution,
            "total_research_execution_work": organization_research_execution_work,
            "total_execution_capacity_lower_bound_days": (
                organization_research_execution_work / research_execution_per_day
                if research_execution_per_day > 0 else
                0.0 if organization_research_execution_work == 0 else None
            ),
            "generation_capacity_lower_bound_days": theory_days_by_generation,
            "phase_execution_capacity_points": research_execution_per_day * days,
            "phase_execution_capacity_gap_points": max(0.0, research_points - research_execution_per_day * days),
            "start_points": start_rp, "nominal_generation_points": generated_rp,
            "research_stage_demand_points": research_points,
            "notional_end_points": stored_research_points,
            "point_shortfall": max(0.0, -stored_research_points),
            "nominal_storage_capacity_points": research_storage_nominal,
            "storage_excess_points": max(0.0, stored_research_points - research_storage_nominal),
            "nominal_execution_per_day": research_execution_per_day,
            "crew_requirement_person_days_per_day": research_crew_demand_per_day,
            "conditional_scientific_exploration_reward_points_not_awarded": science_reward_conditional,
        }
        constraints = []
        for node in sorted(set(power_supply) | set(power_load) | set(work) | set(life_support_supplied) | set(housing_nominal) | {n for n, _ in services}):
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
                "housing_nominal_people": housing_nominal[node],
                "conditional_supported_residents_people": life_support_committed[node],
                "conditional_housing_gap_people": max(0.0, life_support_committed[node] - housing_nominal[node]),
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
            "one_time_investment_and_activity_demand_t", "nominal_recurring_net_t_per_day",
            "production_t", "process_demand_t", "maintenance_demand_t",
            "construction_demand_t", "vehicle_build_demand_t", "fleet_turnaround_demand_t",
            "transport_service_demand_t", "research_material_demand_t", "science_material_demand_t", "founding_payload_demand_t", "passenger_provisions_demand_t", "life_support_demand_t", "external_net_t",
            "shipped_t", "received_t", "cumulative_unverified_incoming_cargo_t",
            "notional_end_without_assumed_arrivals_t", "shortfall_without_assumed_arrivals_t",
            "net_t", "notional_end_t", "shortfall_t",
        ))
        system_services = _aggregate_by_dimension(service_constraints, "service", (
            "required_per_day", "nominal_capacity_per_day", "nominal_gap_per_day",
        ))
        report.append({"name": phase["name"], "days": days,
                       "activity_sources": activity_sources,
                       "unassessed_constraints": sorted(unassessed),
                       "investment_constraints": investment_constraints,
                       "research_stages": stage_details,
                       "research_service_constraints": research_services,
                       "spatial_projects": spatial_activity_details,
                       "upgrade_projects": upgrade_activity_details,
                       "science_campaigns": science_activity_details,
                       "survey_activities": survey_activity_details,
                       "founding_projects": founding_activity_details,
                       "passenger_transfer_requirements": passenger_activity_details,
                       "market_buys": market_activity_details,
                       "market_provider_constraints": market_provider_constraints,
                       "market_funds_condition": market_funds,
                       "transfer_requirements": transfer_details,
                       "transport_services": transport_services,
                       "od_transport_constraints": od_transport_constraints,
                       "extraction_world_context": extraction_context_report,
                       "power_world_context": power_world_context_report,
                       "resources": breakdown,
                       "resource_contributions": [
                           {"node": node, "resource": resource, "dimension": dimension,
                            "origin_kind": kind, "origin_definition": source,
                            "quantity_basis": basis, "amount_t": amount}
                           for (node, resource, dimension, kind, source, basis), amount
                           in sorted(resource_origins.items()) if abs(amount) > 1e-12
                       ],
                       "service_contributions": [
                           {"node": node, "service": service, "role": role,
                            "origin_kind": kind, "origin_definition": source,
                            "quantity_basis": basis, "rate_per_day": rate}
                           for (node, service, role, kind, source, basis), rate
                           in sorted(service_origins.items()) if abs(rate) > 1e-12
                       ],
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
        previous_assets = assets
    return {"model": "definition_quantity_projection_v1", "content_id": app.content_id,
            "world_definition_id": app.world_definition_id,
            "assumptions": [
                "Requested production, maintenance, construction and transport are not settled Game flow.",
                "Facility changes take effect at phase start; construction work is a separate nominal demand, not scheduled completion.",
                "Spatial Development projects consume registered inputs and work, but do not create developed Cells or establish Nodes.",
                "Facility Upgrade projects consume registered materials and work, without Level transition, completion sequencing, or updated provider capability.",
                "Scientific Exploration campaigns include registered resources and potential RP rewards; for selected crewed trips to unestablished physical targets, onboard Resource demand covers only the registered site-duration lower bound, not unknown travel or return. No mission or Population progression is executed.",
                "Survey is a conditional Provider/Mode/Target capacity comparison; no Survey State, reach, eligibility, or progress is executed.",
                "Founding projects consume registered deployment payloads and preparation service; they do not found Nodes, transfer cargo, or build Facilities in-place.",
                "Dedicated passenger transfer requirements use actual Vehicle accommodation and one-shot Fleet commitments with authored onboard duration. They do not prove Movement, dispatch, population availability, destination admission or Cargo settlement.",
                "Market provider supply, replenishment, price and lead time bound explicitly requested purchases; they are not settled Market delivery or new Resource Stock.",
                "Negative projected stock records unsatisfied notional demand; no automatic procurement or allocation occurs.",
                "Power and finite service are nominal capacities, not eligibility or maintenance-adjusted availability.",
                "Extraction with no explicit yield fraction credits no production and records unassessed geology/Knowledge; an explicit fraction is only an authored assumption.",
                "Research stages contribute typed RP, work, experience, execution requirements, and physical inputs. RP supply requires an authored compatible Facility or Fleet provider assignment, without technology/site/crew availability validation.",
                "Life Support resource demand uses explicitly assigned person-days and registered per-person rates, not population planning. Installed Housing is compared to that authored conditional resident count, not an admission or occupancy calculation.",
                "Authored transfer arrivals omit travel time and Fleet operation requirements; capacities are compared only. Conditional end Stock has a separate no-arrivals lower bound retaining all prior unverified receipts.",
                "Fleet holdings are assumed at phase start; new units incur production inputs and work, not scheduled completion.",
                "Fleet turnaround frequency without an OD plan is an explicit activity assumption; routed OD services use Transport-owned cycle, payload, propellant and maintenance quantities as conditional upper bounds.",
                "System totals preserve resource and Service types and sum local shortfalls without transferring excess capacity between nodes.",
                "Solar yield is an authored site flux/availability ratio to reference flux, not a dynamically resolved environment.",
                "Maintenance approximates invested material using base construction recipe; Upgrade investment is accounted separately without Level transition, salvage is not simulated.",
            ], "phases": report}


def _apply_case_updates(base: dict, updates: list) -> dict:
    """Apply bounded, identity-addressed sensitivity changes to one shared case.

    Existing entries can be changed, and new explicitly selected asset/source
    rows can be added; neither operation selects a programme, routes Cargo,
    acquires assets nor settles an action on the user's behalf.
    """
    if not isinstance(updates, list):
        raise ValueError("case updates must be a list")
    plan = deepcopy(base)
    seen = set()
    for change in updates:
        if not isinstance(change, dict):
            raise ValueError("case update must be an object")
        collection = change.get("collection")
        if change.get("action") == "add":
            # Cases can select *additional* real assets and activities, rather
            # than copying every phase to compare a new capability.
            # This changes only the comparison composition. No acquisition,
            # provider eligibility or actual Game State is inferred here.
            _keys(change, {"collection", "phase", "action", "row"},
                  {"collection", "phase", "action", "row"}, "case addition")
            if collection not in {"facilities", "fleet", "research_provider_allocations", "passenger_transfers", "science_campaigns", "spatial_projects"}:
                raise ValueError("case addition requires an asset, Research Provider or explicitly selected activity collection")
            row = change["row"]
            if not isinstance(row, dict):
                raise ValueError("case addition row must be an object")
            identity_fields = ({"facilities": ("node", "facility"),
                                "fleet": ("node", "vehicle"),
                                "research_provider_allocations": ("node", "provider"),
                                "passenger_transfers": ("origin", "destination", "vehicle"),
                                "science_campaigns": ("campaign",),
                                "spatial_projects": ("node", "recipe")})[collection]
            if any(not isinstance(row.get(key), str) or not row[key] for key in identity_fields):
                raise ValueError("case addition requires explicit activity identity and Definition ID")
            phases = [phase for phase in plan["phases"] if phase["name"] == change["phase"]]
            if len(phases) != 1:
                raise ValueError("case addition requires exactly one existing phase")
            rows = phases[0].setdefault(collection, [])
            if any(tuple(existing.get(key) for key in identity_fields) ==
                   tuple(row[key] for key in identity_fields) for existing in rows):
                raise ValueError("case addition cannot duplicate a selected source or activity")
            identity = (collection, change["phase"], *(row[key] for key in identity_fields))
            if identity in seen:
                raise ValueError(f"duplicate case update: {identity}")
            seen.add(identity)
            rows.append(deepcopy(row))
            continue
        if collection == "phase":
            _keys(change, {"collection", "phase", "days"}, {"collection", "phase", "days"}, "case update")
            candidates = [row for row in plan["phases"] if row["name"] == change["phase"]]
            edits = {"days": change["days"]}
            identity = (collection, change["phase"])
        elif collection == "solar_yield":
            _keys(change, {"collection", "node", "factor"}, {"collection", "node", "factor"}, "case update")
            if change["node"] not in plan.get("solar_yield", {}):
                raise ValueError("solar sensitivity requires an existing declared site factor")
            candidates = [plan["solar_yield"]]
            edits = {change["node"]: change["factor"]}
            identity = (collection, change["node"])
        elif collection == "solar_sites":
            _keys(change, {"collection", "node", "id", "context", "day"},
                  {"collection", "node", "id"}, "case update")
            edits = {key: change[key] for key in ("context", "day") if key in change}
            candidates = [row for row in plan.get("solar_sites", ())
                          if row["node"] == change["node"] and row["facility"] == change["id"]]
            identity = (collection, change["node"], change["id"])
            if not edits:
                raise ValueError("empty World solar site sensitivity")
        elif collection == "initial_stock":
            _keys(change, {"collection", "node", "id", "amount_t"},
                  {"collection", "node", "id", "amount_t"}, "case update")
            candidates = [row for row in plan.get("initial_stock", ())
                          if row["node"] == change["node"] and row["resource"] == change["id"]]
            edits = {"amount_t": change["amount_t"]}
            identity = (collection, change["node"], change["id"])
        elif collection == "extraction_sites":
            _keys(change, {"collection", "phase", "node", "developed_cells", "knowledge", "day"},
                  {"collection", "phase", "node"}, "case update")
            edits = {key: change[key] for key in ("developed_cells", "knowledge", "day") if key in change}
            candidates = [row for phase in plan["phases"] if phase["name"] == change["phase"]
                          for row in phase.get("extraction_sites", ()) if row["node"] == change["node"]]
            identity = (collection, change["phase"], change["node"])
            if not edits:
                raise ValueError("empty extraction site sensitivity")
        elif collection == "transport_allocations":
            _keys(change, {"collection", "phase", "origin", "destination", "id", "units", "duty", "day"},
                  {"collection", "phase", "origin", "destination", "id"}, "case update")
            edits = {key: change[key] for key in ("units", "duty", "day") if key in change}
            candidates = [row for phase in plan["phases"] if phase["name"] == change["phase"]
                          for row in phase.get("transport_allocations", ())
                          if row["origin"] == change["origin"] and row["destination"] == change["destination"]
                          and row["vehicle"] == change["id"]]
            identity = (collection, change["phase"], change["origin"], change["destination"], change["id"])
            if not edits:
                raise ValueError("empty transport allocation sensitivity")
        elif collection in ("facilities", "fleet", "research_provider_allocations"):
            _keys(change, {"phase", "collection", "node", "id", "units", "duty",
                           "turnarounds_per_unit_per_day", "level", "process", "extraction",
                           "supported_person_days_per_day", "extraction_yield_fraction"},
                  {"phase", "collection", "node", "id"}, "case update")
            allowed = ({"units", "duty", "process", "extraction",
                        "supported_person_days_per_day", "extraction_yield_fraction"}
                       if collection == "facilities" else
                       {"units", "turnarounds_per_unit_per_day"} if collection == "fleet" else
                       {"units", "duty", "level"})
            edits = {k: v for k, v in change.items() if k in allowed}
            if not edits or (set(change) - {"phase", "collection", "node", "id"}) - allowed:
                raise ValueError("invalid asset sensitivity fields")
            phases = [p for p in plan["phases"] if p["name"] == change["phase"]]
            key = ("facility" if collection == "facilities" else
                   "vehicle" if collection == "fleet" else "provider")
            candidates = [row for phase in phases for row in phase.get(collection, ())
                          if row["node"] == change["node"] and row[key] == change["id"]]
            identity = (collection, change["phase"], change["node"], change["id"])
            if collection == "facilities" and ("process" in edits or "extraction" in edits):
                if len(candidates) != 1 or not ("process" in candidates[0] or "extraction" in candidates[0]):
                    raise ValueError("method sensitivity requires exactly one existing operating Facility")
                # The analyst may select a different registered method, never
                # introduce a new simultaneous Process/Extraction assignment.
                if ("process" in edits) != ("process" in candidates[0]):
                    raise ValueError("method sensitivity must preserve Process/Extraction kind")
                if ("extraction" in edits) != ("extraction" in candidates[0]):
                    raise ValueError("method sensitivity must preserve Process/Extraction kind")
        else:
            raise ValueError(f"unsupported sensitivity collection: {collection!r}")
        if identity in seen:
            raise ValueError(f"duplicate case update: {identity}")
        seen.add(identity)
        if len(candidates) != 1:
            raise ValueError(f"case update requires exactly one existing target: {identity}")
        candidates[0].update(edits)
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
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
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
        results.append({"name": case["name"], "projection": evaluate(
            case_plan, app=app, _definition_graph=graph)})
    differences = []
    baseline = results[0]["projection"]["phases"]
    for alternative in results[1:]:
        alternative_phases = alternative["projection"]["phases"]
        for index, (left, right) in enumerate(zip(baseline, alternative_phases)):
            if left["name"] != right["name"] or left["days"] != right["days"]:
                differences.append({"case": alternative["name"], "baseline_phase": left["name"],
                                    "phase": right["name"], "section": "incomparable_phase_basis",
                                    "baseline_days": left["days"], "case_days": right["days"]})
                continue  # Different time bases cannot be compared as like quantities.
            left_rp, right_rp = left["research_point_balance"], right["research_point_balance"]
            rp_delta = {key: right_rp[key] - left_rp[key] for key in left_rp
                        if isinstance(right_rp[key], (int, float)) and isinstance(left_rp[key], (int, float))
                        and abs(right_rp[key] - left_rp[key]) > 1e-12}
            if rp_delta:
                differences.append({"case": alternative["name"], "phase": left["name"],
                                    "section": "research_point_balance", "identity": {"pool": "organization"},
                                    "delta_from_baseline": rp_delta})
            for section, key_fields, metrics in (
                ("research_service_constraints", ("scope", "service"),
                 ("total_required", "nominal_capacity_per_day", "conditional_lower_bound_days")),
                ("service_contributions", ("node", "service", "role", "origin_kind", "origin_definition", "quantity_basis"),
                 ("rate_per_day",)),
                ("resource_contributions", ("node", "resource", "dimension", "origin_kind", "origin_definition", "quantity_basis"),
                 ("amount_t",)),
                ("service_constraints", ("node", "service"),
                 ("required_per_day", "nominal_capacity_per_day", "nominal_gap_per_day")),
                ("system_resources", ("resource",), ("one_time_investment_and_activity_demand_t", "nominal_recurring_net_t_per_day", "production_t", "process_demand_t",
                      "maintenance_demand_t", "construction_demand_t", "vehicle_build_demand_t",
                      "fleet_turnaround_demand_t", "transport_service_demand_t", "passenger_provisions_demand_t", "notional_end_t", "shortfall_t")),
                ("system_services", ("service",), ("required_per_day", "nominal_capacity_per_day",
                       "nominal_gap_per_day")),
                ("resources", ("node", "resource"), ("one_time_investment_and_activity_demand_t", "nominal_recurring_net_t_per_day", "opening_investment_stock_shortfall_t", "conditional_stock_exhaustion_days_after_investment", "production_t", "process_demand_t",
                       "maintenance_demand_t", "construction_demand_t", "vehicle_build_demand_t", "fleet_turnaround_demand_t",
                       "transport_service_demand_t", "research_material_demand_t", "science_material_demand_t", "founding_payload_demand_t", "passenger_provisions_demand_t", "life_support_demand_t", "notional_end_t", "shortfall_t", "cumulative_unverified_incoming_cargo_t", "shortfall_without_assumed_arrivals_t")),
                ("constraints", ("node",), ("power_generation_nominal_mw", "power_demand_nominal_mw",
                       "power_gap_mw", "life_support_nominal_person_days_per_day", "life_support_assigned_person_days_per_day",
                       "life_support_gap_person_days_per_day", "housing_nominal_people",
                       "conditional_supported_residents_people", "conditional_housing_gap_people",
                       "construction_work_required", "construction_work_nominal_capacity",
                       "construction_work_gap", "cargo_transfer_demand_t_per_day", "cargo_transfer_gap_t_per_day")),
                ("od_transport_constraints", ("origin", "destination"),
                 ("demand_t_per_day", "nominal_capacity_t_per_day", "nominal_gap_t_per_day")),
                ("fleet", ("node", "vehicle"), ("units", "units_built", "assumed_turnarounds")),
                ("storage", ("node", "pool"), ("physical_capacity_t", "notional_occupied_t",
                       "capacity_excess_t")),
                ("extraction_world_context", ("node", "resource", "output_resource"),
                 ("effective_opportunity", "adjusted_installed_capacity_t_per_day",
                  "diminishing_output_t_per_day", "marginal_efficiency")),
                ("power_world_context", ("node", "facility"),
                 ("nominal_unallocated_generation_mw",)),
                ("investment_constraints", ("node",),
                 ("required_work", "pre_investment_work_per_day", "pre_investment_work_lower_bound_days")),
                ("spatial_projects", ("node", "recipe"), ("units", "required_construction_work")),
                ("upgrade_projects", ("node", "facility", "target_level"),
                 ("units", "required_construction_work")),
                ("survey_activities", ("node", "provider", "source", "mode", "target_cell", "target_resource"),
                 ("units", "nominal_progress_per_day", "conditional_minimum_days")),
                ("science_campaigns", ("campaign",),
                 ("conditional_rp_reward", "required_fleet_units", "required_crew", "duration_days",
                  "crew_seat_gap_people", "crew_registered_site_days_lower_bound",
                  "crew_minimum_loaded_payload_lower_bound_t")),
                ("founding_projects", ("staging_node", "recipe", "target"),
                 ("payload_t", "required_vehicle_units", "preparation_work")),
                ("passenger_transfer_requirements", ("origin", "destination", "vehicle"),
                 ("requested_people", "reserved_fleet_units", "nominal_supportable_seats",
                  "nominal_seat_gap_people", "assumed_onboard_days", "total_departure_payload_t",
                  "vehicle_nameplate_payload_upper_bound_t", "nameplate_payload_gap_t")),
                ("market_provider_constraints", ("provider", "resource"),
                 ("total_requested_t", "nominal_cost_musd", "conditional_arrival_window_upper_bound_t",
                  "theoretical_shortfall_t")),
                ("research_stages", ("research", "stage"), ("point_cost", "work")),
                ("transport_services", ("origin", "destination", "vehicle"),
                 ("fleet_units", "forward_capacity_t_per_day", "reverse_capacity_t_per_day", "cycle_days")),
            ):
                def indexed(items):
                    # Several explicitly authored activity rows may refer to the
                    # same Definition/OD. Do not silently lose any quantities.
                    grouped = {}
                    for row in items:
                        key = tuple(row[field] for field in key_fields)
                        values = {metric: row.get(metric, 0.0) for metric in metrics}
                        if key in grouped:
                            for metric in metrics:
                                old = grouped[key][metric]
                                value = values[metric]
                                if metric in {"cycle_days", "duration_days", "conditional_minimum_days",
                                              "marginal_efficiency", "pre_investment_work_lower_bound_days",
                                              "conditional_lower_bound_days",
                                              "conditional_stock_exhaustion_days_after_investment"}:
                                    grouped[key][metric] = old if old == value else None
                                else:
                                    grouped[key][metric] = (old + value if old is not None and value is not None
                                                            else None)
                        else:
                            grouped[key] = values
                    return grouped
                l, r = indexed(left[section]), indexed(right[section])
                for key in sorted(set(l) | set(r)):
                    delta = {}
                    incomparable = {}
                    for metric in metrics:
                        before = l.get(key, {}).get(metric, 0.0)
                        after = r.get(key, {}).get(metric, 0.0)
                        if before is None or after is None:
                            if before != after:
                                incomparable[metric] = {"baseline": before, "case": after}
                            continue
                        if abs(after - before) > 1e-12:
                            delta[metric] = after - before
                    if delta or incomparable:
                        change = {"case": alternative["name"], "phase": left["name"],
                                  "section": section, "identity": dict(zip(key_fields, key))}
                        if delta:
                            change["delta_from_baseline"] = delta
                        if incomparable:
                            change["incomparable_unassessed_metrics"] = incomparable
                        differences.append(change)
        for unmatched in baseline[len(alternative_phases):]:
            differences.append({"case": alternative["name"], "baseline_phase": unmatched["name"],
                                "phase": None, "section": "incomparable_phase_basis",
                                "reason": "missing_case_phase"})
        for unmatched in alternative_phases[len(baseline):]:
            differences.append({"case": alternative["name"], "baseline_phase": None,
                                "phase": unmatched["name"], "section": "incomparable_phase_basis",
                                "reason": "missing_baseline_phase"})
    return {"model": "definition_quantity_comparison_v1", "baseline_case": results[0]["name"],
            "cases": results, "differences": differences}


def _leading_activity_drivers(phase: dict, collection: str, *, node: str,
                              category: str, identifier: str, quantity: str,
                              top: int = 3) -> dict:
    """A bounded and clearly non-exhaustive view of the full activity ledger.

    The detailed report remains the single source for exact reconciliation;
    multiple activities with the same Definition remain distinct there.
    """
    entries = [row for row in phase[collection]
               if row["node"] == node and row[category] == identifier
               and abs(row[quantity]) > 1e-12]
    entries.sort(key=lambda row: (-abs(row[quantity]), row["origin_kind"],
                                  str(row["origin_definition"]), row.get("dimension", row.get("role", ""))))
    fields = ("origin_kind", "origin_definition", "dimension", "amount_t") if collection == "resource_contributions" else (
        "origin_kind", "origin_definition", "role", "rate_per_day")
    return {"drivers": [{key: row[key] for key in fields} for row in entries[:top]],
            "total_driver_count": len(entries), "driver_detail_section": collection}


def summarize_projection(projection: dict) -> dict:
    """Overview of unlike quantities, with sections traceable in the full projection.

    This is not a ranking or feasibility score. Only positive shortfalls and
    explicit unresolved limits are surfaced; all Definition coefficients remain
    available in the unabridged read-only report.
    """
    phases = []
    for phase in projection["phases"]:
        def resource_drivers(row):
            return _leading_activity_drivers(phase, "resource_contributions", node=row["node"],
                                             category="resource", identifier=row["resource"],
                                             quantity="amount_t")

        def service_drivers(row):
            return _leading_activity_drivers(phase, "service_contributions", node=row["node"],
                                             category="service", identifier=row["service"],
                                             quantity="rate_per_day")

        phases.append({
            "name": phase["name"], "days": phase["days"],
            "scale": phase["scale"],
            "resource_shortfalls_by_node": [
                {"node": row["node"], "resource": row["resource"], "shortfall_t": row["shortfall_t"],
                 "opening_investment_stock_shortfall_t": row["opening_investment_stock_shortfall_t"],
                 "one_time_investment_and_activity_demand_t": row["one_time_investment_and_activity_demand_t"],
                 "nominal_recurring_net_t_per_day": row["nominal_recurring_net_t_per_day"],
                 "conditional_stock_exhaustion_days_after_investment": row["conditional_stock_exhaustion_days_after_investment"],
                 "shortfall_without_assumed_arrivals_t": row["shortfall_without_assumed_arrivals_t"],
                 **resource_drivers(row)}
                for row in phase["resources"] if row["shortfall_t"] > 1e-12
            ],
            "conditional_incoming_cargo_risks_by_node": [
                {"node": row["node"], "resource": row["resource"],
                 "cumulative_unverified_incoming_cargo_t": row["cumulative_unverified_incoming_cargo_t"],
                 "shortfall_with_assumed_arrivals_t": row["shortfall_t"],
                 "shortfall_without_assumed_arrivals_t": row["shortfall_without_assumed_arrivals_t"],
                 "status": "incoming_cargo_not_settled_or_guaranteed"}
                for row in phase["resources"] if row["cumulative_unverified_incoming_cargo_t"] > 1e-12
            ],
            "recurring_resource_pressures_by_node": [
                {"node": row["node"], "resource": row["resource"],
                 "nominal_recurring_net_t_per_day": row["nominal_recurring_net_t_per_day"],
                 "conditional_stock_exhaustion_days_after_investment": row["conditional_stock_exhaustion_days_after_investment"]}
                for row in phase["resources"] if row["nominal_recurring_net_t_per_day"] < -1e-12
            ],
            "service_shortfalls_by_node": [
                {"node": row["node"], "service": row["service"], "gap_per_day": row["nominal_gap_per_day"],
                 **service_drivers(row)}
                for row in phase["service_constraints"] if row["nominal_gap_per_day"] > 1e-12
            ],
            "power_and_population_by_node": [
                {k: row[k] for k in ("node", "power_generation_nominal_mw", "power_demand_nominal_mw",
                                         "power_gap_mw", "life_support_nominal_person_days_per_day",
                                         "life_support_assigned_person_days_per_day",
                                         "life_support_gap_person_days_per_day", "housing_nominal_people",
                                         "conditional_supported_residents_people", "conditional_housing_gap_people")}
                for row in phase["constraints"]
                if row["power_generation_nominal_mw"] > 0 or row["power_demand_nominal_mw"] > 0
                or row["housing_nominal_people"] > 0 or row["life_support_nominal_person_days_per_day"] > 0
                or row["life_support_assigned_person_days_per_day"] > 0
            ],
            "research_point_balance": phase["research_point_balance"],
            "research_service_constraints": phase["research_service_constraints"],
            "investment_constraints": phase["investment_constraints"],
            "od_transport_constraints": phase["od_transport_constraints"],
            "extraction_world_context": phase["extraction_world_context"],
            "power_world_context": phase["power_world_context"],
            "science_activity_bounds": [
                {k: item[k] for k in ("campaign", "origin", "duration_days", "conditional_rp_reward",
                                     "required_crew", "crew_seat_gap_people", "crew_registered_site_days_lower_bound",
                                     "crew_site_provisions_lower_bound_t", "crew_minimum_loaded_payload_lower_bound_t", "status")}
                for item in phase["science_campaigns"]],
            "survey_capacity_bounds": [
                {k: item[k] for k in ("node", "provider", "target_cell", "target_resource",
                                     "nominal_progress_per_day", "conditional_minimum_days", "status")}
                for item in phase["survey_activities"]],
            "spatial_and_upgrade_investment": [
                {k: item[k] for k in ("node", "recipe", "units", "required_construction_work", "status")}
                for item in phase["spatial_projects"]] + [
                {k: item[k] for k in ("node", "facility", "target_level", "units", "required_construction_work", "status")}
                for item in phase["upgrade_projects"]],
            "passenger_transfer_requirements": [
                {k: item[k] for k in ("origin", "destination", "vehicle", "requested_people",
                                     "nominal_supportable_seats", "nominal_seat_gap_people",
                                     "assumed_onboard_days", "total_departure_payload_t",
                                     "vehicle_nameplate_payload_upper_bound_t", "nameplate_payload_gap_t",
                                     "assumed_duration_exceeds_vehicle_endurance", "status")}
                for item in phase["passenger_transfer_requirements"]],
            "founding_investment": [
                {k: item[k] for k in ("staging_node", "recipe", "target", "payload_t", "preparation_work", "status")}
                for item in phase["founding_projects"]],
            "market_provider_bounds": phase["market_provider_constraints"],
            "market_funds_condition": phase["market_funds_condition"],
            "unassessed_constraints": phase["unassessed_constraints"],
            "detail_sections": [
                "activity_sources", "resources", "resource_contributions", "service_contributions", "service_constraints", "research_stages", "research_service_constraints", "power_world_context",
                "transport_services", "transfer_requirements", "spatial_projects", "upgrade_projects", "science_campaigns", "survey_activities", "founding_projects", "passenger_transfer_requirements",
                "market_buys", "market_provider_constraints", "market_funds_condition", "system_resources", "system_services",
            ],
        })
    return {"content_id": projection["content_id"], "world_definition_id": projection["world_definition_id"],
            "model": "definition_quantity_summary_v1", "phases": phases}


_SUMMARY_ROW_IDENTITY = {
    "resource_shortfalls_by_node": ("node", "resource"),
    "recurring_resource_pressures_by_node": ("node", "resource"),
    "conditional_incoming_cargo_risks_by_node": ("node", "resource"),
    "service_shortfalls_by_node": ("node", "service"),
    "power_and_population_by_node": ("node",),
    "od_transport_constraints": ("origin", "destination"),
    "extraction_world_context": ("node", "resource", "output_resource"),
    "power_world_context": ("node", "facility"),
    "science_activity_bounds": ("campaign", "origin"),
    "survey_capacity_bounds": ("node", "provider", "target_cell", "target_resource"),
    "founding_investment": ("staging_node", "recipe", "target"),
    "passenger_transfer_requirements": ("origin", "destination", "vehicle"),
    "market_provider_bounds": ("provider", "resource"),
}


def _relative_phase_overview(baseline: dict, chosen: dict) -> dict:
    """Only modified conditions appear; omissions mean *unchanged*, not available.

    This is a display reduction of two projections, never a second quantity
    calculator or an interpretation of successful Research/Movement/Allocation.
    """
    changed = {}
    for section, after in chosen.items():
        if section in {"name", "days", "detail_sections"}:
            continue
        before = baseline.get(section)
        if before == after:
            continue
        fields = _SUMMARY_ROW_IDENTITY.get(section)
        if fields is None or not isinstance(before, list) or not isinstance(after, list):
            if section == "unassessed_constraints":
                changed[section] = {"new": sorted(set(after) - set(before)),
                                    "no_longer_listed": sorted(set(before) - set(after))}
            else:
                changed[section] = after
            continue
        # Some sources (e.g. multiple Survey allocations) may share an identity.
        # Do not collapse activity rows into an invented combined provider.
        def grouped(rows):
            result = defaultdict(list)
            for row in rows:
                result[tuple(row[field] for field in fields)].append(row)
            return result
        initial, altered = grouped(before), grouped(after)
        new_rows = [row for key in sorted(altered) if initial.get(key) != altered[key]
                    for row in altered[key]]
        removed_keys = [dict(zip(fields, key)) for key in sorted(initial)
                        if key not in altered]
        changed[section] = {"changed_or_added": new_rows,
                            "no_longer_listed": removed_keys,
                            "full_details_section": section}
    return {"name": chosen["name"], "days": chosen["days"],
            "changed_sections": changed}


def summarize(result: dict) -> dict:
    """A complete baseline and explicit *changes* for each alternative.

    Unlike a second copy of every unchanged phase/ledger, this remains usable
    with many cases. An absent case quantity means unchanged from baseline, NOT
    zero. Detailed unabridged report includes full per-case rows and differences.
    """
    if "cases" not in result:
        return summarize_projection(result)
    baseline = result["cases"][0]
    baseline_summary = summarize_projection(baseline["projection"])
    case_overviews = [{"name": baseline["name"], "summary": baseline_summary}]
    for case in result["cases"][1:]:
        summary = summarize_projection(case["projection"])
        if len(summary["phases"]) != len(baseline_summary["phases"]) or any(
            lhs["name"] != rhs["name"] or lhs["days"] != rhs["days"]
            for lhs, rhs in zip(baseline_summary["phases"], summary["phases"])
        ):
            # Different durations/phase sets are not equivalent quantity bases.
            case_overviews.append({"name": case["name"], "summary": summary,
                                   "incomparable_phase_basis": True})
            continue
        case_overviews.append({"name": case["name"], "relative_to_baseline": baseline["name"],
                               "unchanged_quantities_omitted": True,
                               "changed_phases": [
                                   _relative_phase_overview(base_phase, chosen_phase)
                                   for base_phase, chosen_phase in zip(
                                       baseline_summary["phases"], summary["phases"])
                                   if base_phase != chosen_phase]})
    differences_by_case = {case["name"]: Counter() for case in result["cases"][1:]}
    for row in result["differences"]:
        differences_by_case[row["case"]][row["section"]] += 1
    return {"model": "definition_quantity_comparison_summary_v1",
            "baseline_case": baseline["name"], "cases": case_overviews,
            "difference_sections": sorted({row["section"] for row in result["differences"]}),
            "difference_counts_by_case_and_section": [
                {"case": case["name"], "sections": dict(sorted(differences_by_case[case["name"]].items()))}
                for case in result["cases"][1:]],
            "full_differences_detail_section": "differences"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON phases specifying activities, assets and demands")
    parser.add_argument("--summary", action="store_true", help="show gaps, capacity bounds and assumptions without expanding every coefficient")
    args = parser.parse_args()
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    result = compare_cases(payload) if "cases" in payload else evaluate(payload)
    json.dump(summarize(result) if args.summary else result, sys.stdout,
              ensure_ascii=False, indent=2, allow_nan=False)
    print()


if __name__ == "__main__":
    main()
