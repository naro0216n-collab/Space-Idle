"""Physical Content measurements at authored World contexts, not a game simulator.

The caller chooses the context and equipment; no Location, Fleet, research,
stock, cargo, or day-progress State is created. Eligibility and allocation are
never inferred from these static physical coefficients.
"""
from __future__ import annotations

from typing import Any
from math import isfinite

from .catalog import describe_site_requirements
from .world import physical_context_evidence
from space_idle.site import evaluate_physical_site_requirements
from space_idle.spatial import IlluminationField, SpatialContextId
from space_idle.shared import DefinitionId
from space_idle.simulation import Simulation


def _physical_failures(sim: Simulation, requirements, context_id) -> list[dict[str, str]]:
    return [
        {"code": failure.code, "detail": failure.detail}
        for failure in evaluate_physical_site_requirements(
            requirements, context_id, sim.facilities.environment
        )
    ]


def physical_site_conditions(sim: Simulation, context_id: SpatialContextId, requirements) -> dict[str, Any]:
    """Authoritative physical Site coefficient, without installed Capabilities.

    Capability prerequisites are retained in the typed definition description.
    They cannot be declared fulfilled at an unestablished World context.
    """
    if context_id not in sim.graph.nodes and context_id not in sim.graph.surface_cells:
        raise KeyError(f'unknown World context: {context_id}')
    return {
        'site': describe_site_requirements(requirements),
        'physical_environment_failures': _physical_failures(sim, requirements, context_id),
    }


def site_evidence(
    sim: Simulation, context_id: SpatialContextId, facility_id: DefinitionId,
    *, method_id: DefinitionId | None = None, level: int = 1,
) -> dict[str, Any]:
    """One equipment choice at one physical context, independently of ownership.

    Extraction assumes the Resource is surveyed solely for its physical
    opportunity coefficient. No Survey Knowledge, installed capacity, Power,
    Service fulfillment or Construction success is asserted.
    """
    graph = sim.graph
    if context_id not in graph.nodes and context_id not in graph.surface_cells:
        raise KeyError(f"unknown World context: {context_id}")
    if facility_id not in sim.facilities.definitions:
        raise KeyError(f"unknown Facility: {facility_id}")
    if type(level) is not int or level < 1:
        raise ValueError("level must be a positive integer")
    definition = sim.facilities.definitions[facility_id]
    recipe = sim.projects.recipes.get(facility_id)
    illumination = sim.facilities.environment.get(context_id, IlluminationField)
    # Climate-averaged site coefficient, not a calendar forecast or simulated production.
    generation, load = sim.power.nominal_for_definition_at_context(facility_id, context_id)
    research_provider = sim.research.facility_provider_for_definition(facility_id)
    method = None if method_id is None else sim.extraction.specs[method_id]
    result: dict[str, Any] = {
        "context_id": str(context_id), "facility_id": str(facility_id), "level": level,
        "assumptions": "physical context only; neither Location nor Facility is installed; no Knowledge or Allocation",
        "illumination": None if illumination is None else {
            "solar_flux_w_m2": illumination.solar_flux_w_m2,
            "availability": illumination.availability,
        },
        "power": {"generation_mw_per_facility": generation, "active_load_mw_per_facility": load,
                  "basis": "PowerService.nominal_for_definition_at_context; representative climate/exposure, no daily forecast or fulfillment"},
        "construction": None if recipe is None else {
            "resources_t_per_facility": {str(row.resource_id): row.amount_t for row in recipe.resources},
            "work_per_facility": recipe.construction_work,
            "prerequisite_technologies": sorted(map(str, recipe.prerequisite_technologies)),
            "site": describe_site_requirements(recipe.site_requirements),
            "physical_environment_failures": _physical_failures(sim, recipe.site_requirements, context_id),
        },
        "installation": {"site": describe_site_requirements(definition.installation_requirements),
                         "physical_environment_failures": _physical_failures(
                             sim, definition.installation_requirements, context_id
                         )},
        "operation": {"site": describe_site_requirements(definition.operating_requirements),
                      "physical_environment_failures": _physical_failures(
                          sim, definition.operating_requirements, context_id
                      )},
        "research_provider": None if research_provider is None else {
            "id": str(research_provider.id),
            **physical_site_conditions(sim, context_id, research_provider.site_requirements),
        },
        "nominal_process_executions_per_day_per_facility": definition.process_throughput_per_day,
        "extraction": None,
    }
    if method_id is not None:
        if sim.extraction is None:
            raise ValueError("Extraction Domain is unavailable")
        method = sim.extraction.specs[method_id]
        if method not in sim.extraction.compatible_methods(facility_id):
            raise ValueError(f"extraction method {method_id} incompatible with {facility_id}")
        if context_id not in graph.surface_cells:
            raise ValueError("extraction opportunity requires a Surface Cell")
        nominal = sim.extraction.nominal_capacity_for_level(facility_id, level)
        opportunity = sim.extraction.opportunity_for_cells(
            method.resource_id, (method,), (context_id,),
            eligible=lambda candidate, cell: True,
        )
        result["extraction"] = {
            "method_id": str(method.id), "resource_id": str(method.resource_id),
            "output_resource_id": str(method.output_resource_id),
            "opportunity_site": describe_site_requirements(method.opportunity_requirements),
            "opportunity_environment_failures": _physical_failures(
                sim, method.opportunity_requirements, context_id
            ),
            "prerequisite_technologies": sorted(map(str, method.prerequisite_technologies)),
            "nominal_capacity_t_per_day": nominal,
            "physical_opportunity_before_knowledge": opportunity,
            "diminishing_response_t_per_day": sim.extraction.diminishing_response(nominal, opportunity),
            "marginal_response": sim.extraction.marginal_response(nominal, opportunity),
            "basis": "ExtractionService.opportunity_for_cells / diminishing_response, Knowledge assumed eligible; no Power/Service/Allocation",
        }
    return result


