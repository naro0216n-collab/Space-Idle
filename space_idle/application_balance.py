"""Read-only balance-design projections of canonical domain-owned coefficients.

This is not a simulation or an alternative eligibility/allocator. Every cost,
capability, and research stage is obtained from its existing owner.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from hashlib import sha256
import json

from .app_contracts.queries import GetCatalog, GetDependencyAnalytics, GetFleet
from .research_models import (
    ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
)


def _execution_requirements(requirements):
    rows = []
    for requirement in requirements:
        row = {"kind": type(requirement).__name__}
        for name in ("resource_id", "service_type", "pool_id", "amount_per_execution", "scope", "scope_id"):
            value = getattr(requirement, name, None)
            if value is not None:
                row[name] = str(value.value) if hasattr(value, "value") else (str(value) if name.endswith("_id") else value)
        rows.append(row)
    return rows


def _resources(rows):
    return {str(k): float(v) for k, v in sorted(rows, key=lambda x: str(x[0]))}


def project_balance_definitions(app) -> dict:
    """Application-owned, non-mutating definition and actual-base-state projection."""
    sim = app._simulation
    catalog = app.query(GetCatalog())
    definitions = sim.facilities.definitions
    facility_rows = {}
    for key, facility in sorted(definitions.items(), key=lambda x: str(x[0])):
        recipe = sim.projects.recipes.get(key)
        invested = {} if recipe is None else _resources((row.resource_id, row.amount_t) for row in recipe.resources)
        provider = sim.research.facility_provider_for_definition(key) if sim.research is not None else None
        power_spec = sim.power.specs.get(key)
        generation = None if power_spec is None else power_spec.generation
        power_reference = (0.0 if generation is None else
                           generation.mw if hasattr(generation, "mw") else generation.rated_mw_at_reference_flux)
        facility_rows[str(key)] = {
            "name": facility.display_name,
            "construction_resources_t": invested if recipe else None,
            "construction_work": None if recipe is None else recipe.construction_work,
            "self_deploying": None if recipe is None else recipe.self_deploying,
            "prerequisites": [] if recipe is None else sorted(map(str, recipe.prerequisite_technologies)),
            "maintenance_per_day_t": _resources(sim.facilities.maintenance_requirements_for_investment(key, {
                # Owner method accepts authoritative DefinitionIds, not display names.
                row.resource_id: row.amount_t for row in recipe.resources
            }).items()) if recipe is not None else None,
            "operating_per_day_t": _resources(facility.operating_resources_per_day),
            "services_per_day": {p.service_type: p.nominal_rate for p in facility.service_capacity_supplies},
            "process_throughput_per_day": facility.process_throughput_per_day,
            "construction_work_per_day": (sim.projects.construction_providers[key].work_per_day if key in sim.projects.construction_providers else 0.0),
            "power_load_mw": 0.0 if power_spec is None else power_spec.load_mw,
            "power_generation_kind": "none" if generation is None else type(generation).__name__,
            "power_reference_generation_mw": power_reference,
            "extraction_capacity_t_per_day": facility.extraction_capacity_t_per_day,
            "housing_capacity": facility.housing_capacity,
            "life_support_person_days_per_day": None if facility.life_support is None else facility.life_support.person_days_per_day,
            "life_support_resources_per_person_day_t": {} if facility.life_support is None else _resources(facility.life_support.net_resources),
            "capabilities": sorted(facility.capability_ids),
            "placement_scope": facility.placement_scope.value,
            "research_provider": None if provider is None else {
                "id": str(provider.id), "tier": provider.tier,
                "generation_points_per_day": provider.levels[0].generation_points_per_day,
                "research_execution_per_day": provider.levels[0].research_execution_per_day,
                "storage_capacity_points": provider.levels[0].storage_capacity_points,
                "crew_person_days_per_research_point": provider.crew_person_days_per_research_point,
            },
        }
    vehicles = {}
    for vehicle in sim.transport.vehicle_definitions():
        provider_specs = [] if sim.research is None else [
            p for p in sim.research.providers.values()
            if p.source_kind.value == "fleet" and p.accepts_source(vehicle.generic_capabilities)
        ]
        vehicles[str(vehicle.id)] = {
            "name": vehicle.display_name,
            "production_resources_t": _resources(vehicle.production_resources),
            "production_service_type": vehicle.production_service_type,
            "production_days": vehicle.production_days,
            "turnaround_resources_t": _resources(vehicle.turnaround_resources),
            "turnaround_service_type": vehicle.turnaround_service_type,
            "turnaround_days": vehicle.turnaround_days,
            "payload_t": vehicle.payload_t,
            "propellant_capacity_t": vehicle.propellant_capacity_t,
            "propellant_resource_id": None if vehicle.propellant_resource_id is None else str(vehicle.propellant_resource_id),
            "research_providers": [{"id": str(p.id), "tier": p.tier,
                "generation_points_per_day": p.levels[0].generation_points_per_day,
                "research_execution_per_day": p.levels[0].research_execution_per_day,
                "storage_capacity_points": p.levels[0].storage_capacity_points} for p in provider_specs],
        }
    research = {}
    if sim.research is not None:
        for research_def in sorted(sim.research.definitions.values(), key=lambda x: str(x.id)):
            stages = []
            for spec in research_def.stage_specs:
                row = {"id": spec.stage_id, "kind": spec.stage_type.value}
                if isinstance(spec, ResearchTheoryStageSpec):
                    row["rp"] = spec.research_point_cost
                elif isinstance(spec, ResearchPrototypeStageSpec):
                    row.update({"work": spec.required_work, "resources_t": _resources(spec.resources.items())})
                elif isinstance(spec, ResearchDemonstrationStageSpec):
                    row["work"] = spec.required_work
                elif isinstance(spec, ResearchOperationalExperienceStageSpec):
                    row["experience"] = dict(sorted(spec.requirements.items()))
                row["execution_requirements"] = _execution_requirements(getattr(spec, "execution_requirements", ()))
                stages.append(row)
            research[str(research_def.id)] = {
                "name": research_def.display_name,
                "stage": research_def.progression_stage,
                "category": research_def.category,
                "series": research_def.series,
                "prerequisites": sorted(map(str, research_def.prerequisites)),
                "stages": stages,
            }
    extraction = {}
    if sim.extraction is not None:
        for spec in sim.extraction.specs.values():
            extraction[str(spec.id)] = {
                "name": spec.display_name or str(spec.id), "resource_id": str(spec.resource_id),
                "output_resource_id": str(spec.output_resource_id),
                "prerequisites": sorted(map(str, spec.prerequisite_technologies)),
                "provider_facilities": sorted(str(fid) for fid in definitions if spec in sim.extraction.compatible_methods(fid)),
            }
    processes = {}
    for process in sorted(sim.industry.processes.values(), key=lambda x: str(x.id)):
        processes[str(process.id)] = {
            "name": process.display_name,
            "inputs_per_unit_t": _resources(process.inputs_per_day.items()),
            "outputs_per_unit_t": _resources(process.outputs_per_day.items()),
            "required_capabilities": sorted(process.required_capabilities),
            "prerequisites": sorted(map(str, process.prerequisite_technologies)),
            "provider_facilities": sorted(str(key) for key, value in definitions.items()
                if process.required_capabilities <= value.capability_ids),
        }
    owned_facilities = defaultdict(int)
    installed_facilities = []
    actual_maintenance = defaultdict(float)
    for state in sim.facilities.facilities.values():
        row = {"node": str(state.operational_node_id), "facility": str(state.definition_id),
               "level": state.level, "process": None if state.selected_process_id is None else str(state.selected_process_id),
               "extraction_method": None if state.selected_extraction_method_id is None else str(state.selected_extraction_method_id),
               "invested_resources_t": _resources(state.invested_resources.items())}
        for resource_id, amount in sim.facilities.maintenance_requirements_per_day(state.id).items():
            actual_maintenance[(str(state.operational_node_id), str(state.definition_id), str(resource_id))] += amount
        installed_facilities.append(row)
        owned_facilities[(row["node"], row["facility"])] += state.level
    fleet = app.query(GetFleet())
    existing_fleet = defaultdict(int)
    detached_fleet = []
    for pool in fleet.pools:
        existing_fleet[(pool.operational_node_id, pool.vehicle_definition_id)] += pool.total_units
    for row in fleet.commitments:
        if row.operational_node_id is None:
            detached_fleet.append({"vehicle": row.vehicle_definition_id, "units": row.quantity,
                                   "location_kind": row.location_kind,
                                   "movement_execution_id": row.movement_execution_id})
    baseline_population = []
    if sim.population is not None:
        for node in sim.graph.operational_node_ids():
            people = sim.population.count_at(node)
            if people:
                baseline_population.append({"node": str(node), "people": people})
    initial_available_stock = []
    for node, resource in sorted(sim.inventory.stock, key=lambda pair:(str(pair[0]),str(pair[1]))):
        available = sim.inventory.available(node, resource)
        if available > 0:
            initial_available_stock.append({"node": str(node), "resource": str(resource),
                                            "available_t": available})
    # Physical World design statistics; no Survey or hidden Player Knowledge is changed.
    world_summary = {}
    for cell in sorted(sim.graph.surface_cells.values(), key=lambda row: str(row.id)):
        body_id = str(cell.body_id)
        stats = world_summary.setdefault(body_id, {"cells": 0, "area_km2": 0.0, "terrain_profiles": {},
                                                   "resources": {}})
        stats["cells"] += 1
        stats["area_km2"] += cell.area_km2
        stats["terrain_profiles"][cell.terrain.profile_id] = stats["terrain_profiles"].get(cell.terrain.profile_id, 0) + 1
        for resource, potential in cell.resource_potential_by_resource.items():
            r = stats["resources"].setdefault(str(resource), {"covered_cells": 0,
                "covered_area_km2": 0.0, "area_weighted_potential": 0.0,
                "min_potential": potential, "max_potential": potential})
            r["covered_cells"] += 1
            r["covered_area_km2"] += cell.area_km2
            r["area_weighted_potential"] += cell.area_km2 * potential
            r["min_potential"] = min(r["min_potential"], potential)
            r["max_potential"] = max(r["max_potential"], potential)
    for body in world_summary.values():
        body["terrain_profiles"] = dict(sorted(body["terrain_profiles"].items()))
        for resource in body["resources"].values():
            resource["area_weighted_mean_potential"] = resource.pop("area_weighted_potential") / resource["covered_area_km2"]
        body["resources"] = dict(sorted(body["resources"].items()))
    result = {
        "identity": {"content_id": app.content_id, "world_definition_id": app.world_definition_id,
                     "scenario_id": app.scenario_id, "game_day": app.game_day},
        "resources": {row.id: {"name": row.display_name, "unit": row.unit, "category": row.category}
                      for row in catalog.resources},
        "research": research, "facilities": facility_rows, "vehicles": vehicles, "processes": processes, "extraction": extraction,
        "world": {"bodies": [asdict(row) for row in catalog.celestial_bodies],
                  "nodes": [asdict(row) for row in catalog.operational_nodes],
                  "surface_resource_distribution": dict(sorted(world_summary.items()))},
        "owned": {"facilities": [{"node": node, "facility": facility, "count": count}
                                for (node, facility), count in sorted(owned_facilities.items())],
                  "fleet": [{"node": node, "vehicle": vehicle, "count": count}
                            for (node, vehicle), count in sorted(existing_fleet.items())],
                  "installed_facilities": sorted(installed_facilities, key=lambda r:(r["node"], r["facility"],r["level"])),
                  "detached_fleet": detached_fleet,
                  "population": sorted(baseline_population, key=lambda r:r["node"]),
                  "stored_research_points": None if sim.research is None else sim.research.stored_points,
                  "available_inventory": initial_available_stock,
                  "actual_maintenance": [{"node": n, "facility": f, "resource": r, "quantity": amount}
                                         for (n, f, r), amount in sorted(actual_maintenance.items())]},
    }
    # Content ID can be unchanged after balance edits. A normalized coefficient
    # digest makes evaluation reports distinguish physically different Definitions.
    design = {key: result[key] for key in ("resources", "research", "facilities", "vehicles", "processes", "extraction", "world")}
    encoded = json.dumps(design, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    result["identity"]["balance_definition_sha256"] = sha256(encoded.encode("utf-8")).hexdigest()
    return result


def project_balance_current(app) -> dict:
    """Current, explicitly state-bound Resource and finite Service evidence."""
    current = app.query(GetDependencyAnalytics(scope_kind="player", time_basis="CURRENT"))
    return {
        "day": current.day, "scope": current.scope_kind, "node_ids": list(current.node_ids),
        "resources": [asdict(row) for row in current.current_resources],
        "services": [asdict(row) for row in current.current_services],
        "source": "GetDependencyAnalytics(CURRENT): real state, not prospective balance",
    }


def project_balance_site_power(app, node_id: str, facility_id: str) -> dict:
    """Canonical Power owner supplies environmental coefficients; no private solar calculation."""
    from .shared import DefinitionId, SpatialNodeId
    sim = app._simulation
    if not sim.graph.has_operational_node(SpatialNodeId(node_id)):
        raise ValueError(f"unknown operational node: {node_id}")
    if DefinitionId(facility_id) not in sim.facilities.definitions:
        raise ValueError(f"unknown facility: {facility_id}")
    if sim.facilities.definitions[DefinitionId(facility_id)].placement_scope.value != "OPERATIONAL_NODE":
        return {"generation_mw": None, "load_mw": None, "status": "surface_cell_not_selected"}
    generation, load = sim.power.nominal_for_definition_at_context(
        DefinitionId(facility_id), SpatialNodeId(node_id))
    return {"generation_mw": generation, "load_mw": load, "status": "nominal_site_coefficient"}
