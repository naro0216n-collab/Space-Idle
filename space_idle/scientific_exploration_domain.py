from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .scientific_exploration import (ScientificExplorationCompletionDisposition, ScientificExplorationPhase, ScientificExplorationState, ScientificExplorationTerminationIntent)
from .shared import DefinitionId, EntityId
from .transport.models import FleetActivityRef, MovementExecutionKind
from .validation_support import ValidationContext, require as _require, validate_site_requirements


def capture_scientific_exploration(sim: Any) -> dict[str, Any]:
    service = sim.scientific_exploration
    return {
        "campaigns": [
            {
                "definition_id": str(state.definition_id),
                "phase": state.phase.value,
                "vehicle_definition_id": None if state.vehicle_definition_id is None else str(state.vehicle_definition_id),
                "fleet_commitment_id": None if state.fleet_commitment_id is None else str(state.fleet_commitment_id),
                "progress_days": state.progress_days,
                "research_points_awarded": state.research_points_awarded,
                "inputs_consumed": state.inputs_consumed,
                "paused": state.paused,
                "created_day": state.created_day,
                "priority": int(state.priority),
                "movement_execution_id": (
                    None if state.movement_execution_id is None else str(state.movement_execution_id)
                ),
                "completion_disposition": state.completion_disposition.value,
                "termination_intent": None if state.termination_intent is None else state.termination_intent.value,
            }
            for state in sorted(service.campaigns.values(), key=lambda row: str(row.definition_id))
        ]
    }