def surface_region_evidence(
    sim: Simulation, cell_ids, method_id: DefinitionId, facility_id: DefinitionId,
    *, facility_units: int = 1, level: int = 1,
    anchor_cell_ids=(),
) -> dict[str, Any]:
    """Explicit prospective territory; no Location, Survey or active anchor.

    Uses the extraction owner's opportunity and the surface infrastructure
    owner's distance/area load. The named assets are not installed or powered.
    """
    cells = tuple(sorted(set(cell_ids), key=str))
    if not cells:
        raise ValueError('a physical territory needs at least one Cell')
    if type(facility_units) is not int or facility_units < 0:
        raise ValueError('facility_units must be a non-negative integer')
    if type(level) is not int or level < 1:
        raise ValueError('level must be a positive integer')
    body_ids = set()
    for cell_id in cells:
        if cell_id not in sim.graph.surface_cells:
            raise KeyError(f'unknown Surface Cell: {cell_id}')
        body_ids.add(sim.graph.surface_cells[cell_id].body_id)
    if len(body_ids) != 1:
        raise ValueError('physical territory cannot combine multiple celestial bodies')
    body_id = next(iter(body_ids))
    if sim.graph.bodies[body_id].physical_surface.value != 'solid':
        raise ValueError('physical territory requires a solid surface')
    method = sim.extraction.specs[method_id]
    if method not in sim.extraction.compatible_methods(facility_id):
        raise ValueError(f'extraction method {method_id} incompatible with {facility_id}')
    per_cell = []
    for cell_id in cells:
        opportunity = sim.extraction.opportunity_for_cells(
            method.resource_id, (method,), (cell_id,),
            eligible=lambda candidate, cell: True,
        )
        per_cell.append({
            'cell_id': str(cell_id),
            'world_context': physical_context_evidence(sim, cell_id),
            'static_resource_potential': sim.graph.surface_cells[cell_id].resource_potential_by_resource.get(
                method.resource_id, 0.0),
            'physical_opportunity_before_knowledge': opportunity,
            'method_environment_failures': _physical_failures(
                sim, method.opportunity_requirements, cell_id),
        })
    total = sim.extraction.opportunity_for_cells(
        method.resource_id, (method,), cells,
        eligible=lambda candidate, cell: True,
    )
    nominal = sim.extraction.nominal_capacity_for_level(facility_id, level) * facility_units
    loads = sim.surface_infrastructure.physical_load_sources_for_cells(
        body_id, cells, anchor_cell_ids
    )
    return {
        'body_id': str(body_id), 'cell_ids': list(map(str, cells)),
        'method_id': str(method_id), 'resource_id': str(method.resource_id),
        'output_resource_id': str(method.output_resource_id),
        'method_site': describe_site_requirements(method.opportunity_requirements),
        'minimum_survey_knowledge_level': (
            None if method.minimum_knowledge_level is None
            else getattr(method.minimum_knowledge_level, 'value', method.minimum_knowledge_level)
        ),
        'prerequisite_technologies': sorted(map(str, method.prerequisite_technologies)),
        'per_cell': per_cell, 'physical_opportunity_before_knowledge': total,
        'facility_id': str(facility_id), 'facility_units': facility_units, 'facility_level': level,
        'nominal_extraction_capacity_t_per_day': nominal,
        'physical_diminishing_response_t_per_day': sim.extraction.diminishing_response(nominal, total),
        'physical_marginal_response': sim.extraction.marginal_response(nominal, total),
        'assumed_active_anchor_cell_ids': sorted(map(str, set(anchor_cell_ids))),
        'surface_infrastructure_nominal_loads': [
            {'kind': row.code, 'units': row.demand} for row in loads
        ],
        'surface_infrastructure_nominal_demand': sum(row.demand for row in loads),
        'basis': ('ExtractionService.opportunity_for_cells/diminishing_response and '
                  'SurfaceInfrastructureService.physical_load_sources_for_cells'),
        'interpretation': ('Cell Knowledge eligibility and facility operation assumed only for physical coefficients; '
                           'territory topology is checked but no Location or active anchor is established, '
                           'no Service Allocation, Resource production, owned Location or Survey state'),
    }


