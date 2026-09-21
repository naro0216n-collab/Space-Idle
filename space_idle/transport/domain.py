from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec, decode_bool, decode_float, decode_int
from ..validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)
from ..shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId, SurfaceCellId
from .models import (
    DirectionalCapacity,
    FleetPool,
    FleetRelocation,
    FleetRelocationResourceNeed,
    FleetRelease,
    FleetActivityRef,
    FleetCommitmentState,
    FleetRetirementPhase,
    FleetRetirementState,
    MovementEndpoint,
    MovementExecution,
    MovementExecutionKind,
    MovementExecutionLeg,
    MovementExecutionPayloadResource,
    MovementExecutionResourceRequirement,
    OperationAssetDisposition,
    TransportOperationRequirement,
    TransportAllocation,
)
from .production import VehicleProductionPhase, VehicleProductionState


def _capture_movement_endpoint(endpoint: MovementEndpoint) -> dict[str, Any]:
    return {
        "operational_node_id": None if endpoint.operational_node_id is None else str(endpoint.operational_node_id),
        "surface_interface_id": None if endpoint.surface_interface_id is None else str(endpoint.surface_interface_id),
        "access_cell_id": None if endpoint.access_cell_id is None else str(endpoint.access_cell_id),
        "non_surface_interface": endpoint.non_surface_interface,
        "physical_target_cell_id": None if endpoint.physical_target_cell_id is None else str(endpoint.physical_target_cell_id),
        "physical_target_node_id": None if endpoint.physical_target_node_id is None else str(endpoint.physical_target_node_id),
    }


def _restore_movement_endpoint(data: dict[str, Any]) -> MovementEndpoint:
    return MovementEndpoint(
        operational_node_id=None if data["operational_node_id"] is None else SpatialNodeId(data["operational_node_id"]),
        surface_interface_id=None if data["surface_interface_id"] is None else EntityId(data["surface_interface_id"]),
        access_cell_id=None if data["access_cell_id"] is None else SurfaceCellId(data["access_cell_id"]),
        non_surface_interface=data["non_surface_interface"],
        physical_target_cell_id=None if data["physical_target_cell_id"] is None else SurfaceCellId(data["physical_target_cell_id"]),
        physical_target_node_id=None if data["physical_target_node_id"] is None else SpatialNodeId(data["physical_target_node_id"]),
    )


def _capture_movement_execution(row: MovementExecution) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "owner_id": str(row.owner_id),
        "kind": row.kind.value,
        "fleet_commitment_id": str(row.fleet_commitment_id),
        "payload_t_per_unit": row.payload_t_per_unit,
        "started_day": row.started_day,
        "completion_day": row.completion_day,
        "payload_resources": [
            {"resource_id": str(payload.resource_id), "amount_t": payload.amount_t}
            for payload in row.payload_resources
        ],
        "legs": [
            {
                "movement_plan_id": str(leg.movement_plan_id),
                "origin": _capture_movement_endpoint(leg.origin),
                "destination": _capture_movement_endpoint(leg.destination),
                "operations": [
                    {"operation_type": operation.operation_type, "delta_v_km_s": operation.delta_v_km_s}
                    for operation in leg.operations
                ],
                "latency_days": leg.latency_days,
                "payload_capacity_t": leg.payload_capacity_t,
                "propellant_t_per_unit": leg.propellant_t_per_unit,
                "asset_disposition": leg.asset_disposition.value,
                "resource_requirements": [
                    {
                        "operational_node_id": str(requirement.operational_node_id),
                        "resource_id": str(requirement.resource_id),
                        "required_t": requirement.required_t,
                    }
                    for requirement in leg.resource_requirements
                ],
            }
            for leg in row.legs
        ],
    }


