from __future__ import annotations

from .application_catalog_support import operation_capability_definition, site_requirements_definition
from .application_transport_support import vehicle_concept
from .application_views import MovementPlanDefinitionRow, VehicleDefinitionRow


def project_vehicles(projector):
    sim = projector._simulation
    return tuple(
        VehicleDefinitionRow(
            str(definition.id), definition.display_name, vehicle_concept(definition),
            definition.dry_mass_t, definition.payload_t, definition.endurance_days, definition.propellant_capacity_t,
            None if definition.propellant_resource_id is None else str(definition.propellant_resource_id),
            tuple(sorted(definition.generic_capabilities)),
            tuple((req.operation_type, req.location.value, req.capability_id) for req in definition.operation_support_requirements),
            definition.production_service_type, definition.production_days,
            tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.production_resources),
            definition.turnaround_service_type, definition.turnaround_days,
            tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.turnaround_resources),
            tuple(operation_capability_definition(capability) for capability in definition.performance.operation_capabilities),
        )
        for definition in sim.transport.vehicle_definitions()
    )


def project_movement_plans(projector):
    return tuple(
        MovementPlanDefinitionRow(
            str(movement_plan.id), movement_plan.display_name or str(movement_plan.id), str(movement_plan.origin_id), str(movement_plan.destination_id),
            movement_plan.transit_days, movement_plan.delta_v_km_s,
            tuple((operation.operation_type, operation.delta_v_km_s) for operation in movement_plan.operations),
            site_requirements_definition(movement_plan.origin_requirements),
            site_requirements_definition(movement_plan.destination_requirements),
        )
        for movement_plan in projector._simulation.transport.movement_plan_options()
    )
