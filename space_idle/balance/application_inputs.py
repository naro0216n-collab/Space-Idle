"""Translate shared Application Query projections into development quantities.

This module has no Domain, Simulation or private GameApplication dependencies.
All definition fields come from the very same GetCatalog rows used by the UI.
Actual assets and current resources come from UI-facing Query responses.
Only physical World design statistics require a separate non-player Query.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from hashlib import sha256
import json

from ..app_contracts.queries import (
    GetCatalog, GetDevelopmentWorldReference, GetFleet, GetOperationalNode, GetResearch,
)


def _resources(rows):
    return {str(k): float(v) for k, v in rows}


def _provider(row):
    return {
        "id": row.id, "tier": row.tier,
        "generation_points_per_day": row.generation_points_per_day,
        "research_execution_per_day": row.research_execution_per_day,
        "storage_capacity_points": row.storage_capacity_points,
        "crew_person_days_per_research_point": row.crew_person_days_per_research_point,
    }


def collect_application_inputs(app) -> dict:
    """Read-only report source, with no independent traversal of implementation internals."""
    base = app.query_many({
        "catalog": GetCatalog(),
        "fleet": GetFleet(),
        "research_state": GetResearch(),
        "world_reference": GetDevelopmentWorldReference(),
    })
    catalog = base["catalog"]
    fleet = base["fleet"]
    research_state = base["research_state"]
    nodes = app.query_many({row.id: GetOperationalNode(row.id) for row in catalog.operational_nodes})

    facilities = {}
    for row in catalog.facilities:
        d = row.design
        if d is None:
            raise ValueError(f"catalog definition omitted design coefficients: {row.id}")
        facilities[row.id] = {
            "name": row.display_name,
            "construction_resources_t": None if d.construction_resources_t is None else _resources(d.construction_resources_t),
            "construction_work": d.construction_work,
            "self_deploying": d.self_deploying,
            "prerequisites": list(d.prerequisites),
            "maintenance_per_day_t": None if d.maintenance_per_day_t is None else _resources(d.maintenance_per_day_t),
            "operating_per_day_t": _resources(d.operating_per_day_t),
            "services_per_day": dict(row.service_capacity_supplies),
            "process_throughput_per_day": d.process_throughput_per_day,
            "construction_work_per_day": d.construction_work_per_day,
            "power_load_mw": d.power_load_mw,
            "power_generation_kind": d.power_generation_kind,
            "power_reference_generation_mw": d.power_reference_generation_mw,
            "extraction_capacity_t_per_day": d.extraction_capacity_t_per_day,
            "housing_capacity": d.housing_capacity,
            "life_support_person_days_per_day": d.life_support_person_days_per_day,
            "life_support_resources_per_person_day_t": _resources(d.life_support_resources_per_person_day_t),
            "capabilities": list(row.capabilities),
            "placement_scope": row.placement_scope,
            "research_provider": None if d.research_provider is None else _provider(d.research_provider),
        }
    vehicles = {}
    for row in catalog.vehicles:
        vehicles[row.id] = {
            "name": row.display_name,
            "production_resources_t": _resources(row.production_resources),
            "production_service_type": row.production_service_type,
            "production_days": row.production_days,
            "turnaround_resources_t": _resources(row.turnaround_resources),
            "turnaround_service_type": row.turnaround_service_type,
            "turnaround_days": row.turnaround_days,
            "payload_t": row.payload_t,
            "propellant_capacity_t": row.propellant_capacity_t,
            "propellant_resource_id": row.propellant_resource_id,
            "research_providers": [{k: v for k, v in _provider(p).items()
                                    if k != "crew_person_days_per_research_point"}
                                   for p in row.research_providers],
        }
    research = {}
    for row in catalog.research:
        stages = []
        for stage in row.stages:
            entry = {"id": stage.stage_id, "kind": stage.stage_type}
            if stage.stage_type == "theory":
                entry["rp"] = stage.required_progress
            elif stage.stage_type == "prototype":
                entry.update({"work": stage.required_progress, "resources_t": _resources(stage.resources)})
            elif stage.stage_type == "demonstration":
                entry["work"] = stage.required_progress
            elif stage.stage_type == "operational_experience":
                entry["experience"] = dict(stage.operational_experience)
            entry["execution_requirements"] = [dict(req) for req in stage.execution_requirements]
            stages.append(entry)
        research[row.id] = {
            "name": row.display_name, "stage": row.progression_stage,
            "category": row.category, "series": row.series,
            "prerequisites": list(row.prerequisites), "stages": stages,
        }
    processes = {row.id: {
        "name": row.display_name,
        "inputs_per_unit_t": _resources(row.inputs_per_day),
        "outputs_per_unit_t": _resources(row.outputs_per_day),
        "required_capabilities": list(row.required_capabilities),
        "prerequisites": list(row.prerequisites),
        "provider_facilities": list(row.provider_facilities),
    } for row in catalog.processes}
    extraction = {row.id: {
        "name": row.display_name,
        "resource_id": row.resource_id, "output_resource_id": row.output_resource_id,
        "prerequisites": list(row.prerequisites),
        "provider_facilities": list(row.provider_facilities),
    } for row in catalog.extraction_methods}

    owned_facilities = defaultdict(int)
    installed_facilities = []
    maintenance = defaultdict(float)
    available_inventory = []
    population = []
    for node_id, node in sorted(nodes.items()):
        for row in node.facilities:
            installed_facilities.append({
                "node": node_id, "facility": row.definition_id, "level": row.level,
                "process": row.selected_process_id,
                "extraction_method": row.selected_extraction_method_id,
                "invested_resources_t": _resources(row.invested_resources),
            })
            owned_facilities[(node_id, row.definition_id)] += row.level
            for resource_id, amount in row.maintenance_demand_per_day:
                maintenance[(node_id, row.definition_id, resource_id)] += amount
        for row in node.inventory:
            if row.available > 0:
                available_inventory.append({"node": node_id, "resource": row.resource_id, "available_t": row.available})
        if node.population is not None and node.population.current_count:
            population.append({"node": node_id, "people": node.population.current_count})
    existing_fleet = defaultdict(int)
    detached_fleet = []
    for row in fleet.pools:
        existing_fleet[(row.operational_node_id, row.vehicle_definition_id)] += row.total_units
    for row in fleet.commitments:
        if row.operational_node_id is None:
            detached_fleet.append({"vehicle": row.vehicle_definition_id, "units": row.quantity,
                                   "location_kind": row.location_kind,
                                   "movement_execution_id": row.movement_execution_id})

    result = {
        "identity": {"content_id": app.content_id, "world_definition_id": app.world_definition_id,
                     "scenario_id": app.scenario_id, "game_day": app.game_day},
        "resources": {r.id: {"name": r.display_name, "unit": r.unit, "category": r.category}
                      for r in catalog.resources},
        "research": research, "facilities": facilities, "vehicles": vehicles,
        "processes": processes, "extraction": extraction,
        "world": {"bodies": [asdict(row) for row in catalog.celestial_bodies],
                  "nodes": [asdict(row) for row in catalog.operational_nodes],
                  "surface_resource_distribution": base["world_reference"].surface_resource_distribution},
        "owned": {
            "facilities": [{"node": node, "facility": facility, "count": count}
                           for (node, facility), count in sorted(owned_facilities.items())],
            "fleet": [{"node": node, "vehicle": vehicle, "count": count}
                      for (node, vehicle), count in sorted(existing_fleet.items())],
            "installed_facilities": sorted(installed_facilities, key=lambda r:(r["node"],r["facility"],r["level"])),
            "detached_fleet": detached_fleet,
            "population": population,
            "stored_research_points": research_state.stored_points,
            "available_inventory": available_inventory,
            "completed_technologies": list(research_state.completed_technologies),
            "actual_maintenance": [{"node": n, "facility": f, "resource": r, "quantity": amount}
                                   for (n, f, r), amount in sorted(maintenance.items())],
        },
    }
    design = {key: result[key] for key in ("resources", "research", "facilities", "vehicles", "processes", "extraction", "world")}
    encoded = json.dumps(design, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    result["identity"]["balance_definition_sha256"] = sha256(encoded.encode("utf-8")).hexdigest()
    return result
