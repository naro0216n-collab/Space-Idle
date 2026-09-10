from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .scientific_exploration import ScientificExplorationPhase, ScientificExplorationState
from .shared import DefinitionId, EntityId
from .transport.models import VehicleStatus
from .validation_support import ValidationContext, require as _require, validate_site_requirements


def capture_scientific_exploration(sim: Any) -> dict[str, Any]:
    service = sim.scientific_exploration
    return {
        "campaigns": [
            {
                "definition_id": str(state.definition_id),
                "phase": state.phase.value,
                "vehicle_id": None if state.vehicle_id is None else str(state.vehicle_id),
                "progress_days": state.progress_days,
                "research_points_awarded": state.research_points_awarded,
                "inputs_consumed": state.inputs_consumed,
                "paused": state.paused,
                "created_day": state.created_day,
            }
            for state in sorted(service.campaigns.values(), key=lambda row: str(row.definition_id))
        ]
    }


def restore_scientific_exploration(sim: Any, data: dict[str, Any]) -> None:
    service = sim.scientific_exploration
    service.campaigns = {
        DefinitionId(row["definition_id"]): ScientificExplorationState(
            DefinitionId(row["definition_id"]),
            ScientificExplorationPhase(row.get("phase", "awaiting_vehicle")),
            None if row.get("vehicle_id") is None else EntityId(row["vehicle_id"]),
            float(row.get("progress_days", 0.0)),
            float(row.get("research_points_awarded", 0.0)),
            bool(row.get("inputs_consumed", False)),
            bool(row.get("paused", False)),
            int(row.get("created_day", 0)),
        )
        for row in data.get("campaigns", [])
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return {
        resource_id
        for definition in sim.scientific_exploration.definitions.values()
        for resource_id, _amount in definition.consumable_resources
    }


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    capabilities = ctx.known_capabilities
    nodes = ctx.nodes
    for definition_id, definition in sim.scientific_exploration.definitions.items():
        _require(definition_id == definition.id, f"scientific exploration key mismatch: {definition_id}")
        _require(definition.origin_id in nodes and definition.destination_id in nodes, f"scientific exploration references unknown endpoint: {definition_id}")
        _require(definition.mission_duration_days > 0, f"scientific exploration has non-positive mission duration: {definition_id}")
        _require(definition.duration_days > 0, f"scientific exploration has non-positive campaign duration: {definition_id}")
        _require(definition.research_points_total > 0, f"scientific exploration has non-positive RP reward: {definition_id}")
        _require(all(amount >= 0 for _resource, amount in definition.consumable_resources), f"scientific exploration has negative consumable: {definition_id}")
        consumable_ids = [resource_id for resource_id, _amount in definition.consumable_resources]
        _require(
            len(consumable_ids) == len(set(consumable_ids)),
            f"scientific exploration has duplicate consumable resource: {definition_id}",
        )
        for operation in definition.operations:
            _require(sim.logistics.operation_registry.supports(operation.operation_type), f"scientific exploration references unknown operation: {definition_id}/{operation.operation_type}")
        validate_site_requirements(definition.origin_requirements, capabilities, f"scientific_exploration:{definition_id}:origin")
        validate_site_requirements(definition.destination_requirements, capabilities, f"scientific_exploration:{definition_id}:destination")


def validate_runtime(sim: Any) -> None:
    service = sim.scientific_exploration
    assigned: set[EntityId] = set()
    for definition_id, state in service.campaigns.items():
        _require(definition_id in service.definitions, f"scientific exploration state references unknown definition: {definition_id}")
        definition = service.definitions[definition_id]
        _require(-1e-9 <= state.progress_days <= definition.duration_days + 1e-8, f"invalid scientific exploration progress: {definition_id}")
        _require(-1e-9 <= state.research_points_awarded <= definition.research_points_total + 1e-8, f"invalid scientific exploration RP award: {definition_id}")
        if state.vehicle_id is not None:
            _require(state.vehicle_id in sim.logistics.vehicles, f"scientific exploration references unknown vehicle: {definition_id}")
            _require(state.vehicle_id not in assigned, f"vehicle assigned to multiple scientific explorations: {state.vehicle_id}")
            assigned.add(state.vehicle_id)
            vehicle = sim.logistics.vehicles[state.vehicle_id]
            if state.phase is ScientificExplorationPhase.COMPLETE:
                _require(vehicle.status is not VehicleStatus.ASSIGNED, f"completed exploration retains vehicle assignment: {definition_id}")
            else:
                _require(vehicle.status is VehicleStatus.ASSIGNED, f"assigned exploration vehicle has wrong status: {definition_id}/{state.vehicle_id}")
                _require(vehicle.assignment_id == EntityId(f"scientific_exploration:{definition_id}"), f"vehicle exploration assignment mismatch: {definition_id}/{state.vehicle_id}")
                _require(vehicle.assignment_kind == "scientific_exploration", f"vehicle exploration assignment kind mismatch: {definition_id}/{state.vehicle_id}")
        if state.phase is ScientificExplorationPhase.COMPLETE:
            _require(state.progress_days + 1e-8 >= definition.duration_days, f"completed exploration lacks duration: {definition_id}")
            _require(state.research_points_awarded + 1e-8 >= definition.research_points_total, f"completed exploration lacks RP reward: {definition_id}")


STATE_CODEC = StateCodec("scientific_exploration", capture_scientific_exploration, restore_scientific_exploration)
DOMAIN_EXTENSION = DomainExtension(
    "scientific_exploration",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
