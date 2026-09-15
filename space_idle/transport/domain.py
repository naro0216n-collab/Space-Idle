from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)
from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import (
    DirectionalCapacity,
    FleetPool,
    FleetRelocation,
    FleetRelocationResourceNeed,
    FleetRelease,
    FleetReservation,
    FleetReservationKind,
    PathPolicy,
    TransportAllocation,
    TransportControlMode,
)
from .production import VehicleProductionPhase, VehicleProductionState


def capture_transport(sim: Any) -> dict[str, Any]:
    tr = sim.transport
    return {
        "transport_allocation_counter": tr._transport_allocation_counter,
        "fleet_relocation_counter": tr._fleet_relocation_counter,
        "fleet_release_counter": tr._fleet_release_counter,
        "fleet_pools": [
            {
                "vehicle_definition_id": str(pool.vehicle_definition_id),
                "operational_node_id": str(pool.operational_node_id),
                "total_units": pool.total_units,
            }
            for pool in sorted(tr.fleet_pools.values(), key=lambda row: (str(row.vehicle_definition_id), str(row.operational_node_id)))
            if pool.total_units > 0
        ],
        "fleet_reservations": [
            {
                "id": str(row.id),
                "owner_id": str(row.owner_id),
                "kind": row.kind.value,
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "operational_node_id": str(row.operational_node_id),
                "units": row.units,
            }
            for row in sorted(tr.fleet_reservations.values(), key=lambda row: str(row.id))
        ],
        "transport_allocations": [
            {
                "id": str(row.id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "anchor_node_id": str(row.anchor_node_id),
                "destination_id": str(row.destination_id),
                "provisioning_priority": int(row.provisioning_priority),
                "control_mode": row.control_mode.value,
                "target_units": row.target_units,
                "target_capacity": None if row.target_capacity is None else {
                    "forward_t_per_day": row.target_capacity.forward_t_per_day,
                    "reverse_t_per_day": row.target_capacity.reverse_t_per_day,
                },
                "path": None if row.path is None else [str(route_id) for route_id in row.path],
                "path_policy": row.path_policy.value,
                "paused": row.paused,
                "last_operated_day": row.last_operated_day,
            }
            for row in sorted(tr.transport_allocations.values(), key=lambda row: str(row.id))
        ],
        "fleet_relocations": [
            {
                "id": str(row.id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "units": row.units,
                "source_id": str(row.source_id),
                "destination_id": str(row.destination_id),
                "requested_day": row.requested_day,
                "travel_days": row.travel_days,
                "path": [str(route_id) for route_id in row.path],
                "priority": row.priority,
                "departure_day": row.departure_day,
                "arrival_day": row.arrival_day,
                "resource_needs": [
                    {
                        "operational_node_id": str(need.operational_node_id),
                        "resource_id": str(need.resource_id),
                        "required_t": need.required_t,
                    }
                    for need in row.resource_needs
                ],
            }
            for row in sorted(tr.fleet_relocations.values(), key=lambda row: str(row.id))
        ],
        "fleet_releases": [
            {
                "id": str(row.id),
                "allocation_id": str(row.allocation_id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "operational_node_id": str(row.operational_node_id),
                "units": row.units,
                "release_day": row.release_day,
            }
            for row in sorted(tr.fleet_releases.values(), key=lambda row: str(row.id))
        ],
        "vehicle_production": {
            "counter": tr._vehicle_production_counter,
            "projects": [
                {
                    "id": str(state.id), "vehicle_definition_id": str(state.vehicle_definition_id),
                    "operational_node_id": str(state.operational_node_id), "priority": state.priority,
                    "progress_days": state.progress_days,
                    "phase": state.phase.value, "paused": state.paused,
                    "completed_units": state.completed_units, "created_day": state.created_day,
                }
                for state in sorted(tr.vehicle_production_projects.values(), key=lambda row: str(row.id))
            ],
        },
    }


def restore_transport(sim: Any, data: dict[str, Any]) -> None:
    tr = sim.transport
    tr._transport_allocation_counter = int(data.get("transport_allocation_counter", 0))
    tr._fleet_relocation_counter = int(data.get("fleet_relocation_counter", 0))
    tr._fleet_release_counter = int(data.get("fleet_release_counter", 0))
    tr.fleet_pools = {
        (DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["operational_node_id"])): FleetPool(
            DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["operational_node_id"]), int(row["total_units"])
        )
        for row in data.get("fleet_pools", [])
    }
    tr.fleet_reservations = {
        EntityId(row["id"]): FleetReservation(
            EntityId(row["id"]), EntityId(row["owner_id"]), FleetReservationKind(row["kind"]),
            DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["operational_node_id"]), int(row["units"])
        )
        for row in data.get("fleet_reservations", [])
    }
    tr.transport_allocations = {}
    for row in data.get("transport_allocations", []):
        target = row.get("target_capacity")
        allocation = TransportAllocation(
            id=EntityId(row["id"]), vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            anchor_node_id=SpatialNodeId(row["anchor_node_id"]), destination_id=SpatialNodeId(row["destination_id"]),
            provisioning_priority=int(row["provisioning_priority"]), control_mode=TransportControlMode(row["control_mode"]),
            target_units=None if row.get("target_units") is None else int(row["target_units"]),
            target_capacity=None if target is None else DirectionalCapacity(float(target["forward_t_per_day"]), float(target["reverse_t_per_day"])),
            path=None if row.get("path") is None else tuple(RouteId(value) for value in row["path"]),
            path_policy=PathPolicy(row.get("path_policy", "fastest")), paused=bool(row.get("paused", False)),
            last_operated_day=None if row.get("last_operated_day") is None else int(row["last_operated_day"]),
        )
        tr.transport_allocations[allocation.id] = allocation
    tr.fleet_relocations = {
        EntityId(row["id"]): FleetRelocation(
            EntityId(row["id"]), DefinitionId(row["vehicle_definition_id"]), int(row["units"]),
            SpatialNodeId(row["source_id"]), SpatialNodeId(row["destination_id"]), int(row["requested_day"]),
            int(row["travel_days"]), tuple(RouteId(value) for value in row["path"]),
            tuple(
                FleetRelocationResourceNeed(SpatialNodeId(need["operational_node_id"]), DefinitionId(need["resource_id"]), float(need["required_t"]))
                for need in row.get("resource_needs", [])
            ),
            int(row["priority"]),
            None if row.get("departure_day") is None else int(row["departure_day"]),
            None if row.get("arrival_day") is None else int(row["arrival_day"]),
        )
        for row in data.get("fleet_relocations", [])
    }
    tr.fleet_releases = {
        EntityId(row["id"]): FleetRelease(
            EntityId(row["id"]), EntityId(row["allocation_id"]), DefinitionId(row["vehicle_definition_id"]),
            SpatialNodeId(row["operational_node_id"]), int(row["units"]), int(row["release_day"])
        )
        for row in data.get("fleet_releases", [])
    }
    production_data = data.get("vehicle_production", {})
    tr._vehicle_production_counter = int(production_data.get("counter", 0))
    tr.vehicle_production_projects = {
        EntityId(row["id"]): VehicleProductionState(
            id=EntityId(row["id"]), vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            operational_node_id=SpatialNodeId(row["operational_node_id"]), priority=int(row["priority"]),
            progress_days=float(row.get("progress_days", 0.0)),
            phase=VehicleProductionPhase(row.get("phase", "awaiting_inputs")), paused=bool(row.get("paused", False)),
            completed_units=int(row.get("completed_units", 0)), created_day=int(row.get("created_day", 0)),
        )
        for row in production_data.get("projects", [])
    }
    tr.reconcile_fleet_allocations(sim.day)


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    profiles = [
        vehicle.performance for vehicle in sim.transport.vehicle_defs.values()
    ] + [
        service.performance for service in sim.transport.external_services.values()
    ]
    for profile in profiles:
        if profile.propellant_resource_id is not None:
            result.add(profile.propellant_resource_id)
        result.update(
            requirement.resource_id
            for requirement in profile.resource_support_requirements
        )
    for vehicle in sim.transport.vehicle_defs.values():
        result.update(resource_id for resource_id, _amount in vehicle.maintenance.resources)
        result.update(resource_id for resource_id, _amount in vehicle.production.resources)
    return result


