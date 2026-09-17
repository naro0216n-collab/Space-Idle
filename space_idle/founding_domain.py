from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .founding import FoundingStatus, LocationFoundingProject
from .shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from .transport.models import FleetActivityRef, MovementExecutionKind
from .validation_support import ValidationContext, require as _require, validate_site_requirements


def capture_founding(sim: Any) -> dict[str, Any]:
    service = sim.founding
    if service is None:
        return {"counter": 0, "projects": []}
    return {
        "counter": service._counter,
        "projects": [
            {
                "id": str(p.id),
                "staging_node_id": str(p.staging_node_id),
                "display_name": p.display_name,
                "target_body_id": str(p.target_body_id),
                "target_core_cell_id": str(p.target_core_cell_id),
                "new_location_id": str(p.new_location_id),
                "founding_package_id": str(p.founding_package_id),
                "vehicle_definition_id": str(p.vehicle_definition_id),
                "priority": p.priority,
                "fleet_commitment_id": None if p.fleet_commitment_id is None else str(p.fleet_commitment_id),
                "status": p.status.value,
                "preparation_done": p.preparation_done,
                "inputs_consumed": p.inputs_consumed,
                "paused": p.paused,
                "movement_execution_id": None if p.movement_execution_id is None else str(p.movement_execution_id),
                "completed_day": p.completed_day,
            }
            for p in sorted(service.projects.values(), key=lambda row: str(row.id))
        ],
    }


def restore_founding(sim: Any, data: dict[str, Any]) -> None:
    service = sim.founding
    if service is None:
        return
    service._counter = int(data.get("counter", 0))
    service.projects = {}
    for row in data.get("projects", []):
        p = LocationFoundingProject(
            id=ProjectId(row["id"]),
            staging_node_id=SpatialNodeId(row["staging_node_id"]),
            display_name=str(row["display_name"]),
            target_body_id=CelestialBodyId(row["target_body_id"]),
            target_core_cell_id=SurfaceCellId(row["target_core_cell_id"]),
            new_location_id=SpatialNodeId(row["new_location_id"]),
            founding_package_id=DefinitionId(row["founding_package_id"]),
            vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            priority=row["priority"],
            fleet_commitment_id=None if row.get("fleet_commitment_id") is None else EntityId(row["fleet_commitment_id"]),
            status=FoundingStatus(row.get("status", FoundingStatus.PREPARING.value)),
            preparation_done=float(row.get("preparation_done", 0.0)),
            inputs_consumed=bool(row.get("inputs_consumed", False)),
            paused=bool(row.get("paused", False)),
            movement_execution_id=None if row.get("movement_execution_id") is None else EntityId(row["movement_execution_id"]),
            completed_day=None if row.get("completed_day") is None else int(row["completed_day"]),
        )
        service.projects[p.id] = p


def referenced_resources(sim: Any) -> set[DefinitionId]:
    if sim.founding is None:
        return set()
    return {req.resource_id for package in sim.founding.packages.values() for req in package.payload_resources}


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    service = sim.founding
    if service is None:
        return
    for package_id, package in service.packages.items():
        _require(package_id == package.id, f"founding package key mismatch: {package_id}")
        _require(package.required_units > 0, f"founding package has invalid fleet units: {package_id}")
        validate_site_requirements(package.staging_requirements, ctx.known_capabilities, f"founding:{package_id}:staging")
        validate_site_requirements(package.target_requirements, ctx.known_capabilities, f"founding:{package_id}:target")
        _require(
            not package.target_requirements.capability_requirements,
            f"founding target requirements cannot depend on pre-location capabilities: {package_id}",
        )
        for deployment in package.deployed_facilities:
            _require(deployment.facility_def_id in ctx.facility_defs, f"founding package references unknown facility: {package_id}/{deployment.facility_def_id}")


