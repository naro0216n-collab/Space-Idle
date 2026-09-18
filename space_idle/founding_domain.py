from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .founding import (
    FoundingResourceRequirement,
    FoundingStatus,
    NonSurfaceOperationalNodeTargetSpec,
    OperationalNodeFoundingProject,
    SurfaceLocationTargetSpec,
)
from .shared import DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId, CelestialBodyId
from .transport.models import FleetActivityRef, MovementExecutionKind
from .validation_support import ValidationContext, require as _require, validate_site_requirements


def _capture_target_spec(target_spec) -> dict[str, Any]:
    if isinstance(target_spec, SurfaceLocationTargetSpec):
        return {
            "type": "surface_location",
            "body_id": str(target_spec.body_id),
            "core_cell_id": str(target_spec.core_cell_id),
            "operational_node_id": str(target_spec.operational_node_id),
        }
    return {
        "type": "non_surface_operational_node",
        "spatial_node_id": str(target_spec.spatial_node_id),
    }


def _restore_target_spec(row: dict[str, Any]):
    target_type = row["type"]
    if target_type == "surface_location":
        return SurfaceLocationTargetSpec(
            CelestialBodyId(row["body_id"]),
            SurfaceCellId(row["core_cell_id"]),
            SpatialNodeId(row["operational_node_id"]),
        )
    if target_type == "non_surface_operational_node":
        return NonSurfaceOperationalNodeTargetSpec(SpatialNodeId(row["spatial_node_id"]))
    raise ValueError(f"unknown founding target type: {target_type}")


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
                "target_spec": _capture_target_spec(p.target_spec),
                "deployment_recipe_id": str(p.deployment_recipe_id),
                "vehicle_definition_id": str(p.vehicle_definition_id),
                "resource_requirements": [
                    {"resource_id": str(req.resource_id), "amount_t": req.amount_t}
                    for req in p.resource_requirements
                ],
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
    service._counter = int(data["counter"])
    service.projects = {}
    for row in data["projects"]:
        p = OperationalNodeFoundingProject(
            id=ProjectId(row["id"]),
            staging_node_id=SpatialNodeId(row["staging_node_id"]),
            display_name=str(row["display_name"]),
            target_spec=_restore_target_spec(row["target_spec"]),
            deployment_recipe_id=DefinitionId(row["deployment_recipe_id"]),
            vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            resource_requirements=tuple(
                FoundingResourceRequirement(DefinitionId(req["resource_id"]), float(req["amount_t"]))
                for req in row["resource_requirements"]
            ),
            priority=row["priority"],
            fleet_commitment_id=None if row["fleet_commitment_id"] is None else EntityId(row["fleet_commitment_id"]),
            status=FoundingStatus(row["status"]),
            preparation_done=float(row["preparation_done"]),
            inputs_consumed=bool(row["inputs_consumed"]),
            paused=bool(row["paused"]),
            movement_execution_id=None if row["movement_execution_id"] is None else EntityId(row["movement_execution_id"]),
            completed_day=None if row["completed_day"] is None else int(row["completed_day"]),
        )
        service.projects[p.id] = p


def referenced_resources(sim: Any) -> set[DefinitionId]:
    if sim.founding is None:
        return set()
    resources = {
        req.resource_id
        for recipe in sim.founding.deployment_recipes.values()
        for req in recipe.payload_resources
    }
    resources.update(
        requirement.subject_resource_id
        for recipe in sim.founding.deployment_recipes.values()
        for requirement in recipe.knowledge_requirements
    )
    return resources


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    service = sim.founding
    if service is None:
        return
    for recipe_id, recipe in service.deployment_recipes.items():
        _require(recipe_id == recipe.id, f"deployment recipe key mismatch: {recipe_id}")
        _require(recipe.required_units > 0, f"deployment recipe has invalid fleet units: {recipe_id}")
        validate_site_requirements(recipe.staging_requirements, ctx.known_capabilities, f"founding:{recipe_id}:staging")
        validate_site_requirements(recipe.target_requirements, ctx.known_capabilities, f"founding:{recipe_id}:target")
        _require(
            not recipe.target_requirements.capability_requirements,
            f"founding target requirements cannot depend on pre-node capabilities: {recipe_id}",
        )
        for deployment in recipe.deployed_facilities:
            _require(
                deployment.facility_def_id in ctx.facility_defs,
                f"deployment recipe references unknown facility: {recipe_id}/{deployment.facility_def_id}",
            )