def _validate_transport_profile(sim: Any, profile, known_capabilities: set[str], label: str) -> None:
    _require(profile.dry_mass_t >= 0, f"negative transport dry mass: {label}")
    _require(profile.payload_t > 0, f"non-positive transport payload: {label}")
    _require(profile.transit_time_multiplier > 0, f"non-positive transport time multiplier: {label}")
    if profile.endurance_days is not None:
        _require(profile.endurance_days > 0, f"non-positive transport endurance: {label}")
    _require(profile.propellant_capacity_t >= 0, f"negative propellant capacity: {label}")
    _require(profile.propellant_t_per_total_t_per_km_s >= 0, f"negative propellant use: {label}")
    if profile.propellant_t_per_total_t_per_km_s > 0:
        _require(profile.propellant_resource_id is not None, f"propellant rate without resource: {label}")
        _require(profile.propellant_capacity_t > 0, f"propellant rate without tank capacity: {label}")
    operation_types = [capability.operation_type for capability in profile.operation_capabilities]
    _require(len(operation_types) == len(set(operation_types)), f"duplicate transport operation capability: {label}")
    generic_capabilities = list(profile.generic_capabilities)
    _require(
        all(capability for capability in generic_capabilities),
        f"empty generic vehicle capability: {label}",
    )
    _require(
        len(generic_capabilities) == len(set(generic_capabilities)),
        f"duplicate generic vehicle capability: {label}",
    )
    resource_support_keys: set[tuple[DefinitionId, str, str | None]] = set()
    for requirement in profile.resource_support_requirements:
        _require(
            bool(requirement.infrastructure_capability_id),
            f"empty transport resource support capability: {label}",
        )
        _require(
            requirement.infrastructure_capability_id in known_capabilities,
            f"transport resource support references unknown capability: {label}/{requirement.infrastructure_capability_id}",
        )
        if requirement.vehicle_capability_id is not None:
            _require(
                bool(requirement.vehicle_capability_id),
                f"empty transport resource vehicle capability: {label}",
            )
            _require(
                requirement.vehicle_capability_id in generic_capabilities,
                f"transport resource support requires undeclared vehicle capability: {label}/{requirement.vehicle_capability_id}",
            )
        key = (
            requirement.resource_id,
            requirement.infrastructure_capability_id,
            requirement.vehicle_capability_id,
        )
        _require(
            key not in resource_support_keys,
            f"duplicate transport resource support requirement: {label}",
        )
        resource_support_keys.add(key)
    for capability in profile.operation_capabilities:
        _require(
            sim.transport.operation_registry.supports(capability.operation_type),
            f"unregistered transport operation capability: {label}/{capability.operation_type}",
        )
        for field_name, value in vars(capability).items():
            if field_name == "operation_type":
                continue
            if isinstance(value, (int, float)):
                _require(value >= 0, f"negative transport capability {capability.operation_type}.{field_name}: {label}")
    for requirement in profile.operation_support_requirements:
        _require(requirement.capability_id, f"empty transport operation support capability: {label}")
        _require(
            requirement.capability_id in known_capabilities,
            f"transport operation support references unknown capability: {label}/{requirement.capability_id}",
        )
        _require(
            requirement.operation_type in operation_types,
            f"transport operation support has no matching vehicle capability: {label}/{requirement.operation_type}",
        )


