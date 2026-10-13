"""Content-authoring evidence across the registered game system.

This is not a second Simulation, a player plan evaluator, an optimizer, or a
catalog validation oracle. It exposes physical *coefficients and relationships*
which a designer can use to formulate and revise a development-stage hypothesis.
Nothing here prescribes quantities of facilities, routes, or technologies to buy.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .catalog import GameCatalog
from .construction.models import BuildResourceRequirement
from .execution_requirements import (
    ResourceRequirement, ServiceCapacityRequirement, PoolRequirement,
    PoolAdmissionRequirement, StockOrPoolAdmissionRequirement,
)
from .site import RequiresFacet, FacetValueRange, AtmosphericPartialPressureRange
from .power import FixedGeneration, SolarGeneration
from .research_models import (
    ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
)
from .research_models import ResearchProviderSourceKind
from .scenario import ScenarioDefinition
from .simulation import Simulation


def _sorted_resources(amounts: dict | tuple) -> dict[str, float]:
    return {str(k): float(v) for k, v in sorted(dict(amounts).items(), key=lambda kv: str(kv[0]))}


def _recipe_resources(rows: tuple[BuildResourceRequirement, ...]) -> dict[str, float]:
    return _sorted_resources({row.resource_id: row.amount_t for row in rows})


def _environment_condition(condition) -> dict[str, Any]:
    row: dict[str, Any] = {"code": condition.code, "description": condition.description}
    if isinstance(condition, (RequiresFacet, FacetValueRange)):
        row["facet"] = condition.facet_type.__name__
    if isinstance(condition, FacetValueRange):
        row.update(attribute=condition.attribute, minimum=condition.minimum, maximum=condition.maximum)
    if isinstance(condition, AtmosphericPartialPressureRange):
        row.update(species_id=str(condition.species_id), minimum_pa=condition.minimum_pa,
                   maximum_pa=condition.maximum_pa)
    return row


def _execution_requirement(requirement) -> dict[str, Any]:
    row: dict[str, Any] = {"amount_per_execution": requirement.amount_per_execution}
    if isinstance(requirement, ResourceRequirement):
        row.update(kind="resource", resource_id=str(requirement.resource_id),
                   constraint_node_id=None if requirement.constraint_node_id is None
                   else str(requirement.constraint_node_id))
    elif isinstance(requirement, ServiceCapacityRequirement):
        row.update(kind="service", service_type=requirement.service_type,
                   scope=requirement.scope.value, scope_id=requirement.scope_id,
                   constraint_node_id=None if requirement.constraint_node_id is None
                   else str(requirement.constraint_node_id))
    elif isinstance(requirement, (PoolRequirement, PoolAdmissionRequirement, StockOrPoolAdmissionRequirement)):
        row.update(kind=("pool" if isinstance(requirement, PoolRequirement) else
                         "pool_admission" if isinstance(requirement, PoolAdmissionRequirement) else
                         "stock_or_pool_admission"), pool_id=requirement.pool_id)
        if not isinstance(requirement, StockOrPoolAdmissionRequirement):
            row["scope_id"] = requirement.scope_id
    else:
        raise TypeError(f"Unsupported registered execution requirement: {type(requirement).__name__}")
    return row


def _site(req) -> dict[str, Any]:
    return {
        "classifications": sorted(str(row.classification.value) for row in req.spatial_classification_requirements),
        "capabilities": [
            {"id": row.capability_id, "required_state": row.required_state.value}
            for row in sorted(req.capability_requirements, key=lambda r: (r.capability_id, r.required_state.value))
        ],
        "environment": [_environment_condition(row) for row in sorted(req.environment, key=lambda r: r.code)],
    }


def _power(spec) -> dict[str, Any]:
    if spec is None:
        return {}
    generation = None
    if isinstance(spec.generation, FixedGeneration):
        generation = {"kind": "fixed", "mw": spec.generation.mw}
    elif isinstance(spec.generation, SolarGeneration):
        generation = {
            "kind": "solar", "rated_mw_at_reference_flux": spec.generation.rated_mw_at_reference_flux,
            "reference_flux_w_m2": spec.generation.reference_flux_w_m2,
        }
    return {"generation": generation, "load_mw": spec.load_mw, "standby_load_mw": spec.standby_load_mw}


def _stage(spec) -> dict[str, Any]:
    row: dict[str, Any] = {"kind": spec.stage_type.value, "id": spec.stage_id}
    if hasattr(spec, "execution_requirements"):
        row["execution_requirements"] = [_execution_requirement(req) for req in spec.execution_requirements]
    if isinstance(spec, ResearchTheoryStageSpec):
        row["rp"] = spec.research_point_cost
    elif isinstance(spec, ResearchPrototypeStageSpec):
        row["resources_t"] = _sorted_resources(spec.resources)
        row["work"] = spec.required_work
        row["site"] = _site(spec.site_requirements)
    elif isinstance(spec, ResearchDemonstrationStageSpec):
        row["work"] = spec.required_work
        row["site"] = _site(spec.site_requirements)
    elif isinstance(spec, ResearchOperationalExperienceStageSpec):
        row["experience"] = dict(sorted(spec.requirements.items()))
    return row


def review_content(sim: Simulation, catalog: GameCatalog, scenario: ScenarioDefinition) -> dict[str, Any]:
    """Read one composed Definition/World/Scenario; never touch runtime State.

    Coefficients retain their original basis. A producer's *per-facility*
    nominal rate is not aggregate output or a demonstrated ability to operate.
    Purchase requirements are not added into an invented overall demand.
    """
    links: dict[str, dict[str, list[dict[str, Any]]]] = {
        str(id): {"sources": [], "uses": []} for id in catalog.resources
    }

    def link(resource: str, direction: str, *, owner_kind: str, owner_id: str,
             quantity: float, basis: str, **extra) -> None:
        # New Content resources must originate from the registered Catalog.
        key = str(resource)
        if key not in links:
            raise ValueError(f"Content refers to unregistered resource {key} in {owner_kind}:{owner_id}")
        links[key][direction].append({
            "owner_kind": owner_kind, "owner_id": str(owner_id), "quantity_t": float(quantity),
            "basis": basis, **extra,
        })

    facilities: list[dict[str, Any]] = []
    for fid, definition in sorted(sim.facilities.definitions.items()):
        recipe = sim.projects.recipes.get(fid)
        resource_inputs = _recipe_resources(recipe.resources) if recipe else {}
        for resource, amount in resource_inputs.items():
            link(resource, "uses", owner_kind="facility_construction", owner_id=fid,
                 quantity=amount, basis="t_per_new_facility")
            if definition.maintenance_fraction_per_year:
                link(resource, "uses", owner_kind="facility_maintenance", owner_id=fid,
                     quantity=amount * definition.maintenance_fraction_per_year,
                     basis="t_per_year_per_new_facility_at_recipe_investment")
        p = sim.research.facility_provider_for_definition(fid) if sim.research is not None else None
        facilities.append({
            "id": str(fid), "name": definition.display_name,
            "capabilities": sorted(row.id for row in definition.capability_supplies),
            "service_capacity_per_day": {
                row.service_type: row.nominal_rate for row in definition.service_capacity_supplies
            },
            "process_throughput_per_day": definition.process_throughput_per_day,
            "extraction_capacity_t_per_day": definition.extraction_capacity_t_per_day,
            "construction": None if recipe is None else {
                "resources_t": resource_inputs, "work": recipe.construction_work,
                "prerequisite_technologies": sorted(map(str, recipe.prerequisite_technologies)),
                "site": _site(recipe.site_requirements),
            },
            "maintenance_fraction_per_year": definition.maintenance_fraction_per_year,
            "power": _power(sim.power.specs.get(fid)),
            "housing_people": definition.housing_capacity,
            "life_support": None if definition.life_support is None else {
                "person_days_per_day": definition.life_support.person_days_per_day,
                "net_resources_t_per_person_day": _sorted_resources(definition.life_support.net_resources),
            },
            "research_provider": None if p is None else str(p.id),
            "site": _site(definition.installation_requirements),
        })
        if definition.life_support is not None:
            for rid, rate in definition.life_support.net_resources:
                link(rid, "uses", owner_kind="life_support", owner_id=fid,
                     quantity=rate, basis="t_per_person_day")

    vehicles: list[dict[str, Any]] = []
    for vid, vehicle in sorted(sim.transport.vehicle_defs.items()):
        for resource, amount in vehicle.production.resources:
            link(resource, "uses", owner_kind="vehicle_production", owner_id=vid,
                 quantity=amount, basis="t_per_new_vehicle")
        vehicles.append({
            "id": str(vid), "name": vehicle.display_name, "payload_t": vehicle.payload_t,
            "dry_mass_t": vehicle.dry_mass_t, "propellant_capacity_t": vehicle.propellant_capacity_t,
            "turnaround_days_per_service_cycle": vehicle.turnaround_days,
            "endurance_days": vehicle.performance.endurance_days,
            "refueling_requirements": [
                {"resource_id": str(req.resource_id),
                 "infrastructure_capability_id": req.infrastructure_capability_id,
                 "vehicle_capability_id": req.vehicle_capability_id}
                for req in vehicle.performance.resource_support_requirements
            ],
            "propellant_resource": None if vehicle.propellant_resource_id is None else str(vehicle.propellant_resource_id),
            "operation_types": sorted(cap.operation_type for cap in vehicle.performance.operation_capabilities),
            "capabilities": sorted(vehicle.generic_capabilities),
            "production": {
                "resources_t": _sorted_resources(vehicle.production.resources),
                "days_per_vehicle_nominal": vehicle.production.days,
                "service": vehicle.production.service_type,
                "prerequisite_technologies": sorted(map(str, vehicle.production.prerequisite_technologies)),
                "site": _site(vehicle.production.site_requirements),
            },
            "turnaround_resources": _sorted_resources(vehicle.maintenance.resources),
            "seats": vehicle.passengers.seats,
        })
        for resource, amount in vehicle.maintenance.resources:
            link(resource, "uses", owner_kind="vehicle_turnaround", owner_id=vid,
                 quantity=amount, basis="t_per_turnaround")

    processes: list[dict[str, Any]] = []
    for pid, process in sorted(sim.industry.processes.items()):
        providers = sorted(map(str, sim.industry.service_capacity_provider_definition_ids(
            sim.industry.process_service_type(pid))))
        for rid, amount in process.inputs_per_day.items():
            link(rid, "uses", owner_kind="process", owner_id=pid,
                 quantity=amount, basis="t_per_process_execution_unit")
        for rid, amount in process.outputs_per_day.items():
            for fid in providers:
                rate = sim.facilities.definitions[fid].process_throughput_per_day
                link(rid, "sources", owner_kind="process_facility", owner_id=pid,
                     quantity=amount * rate, basis="t_per_day_per_nominal_facility",
                     facility_id=fid)
        processes.append({
            "id": str(pid), "name": process.display_name,
            "inputs_t_per_execution": _sorted_resources(process.inputs_per_day),
            "outputs_t_per_execution": _sorted_resources(process.outputs_per_day),
            "required_capabilities": sorted(process.required_capabilities),
            "prerequisite_technologies": sorted(map(str, process.prerequisite_technologies)),
            "compatible_facilities": [
                {"id": fid, "executions_per_day_nominal": sim.facilities.definitions[fid].process_throughput_per_day}
                for fid in providers
            ],
        })

    extraction: list[dict[str, Any]] = []
    if sim.extraction is not None:
        for method_id, method in sorted(sim.extraction.specs.items()):
            providers = sorted((str(fid) for fid in sim.facilities.definitions
                                if method in sim.extraction.compatible_methods(fid)))
            for fid in providers:
                # Own Domain's installed nominal capacity; actual geology/Knowledge
                # and soft saturation must be evaluated at a real physical site.
                link(method.output_resource_id, "sources", owner_kind="extraction_facility",
                     owner_id=method_id,
                     quantity=sim.extraction.nominal_capacity_for_level(fid, 1),
                     basis="t_per_day_per_nominal_facility_before_site_saturation", facility_id=fid)
            extraction.append({
                "id": str(method_id), "resource": str(method.output_resource_id),
                "required_capabilities": sorted(method.required_capabilities),
                "compatible_facilities": providers,
                "prerequisite_technologies": sorted(map(str, method.prerequisite_technologies)),
                "geology_accessibility_key": method.geology_accessibility_key,
                "minimum_knowledge_level": method.minimum_knowledge_level.name,
            })

    # One founding payload is a physical manifest: hardware plus starting stock.
    # Do not add the deployed Facilities' construction Recipes a second time.
    founding = []
    for recipe_id, recipe in sorted(sim.founding.deployment_recipes.items()):
        for requirement in recipe.payload_resources:
            link(requirement.resource_id, "uses", owner_kind="founding_payload",
                 owner_id=recipe_id, quantity=requirement.amount_t,
                 basis="t_per_founding_package_including_deployed_hardware_and_initial_stock")
        founding.append({
            "id": str(recipe_id), "name": recipe.display_name,
            "payload_t": recipe.payload_t,
            "payload_t_per_required_unit": recipe.payload_t_per_unit,
            "required_units": recipe.required_units,
            "preparation_work": recipe.preparation_work,
            "preparation_service": recipe.preparation_service_type,
            "deployed_facilities": [str(row.facility_def_id) for row in recipe.deployed_facilities],
            "invested_resources_t": _sorted_resources(recipe.investment_totals()),
            "initial_inventory_t": _sorted_resources(recipe.initial_inventory_totals()),
            "staging_site": _site(recipe.staging_requirements),
            "target_site": _site(recipe.target_requirements),
        })
    location_development = []
    for recipe_id, recipe in sorted(sim.projects.spatial_recipes.items()):
        for resource in recipe.resources:
            link(resource.resource_id, "uses", owner_kind="location_development",
                 owner_id=recipe_id, quantity=resource.amount_t,
                 basis="t_per_development_project")
        location_development.append({
            "id": str(recipe_id), "name": recipe.display_name,
            "resources_t": _recipe_resources(recipe.resources),
            "construction_work": recipe.construction_work,
            "prerequisite_technologies": sorted(map(str, recipe.prerequisite_technologies)),
            "site": _site(recipe.site_requirements),
        })

    markets = []
    for provider_id, provider in sorted(sim.market.provider_defs.items()):
        markets.append({
            "id": str(provider_id), "lead_time_days": provider.lead_time_days,
            "buy_musd_per_t": _sorted_resources(provider.buy_offers_musd_per_t),
            "sell_musd_per_t": _sorted_resources(provider.sell_offers_musd_per_t),
            "supply_t": {str(row.resource_id): {"initial": row.initial_t,
                            "capacity": row.capacity_t, "replenishment_per_day": row.replenishment_t_per_day}
                         for row in provider.supply},
        })

    research: list[dict[str, Any]] = []
    for tid, technology in sorted(sim.research.definitions.items()):
        specs = [_stage(spec) for spec in technology.stage_specs]
        for spec in specs:
            for rid, amount in spec.get("resources_t", {}).items():
                link(rid, "uses", owner_kind="research_prototype", owner_id=tid,
                     quantity=amount, basis="t_per_stage_once", stage_id=spec["id"])
        research.append({
            "id": str(tid), "name": technology.display_name,
            "progression_stage": technology.progression_stage,
            "category": technology.category,
            "series": technology.series,
            "prerequisites": sorted(map(str, technology.prerequisites)),
            "stages": specs,
        })

    provider_rows = []
    for rid, provider in sorted(sim.research.providers.items()):
        sources = (sim.research.compatible_facility_definition_ids(rid)
                   if provider.source_kind is ResearchProviderSourceKind.FACILITY
                   else (v.id for v in sim.research.compatible_vehicle_definitions(rid)))
        provider_rows.append({
            "id": str(rid), "tier": provider.tier, "source_kind": provider.source_kind.value,
            "physical_source_ids": sorted(map(str, sources)),
            "levels": [{"level": lev.level, "rp_per_day": lev.generation_points_per_day,
                        "execution_per_day": lev.research_execution_per_day,
                        "rp_storage": lev.storage_capacity_points} for lev in provider.levels],
        })

    # Each world's cell values are physical *potential*, not deposited stock.
    world = []
    for bid, body in sorted(sim.graph.bodies.items()):
        cells = [cell for cell in sim.graph.surface_cells.values() if cell.body_id == bid]
        by_resource: dict[str, list[float]] = defaultdict(list)
        for cell in cells:
            for rid, amount in cell.resource_potential_by_resource.items():
                by_resource[str(rid)].append(float(amount))
        world.append({
            "id": str(bid), "name": getattr(body, "display_name", str(bid)),
            "body_parameters": {
                "mean_radius_km": body.mean_radius_km,
                "reference_gravity_m_s2": body.representative_gravity_m_s2,
                "parent_body_id": None if body.parent_body_id is None else str(body.parent_body_id),
                "heliocentric_semimajor_axis_au": body.heliocentric_semimajor_axis_au,
                "parent_orbit_semimajor_axis_km": body.parent_orbit_semimajor_axis_km,
                "physical_surface": body.physical_surface.value,
            },
            "surface_cells": [
                {"id": str(cell.id), "area_km2": cell.area_km2,
                 "geology": dict(sorted(cell.static_geology.items())),
                 "terrain": {"terrain_factor": cell.terrain.terrain_factor,
                             "bearing_capacity_factor": cell.terrain.bearing_capacity_factor,
                             "dust_factor": cell.terrain.dust_factor, "slope_factor": cell.terrain.slope_factor},
                 "resource_potential_by_resource": _sorted_resources(cell.resource_potential_by_resource)}
                for cell in sorted(cells, key=lambda value: str(value.id))
            ],
            "surface_cell_count": len(cells),
            "potential_by_resource": {rid: {"positive_cells": sum(x > 0 for x in vals),
                                          "min": min(vals), "max": max(vals)}
                                      for rid, vals in sorted(by_resource.items())},
        })

    for item in world:
        for resource, opportunity in item["potential_by_resource"].items():
            if resource in links and opportunity["positive_cells"]:
                links[resource].setdefault("world_surface_potential", []).append({
                    "body_id": item["id"], **opportunity,
                })

    initial = {
        "scenario_id": scenario.id,
        "facilities": [{"node": str(row.operational_node_id), "id": str(row.definition_id),
                        "level": row.level, "site_cell": None if row.site_cell_id is None else str(row.site_cell_id),
                        "selected_process_id": None if row.selected_process_id is None else str(row.selected_process_id),
                        "selected_extraction_method_id": None if row.selected_extraction_method_id is None
                        else str(row.selected_extraction_method_id),
                        "invested_resources_t": _sorted_resources(row.invested_resources)}
                       for row in scenario.facilities],
        "fleet": [{"node": str(row.operational_node_id), "id": str(row.vehicle_definition_id),
                   "units": row.units} for row in scenario.fleet],
        "inventory": [{"node": str(row.operational_node_id), "resource": str(row.resource_id),
                       "quantity_t": row.amount_t} for row in scenario.inventory_stock],
        "population": [{"node": str(row.operational_node_id), "people": row.count}
                       for row in scenario.initial_population],
        "researched": sorted(map(str, scenario.completed_technologies)),
        "funds_balance_musd": scenario.funds_balance_musd,
        "market_provider_ids": sorted(map(str, scenario.market_provider_ids)),
        "market_interfaces": [
            {"id": str(row.id), "node": str(row.operational_node_id),
             "provider_id": str(row.provider_id), "enabled": row.enabled}
            for row in scenario.market_interfaces
        ],
        "research_fleet_assignments": [
            {"provider_definition_id": str(row.provider_definition_id),
             "node": str(row.operational_node_id), "vehicle_id": str(row.vehicle_definition_id),
             "units": row.units}
            for row in scenario.research_fleet_assignments
        ],
        "survey_fleet_assignments": [
            {"provider_definition_id": str(row.provider_definition_id),
             "node": str(row.operational_node_id), "vehicle_id": str(row.vehicle_definition_id),
             "units": row.units}
            for row in scenario.survey_fleet_assignments
        ],
        "known_surface_resources": [
            {"cell_id": str(cell_id), "resource_id": str(resource_id)}
            for cell_id, resource_id in scenario.known_surface_resources
        ],
        "established_nodes": sorted({str(row.operational_node_id) for row in scenario.surface_locations} |
                                    set(map(str, scenario.operational_node_ids))),
    }
    for rid in links:
        for direction in ("sources", "uses"):
            links[rid][direction].sort(key=lambda row: (row["owner_kind"], row["owner_id"], row["basis"], row.get("facility_id", "")))

    return {
        "meaning": {
            "scope": "registered content design coefficients, not an achievable playthrough",
            "source": "composed Definition, World, standard Scenario",
            "interpretation": "no implicit facility counts, process operation, research completion, fleet commitment, or cargo settlement",
        },
        "initial": initial,
        "resources": links,
        "facilities": facilities,
        "vehicles": vehicles,
        "processes": processes,
        "extraction": extraction,
        "founding": founding,
        "location_development": location_development,
        "markets": markets,
        "research": research,
        "research_providers": provider_rows,
        "world": world,
    }
