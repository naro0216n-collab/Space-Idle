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
    CargoFlowBatch,
    CargoFlowStatus,
    DirectionalCapacity,
    FleetPool,
    FleetRelocation,
    FleetRelease,
    FleetReservation,
    FleetReservationKind,
    LogisticsLane,
    PathPolicy,
    TransportAllocation,
    TransportControlMode,
)
from .production import VehicleProductionPhase, VehicleProductionState


def capture_logistics(sim: Any) -> dict[str, Any]:
    lg = sim.logistics
    return {
        "lane_counter": lg._lane_counter,
        "transport_allocation_counter": lg._transport_allocation_counter,
        "cargo_flow_counter": lg._cargo_flow_counter,
        "fleet_relocation_counter": lg._fleet_relocation_counter,
        "fleet_release_counter": lg._fleet_release_counter,
        "fleet_pools": [
            {
                "vehicle_definition_id": str(pool.vehicle_definition_id),
                "location_id": str(pool.location_id),
                "total_units": pool.total_units,
            }
            for pool in sorted(lg.fleet_pools.values(), key=lambda row: (str(row.vehicle_definition_id), str(row.location_id)))
            if pool.total_units > 0
        ],
        "fleet_reservations": [
            {
                "id": str(row.id),
                "owner_id": str(row.owner_id),
                "kind": row.kind.value,
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "location_id": str(row.location_id),
                "units": row.units,
            }
            for row in sorted(lg.fleet_reservations.values(), key=lambda row: str(row.id))
        ],
        "transport_allocations": [
            {
                "id": str(row.id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "anchor_location_id": str(row.anchor_location_id),
                "destination_id": str(row.destination_id),
                "priority": row.priority,
                "control_mode": row.control_mode.value,
                "target_units": row.target_units,
                "target_capacity": None if row.target_capacity is None else {
                    "forward_t_per_day": row.target_capacity.forward_t_per_day,
                    "reverse_t_per_day": row.target_capacity.reverse_t_per_day,
                },
                "path": None if row.path is None else [str(route_id) for route_id in row.path],
                "path_policy": row.path_policy.value,
                "paused": row.paused,
                "active_units": row.active_units,
                "last_operated_day": row.last_operated_day,
            }
            for row in sorted(lg.transport_allocations.values(), key=lambda row: str(row.id))
        ],
        "fleet_relocations": [
            {
                "id": str(row.id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "units": row.units,
                "source_id": str(row.source_id),
                "destination_id": str(row.destination_id),
                "departure_day": row.departure_day,
                "arrival_day": row.arrival_day,
            }
            for row in sorted(lg.fleet_relocations.values(), key=lambda row: str(row.id))
        ],
        "fleet_releases": [
            {
                "id": str(row.id),
                "allocation_id": str(row.allocation_id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "location_id": str(row.location_id),
                "units": row.units,
                "release_day": row.release_day,
            }
            for row in sorted(lg.fleet_releases.values(), key=lambda row: str(row.id))
        ],
        "cargo_flows": [
            {
                "id": str(row.id),
                "resource_id": str(row.resource_id),
                "amount_t": row.amount_t,
                "source_id": str(row.source_id),
                "destination_id": str(row.destination_id),
                "lane_id": None if row.lane_id is None else str(row.lane_id),
                "demand_id": None if row.demand_id is None else str(row.demand_id),
                "owner_kind": row.owner_kind,
                "owner_id": str(row.owner_id),
                "priority": row.priority,
                "service_ids": list(row.service_ids),
                "service_destinations": [str(value) for value in row.service_destinations],
                "departure_day": row.departure_day,
                "ready_day": row.ready_day,
                "leg_index": row.leg_index,
                "status": row.status.value,
            }
            for row in sorted(lg.cargo_flows.values(), key=lambda row: str(row.id))
        ],
        "lanes": [
            {
                "id": str(lane.id),
                "source_id": str(lane.source_id),
                "destination_id": str(lane.destination_id),
                "requested_capacity_t_per_day": lane.requested_capacity_t_per_day,
                "priority": lane.priority,
                "path": None if lane.path is None else [str(route_id) for route_id in lane.path],
                "path_policy": lane.path_policy.value,
                "paused": lane.paused,
            }
            for lane in sorted(lg.lanes.values(), key=lambda row: str(row.id))
        ],
        "vehicle_production": {
            "counter": lg._vehicle_production_counter,
            "projects": [
                {
                    "id": str(state.id), "vehicle_definition_id": str(state.vehicle_definition_id),
                    "location_id": str(state.location_id), "priority": state.priority,
                    "allocation_weight": state.allocation_weight, "progress_days": state.progress_days,
                    "phase": state.phase.value, "paused": state.paused,
                    "completed_units": state.completed_units, "created_day": state.created_day,
                }
                for state in sorted(lg.vehicle_production_projects.values(), key=lambda row: str(row.id))
            ],
        },
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._lane_counter = int(data.get("lane_counter", 0))
    lg._transport_allocation_counter = int(data.get("transport_allocation_counter", 0))
    lg._cargo_flow_counter = int(data.get("cargo_flow_counter", 0))
    lg._fleet_relocation_counter = int(data.get("fleet_relocation_counter", 0))
    lg._fleet_release_counter = int(data.get("fleet_release_counter", 0))
    lg.fleet_pools = {
        (DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["location_id"])): FleetPool(
            DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["location_id"]), int(row["total_units"])
        )
        for row in data.get("fleet_pools", [])
    }
    lg.fleet_reservations = {
        EntityId(row["id"]): FleetReservation(
            EntityId(row["id"]), EntityId(row["owner_id"]), FleetReservationKind(row["kind"]),
            DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["location_id"]), int(row["units"])
        )
        for row in data.get("fleet_reservations", [])
    }
    lg.transport_allocations = {}
    for row in data.get("transport_allocations", []):
        target = row.get("target_capacity")
        allocation = TransportAllocation(
            id=EntityId(row["id"]), vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            anchor_location_id=SpatialNodeId(row["anchor_location_id"]), destination_id=SpatialNodeId(row["destination_id"]),
            priority=int(row["priority"]), control_mode=TransportControlMode(row["control_mode"]),
            target_units=None if row.get("target_units") is None else int(row["target_units"]),
            target_capacity=None if target is None else DirectionalCapacity(float(target["forward_t_per_day"]), float(target["reverse_t_per_day"])),
            path=None if row.get("path") is None else tuple(RouteId(value) for value in row["path"]),
            path_policy=PathPolicy(row.get("path_policy", "fastest")), paused=bool(row.get("paused", False)),
            active_units=int(row.get("active_units", 0)),
            last_operated_day=None if row.get("last_operated_day") is None else int(row["last_operated_day"]),
        )
        lg.transport_allocations[allocation.id] = allocation
    lg.fleet_relocations = {
        EntityId(row["id"]): FleetRelocation(EntityId(row["id"]), DefinitionId(row["vehicle_definition_id"]), int(row["units"]), SpatialNodeId(row["source_id"]), SpatialNodeId(row["destination_id"]), int(row["departure_day"]), int(row["arrival_day"]))
        for row in data.get("fleet_relocations", [])
    }
    lg.fleet_releases = {
        EntityId(row["id"]): FleetRelease(EntityId(row["id"]), EntityId(row["allocation_id"]), DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["location_id"]), int(row["units"]), int(row["release_day"]))
        for row in data.get("fleet_releases", [])
    }
    lg.cargo_flows = {
        EntityId(row["id"]): CargoFlowBatch(
            EntityId(row["id"]), DefinitionId(row["resource_id"]), float(row["amount_t"]),
            SpatialNodeId(row["source_id"]), SpatialNodeId(row["destination_id"]),
            None if row.get("lane_id") is None else EntityId(row["lane_id"]),
            None if row.get("demand_id") is None else EntityId(row["demand_id"]),
            row["owner_kind"], EntityId(row["owner_id"]), int(row["priority"]), tuple(row["service_ids"]),
            tuple(SpatialNodeId(value) for value in row["service_destinations"]), int(row["departure_day"]), int(row["ready_day"]),
            int(row.get("leg_index", 0)), CargoFlowStatus(row.get("status", "in_transit")),
        )
        for row in data.get("cargo_flows", [])
    }
    lg.lanes = {
        EntityId(row["id"]): LogisticsLane(
            EntityId(row["id"]), SpatialNodeId(row["source_id"]), SpatialNodeId(row["destination_id"]),
            float(row["requested_capacity_t_per_day"]), int(row["priority"]),
            None if row.get("path") is None else tuple(RouteId(value) for value in row["path"]),
            PathPolicy(row.get("path_policy", "fastest")), bool(row.get("paused", False)),
        )
        for row in data.get("lanes", [])
    }
    production_data = data.get("vehicle_production", {})
    lg._vehicle_production_counter = int(production_data.get("counter", 0))
    lg.vehicle_production_projects = {
        EntityId(row["id"]): VehicleProductionState(
            id=EntityId(row["id"]), vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            location_id=SpatialNodeId(row["location_id"]), priority=int(row.get("priority", 50)),
            allocation_weight=float(row.get("allocation_weight", 1.0)), progress_days=float(row.get("progress_days", 0.0)),
            phase=VehicleProductionPhase(row.get("phase", "awaiting_inputs")), paused=bool(row.get("paused", False)),
            completed_units=int(row.get("completed_units", 0)), created_day=int(row.get("created_day", 0)),
        )
        for row in production_data.get("projects", [])
    }
    lg.reconcile_fleet_allocations(sim.day)