def _validate_unique_resources(resources, label: str) -> None:
    resource_ids = [resource_id for resource_id, _amount in resources]
    _require(
        len(resource_ids) == len(set(resource_ids)),
        f"duplicate vehicle resource input: {label}",
    )


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    sim.transport.synchronize_surface_access_routes()
    nodes = ctx.nodes
    known_capabilities = ctx.known_capabilities
    known_service_types = ctx.known_service_types
    for route_id, route in sim.transport.routes.items():
        _require(route_id == route.id, f"route definition key mismatch: {route_id}")
        _require(route.origin_id in nodes and route.destination_id in nodes, f"route references unknown location: {route_id}")
        _require(route.origin_id != route.destination_id, f"route loops to same location: {route_id}")
        _require(route.transit_days >= 0, f"negative route transit time: {route_id}")
        _require(route.delta_v_km_s >= 0, f"negative route delta-v: {route_id}")
        for operation in route.operations:
            _require(
                sim.transport.operation_registry.supports(operation.operation_type),
                f"route references unregistered transport operation: {route_id}/{operation.operation_type}",
            )
        _validate_site_requirements(route.origin_requirements, known_capabilities, f"route:{route_id}:origin", known_service_types)
        _validate_site_requirements(route.destination_requirements, known_capabilities, f"route:{route_id}:destination", known_service_types)
    for service_id, service in sim.transport.external_services.items():
        _require(service_id == service.id, f"transport service key mismatch: {service_id}")
        _require(service.capacity_t_per_day >= 0, f"negative transport service capacity: {service_id}")
        _require(service.cost_musd_per_t >= 0, f"negative transport service cost: {service_id}")
        _require(service.transit_time_multiplier > 0, f"non-positive transport service time multiplier: {service_id}")
        _validate_transport_profile(sim, service.performance, known_capabilities, f"transport_service:{service_id}")
        _validate_site_requirements(service.origin_requirements, known_capabilities, f"transport_service:{service_id}:origin", known_service_types)
        _validate_site_requirements(service.destination_requirements, known_capabilities, f"transport_service:{service_id}:destination", known_service_types)
    for vehicle_id, vehicle in sim.transport.vehicle_defs.items():
        _require(vehicle_id == vehicle.id, f"vehicle definition key mismatch: {vehicle_id}")
        _validate_transport_profile(sim, vehicle.performance, known_capabilities, f"vehicle:{vehicle_id}")
        _require(vehicle.maintenance.turnaround_days >= 0, f"negative vehicle turnaround: {vehicle_id}")
        _require(vehicle.maintenance.cost_musd >= 0, f"negative vehicle turnaround cost: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in vehicle.maintenance.resources), f"negative vehicle turnaround resource: {vehicle_id}")
        _validate_unique_resources(vehicle.maintenance.resources, f"maintenance:{vehicle_id}")
        _require(vehicle.production.days >= 0, f"negative vehicle production time: {vehicle_id}")
        _require(vehicle.production.cost_musd >= 0, f"negative vehicle production cost: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in vehicle.production.resources), f"negative vehicle production resource: {vehicle_id}")
        _validate_unique_resources(vehicle.production.resources, f"production:{vehicle_id}")
        _require(vehicle.economics.operating_cost_musd_per_cycle >= 0, f"negative vehicle cycle cost: {vehicle_id}")
        _require(vehicle.economics.operating_cost_musd_per_cargo_t >= 0, f"negative vehicle cargo cost: {vehicle_id}")
        if vehicle.maintenance.service_type is not None:
            _require(
                vehicle.maintenance.service_type in known_service_types,
                f"vehicle turnaround references unknown service type: {vehicle_id}/{vehicle.maintenance.service_type}",
            )
        if vehicle.production.service_type is not None:
            _require(
                vehicle.production.service_type in known_service_types,
                f"vehicle production references unknown service type: {vehicle_id}/{vehicle.production.service_type}",
            )
            _require(vehicle.production.days > 0, f"vehicle production duration must be positive: {vehicle_id}")
            _require(2 <= len(vehicle.production.resources) <= 3, f"vehicle production should use 2-3 physical resources: {vehicle_id}")
            _require(all(amount > 0 for _resource, amount in vehicle.production.resources), f"vehicle production has non-positive resource input: {vehicle_id}")
            _validate_site_requirements(vehicle.production.site_requirements, known_capabilities, f"vehicle_production:{vehicle_id}", known_service_types)
    for route_id in sim.transport.routes:
        external_service_exists = any(
            service.capacity_t_per_day > 1e-12 and not sim.transport.service_route_failures(route_id, service.id, 0)
            for service in sim.transport.external_services.values()
        )
        compatible_vehicle_exists = any(
            not sim.transport.vehicle_route_physical_failures(route_id, vehicle_id, 0)
            for vehicle_id in sim.transport.vehicle_defs
        )
        _require(external_service_exists or compatible_vehicle_exists, f"route has no physically compatible transport mode: {route_id}")


def validate_transport_runtime(sim: Any) -> None:
    tr = sim.transport
    tr.synchronize_surface_access_routes()
    for (vehicle_definition_id, location_id), pool in tr.fleet_pools.items():
        _require(pool.vehicle_definition_id == vehicle_definition_id and pool.operational_node_id == location_id, f"fleet pool key mismatch: {vehicle_definition_id}/{location_id}")
        _require(vehicle_definition_id in tr.vehicle_defs, f"fleet pool references unknown vehicle definition: {vehicle_definition_id}")
        _require(sim.graph.has_operational_node(location_id), f"fleet pool references unknown location: {vehicle_definition_id}/{location_id}")
        _require(pool.total_units >= 0, f"negative fleet total: {vehicle_definition_id}/{location_id}")
        _require(tr.fleet_free_units(vehicle_definition_id, location_id) >= 0, f"fleet pool overcommitted: {vehicle_definition_id}/{location_id}")
    for reservation_id, reservation in tr.fleet_reservations.items():
        _require(reservation_id == reservation.id, f"fleet reservation key mismatch: {reservation_id}")
        _require(reservation.vehicle_definition_id in tr.vehicle_defs, f"fleet reservation references unknown vehicle definition: {reservation_id}")
        _require(sim.graph.has_operational_node(reservation.operational_node_id), f"fleet reservation references unknown location: {reservation_id}")
        _require(reservation.units > 0, f"fleet reservation has non-positive units: {reservation_id}")
        if reservation.kind is FleetReservationKind.TRANSPORT:
            _require(
                reservation.owner_id in tr.transport_allocations,
                f"transport fleet reservation references unknown allocation: {reservation_id}/{reservation.owner_id}",
            )
            allocation = tr.transport_allocations[reservation.owner_id]
            _require(
                reservation_id == tr._transport_reservation_id(allocation.id),
                f"transport fleet reservation id mismatch: {reservation_id}/{allocation.id}",
            )
            _require(
                reservation.vehicle_definition_id == allocation.vehicle_definition_id,
                f"transport fleet reservation vehicle mismatch: {reservation_id}/{allocation.id}",
            )
            _require(
                reservation.operational_node_id == allocation.anchor_node_id,
                f"transport fleet reservation location mismatch: {reservation_id}/{allocation.id}",
            )
    for allocation_id, allocation in tr.transport_allocations.items():
        _require(allocation_id == allocation.id, f"transport allocation key mismatch: {allocation_id}")
        _require(allocation.vehicle_definition_id in tr.vehicle_defs, f"transport allocation references unknown vehicle definition: {allocation_id}")
        _require(sim.graph.has_operational_node(allocation.anchor_node_id) and sim.graph.has_operational_node(allocation.destination_id), f"transport allocation references unknown endpoint: {allocation_id}")
        if allocation.path is not None:
            tr.validate_path_structure(allocation.anchor_node_id, allocation.destination_id, allocation.path)
        required = tr.allocation_required_units(allocation_id, sim.day)
        active_units = tr.transport_active_units(allocation_id)
        _require(active_units <= required, f"transport allocation exceeds target: {allocation_id}")
    for relocation_id, relocation in tr.fleet_relocations.items():
        _require(relocation_id == relocation.id, f"fleet relocation key mismatch: {relocation_id}")
        _require(relocation.vehicle_definition_id in tr.vehicle_defs, f"fleet relocation references unknown vehicle definition: {relocation_id}")
        _require(sim.graph.has_operational_node(relocation.source_id) and sim.graph.has_operational_node(relocation.destination_id), f"fleet relocation references unknown endpoint: {relocation_id}")
        _require(bool(relocation.path), f"fleet relocation has empty path: {relocation_id}")
        _require(relocation.travel_days > 0, f"fleet relocation has invalid travel time: {relocation_id}")
        if relocation.started:
            assert relocation.departure_day is not None and relocation.arrival_day is not None
            _require(relocation.arrival_day > relocation.departure_day, f"invalid fleet relocation timing: {relocation_id}")
    for release_id, release in tr.fleet_releases.items():
        _require(release_id == release.id, f"fleet release key mismatch: {release_id}")
        # The source allocation may have been deleted while its units are still
        # physically returning. The release record itself owns the recovery
        # identity until release_day.
        _require(release.vehicle_definition_id in tr.vehicle_defs, f"fleet release references unknown vehicle definition: {release_id}")
        _require(sim.graph.has_operational_node(release.operational_node_id), f"fleet release references unknown location: {release_id}")
        _require(release.units > 0, f"fleet release has non-positive units: {release_id}")
    for project_id, state in tr.vehicle_production_projects.items():
        _require(project_id == state.id, f"vehicle production state key mismatch: {project_id}")
        _require(state.vehicle_definition_id in tr.vehicle_defs, f"vehicle production references unknown definition: {project_id}")
        _require(sim.graph.has_operational_node(state.operational_node_id), f"vehicle production references unknown location: {project_id}")
        _require(state.progress_days >= -1e-9, f"negative vehicle production progress: {project_id}")
        definition = tr.vehicle_defs[state.vehicle_definition_id]
        _require(state.progress_days <= definition.production.days + 1.0 + 1e-9, f"vehicle production progress exceeds duration: {project_id}")
        for resource_id, required_t in definition.production.resources:
            staged = tr._vehicle_production_staged_t(state, resource_id)
            if state.phase is VehicleProductionPhase.AWAITING_INPUTS:
                _require(
                    staged >= -1e-9 and staged <= required_t + 1e-9,
                    f"vehicle production staged material outside requirement: {project_id}/{resource_id}",
                )
            else:
                _require(
                    staged <= 1e-9,
                    f"started vehicle production retains staged input: {project_id}/{resource_id}",
                )
        if state.phase is VehicleProductionPhase.COMPLETE:
            _require(state.completed_units == 1, f"completed vehicle production has invalid completed unit count: {project_id}")
        else:
            _require(state.completed_units == 0, f"incomplete vehicle production has completed units: {project_id}")




TRANSPORT_STATE_CODEC = StateCodec("transport", capture_transport, restore_transport)
DOMAIN_EXTENSION = DomainExtension(
    "transport",
    state_codec=TRANSPORT_STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_transport_runtime,
    referenced_resources=referenced_resources,
)
