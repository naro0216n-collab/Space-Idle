"""Physical Content measurements at authored World contexts, not a game simulator.

The caller chooses the context and equipment; no Location, Fleet, research,
stock, cargo, or day-progress State is created. Eligibility and allocation are
never inferred from these static physical coefficients.
"""
from __future__ import annotations

from typing import Any
from math import ceil, isfinite

from .catalog import describe_site_requirements
from space_idle.site import evaluate_physical_site_requirements
from space_idle.spatial import IlluminationField, SpatialContextId
from space_idle.shared import DefinitionId
from space_idle.simulation import Simulation


def _physical_failures(sim: Simulation, requirements, context_id, day: int) -> list[dict[str, str]]:
    return [
        {"code": failure.code, "detail": failure.detail}
        for failure in evaluate_physical_site_requirements(
            requirements, context_id, day, sim.facilities.environment
        )
    ]


def site_evidence(
    sim: Simulation, context_id: SpatialContextId, facility_id: DefinitionId,
    *, method_id: DefinitionId | None = None, level: int = 1, day: int = 0,
    window_days: float = 1,
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
    if type(day) is not int or day < 0:
        raise ValueError("day must be a non-negative integer")
    if (isinstance(window_days, bool) or not isinstance(window_days, (int, float))
            or not isfinite(window_days) or window_days <= 0):
        raise ValueError("window_days must be finite and positive")
    definition = sim.facilities.definitions[facility_id]
    recipe = sim.projects.recipes.get(facility_id)
    illumination = sim.facilities.environment.get(context_id, IlluminationField, day)
    generation, load = sim.power.nominal_for_definition_at_context(facility_id, context_id, day)
    # Sample physical Power coefficients at the owning Power Domain. A sub-day
    # remainder weights its calendar day; no operational simulation is run.
    samples = [(sim.power.nominal_for_definition_at_context(facility_id, context_id, day + offset)[0],
                min(1.0, window_days - offset)) for offset in range(ceil(window_days))]
    average_generation = sum(value * weight for value, weight in samples) / window_days
    result: dict[str, Any] = {
        "context_id": str(context_id), "day": day, "facility_id": str(facility_id), "level": level,
        "assumptions": "physical context only; neither Location nor Facility is installed; no Knowledge or Allocation",
        "illumination": None if illumination is None else {
            "solar_flux_w_m2": illumination.solar_flux_w_m2,
            "availability": illumination.availability,
        },
        "power": {"generation_mw_per_facility": generation, "active_load_mw_per_facility": load,
                  "window_start_day": day, "window_days": window_days,
                  "mean_generation_mw_per_facility": average_generation,
                  "minimum_generation_mw_per_facility": min(value for value, _ in samples),
                  "maximum_generation_mw_per_facility": max(value for value, _ in samples),
                  "basis": "PowerService.nominal_for_definition_at_context (unmaintained); sampled over the stated days"},
        "construction": None if recipe is None else {
            "resources_t_per_facility": {str(row.resource_id): row.amount_t for row in recipe.resources},
            "work_per_facility": recipe.construction_work,
            "prerequisite_technologies": sorted(map(str, recipe.prerequisite_technologies)),
            "site": describe_site_requirements(recipe.site_requirements),
            "physical_environment_failures": _physical_failures(sim, recipe.site_requirements, context_id, day),
        },
        "installation": {"site": describe_site_requirements(definition.installation_requirements),
                         "physical_environment_failures": _physical_failures(
                             sim, definition.installation_requirements, context_id, day
                         )},
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
            method.resource_id, (method,), (context_id,), day,
            eligible=lambda candidate, cell: True,
        )
        result["extraction"] = {
            "method_id": str(method.id), "resource_id": str(method.resource_id),
            "prerequisite_technologies": sorted(map(str, method.prerequisite_technologies)),
            "nominal_capacity_t_per_day": nominal,
            "physical_opportunity_before_knowledge": opportunity,
            "diminishing_response_t_per_day": sim.extraction.diminishing_response(nominal, opportunity),
            "marginal_response": sim.extraction.marginal_response(nominal, opportunity),
            "basis": "ExtractionService.opportunity_for_cells / diminishing_response, Knowledge assumed eligible; no Power/Service/Allocation",
        }
    return result


def movement_evidence(
    sim: Simulation, origin_context_id: SpatialContextId, destination_context_id: SpatialContextId,
    vehicle_id: DefinitionId, *, cargo_t: float = 0.0, day: int = 0,
) -> dict[str, Any]:
    """Owner-derived physical Movement candidates, including a separate return.

    Cargo quantity is an explicit design input, not produced or dispatched.
    Operating Service needs founded endpoints, gateway, refueling, servicing,
    inventory and Fleet; none is created or declared satisfied here.
    """
    from math import isfinite
    if not isfinite(cargo_t) or cargo_t < 0:
        raise ValueError("cargo_t must be finite and non-negative")
    if type(day) is not int or day < 0:
        raise ValueError("day must be a non-negative integer")
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
                    plan, vehicle.performance, day, include_operation_support=False
                )),
                "origin_site": describe_site_requirements(plan.origin_requirements),
                "destination_site": describe_site_requirements(plan.destination_requirements),
                "origin_environment_failures": _physical_failures(
                    sim, plan.origin_requirements, origin, day
                ),
                "destination_environment_failures": _physical_failures(
                    sim, plan.destination_requirements, destination, day
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
        "day": day, "vehicle_id": str(vehicle_id),
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