def _restore_movement_execution(data: dict[str, Any]) -> MovementExecution:
    return MovementExecution(
        id=EntityId(data["id"]),
        owner_id=EntityId(data["owner_id"]),
        kind=MovementExecutionKind(data["kind"]),
        fleet_commitment_id=EntityId(data["fleet_commitment_id"]),
        legs=tuple(
            MovementExecutionLeg(
                movement_plan_id=MovementPlanId(leg["movement_plan_id"]),
                origin=_restore_movement_endpoint(leg["origin"]),
                destination=_restore_movement_endpoint(leg["destination"]),
                operations=tuple(
                    TransportOperationRequirement(
                        operation["operation_type"], decode_float(operation["delta_v_km_s"], "movement operation delta_v_km_s")
                    )
                    for operation in leg["operations"]
                ),
                latency_days=decode_int(leg["latency_days"], "movement leg latency_days"),
                payload_capacity_t=decode_float(leg["payload_capacity_t"], "movement leg payload_capacity_t"),
                propellant_t_per_unit=decode_float(leg["propellant_t_per_unit"], "movement leg propellant_t_per_unit"),
                asset_disposition=OperationAssetDisposition(leg["asset_disposition"]),
                resource_requirements=tuple(
                    MovementExecutionResourceRequirement(
                        SpatialNodeId(requirement["operational_node_id"]),
                        DefinitionId(requirement["resource_id"]),
                        decode_float(requirement["required_t"], "movement resource required_t"),
                    )
                    for requirement in leg["resource_requirements"]
                ),
            )
            for leg in data["legs"]
        ),
        payload_t_per_unit=decode_float(data["payload_t_per_unit"], "movement payload_t_per_unit"),
        started_day=decode_int(data["started_day"], "movement started_day"),
        completion_day=decode_int(data["completion_day"], "movement completion_day"),
        payload_resources=tuple(
            MovementExecutionPayloadResource(
                DefinitionId(payload["resource_id"]),
                decode_float(payload["amount_t"], "movement payload amount_t"),
            )
            for payload in data["payload_resources"]
        ),
    )