def movement_evidence(
    sim: Simulation, origin_context_id: SpatialContextId, destination_context_id: SpatialContextId,
    vehicle_id: DefinitionId, *, cargo_t: float = 0.0,
) -> dict[str, Any]:
    """Owner-derived physical Movement candidates, including a separate return.

    Cargo quantity is an explicit design input, not produced or dispatched.
    Operating Service needs founded endpoints, gateway, refueling, servicing,
    inventory and Fleet; none is created or declared satisfied here.
    """
    from math import isfinite
    if not isfinite(cargo_t) or cargo_t < 0:
        raise ValueError("cargo_t must be finite and non-negative")
    vehicle = sim.transport.vehicle_defs[vehicle_id]
    resolver = sim.transport.movement_resolver()

    def candidates(origin, destination) -> list[dict[str, Any]]:
        return [
            {
                "movement_plan_id": str(plan.id),
                "operation_types": [op.operation_type for op in plan.operations],
                "transit_days": sim.transport.performance_movement_transit_days(plan, vehicle.performance),
                "delta_v_km_s": plan.delta_v_km_s,
                "payload_max_t": vehicle.max_cargo_for_movement(plan),
                "requested_cargo_t": cargo_t,
                "cargo_exceeds_physical_capacity": cargo_t > vehicle.max_cargo_for_movement(plan) + 1e-12,
                "propellant_t_empty": vehicle.propellant_t(plan, 0.0),
                "propellant_t_at_requested_cargo": vehicle.propellant_t(plan, cargo_t),
                "propellant_capacity_t": vehicle.propellant_capacity_t,
                "vehicle_physical_failures": list(sim.transport.performance_movement_failures(
                    plan, vehicle.performance, include_operation_support=False
                )),
                "origin_site": describe_site_requirements(plan.origin_requirements),
                "destination_site": describe_site_requirements(plan.destination_requirements),
                "origin_environment_failures": _physical_failures(
                    sim, plan.origin_requirements, origin
                ),
                "destination_environment_failures": _physical_failures(
                    sim, plan.destination_requirements, destination
                ),
                "asset_disposition": vehicle.movement_asset_disposition(plan).value,
            }
            for plan in resolver.physical_context_plans(origin, destination)
        ]

    forward_plans = resolver.physical_context_plans(origin_context_id, destination_context_id)
    return_plans = resolver.physical_context_plans(destination_context_id, origin_context_id)
    cycle_rows = []
    for forward_plan in forward_plans:
        returns = ((None,) if vehicle.movement_asset_disposition(forward_plan).value == 'origin'
                   else return_plans)
        for return_plan in returns:
            physical = sim.transport.physical_cycle_coefficients(
                vehicle_id, (forward_plan,), () if return_plan is None else (return_plan,),
                anchor_context_id=origin_context_id,
            )
            cycle_rows.append({
                'forward_plan_id': str(forward_plan.id),
                'reverse_plan_id': None if return_plan is None else str(return_plan.id),
                'cycle_days': physical.cycle_days,
                'forward_latency_days': physical.forward_days,
                'reverse_latency_days': physical.reverse_days,
                'forward_t_per_day_per_nominal_unit': physical.nominal_per_unit.forward_t_per_day,
                'reverse_t_per_day_per_nominal_unit': physical.nominal_per_unit.reverse_t_per_day,
                'servicing_units_per_day_per_nominal_unit': physical.servicing_units_per_full_utilization_day,
                'resource_t_per_full_utilization_day_per_unit': [
                    {'context_id': str(node), 'resource_id': str(rid), 'quantity_t_per_day': rate}
                    for node, rid, rate in physical.resource_t_per_full_utilization_day
                ],
                'resource_t_per_empty_cycle_day_per_unit': [
                    {'context_id': str(node), 'resource_id': str(rid), 'quantity_t_per_day': rate}
                    for node, rid, rate in physical.resource_t_per_empty_cycle_day
                ],
                'resource_t_per_forward_payload_increment_day_per_unit': [
                    {'context_id': str(node), 'resource_id': str(rid), 'quantity_t_per_day': rate}
                    for node, rid, rate in physical.resource_t_per_forward_payload_increment_day
                ],
                'resource_t_per_reverse_payload_increment_day_per_unit': [
                    {'context_id': str(node), 'resource_id': str(rid), 'quantity_t_per_day': rate}
                    for node, rid, rate in physical.resource_t_per_reverse_payload_increment_day
                ],
                'endurance_failures': list(vehicle.endurance_failures(
                    physical.forward_days + physical.reverse_days)),
                'basis': 'TransportDomain.physical_cycle_coefficients, without founded endpoints or fulfillment',
            })

    return {
        "origin_context_id": str(origin_context_id), "destination_context_id": str(destination_context_id),
        "world_contexts": {
            "origin": physical_context_evidence(sim, origin_context_id),
            "destination": physical_context_evidence(sim, destination_context_id),
        },
        "vehicle_id": str(vehicle_id),
        "cargo_t_per_movement": cargo_t,
        "turnaround_days_per_cycle": vehicle.turnaround_days,
        "turnaround_resources_t_per_cycle": {str(rid): amount for rid, amount in vehicle.turnaround_resources},
        "propellant_resource_id": None if vehicle.propellant_resource_id is None else str(vehicle.propellant_resource_id),
        "operation_support_requirements": [
            {"operation_type": req.operation_type, "location": req.location.value,
             "capability_id": req.capability_id}
            for req in vehicle.performance.operation_support_requirements
        ],
        "resource_support_requirements": [
            {"resource_id": str(req.resource_id),
             "infrastructure_capability_id": req.infrastructure_capability_id,
             "vehicle_capability_id": req.vehicle_capability_id}
            for req in vehicle.performance.resource_support_requirements
        ],
        "forward": candidates(origin_context_id, destination_context_id),
        "reverse": candidates(destination_context_id, origin_context_id),
        "physical_cycle_options": cycle_rows,
        "interpretation": (
            "Physical Movement and optionally reusable cycle coefficients only; not an active Transport Service. "
            "Cycle options use full payload per direction and unmaintained nominal rates. "
            "Installed infrastructure, refueling, availability, exclusive Fleet, actual Cargo and Supply are not granted"
        ),
    }
