from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .founding import FoundingProjectStatus, LocationFoundingProject
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .transport.models import FleetReservationKind
from .validation_support import ValidationContext, require as _require, validate_site_requirements


def capture_founding(sim: Any) -> dict[str, Any]:
    service = sim.founding
    if service is None:
        return {"counter": 0, "projects": []}
    return {
        "counter": service._counter,
        "projects": [
            {
                "id": str(project.id),
                "package_id": str(project.package_id),
                "staging_location_id": str(project.staging_location_id),
                "target_cell_id": str(project.target_cell_id),
                "new_location_id": str(project.new_location_id),
                "display_name": project.display_name,
                "vehicle_definition_id": str(project.vehicle_definition_id),
                "priority": project.priority,
                "status": project.status.value,
                "preparation_done": project.preparation_done,
                "progress_days": project.progress_days,
                "inputs_consumed": project.inputs_consumed,
                "paused": project.paused,
                "created_day": project.created_day,
                "completed_facility_ids": [str(row) for row in project.completed_facility_ids],
            }
            for project in sorted(service.projects.values(), key=lambda row: str(row.id))
        ],
    }


def restore_founding(sim: Any, data: dict[str, Any]) -> None:
    service = sim.founding
    if service is None:
        return
    service._counter = int(data.get("counter", 0))
    service.projects = {
        EntityId(row["id"]): LocationFoundingProject(
            id=EntityId(row["id"]),
            package_id=DefinitionId(row["package_id"]),
            staging_location_id=SpatialNodeId(row["staging_location_id"]),
            target_cell_id=SurfaceCellId(row["target_cell_id"]),
            new_location_id=SpatialNodeId(row["new_location_id"]),
            display_name=str(row["display_name"]),
            vehicle_definition_id=DefinitionId(row["vehicle_definition_id"]),
            priority=int(row.get("priority", 50)),
            status=FoundingProjectStatus(row["status"]),
            preparation_done=float(row.get("preparation_done", 0.0)),
            progress_days=float(row.get("progress_days", 0.0)),
            inputs_consumed=bool(row.get("inputs_consumed", False)),
            paused=bool(row.get("paused", False)),
            created_day=int(row.get("created_day", 0)),
            completed_facility_ids=tuple(EntityId(value) for value in row.get("completed_facility_ids", [])),
        )
        for row in data.get("projects", [])
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    service = sim.founding
    if service is None:
        return set()
    rows: set[DefinitionId] = set()
    for package in service.definitions.values():
        rows.update(resource_id for resource_id, _amount in package.resource_requirements)
    for vehicle in sim.logistics.vehicle_defs.values():
        if vehicle.propellant_resource_id is not None:
            rows.add(vehicle.propellant_resource_id)
    return rows


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    service = sim.founding
    if service is None:
        return
    _require(service.graph is sim.graph, "founding service must use simulation spatial graph")
    for package_id, package in service.definitions.items():
        _require(package_id == package.id, f"founding package key mismatch: {package_id}")
        _require(package.transit_days > 0, f"founding package has non-positive transit: {package_id}")
        _require(package.preparation_work >= 0, f"founding package has negative preparation work: {package_id}")
        _require(package.required_units > 0, f"founding package has non-positive Fleet units: {package_id}")
        _require(0 <= package.minimum_survey_knowledge_level <= 4, f"founding package invalid survey level: {package_id}")
        _require(not package.target_requirements.capability_requirements, f"founding target requires pre-existing capability: {package_id}")
        validate_site_requirements(package.staging_requirements, ctx.known_capabilities, f"founding:{package_id}:staging")
        validate_site_requirements(package.target_requirements, ctx.known_capabilities, f"founding:{package_id}:target")
        for operation in package.operations:
            _require(sim.logistics.operation_registry.supports(operation.operation_type), f"founding package references unknown operation: {package_id}/{operation.operation_type}")
        for deployment in package.facilities:
            _require(deployment.facility_definition_id in ctx.facility_defs, f"founding package references unknown facility: {package_id}/{deployment.facility_definition_id}")
            if deployment.facility_definition_id in ctx.facility_defs:
                scope = sim.facilities.definitions[deployment.facility_definition_id].placement_scope
                if str(scope.value) == "surface_cell":
                    _require(deployment.place_at_core_cell, f"founding surface facility lacks core-cell placement: {package_id}/{deployment.facility_definition_id}")
                else:
                    _require(not deployment.place_at_core_cell, f"founding location facility incorrectly requests a cell: {package_id}/{deployment.facility_definition_id}")


def validate_runtime(sim: Any) -> None:
    service = sim.founding
    if service is None:
        return
    active_cells: set[SurfaceCellId] = set()
    for project_id, project in service.projects.items():
        _require(project.package_id in service.definitions, f"founding project references unknown package: {project_id}")
        _require(project.staging_location_id in sim.graph.operational_node_ids(), f"founding project references unknown staging node: {project_id}")
        _require(project.target_cell_id in sim.graph.surface_cells, f"founding project references unknown target cell: {project_id}")
        _require(project.vehicle_definition_id in sim.logistics.vehicle_defs, f"founding project references unknown vehicle: {project_id}")
        package = service.definitions.get(project.package_id)
        if package is None:
            continue
        _require(0 <= project.priority <= 100, f"founding project invalid priority: {project_id}")
        _require(-1e-9 <= project.preparation_done <= package.preparation_work + 1e-8, f"founding project invalid preparation progress: {project_id}")
        _require(-1e-9 <= project.progress_days <= package.transit_days + 1e-8, f"founding project invalid progress: {project_id}")
        if project.status not in {FoundingProjectStatus.COMPLETE, FoundingProjectStatus.CANCELLED}:
            _require(project.target_cell_id not in active_cells, f"duplicate active founding target: {project.target_cell_id}")
            active_cells.add(project.target_cell_id)
        reservation = sim.logistics.fleet_reservation_snapshot(service._reservation_id(project_id))
        if project.status in {FoundingProjectStatus.PREPARING, FoundingProjectStatus.DEPLOYING}:
            _require(reservation is not None, f"active founding project lacks Fleet reservation: {project_id}")
            if reservation is not None:
                _require(reservation.kind is FleetReservationKind.SPECIAL_MISSION, f"founding reservation kind mismatch: {project_id}")
                _require(reservation.vehicle_definition_id == project.vehicle_definition_id, f"founding reservation vehicle mismatch: {project_id}")
                _require(reservation.location_id == project.staging_location_id, f"founding reservation staging mismatch: {project_id}")
                _require(reservation.units == package.required_units, f"founding reservation unit mismatch: {project_id}")
        else:
            _require(reservation is None, f"closed founding project retains Fleet reservation: {project_id}")
        if project.status is FoundingProjectStatus.COMPLETE:
            _require(project.inputs_consumed, f"completed founding project did not consume inputs: {project_id}")
            _require(project.new_location_id in sim.graph.locations, f"completed founding project lacks Location: {project_id}")
            _require(len(project.completed_facility_ids) == len(package.facilities), f"completed founding package facility count mismatch: {project_id}")
            for facility_id in project.completed_facility_ids:
                _require(facility_id in sim.facilities.facilities, f"founding project references missing completed facility: {project_id}/{facility_id}")
        else:
            _require(project.new_location_id not in sim.graph.locations, f"incomplete founding project already created Location: {project_id}")


STATE_CODEC = StateCodec("founding", capture_founding, restore_founding)
DOMAIN_EXTENSION = DomainExtension(
    "founding",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