def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    for vehicle in sim.logistics.vehicle_defs.values():
        profile = vehicle.performance
        if profile.propellant_resource_id is not None:
            result.add(profile.propellant_resource_id)
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
    for capability in profile.operation_capabilities:
        _require(
            sim.logistics.operation_registry.supports(capability.operation_type),
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
    nodes = ctx.nodes
    known_capabilities = ctx.known_capabilities
    for route_id, route in sim.logistics.routes.items():
        _require(route_id == route.id, f"route definition key mismatch: {route_id}")
        _require(route.origin_id in nodes and route.destination_id in nodes, f"route references unknown location: {route_id}")
        _require(route.origin_id != route.destination_id, f"route loops to same location: {route_id}")
        _require(route.transit_days >= 0, f"negative route transit time: {route_id}")
        _require(route.delta_v_km_s >= 0, f"negative route delta-v: {route_id}")
        for operation in route.operations:
            _require(
                sim.logistics.operation_registry.supports(operation.operation_type),
                f"route references unregistered transport operation: {route_id}/{operation.operation_type}",
            )
        _validate_site_requirements(route.origin_requirements, known_capabilities, f"route:{route_id}:origin")
        _validate_site_requirements(route.destination_requirements, known_capabilities, f"route:{route_id}:destination")
    for service_id, service in sim.logistics.external_services.items():
        _require(service_id == service.id, f"transport service key mismatch: {service_id}")
        _require(service.capacity_t_per_day >= 0, f"negative transport service capacity: {service_id}")
        _require(service.cost_musd_per_t >= 0, f"negative transport service cost: {service_id}")
        _require(service.transit_time_multiplier > 0, f"non-positive transport service time multiplier: {service_id}")
        _validate_transport_profile(sim, service.performance, known_capabilities, f"transport_service:{service_id}")
        _validate_site_requirements(service.origin_requirements, known_capabilities, f"transport_service:{service_id}:origin")
        _validate_site_requirements(service.destination_requirements, known_capabilities, f"transport_service:{service_id}:destination")
    for vehicle_id, vehicle in sim.logistics.vehicle_defs.items():
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
        if vehicle.maintenance.capability_id is not None:
            _require(vehicle.maintenance.capability_id in known_capabilities, f"vehicle turnaround references unknown capability: {vehicle_id}/{vehicle.maintenance.capability_id}")
        if vehicle.production.capability_id is not None:
            _require(vehicle.production.capability_id in known_capabilities, f"vehicle production references unknown capability: {vehicle_id}/{vehicle.production.capability_id}")
            _require(vehicle.production.days > 0, f"vehicle production duration must be positive: {vehicle_id}")
            _require(2 <= len(vehicle.production.resources) <= 3, f"vehicle production should use 2-3 physical resources: {vehicle_id}")
            _require(all(amount > 0 for _resource, amount in vehicle.production.resources), f"vehicle production has non-positive resource input: {vehicle_id}")
            _validate_site_requirements(vehicle.production.site_requirements, known_capabilities, f"vehicle_production:{vehicle_id}")
    for route_id in sim.logistics.routes:
        external_service_exists = any(
            service.capacity_t_per_day > 1e-12 and not sim.logistics.service_route_failures(route_id, service.id, 0)
            for service in sim.logistics.external_services.values()
        )
        compatible_vehicle_exists = any(
            not sim.logistics.vehicle_route_physical_failures(route_id, vehicle_id, 0)
            for vehicle_id in sim.logistics.vehicle_defs
        )
        _require(external_service_exists or compatible_vehicle_exists, f"route has no physically compatible transport mode: {route_id}")


def validate_runtime(sim: Any) -> None:
    lg = sim.logistics
    for (vehicle_definition_id, location_id), pool in lg.fleet_pools.items():
        _require(pool.vehicle_definition_id == vehicle_definition_id and pool.location_id == location_id, f"fleet pool key mismatch: {vehicle_definition_id}/{location_id}")
        _require(vehicle_definition_id in lg.vehicle_defs, f"fleet pool references unknown vehicle definition: {vehicle_definition_id}")
        _require(location_id in sim.graph.nodes, f"fleet pool references unknown location: {vehicle_definition_id}/{location_id}")
        _require(pool.total_units >= 0, f"negative fleet total: {vehicle_definition_id}/{location_id}")
        _require(lg.fleet_free_units(vehicle_definition_id, location_id) >= 0, f"fleet pool overcommitted: {vehicle_definition_id}/{location_id}")
    for reservation_id, reservation in lg.fleet_reservations.items():
        _require(reservation_id == reservation.id, f"fleet reservation key mismatch: {reservation_id}")
        _require(reservation.vehicle_definition_id in lg.vehicle_defs, f"fleet reservation references unknown vehicle definition: {reservation_id}")
        _require(reservation.location_id in sim.graph.nodes, f"fleet reservation references unknown location: {reservation_id}")
        _require(reservation.units > 0, f"fleet reservation has non-positive units: {reservation_id}")
    for allocation_id, allocation in lg.transport_allocations.items():
        _require(allocation_id == allocation.id, f"transport allocation key mismatch: {allocation_id}")
        _require(allocation.vehicle_definition_id in lg.vehicle_defs, f"transport allocation references unknown vehicle definition: {allocation_id}")
        _require(allocation.anchor_location_id in sim.graph.nodes and allocation.destination_id in sim.graph.nodes, f"transport allocation references unknown endpoint: {allocation_id}")
        _require(allocation.active_units >= 0, f"transport allocation has negative active units: {allocation_id}")
        if allocation.path is not None:
            lg.validate_path_structure(allocation.anchor_location_id, allocation.destination_id, allocation.path)
        required = lg.allocation_required_units(allocation_id, sim.day)
        _require(allocation.active_units <= required, f"transport allocation exceeds target: {allocation_id}")
    for relocation_id, relocation in lg.fleet_relocations.items():
        _require(relocation_id == relocation.id, f"fleet relocation key mismatch: {relocation_id}")
        _require(relocation.vehicle_definition_id in lg.vehicle_defs, f"fleet relocation references unknown vehicle definition: {relocation_id}")
        _require(relocation.source_id in sim.graph.nodes and relocation.destination_id in sim.graph.nodes, f"fleet relocation references unknown endpoint: {relocation_id}")
        _require(relocation.arrival_day > relocation.departure_day, f"invalid fleet relocation timing: {relocation_id}")
    for release_id, release in lg.fleet_releases.items():
        _require(release_id == release.id, f"fleet release key mismatch: {release_id}")
        # The source allocation may have been deleted while its units are still
        # physically returning. The release record itself owns the recovery
        # identity until release_day.
        _require(release.vehicle_definition_id in lg.vehicle_defs, f"fleet release references unknown vehicle definition: {release_id}")
        _require(release.location_id in sim.graph.nodes, f"fleet release references unknown location: {release_id}")
        _require(release.units > 0, f"fleet release has non-positive units: {release_id}")
    for flow_id, flow in lg.cargo_flows.items():
        _require(flow_id == flow.id, f"cargo flow key mismatch: {flow_id}")
        _require(flow.source_id in sim.graph.nodes and flow.destination_id in sim.graph.nodes, f"cargo flow references unknown endpoint: {flow_id}")
        _require(flow.amount_t > 0, f"cargo flow has non-positive amount: {flow_id}")
        _require(flow.ready_day >= flow.departure_day, f"cargo flow arrives before departure: {flow_id}")
        if flow.lane_id is not None:
            _require(flow.lane_id in lg.lanes, f"cargo flow references unknown lane: {flow_id}/{flow.lane_id}")
    for project_id, state in lg.vehicle_production_projects.items():
        _require(project_id == state.id, f"vehicle production state key mismatch: {project_id}")
        _require(state.vehicle_definition_id in lg.vehicle_defs, f"vehicle production references unknown definition: {project_id}")
        _require(state.location_id in sim.graph.nodes, f"vehicle production references unknown location: {project_id}")
        _require(state.progress_days >= -1e-9, f"negative vehicle production progress: {project_id}")
        definition = lg.vehicle_defs[state.vehicle_definition_id]
        _require(state.progress_days <= definition.production.days + 1.0 + 1e-9, f"vehicle production progress exceeds duration: {project_id}")
        if state.phase is VehicleProductionPhase.COMPLETE:
            _require(state.completed_units == 1, f"completed vehicle production has invalid completed unit count: {project_id}")
        else:
            _require(state.completed_units == 0, f"incomplete vehicle production has completed units: {project_id}")
    for lane_id, lane in lg.lanes.items():
        _require(lane_id == lane.id, f"lane key mismatch: {lane_id}")
        _require(lane.source_id in sim.graph.nodes and lane.destination_id in sim.graph.nodes, f"lane references unknown endpoint: {lane_id}")
        _require(lane.source_id != lane.destination_id, f"lane loops to same location: {lane_id}")
        _require(lane.requested_capacity_t_per_day > 0, f"lane has non-positive requested capacity: {lane_id}")
        if lane.path is not None:
            lg.validate_path_structure(lane.source_id, lane.destination_id, lane.path)


STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension(
    "logistics",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
