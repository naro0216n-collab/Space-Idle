from __future__ import annotations

from .application_catalog_support import operation_capability_definition, site_requirements_definition
from .application_transport_support import vehicle_concept
from .application_views import RouteDefinitionRow, TransportServiceDefinitionRow, VehicleDefinitionRow


def project_vehicles(projector):
    sim = projector._simulation
    return tuple(
        VehicleDefinitionRow(
            str(definition.id), definition.display_name, vehicle_concept(definition),
            definition.dry_mass_t, definition.payload_t, definition.propellant_capacity_t,
            None if definition.propellant_resource_id is None else str(definition.propellant_resource_id),
            tuple(sorted(capability.operation_type for capability in definition.performance.operation_capabilities)),
            tuple((req.operation_type, req.location.value, req.capability_id) for req in definition.operation_support_requirements),
            definition.production_capability_id, definition.production_days, definition.production_cost_musd,
            tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.production_resources),
            definition.turnaround_capability_id, definition.turnaround_days, definition.turnaround_cost_musd,
            tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.turnaround_resources),
            tuple(operation_capability_definition(capability) for capability in definition.performance.operation_capabilities),
        )
        for definition in sorted(sim.logistics.vehicle_defs.values(), key=lambda d: str(d.id))
    )


def project_routes(projector):
    return tuple(
        RouteDefinitionRow(
            str(route.id), route.display_name or str(route.id), str(route.origin_id), str(route.destination_id),
            route.transit_days, route.delta_v_km_s,
            tuple((operation.operation_type, operation.delta_v_km_s) for operation in route.operations),
            site_requirements_definition(route.origin_requirements),
            site_requirements_definition(route.destination_requirements),
        )
        for route in sorted(projector._simulation.logistics.routes.values(), key=lambda row: str(row.id))
    )


def project_transport_services(projector):
    return tuple(
        TransportServiceDefinitionRow(
            str(service.id), service.display_name, service.capacity_t_per_day, service.cost_musd_per_t,
            service.performance.dry_mass_t, service.performance.payload_t, service.transit_time_multiplier,
            tuple(operation_capability_definition(capability) for capability in service.performance.operation_capabilities),
            site_requirements_definition(service.origin_requirements),
            site_requirements_definition(service.destination_requirements),
        )
        for service in sorted(projector._simulation.logistics.external_services.values(), key=lambda row: str(row.id))
    )