def restore_scientific_exploration(sim: Any, data: dict[str, Any]) -> None:
    service = sim.scientific_exploration
    service.campaigns = {
        DefinitionId(row["definition_id"]): ScientificExplorationState(
            definition_id=DefinitionId(row["definition_id"]),
            phase=ScientificExplorationPhase(row["phase"]),
            vehicle_definition_id=(
                None if row["vehicle_definition_id"] is None
                else DefinitionId(row["vehicle_definition_id"])
            ),
            fleet_commitment_id=(
                None if row["fleet_commitment_id"] is None
                else EntityId(row["fleet_commitment_id"])
            ),
            progress_days=float(row["progress_days"]),
            research_points_awarded=float(row["research_points_awarded"]),
            inputs_consumed=bool(row["inputs_consumed"]),
            paused=bool(row["paused"]),
            created_day=int(row["created_day"]),
            priority=row["priority"],
            movement_execution_id=(
                None if row["movement_execution_id"] is None
                else EntityId(row["movement_execution_id"])
            ),
            completion_disposition=ScientificExplorationCompletionDisposition(
                row.get("completion_disposition",
                    "return_to_origin" if service.definitions[DefinitionId(row["definition_id"])].return_to_origin else "release_at_destination")
            ),
            termination_intent=(None if row.get("termination_intent") is None else ScientificExplorationTerminationIntent(row["termination_intent"])),
        )
        for row in data["campaigns"]
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return {
        resource_id
        for definition in sim.scientific_exploration.definitions.values()
        for resource_id, _amount in definition.consumable_resources
    }


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    capabilities = ctx.known_capabilities
    nodes = ctx.spatial_nodes
    for definition_id, definition in sim.scientific_exploration.definitions.items():
        _require(definition_id == definition.id, f"scientific exploration key mismatch: {definition_id}")
        _require(definition.origin_id in nodes and definition.destination_id in nodes, f"scientific exploration references unknown endpoint: {definition_id}")
        _require(definition.duration_days > 0, f"scientific exploration has non-positive campaign duration: {definition_id}")
        _require(definition.research_points_total > 0, f"scientific exploration has non-positive RP reward: {definition_id}")
        _require(definition.required_units > 0, f"scientific exploration has non-positive Fleet requirement: {definition_id}")
        _require(definition.minimum_payload_t >= 0, f"scientific exploration has negative minimum payload: {definition_id}")
        vehicle_capabilities = list(definition.required_vehicle_capabilities)
        _require(
            all(capability for capability in vehicle_capabilities),
            f"scientific exploration has empty vehicle capability requirement: {definition_id}",
        )
        _require(
            len(vehicle_capabilities) == len(set(vehicle_capabilities)),
            f"scientific exploration has duplicate vehicle capability requirement: {definition_id}",
        )
        _require(all(amount >= 0 for _resource, amount in definition.consumable_resources), f"scientific exploration has negative consumable: {definition_id}")
        consumable_ids = [resource_id for resource_id, _amount in definition.consumable_resources]
        _require(
            len(consumable_ids) == len(set(consumable_ids)),
            f"scientific exploration has duplicate consumable resource: {definition_id}",
        )
        validate_site_requirements(definition.origin_requirements, capabilities, f"scientific_exploration:{definition_id}:origin")
        validate_site_requirements(definition.destination_requirements, capabilities, f"scientific_exploration:{definition_id}:destination")


def validate_runtime(sim: Any) -> None:
    service = sim.scientific_exploration
    for definition_id, state in service.campaigns.items():
        _require(1 <= int(state.priority) <= 5, f"scientific exploration priority must be 1..5: {definition_id}")
        _require(definition_id in service.definitions, f"scientific exploration state references unknown definition: {definition_id}")
        definition = service.definitions[definition_id]
        _require(-1e-9 <= state.progress_days <= definition.duration_days + 1e-8, f"invalid scientific exploration progress: {definition_id}")
        _require(-1e-9 <= state.research_points_awarded <= definition.research_points_total + 1e-8, f"invalid scientific exploration RP award: {definition_id}")

        commitment = (
            None
            if state.fleet_commitment_id is None
            else sim.transport.fleet_commitment_snapshot(state.fleet_commitment_id)
        )
        if state.vehicle_definition_id is None:
            _require(state.phase in {ScientificExplorationPhase.AWAITING_FLEET, ScientificExplorationPhase.ABORTED}, f"unassigned scientific exploration has invalid phase: {definition_id}")
            _require(state.fleet_commitment_id is None, f"unassigned scientific exploration retains Fleet commitment reference: {definition_id}")
            _require(commitment is None, f"unassigned scientific exploration retains Fleet commitment: {definition_id}")
        elif state.phase in {ScientificExplorationPhase.COMPLETE, ScientificExplorationPhase.ABORTED}:
            _require(state.fleet_commitment_id is None, f"terminal scientific exploration retains Fleet commitment reference: {definition_id}")
            _require(commitment is None, f"terminal scientific exploration retains Fleet commitment: {definition_id}")
        else:
            _require(sim.transport.vehicle_definition(state.vehicle_definition_id) is not None, f"scientific exploration references unknown vehicle definition: {definition_id}")
            _require(commitment is not None, f"active scientific exploration lacks Fleet commitment: {definition_id}")
            if commitment is not None:
                _require(commitment.owner_activity_ref == FleetActivityRef("scientific_exploration", EntityId(str(definition_id))), f"scientific exploration Fleet commitment owner mismatch: {definition_id}")
                _require(commitment.vehicle_definition_id == state.vehicle_definition_id, f"scientific exploration Fleet commitment vehicle mismatch: {definition_id}")
                _require(commitment.quantity == definition.required_units, f"scientific exploration Fleet commitment unit mismatch: {definition_id}")
                stationary = state.phase in {
                    ScientificExplorationPhase.PREPARING,
                    ScientificExplorationPhase.ACTIVE,
                    ScientificExplorationPhase.RETURN_PREPARING,
                }
                if stationary:
                    expected_node = (
                        definition.origin_id
                        if state.phase is ScientificExplorationPhase.PREPARING
                        else definition.destination_id
                    )
                    _require(commitment.operational_node_id == expected_node, f"scientific exploration Fleet commitment location mismatch: {definition_id}")
                    _require(commitment.movement_execution_id is None, f"stationary scientific exploration Fleet commitment is moving: {definition_id}")
                else:
                    _require(commitment.operational_node_id is None, f"moving scientific exploration Fleet commitment remains node-local: {definition_id}")
                    _require(commitment.movement_execution_id == state.movement_execution_id, f"scientific exploration Fleet commitment movement mismatch: {definition_id}")

        if state.phase in {ScientificExplorationPhase.OUTBOUND, ScientificExplorationPhase.RETURNING}:
            _require(state.movement_execution_id is not None, f"moving scientific exploration lacks MovementExecution: {definition_id}")
            execution = (
                None if state.movement_execution_id is None
                else sim.transport.movement_execution_snapshot(state.movement_execution_id)
            )
            _require(execution is not None, f"scientific exploration MovementExecution missing: {definition_id}")
            if execution is not None:
                _require(execution.kind is MovementExecutionKind.SCIENTIFIC_EXPLORATION, f"scientific exploration MovementExecution kind mismatch: {definition_id}")
                _require(execution.owner_id == EntityId(str(definition_id)), f"scientific exploration MovementExecution owner mismatch: {definition_id}")
                _require(execution.fleet_commitment_id == state.fleet_commitment_id, f"scientific exploration MovementExecution Fleet commitment mismatch: {definition_id}")
                if state.phase is ScientificExplorationPhase.OUTBOUND:
                    _require(execution.origin.operational_node_id == definition.origin_id, f"scientific exploration outbound origin mismatch: {definition_id}")
                    _require(execution.destination.operational_node_id == definition.destination_id, f"scientific exploration outbound destination mismatch: {definition_id}")
                else:
                    _require(execution.origin.operational_node_id == definition.destination_id, f"scientific exploration return origin mismatch: {definition_id}")
                    _require(execution.destination.operational_node_id == definition.origin_id, f"scientific exploration return destination mismatch: {definition_id}")
        else:
            _require(state.movement_execution_id is None, f"stationary scientific exploration retains MovementExecution: {definition_id}")

        if state.phase is ScientificExplorationPhase.COMPLETE:
            _require(state.progress_days + 1e-8 >= definition.duration_days, f"completed exploration lacks duration: {definition_id}")
            _require(state.research_points_awarded + 1e-8 >= definition.research_points_total, f"completed exploration lacks RP reward: {definition_id}")
        if state.phase in {ScientificExplorationPhase.COMPLETE, ScientificExplorationPhase.ABORTED}:
            _require(state.termination_intent is None, f"terminal exploration retains termination intent: {definition_id}")

    allowed_reservation_owners: set[EntityId] = set()
    known_reservation_owners: set[EntityId] = set()
    for definition_id, state in service.campaigns.items():
        outbound_owner = service._input_reservation_owner_id(definition_id)
        return_owner = service._input_reservation_owner_id(definition_id, returning=True)
        known_reservation_owners.update((outbound_owner, return_owner))
        if state.phase is ScientificExplorationPhase.PREPARING and not state.inputs_consumed:
            allowed_reservation_owners.add(outbound_owner)
        if state.phase is ScientificExplorationPhase.RETURN_PREPARING:
            allowed_reservation_owners.add(return_owner)
    for owner_id, _location_id, _resource_id in sim.inventory.reserved:
        if str(owner_id).startswith("scientific_exploration.inputs:"):
            _require(owner_id in known_reservation_owners, f"orphaned scientific exploration reservation: {owner_id}")
            _require(owner_id in allowed_reservation_owners, f"inactive scientific exploration retains input reservation: {owner_id}")


STATE_CODEC = StateCodec("scientific_exploration", capture_scientific_exploration, restore_scientific_exploration)
DOMAIN_EXTENSION = DomainExtension(
    "scientific_exploration",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