def validate_runtime(sim: Any) -> None:
    service = sim.founding
    if service is None:
        return
    active_cells: set[SurfaceCellId] = set()
    active_target_nodes: set[SpatialNodeId] = set()
    for project_id, p in service.projects.items():
        _require(project_id == p.id, f"founding project key mismatch: {project_id}")
        _require(p.deployment_recipe_id in service.deployment_recipes, f"founding deployment recipe missing: {project_id}")
        _require(sim.transport.vehicle_definition(p.vehicle_definition_id) is not None, f"founding project vehicle missing: {project_id}")
        recipe = service.deployment_recipes.get(p.deployment_recipe_id)
        if recipe is not None:
            _require(-1e-9 <= p.preparation_done <= recipe.preparation_work + 1e-9, f"founding preparation out of range: {project_id}")
            _require(bool(p.resource_requirements), f"founding project lacks planned Resource requirements: {project_id}")
            _require(
                len({req.resource_id for req in p.resource_requirements}) == len(p.resource_requirements),
                f"founding project has duplicate planned Resource requirements: {project_id}",
            )

        target_node_id = service.target_operational_node_id(p.target_spec)
        active = p.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}
        if isinstance(p.target_spec, SurfaceLocationTargetSpec):
            target = p.target_spec
            _require(target.core_cell_id in sim.graph.surface_cells, f"founding target cell missing: {project_id}")
            if target.core_cell_id in sim.graph.surface_cells:
                _require(sim.graph.surface_cells[target.core_cell_id].body_id == target.body_id, f"founding target body mismatch: {project_id}")
            if active:
                _require(target.core_cell_id not in active_cells, f"duplicate active founding cell: {target.core_cell_id}")
                active_cells.add(target.core_cell_id)
                _require(target.operational_node_id not in sim.graph.locations, f"active founding location already exists: {project_id}")
        else:
            target = p.target_spec
            _require(target.spatial_node_id in sim.graph.nodes, f"founding non-surface target missing: {project_id}")
            if active:
                _require(not sim.graph.has_operational_node(target.spatial_node_id), f"active non-surface founding target already operational: {project_id}")

        if active:
            _require(target_node_id not in active_target_nodes, f"duplicate active founding target node: {target_node_id}")
            active_target_nodes.add(target_node_id)

        payload_owner_id = service.payload_owner_id(project_id)
        if recipe is not None:
            required = service.project_resource_requirements(project_id)
            fully_staged = True
            for requirement in required:
                staged = sim.inventory.staged_for(
                    payload_owner_id, p.staging_node_id, requirement.resource_id
                )
                if p.status is FoundingStatus.PREPARING:
                    _require(
                        -1e-9 <= staged <= requirement.amount_t + 1e-9,
                        f"founding payload commitment out of range: {project_id}/{requirement.resource_id}",
                    )
                    if staged + 1e-9 < requirement.amount_t:
                        fully_staged = False
                else:
                    _require(staged <= 1e-9, f"inactive founding retains prepared payload: {project_id}/{requirement.resource_id}")
            if p.status is FoundingStatus.PREPARING:
                _require(p.inputs_consumed == fully_staged, f"founding payload completion flag mismatch: {project_id}")

        commitment = None if p.fleet_commitment_id is None else sim.transport.fleet_commitment_snapshot(p.fleet_commitment_id)
        if p.status in {FoundingStatus.PREPARING, FoundingStatus.DEPLOYING}:
            _require(commitment is not None, f"active founding missing Fleet commitment: {project_id}")
            if commitment is not None and recipe is not None:
                _require(commitment.owner_activity_ref == FleetActivityRef("founding", EntityId(str(project_id))), f"founding Fleet commitment owner mismatch: {project_id}")
                _require(commitment.vehicle_definition_id == p.vehicle_definition_id, f"founding Fleet commitment vehicle mismatch: {project_id}")
                _require(commitment.quantity == recipe.required_units, f"founding Fleet commitment units mismatch: {project_id}")
                if p.status is FoundingStatus.PREPARING:
                    _require(commitment.operational_node_id == p.staging_node_id, f"founding Fleet commitment staging mismatch: {project_id}")
                    _require(commitment.movement_execution_id is None, f"preparing founding Fleet commitment is moving: {project_id}")
                else:
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
                    if isinstance(p.target_spec, SurfaceLocationTargetSpec):
                        _require(execution.destination.physical_target_cell_id == p.target_spec.core_cell_id, f"founding MovementExecution target mismatch: {project_id}")
                    else:
                        _require(execution.destination.physical_target_node_id == p.target_spec.spatial_node_id, f"founding MovementExecution target mismatch: {project_id}")
                    if recipe is not None:
                        _require(abs(execution.payload_t_per_unit - recipe.payload_t_per_unit) <= 1e-9, f"founding MovementExecution payload mismatch: {project_id}")
                        expected_payload = {req.resource_id: req.amount_t for req in recipe.payload_resources}
                        actual_payload = {req.resource_id: req.amount_t for req in execution.payload_resources}
                        _require(actual_payload.keys() == expected_payload.keys(), f"founding MovementExecution payload resources mismatch: {project_id}")
                        for resource_id, amount_t in expected_payload.items():
                            _require(abs(actual_payload[resource_id] - amount_t) <= 1e-9, f"founding MovementExecution payload amount mismatch: {project_id}/{resource_id}")
        elif p.status is FoundingStatus.COMPLETE:
            _require(p.movement_execution_id is None, f"completed founding retains MovementExecution: {project_id}")
            _require(sim.graph.has_operational_node(target_node_id), f"completed founding Operational Node missing: {project_id}")
            if isinstance(p.target_spec, SurfaceLocationTargetSpec):
                _require(target_node_id in sim.graph.locations, f"completed founding Surface Location missing: {project_id}")
                if target_node_id in sim.graph.locations:
                    loc = sim.graph.locations[target_node_id]
                    _require(loc.body_id == p.target_spec.body_id and loc.core_cell_id == p.target_spec.core_cell_id, f"completed founding Surface Location mismatch: {project_id}")
            _require(p.completed_day is not None, f"completed founding lacks completion day: {project_id}")


STATE_CODEC = StateCodec("founding", capture_founding, restore_founding, True)
DOMAIN_EXTENSION = DomainExtension(
    "founding",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
