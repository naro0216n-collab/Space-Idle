from __future__ import annotations


def resolve_authorized_logistics(sim, day, plan, *, static_intents=()):
    """Resolve an already-authorized Logistics plan through canonical shared Bundles.

    This is test composition only: production Simulation uses the same fixed-point
    resolver while also supplying the other current-tick Activity intents.
    """
    locations = sim._active_locations() | set(sim.graph.operational_node_ids())
    powers = {
        location_id: sim.power.snapshot(location_id, sim.facilities, day)
        for location_id in locations
    }
    provider_plan = sim._allocate_tick_services(powers, requests=())
    all_service_requests = sim._complete_service_requests(
        sim.transport.transport_service_capacity_requests(day, plan.planned_usage)
    )
    shared, usage, reference, surface, surface_limits = (
        sim._resolve_transport_execution_fixed_point(
            day, plan, tuple(static_intents), provider_plan, all_service_requests
        )
    )
    resource_overrides, service_overrides = (
        sim.logistics.transport_operation_allocation_overrides(day, usage)
    )
    projection_claims = sim.logistics.resource_allocation_projection_claims(
        day, plan, reference
    )
    resources = sim._resource_plan_from_execution(
        projection_claims, shared, allocation_overrides=resource_overrides
    )
    services = sim._service_plan_from_execution(
        all_service_requests,
        shared,
        provider_plan,
        allocation_overrides=service_overrides,
    )
    operation_factors = sim.logistics.transport_operation_execution_projection(
        day,
        plan,
        shared,
        usage,
        reference,
        surface,
        surface_limits,
    )
    execution = sim.logistics.build_capacity_logistics_execution(
        day, plan, shared, operation_factors
    )
    return shared, execution, resources, services