def capture_transport(sim: Any) -> dict[str, Any]:
    tr = sim.transport
    return {
        "transport_allocation_counter": tr._transport_allocation_counter,
        "fleet_relocation_counter": tr._fleet_relocation_counter,
        "fleet_release_counter": tr._fleet_release_counter,
        "fleet_retirement_counter": tr._fleet_retirement_counter,
        "fleet_pools": [
            {
                "vehicle_definition_id": str(pool.vehicle_definition_id),
                "operational_node_id": str(pool.operational_node_id),
                "total_units": pool.total_units,
            }
            for pool in sorted(tr.fleet_pools.values(), key=lambda row: (str(row.vehicle_definition_id), str(row.operational_node_id)))
            if pool.total_units > 0
        ],
        "fleet_commitments": [
            {
                "id": str(row.id),
                "owner_activity_type": row.owner_activity_ref.activity_type,
                "owner_activity_id": str(row.owner_activity_ref.activity_id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "quantity": row.quantity,
                "operational_node_id": None if row.operational_node_id is None else str(row.operational_node_id),
                "movement_execution_id": None if row.movement_execution_id is None else str(row.movement_execution_id),
            }
            for row in sorted(tr.fleet_commitments.values(), key=lambda row: str(row.id))
        ],
        "transport_allocations": [
            {
                "id": str(row.id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "anchor_node_id": str(row.anchor_node_id),
                "destination_id": str(row.destination_id),
                "provisioning_priority": int(row.provisioning_priority),
                "target_capacity": {
                    "forward_t_per_day": row.target_capacity.forward_t_per_day,
                    "reverse_t_per_day": row.target_capacity.reverse_t_per_day,
                },
                "movement_hard_constraint": (
                    None
                    if row.movement_hard_constraint is None
                    else [str(value) for value in row.movement_hard_constraint]
                ),
                "paused": row.paused,
                "last_operated_day": row.last_operated_day,
            }
            for row in sorted(tr.transport_allocations.values(), key=lambda row: str(row.id))
        ],
        "fleet_relocations": [
            {
                "id": str(row.id),
                "vehicle_definition_id": str(row.vehicle_definition_id),
                "requested_units": row.requested_units,
                "fleet_commitment_id": str(row.fleet_commitment_id),
                "source_id": str(row.source_id),
                "destination_id": str(row.destination_id),
                "requested_day": row.requested_day,
                "path": [str(movement_plan_id) for movement_plan_id in row.path],
                "priority": int(row.priority),
                "movement_execution_id": None if row.movement_execution_id is None else str(row.movement_execution_id),
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
        "movement_executions": [
            _capture_movement_execution(row)
            for row in sorted(tr.movement_executions.values(), key=lambda row: str(row.id))
        ],
        "fleet_releases": [
            {
                "id": str(row.id),
                "allocation_id": str(row.allocation_id),
                "fleet_commitment_id": str(row.fleet_commitment_id),
                "release_day": row.release_day,
            }
            for row in sorted(tr.fleet_releases.values(), key=lambda row: str(row.id))
        ],
        "fleet_retirements": [
            {
                "id": str(state.id),
                "vehicle_definition_id": str(state.vehicle_definition_id),
                "operational_node_id": str(state.operational_node_id),
                "requested_units": state.requested_units,
                "fleet_commitment_id": str(state.fleet_commitment_id),
                "priority": int(state.priority),
                "progress_work": state.progress_work,
                "phase": state.phase.value,
                "irreversible_started": state.irreversible_started,
                "created_day": state.created_day,
                "salvage_recovered_fraction": state.salvage_recovered_fraction,
            }
            for state in sorted(tr.fleet_retirements.values(), key=lambda row: str(row.id))
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
    tr._transport_allocation_counter = decode_int(data["transport_allocation_counter"], "transport allocation counter")
    tr._fleet_relocation_counter = decode_int(data["fleet_relocation_counter"], "fleet relocation counter")
    tr._fleet_release_counter = decode_int(data["fleet_release_counter"], "fleet release counter")
    tr._fleet_retirement_counter = decode_int(data["fleet_retirement_counter"], "fleet retirement counter")
    tr.fleet_pools = {
        (DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["operational_node_id"])): FleetPool(
            DefinitionId(row["vehicle_definition_id"]), SpatialNodeId(row["operational_node_id"]), decode_int(row["total_units"], "fleet total_units")
        )
        for row in data["fleet_pools"]
    }
    tr.fleet_commitments = {
        EntityId(row["id"]): FleetCommitmentState(
            id=EntityId(row["id"]),
            owner_activity_ref=FleetActivityRef(
                str(row["owner_activity_type"]), EntityId(row["owner_activity_id"])
            ),
            vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            quantity=decode_int(row["quantity"], "fleet commitment quantity"),
            operational_node_id=(
                None if row["operational_node_id"] is None
                else SpatialNodeId(row["operational_node_id"])
            ),
            movement_execution_id=(
                None if row["movement_execution_id"] is None
                else EntityId(row["movement_execution_id"])
            ),
        )
        for row in data["fleet_commitments"]
    }
    tr.transport_allocations = {}
    allocation_fields = {
        "id", "vehicle_definition_id", "anchor_node_id", "destination_id",
        "provisioning_priority", "target_capacity", "movement_hard_constraint",
        "paused", "last_operated_day",
    }
    for row in data["transport_allocations"]:
        if set(row) != allocation_fields:
            raise ValueError("transport allocation has invalid fields")
        target = row["target_capacity"]
        if set(target) != {"forward_t_per_day", "reverse_t_per_day"}:
            raise ValueError("transport allocation target capacity has invalid fields")
        allocation = TransportAllocation(
            id=EntityId(row["id"]), vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            anchor_node_id=SpatialNodeId(row["anchor_node_id"]), destination_id=SpatialNodeId(row["destination_id"]),
            provisioning_priority=decode_int(row["provisioning_priority"], "transport provisioning_priority"),
            target_capacity=DirectionalCapacity(
                decode_float(target["forward_t_per_day"], "transport target forward_t_per_day"),
                decode_float(target["reverse_t_per_day"], "transport target reverse_t_per_day"),
            ),
            movement_hard_constraint=(
                None
                if row["movement_hard_constraint"] is None
                else tuple(MovementPlanId(value) for value in row["movement_hard_constraint"])
            ),
            paused=decode_bool(row["paused"], "transport paused"),
            last_operated_day=None if row["last_operated_day"] is None else decode_int(row["last_operated_day"], "transport last_operated_day"),
        )
        tr.transport_allocations[allocation.id] = allocation
    tr.fleet_relocations = {
        EntityId(row["id"]): FleetRelocation(
            id=EntityId(row["id"]),
            vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            requested_units=decode_int(row["requested_units"], "fleet requested_units"),
            fleet_commitment_id=EntityId(row["fleet_commitment_id"]),
            source_id=SpatialNodeId(row["source_id"]),
            destination_id=SpatialNodeId(row["destination_id"]),
            requested_day=decode_int(row["requested_day"], "fleet requested_day"),
            path=tuple(MovementPlanId(value) for value in row["path"]),
            resource_needs=tuple(
                FleetRelocationResourceNeed(
                    SpatialNodeId(need["operational_node_id"]),
                    DefinitionId(need["resource_id"]),
                    decode_float(need["required_t"], "fleet relocation required_t"),
                )
                for need in row["resource_needs"]
            ),
            priority=decode_int(row["priority"], "transport priority"),
            movement_execution_id=None if row["movement_execution_id"] is None else EntityId(row["movement_execution_id"]),
        )
        for row in data["fleet_relocations"]
    }
    tr.movement_executions = {
        execution.id: execution
        for execution in (
            _restore_movement_execution(row) for row in data["movement_executions"]
        )
    }
    tr.fleet_releases = {
        EntityId(row["id"]): FleetRelease(
            EntityId(row["id"]), EntityId(row["allocation_id"]),
            EntityId(row["fleet_commitment_id"]), decode_int(row["release_day"], "fleet release_day")
        )
        for row in data["fleet_releases"]
    }
    tr.fleet_retirements = {
        EntityId(row["id"]): FleetRetirementState(
            id=EntityId(row["id"]),
            vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            operational_node_id=SpatialNodeId(row["operational_node_id"]),
            requested_units=decode_int(row["requested_units"], "fleet requested_units"),
            fleet_commitment_id=EntityId(row["fleet_commitment_id"]),
            priority=decode_int(row["priority"], "transport priority"),
            progress_work=decode_float(row["progress_work"], "fleet retirement progress_work"),
            phase=FleetRetirementPhase(row["phase"]),
            irreversible_started=decode_bool(row["irreversible_started"], "fleet retirement irreversible_started"),
            created_day=decode_int(row["created_day"], "transport created_day"),
            salvage_recovered_fraction=(
                None
                if row["salvage_recovered_fraction"] is None
                else decode_float(row["salvage_recovered_fraction"], "fleet retirement salvage_recovered_fraction")
            ),
        )
        for row in data["fleet_retirements"]
    }
    production_data = data["vehicle_production"]
    tr._vehicle_production_counter = decode_int(production_data["counter"], "vehicle production counter")
    tr.vehicle_production_projects = {
        EntityId(row["id"]): VehicleProductionState(
            id=EntityId(row["id"]), vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            operational_node_id=SpatialNodeId(row["operational_node_id"]), priority=decode_int(row["priority"], "transport priority"),
            progress_days=decode_float(row["progress_days"], "vehicle production progress_days"),
            phase=VehicleProductionPhase(row["phase"]), paused=decode_bool(row["paused"], "transport paused"),
            completed_units=decode_int(row["completed_units"], "vehicle production completed_units"), created_day=decode_int(row["created_day"], "transport created_day"),
        )
        for row in production_data["projects"]
    }
    tr.reconcile_fleet_allocations(sim.day)


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    profiles = [vehicle.performance for vehicle in sim.transport.vehicle_defs.values()]
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
        result.update(resource_id for resource_id, _amount in vehicle.retirement.resources_per_unit)
        result.update(resource_id for resource_id, _amount in vehicle.retirement.recovery_resources_per_unit)
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
    known_capabilities = ctx.known_capabilities
    known_service_types = ctx.known_service_types

    graph = sim.graph
    for rule in sim.transport.surface_movement_rules:
        _require(bool(rule.id), "surface movement rule id must not be empty")
        _require(rule.transit_days > 0, f"non-positive surface movement transit time: {rule.id}")
        _require(
            sim.transport.operation_registry.supports(rule.operation.operation_type),
            f"surface movement rule references unregistered operation: {rule.id}/{rule.operation.operation_type}",
        )
    for rule in sim.transport.surface_access_movement_rules:
        _require(rule.body_id in graph.bodies, f"surface-access movement rule references unknown body: {rule.id}/{rule.body_id}")
        _require(rule.transit_days > 0, f"non-positive surface-access movement transit time: {rule.id}")
        _require(bool(rule.ascent_operations) and bool(rule.descent_operations), f"surface-access movement rule requires both directions: {rule.id}")
        for operation in rule.ascent_operations + rule.descent_operations:
            _require(
                sim.transport.operation_registry.supports(operation.operation_type),
                f"surface-access movement rule references unregistered operation: {rule.id}/{operation.operation_type}",
            )
        _validate_site_requirements(rule.space_requirements, known_capabilities, f"movement_rule:{rule.id}:space")
        _validate_site_requirements(rule.surface_requirements, known_capabilities, f"movement_rule:{rule.id}:surface")
    for rule in sim.transport.spaceflight_movement_rules:
        _require(rule.characteristic_speed_km_per_day > 0, f"non-positive spaceflight characteristic speed: {rule.id}")
        _require(rule.minimum_transit_days > 0, f"non-positive spaceflight minimum transit time: {rule.id}")
        _require(
            sim.transport.operation_registry.supports(rule.operation_type),
            f"spaceflight movement rule references unregistered operation: {rule.id}/{rule.operation_type}",
        )
        _validate_site_requirements(rule.origin_requirements, known_capabilities, f"movement_rule:{rule.id}:origin")
        _validate_site_requirements(rule.destination_requirements, known_capabilities, f"movement_rule:{rule.id}:destination")
    for vehicle_id, vehicle in sim.transport.vehicle_defs.items():
        _require(vehicle_id == vehicle.id, f"vehicle definition key mismatch: {vehicle_id}")
        _validate_transport_profile(sim, vehicle.performance, known_capabilities, f"vehicle:{vehicle_id}")
        _require(vehicle.maintenance.turnaround_days >= 0, f"negative vehicle turnaround: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in vehicle.maintenance.resources), f"negative vehicle turnaround resource: {vehicle_id}")
        _validate_unique_resources(vehicle.maintenance.resources, f"maintenance:{vehicle_id}")
        _require(vehicle.production.days >= 0, f"negative vehicle production time: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in vehicle.production.resources), f"negative vehicle production resource: {vehicle_id}")
        _validate_unique_resources(vehicle.production.resources, f"production:{vehicle_id}")
        retirement = vehicle.retirement
        _require(retirement.work_days_per_unit >= 0, f"negative vehicle retirement work: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in retirement.resources_per_unit), f"negative vehicle retirement resource: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in retirement.recovery_resources_per_unit), f"negative vehicle retirement recovery: {vehicle_id}")
        _validate_unique_resources(retirement.resources_per_unit, f"retirement:{vehicle_id}")
        _validate_unique_resources(retirement.recovery_resources_per_unit, f"retirement_recovery:{vehicle_id}")
        if retirement.enabled:
            _require(retirement.service_type is not None, f"vehicle retirement requires a service type: {vehicle_id}")
            _require(retirement.service_type in known_service_types, f"vehicle retirement references unknown service type: {vehicle_id}/{retirement.service_type}")
            _validate_site_requirements(retirement.site_requirements, known_capabilities, f"vehicle_retirement:{vehicle_id}")
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
            _validate_site_requirements(vehicle.production.site_requirements, known_capabilities, f"vehicle_production:{vehicle_id}")
def validate_transport_runtime(sim: Any) -> None:
    tr = sim.transport

    for (vehicle_definition_id, location_id), pool in tr.fleet_pools.items():
        _require(
            pool.vehicle_definition_id == vehicle_definition_id
            and pool.operational_node_id == location_id,
            f"fleet pool key mismatch: {vehicle_definition_id}/{location_id}",
        )
        _require(vehicle_definition_id in tr.vehicle_defs, f"fleet pool references unknown vehicle definition: {vehicle_definition_id}")
        _require(sim.graph.has_operational_node(location_id), f"fleet pool references unknown location: {vehicle_definition_id}/{location_id}")
        _require(pool.total_units >= 0, f"negative fleet total: {vehicle_definition_id}/{location_id}")
        _require(tr.fleet_free_units(vehicle_definition_id, location_id) >= 0, f"fleet pool overcommitted: {vehicle_definition_id}/{location_id}")

    movement_commitments: dict[EntityId, EntityId] = {}
    for commitment_id, commitment in tr.fleet_commitments.items():
        _require(commitment_id == commitment.id, f"fleet commitment key mismatch: {commitment_id}")
        _require(commitment.vehicle_definition_id in tr.vehicle_defs, f"fleet commitment references unknown vehicle definition: {commitment_id}")
        _require(commitment.quantity > 0, f"fleet commitment has non-positive quantity: {commitment_id}")
        _require(
            (commitment.operational_node_id is None) != (commitment.movement_execution_id is None),
            f"fleet commitment location ownership is ambiguous: {commitment_id}",
        )
        if commitment.operational_node_id is not None:
            _require(sim.graph.has_operational_node(commitment.operational_node_id), f"fleet commitment references unknown location: {commitment_id}")
        if commitment.movement_execution_id is not None:
            _require(commitment.movement_execution_id in tr.movement_executions, f"moving Fleet commitment references missing MovementExecution: {commitment_id}")
            _require(commitment.movement_execution_id not in movement_commitments, f"MovementExecution is owned by multiple Fleet commitments: {commitment.movement_execution_id}")
            movement_commitments[commitment.movement_execution_id] = commitment_id

        owner = commitment.owner_activity_ref
        _require(
            owner.activity_type in tr._fleet_commitment_owner_resolvers,
            f"Fleet commitment owner activity type is not registered: {commitment_id}/{owner.activity_type}",
        )
        _require(
            tr.fleet_commitment_owner_exists(owner),
            f"orphan Fleet commitment owner: {commitment_id}/{owner.activity_type}/{owner.activity_id}",
        )
        if owner.activity_type == "transport_allocation":
            allocation = tr.transport_allocations.get(owner.activity_id)
            _require(allocation is not None, f"transport Fleet commitment references unknown allocation: {commitment_id}/{owner.activity_id}")
            if allocation is not None:
                _require(commitment_id == tr._transport_commitment_id(allocation.id), f"transport Fleet commitment id mismatch: {commitment_id}/{allocation.id}")
                _require(commitment.vehicle_definition_id == allocation.vehicle_definition_id, f"transport Fleet commitment vehicle mismatch: {commitment_id}/{allocation.id}")
                _require(commitment.operational_node_id == allocation.anchor_node_id, f"transport Fleet commitment location mismatch: {commitment_id}/{allocation.id}")
                _require(commitment.movement_execution_id is None, f"transport Allocation Fleet commitment cannot be in one-shot Movement: {commitment_id}")
        elif owner.activity_type == "fleet_relocation":
            relocation = tr.fleet_relocations.get(owner.activity_id)
            _require(relocation is not None, f"relocation Fleet commitment references unknown relocation: {commitment_id}/{owner.activity_id}")
            if relocation is not None:
                _require(commitment_id == relocation.fleet_commitment_id, f"relocation Fleet commitment id mismatch: {commitment_id}/{relocation.id}")
        elif owner.activity_type == "fleet_release":
            release = tr.fleet_releases.get(owner.activity_id)
            _require(release is not None, f"release Fleet commitment references unknown release: {commitment_id}/{owner.activity_id}")
            if release is not None:
                _require(commitment_id == release.fleet_commitment_id, f"release Fleet commitment id mismatch: {commitment_id}/{release.id}")
        elif owner.activity_type == "fleet_retirement":
            state = tr.fleet_retirements.get(owner.activity_id)
            _require(state is not None, f"retirement Fleet commitment references unknown retirement: {commitment_id}/{owner.activity_id}")
            if state is not None:
                _require(commitment_id == state.fleet_commitment_id, f"retirement Fleet commitment id mismatch: {commitment_id}/{state.id}")

    for allocation_id, allocation in tr.transport_allocations.items():
        _require(allocation_id == allocation.id, f"transport allocation key mismatch: {allocation_id}")
        _require(allocation.vehicle_definition_id in tr.vehicle_defs, f"transport allocation references unknown vehicle definition: {allocation_id}")
        _require(sim.graph.has_operational_node(allocation.anchor_node_id) and sim.graph.has_operational_node(allocation.destination_id), f"transport allocation references unknown endpoint: {allocation_id}")
        if allocation.movement_hard_constraint is not None:
            tr.validate_movement_path_structure(
                allocation.anchor_node_id,
                allocation.destination_id,
                allocation.movement_hard_constraint,
            )
        required = tr.allocation_required_units(allocation_id, sim.day)
        active_units = tr.transport_active_units(allocation_id)
        _require(active_units <= required, f"transport allocation exceeds target: {allocation_id}")

    for relocation_id, relocation in tr.fleet_relocations.items():
        _require(relocation_id == relocation.id, f"fleet relocation key mismatch: {relocation_id}")
        _require(relocation.vehicle_definition_id in tr.vehicle_defs, f"fleet relocation references unknown vehicle definition: {relocation_id}")
        _require(sim.graph.has_operational_node(relocation.source_id) and sim.graph.has_operational_node(relocation.destination_id), f"fleet relocation references unknown endpoint: {relocation_id}")
        _require(relocation.requested_units > 0, f"fleet relocation has non-positive requested units: {relocation_id}")
        _require(bool(relocation.path), f"fleet relocation has empty path: {relocation_id}")
        commitment = tr.fleet_commitments.get(relocation.fleet_commitment_id)
        _require(commitment is not None, f"fleet relocation missing Fleet commitment: {relocation_id}")
        if commitment is not None:
            _require(commitment.owner_activity_ref == FleetActivityRef("fleet_relocation", relocation_id), f"fleet relocation commitment owner mismatch: {relocation_id}")
            _require(commitment.vehicle_definition_id == relocation.vehicle_definition_id, f"fleet relocation commitment vehicle mismatch: {relocation_id}")
            _require(commitment.quantity == relocation.requested_units, f"fleet relocation commitment quantity mismatch: {relocation_id}")
            if relocation.movement_execution_id is None:
                _require(commitment.operational_node_id == relocation.source_id, f"pending fleet relocation commitment source mismatch: {relocation_id}")
                _require(commitment.movement_execution_id is None, f"pending fleet relocation commitment is moving: {relocation_id}")
            else:
                _require(commitment.movement_execution_id == relocation.movement_execution_id, f"moving fleet relocation commitment execution mismatch: {relocation_id}")
        if relocation.movement_execution_id is not None:
            execution = tr.movement_executions.get(relocation.movement_execution_id)
            _require(execution is not None, f"fleet relocation missing MovementExecution: {relocation_id}")
            if execution is not None:
                _require(execution.owner_id == relocation.id, f"fleet relocation MovementExecution owner mismatch: {relocation_id}")
                _require(execution.kind is MovementExecutionKind.FLEET_RELOCATION, f"fleet relocation MovementExecution kind mismatch: {relocation_id}")
                _require(execution.fleet_commitment_id == relocation.fleet_commitment_id, f"fleet relocation MovementExecution commitment mismatch: {relocation_id}")
                _require(execution.origin.operational_node_id == relocation.source_id, f"fleet relocation MovementExecution origin mismatch: {relocation_id}")
                _require(execution.destination.operational_node_id == relocation.destination_id, f"fleet relocation MovementExecution destination mismatch: {relocation_id}")

    known_execution_owners: set[tuple[MovementExecutionKind, EntityId]] = set()
    for execution_id, execution in tr.movement_executions.items():
        _require(execution_id == execution.id, f"movement execution key mismatch: {execution_id}")
        commitment = tr.fleet_commitments.get(execution.fleet_commitment_id)
        _require(commitment is not None, f"movement execution references missing Fleet commitment: {execution_id}")
        if commitment is not None:
            _require(commitment.movement_execution_id == execution_id, f"movement execution is not owned by its Fleet commitment: {execution_id}")
            _require(commitment.vehicle_definition_id in tr.vehicle_defs, f"movement Fleet commitment references unknown vehicle definition: {execution_id}")
        _require(execution.started_day < execution.completion_day, f"movement execution has invalid timing: {execution_id}")
        _require(bool(execution.legs), f"movement execution has no legs: {execution_id}")
        _require(execution.latency_days == execution.completion_day - execution.started_day, f"movement execution latency mismatch: {execution_id}")
        owner_key = (execution.kind, execution.owner_id)
        _require(owner_key not in known_execution_owners, f"duplicate active movement execution owner: {execution.kind.value}/{execution.owner_id}")
        known_execution_owners.add(owner_key)
        for leg in execution.legs:
            _require(bool(leg.operations), f"movement execution leg has no operations: {execution_id}")
            _require(leg.latency_days > 0, f"movement execution leg has invalid latency: {execution_id}")
            _require(leg.payload_capacity_t + 1e-9 >= execution.payload_t_per_unit, f"movement execution payload exceeds frozen leg capacity: {execution_id}")

    for release_id, release in tr.fleet_releases.items():
        _require(release_id == release.id, f"fleet release key mismatch: {release_id}")
        commitment = tr.fleet_commitments.get(release.fleet_commitment_id)
        _require(commitment is not None, f"fleet release missing Fleet commitment: {release_id}")
        if commitment is not None:
            _require(commitment.owner_activity_ref == FleetActivityRef("fleet_release", release_id), f"fleet release commitment owner mismatch: {release_id}")
            _require(commitment.operational_node_id is not None, f"fleet release commitment must remain node-local: {release_id}")
            _require(commitment.movement_execution_id is None, f"fleet release commitment unexpectedly moving: {release_id}")

    for retirement_id, state in tr.fleet_retirements.items():
        _require(retirement_id == state.id, f"fleet retirement state key mismatch: {retirement_id}")
        _require(state.vehicle_definition_id in tr.vehicle_defs, f"fleet retirement references unknown vehicle definition: {retirement_id}")
        _require(sim.graph.has_operational_node(state.operational_node_id), f"fleet retirement references unknown location: {retirement_id}")
        _require(state.requested_units > 0, f"fleet retirement has non-positive requested units: {retirement_id}")
        definition = tr.vehicle_defs[state.vehicle_definition_id]
        total_work = definition.retirement.work_days_per_unit * state.requested_units
        _require(state.progress_work >= -1e-9 and state.progress_work <= total_work + 1e-9, f"fleet retirement progress outside work requirement: {retirement_id}")
        commitment = tr.fleet_commitments.get(state.fleet_commitment_id)
        if state.phase in {FleetRetirementPhase.COMMITTED, FleetRetirementPhase.DISMANTLING}:
            _require(commitment is not None, f"active fleet retirement missing Fleet commitment: {retirement_id}")
            if commitment is not None:
                _require(commitment.owner_activity_ref == FleetActivityRef("fleet_retirement", retirement_id), f"fleet retirement commitment owner mismatch: {retirement_id}")
                _require(commitment.vehicle_definition_id == state.vehicle_definition_id, f"fleet retirement commitment vehicle mismatch: {retirement_id}")
                _require(commitment.operational_node_id == state.operational_node_id, f"fleet retirement commitment location mismatch: {retirement_id}")
                _require(commitment.quantity == state.requested_units, f"fleet retirement commitment quantity mismatch: {retirement_id}")
        else:
            _require(commitment is None, f"inactive fleet retirement retains Fleet commitment: {retirement_id}")
        if state.irreversible_started:
            _require(state.phase is not FleetRetirementPhase.COMMITTED, f"irreversible fleet retirement remains committed: {retirement_id}")
        if state.phase is FleetRetirementPhase.DISMANTLING:
            _require(state.irreversible_started, f"dismantling retirement is reversible: {retirement_id}")
        if state.phase is FleetRetirementPhase.COMPLETE:
            _require(
                state.salvage_recovered_fraction is not None
                and -1e-9 <= state.salvage_recovered_fraction <= 1.0 + 1e-9,
                f"completed fleet retirement missing valid salvage fraction: {retirement_id}",
            )
        elif state.phase is FleetRetirementPhase.CANCELLED:
            _require(
                state.salvage_recovered_fraction is None,
                f"cancelled fleet retirement has salvage result: {retirement_id}",
            )

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
                _require(staged >= -1e-9 and staged <= required_t + 1e-9, f"vehicle production staged material outside requirement: {project_id}/{resource_id}")
            else:
                _require(staged <= 1e-9, f"started vehicle production retains staged input: {project_id}/{resource_id}")
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