def validate_runtime(sim: Any) -> None:
    service = sim.founding
    if service is None:
        return
    active_cells: set[SurfaceCellId] = set()
    active_locations: set[SpatialNodeId] = set()
    for project_id, p in service.projects.items():
        _require(project_id == p.id, f"founding project key mismatch: {project_id}")
        _require(p.founding_package_id in service.packages, f"founding project package missing: {project_id}")
        _require(sim.transport.vehicle_definition(p.vehicle_definition_id) is not None, f"founding project vehicle missing: {project_id}")
        _require(p.target_core_cell_id in sim.graph.surface_cells, f"founding target cell missing: {project_id}")
        if p.target_core_cell_id in sim.graph.surface_cells:
            _require(sim.graph.surface_cells[p.target_core_cell_id].body_id == p.target_body_id, f"founding target body mismatch: {project_id}")
        package = service.packages.get(p.founding_package_id)
        if package is not None:
            _require(-1e-9 <= p.preparation_done <= package.preparation_work + 1e-9, f"founding preparation out of range: {project_id}")
        payload_owner_id = service.payload_owner_id(project_id)
        if package is not None:
            required = service.project_resource_requirements(project_id)
            fully_staged = True
            for requirement in required:
                resource_id = requirement.resource_id
                amount = requirement.amount_t
                staged = sim.inventory.staged_for(
                    payload_owner_id, p.staging_node_id, resource_id
                )
                if p.status is FoundingStatus.PREPARING:
                    _require(
                        -1e-9 <= staged <= amount + 1e-9,
                        f"founding payload commitment out of range: {project_id}/{resource_id}",
                    )
                    if staged + 1e-9 < amount:
                        fully_staged = False
                else:
                    _require(
                        staged <= 1e-9,
                        f"inactive founding retains prepared payload: {project_id}/{resource_id}",
                    )
            if p.status is FoundingStatus.PREPARING:
                _require(
                    p.inputs_consumed == fully_staged,
                    f"founding payload completion flag mismatch: {project_id}",
                )
        active = p.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}
        commitment = None if p.fleet_commitment_id is None else sim.transport.fleet_commitment_snapshot(p.fleet_commitment_id)
        if active:
            _require(p.target_core_cell_id not in active_cells, f"duplicate active founding cell: {p.target_core_cell_id}")
            _require(p.new_location_id not in active_locations, f"duplicate active founding location id: {p.new_location_id}")
            active_cells.add(p.target_core_cell_id)
            active_locations.add(p.new_location_id)
            _require(p.new_location_id not in sim.graph.locations, f"active founding location already exists: {project_id}")
        if p.status is FoundingStatus.PREPARING:
            _require(commitment is not None, f"preparing founding missing Fleet commitment: {project_id}")
            if commitment is not None and package is not None:
                _require(commitment.owner_activity_ref == FleetActivityRef("founding", EntityId(str(project_id))), f"founding Fleet commitment owner mismatch: {project_id}")
                _require(commitment.vehicle_definition_id == p.vehicle_definition_id, f"founding Fleet commitment vehicle mismatch: {project_id}")
                _require(commitment.operational_node_id == p.staging_node_id, f"founding Fleet commitment staging mismatch: {project_id}")
                _require(commitment.quantity == package.required_units, f"founding Fleet commitment units mismatch: {project_id}")
                _require(commitment.movement_execution_id is None, f"preparing founding Fleet commitment is moving: {project_id}")
        elif p.status is FoundingStatus.DEPLOYING:
            _require(commitment is not None, f"deploying founding missing Fleet commitment: {project_id}")
            if commitment is not None and package is not None:
                _require(commitment.owner_activity_ref == FleetActivityRef("founding", EntityId(str(project_id))), f"founding Fleet commitment owner mismatch: {project_id}")
                _require(commitment.vehicle_definition_id == p.vehicle_definition_id, f"founding Fleet commitment vehicle mismatch: {project_id}")
                _require(commitment.quantity == package.required_units, f"founding Fleet commitment units mismatch: {project_id}")
                _require(commitment.movement_execution_id == p.movement_execution_id, f"founding Fleet commitment movement mismatch: {project_id}")
        else:
            _require(p.fleet_commitment_id is None, f"inactive founding retains Fleet commitment reference: {project_id}")
            _require(commitment is None, f"inactive founding retains Fleet commitment: {project_id}")
        if p.status is FoundingStatus.PREPARING:
            _require(p.movement_execution_id is None, f"preparing founding has MovementExecution: {project_id}")
        elif p.status is FoundingStatus.DEPLOYING:
            _require(p.movement_execution_id is not None, f"deploying founding lacks MovementExecution: {project_id}")
            _require(not p.paused, f"deploying founding cannot be paused: {project_id}")
            if p.movement_execution_id is not None:
                execution = sim.transport.movement_execution_snapshot(p.movement_execution_id)
                _require(execution is not None, f"deploying founding MovementExecution missing: {project_id}")
                if execution is not None:
                    _require(execution.kind is MovementExecutionKind.FOUNDING_DEPLOYMENT, f"founding MovementExecution kind mismatch: {project_id}")
                    _require(execution.owner_id == EntityId(str(project_id)), f"founding MovementExecution owner mismatch: {project_id}")
                    _require(execution.fleet_commitment_id == p.fleet_commitment_id, f"founding MovementExecution Fleet commitment mismatch: {project_id}")
                    _require(execution.origin.operational_node_id == p.staging_node_id, f"founding MovementExecution origin mismatch: {project_id}")
                    _require(execution.destination.physical_target_cell_id == p.target_core_cell_id, f"founding MovementExecution target mismatch: {project_id}")
                    if package is not None:
                        _require(abs(execution.payload_t_per_unit - package.payload_t_per_unit) <= 1e-9, f"founding MovementExecution payload mismatch: {project_id}")
                        expected_payload = {
                            req.resource_id: req.amount_t for req in package.payload_resources
                        }
                        actual_payload = {
                            req.resource_id: req.amount_t for req in execution.payload_resources
                        }
                        _require(actual_payload.keys() == expected_payload.keys(), f"founding MovementExecution payload resources mismatch: {project_id}")
                        for resource_id, amount_t in expected_payload.items():
                            _require(abs(actual_payload[resource_id] - amount_t) <= 1e-9, f"founding MovementExecution payload amount mismatch: {project_id}/{resource_id}")
        elif p.status is FoundingStatus.COMPLETE:
            _require(p.movement_execution_id is None, f"completed founding retains MovementExecution: {project_id}")
            _require(p.new_location_id in sim.graph.locations, f"completed founding location missing: {project_id}")
            if p.new_location_id in sim.graph.locations:
                loc = sim.graph.locations[p.new_location_id]
                _require(loc.body_id == p.target_body_id and loc.core_cell_id == p.target_core_cell_id, f"completed founding location mismatch: {project_id}")
            _require(p.completed_day is not None, f"completed founding lacks completion day: {project_id}")


STATE_CODEC = StateCodec("founding", capture_founding, restore_founding, True)
DOMAIN_EXTENSION = DomainExtension(
    "founding",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
