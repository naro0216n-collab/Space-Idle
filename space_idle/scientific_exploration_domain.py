from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .scientific_exploration import ScientificExplorationPhase, ScientificExplorationState
from .shared import DefinitionId, EntityId
from .transport.models import FleetReservationKind
from .validation_support import ValidationContext, require as _require, validate_site_requirements


def capture_scientific_exploration(sim: Any) -> dict[str, Any]:
    service = sim.scientific_exploration
    return {
        "campaigns": [
            {
                "definition_id": str(state.definition_id),
                "phase": state.phase.value,
                "vehicle_definition_id": None if state.vehicle_definition_id is None else str(state.vehicle_definition_id),
                "reserved_units": state.reserved_units,
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
            definition_id=DefinitionId(row["definition_id"]),
            phase=ScientificExplorationPhase(row.get("phase", "awaiting_vehicle")),
            vehicle_definition_id=(
                None if row.get("vehicle_definition_id") is None
                else DefinitionId(row["vehicle_definition_id"])
            ),
            reserved_units=int(row.get("reserved_units", 0)),
            progress_days=float(row.get("progress_days", 0.0)),
            research_points_awarded=float(row.get("research_points_awarded", 0.0)),
            inputs_consumed=bool(row.get("inputs_consumed", False)),
            paused=bool(row.get("paused", False)),
            created_day=int(row.get("created_day", 0)),
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
        for operation in definition.operations:
            _require(sim.logistics.operation_registry.supports(operation.operation_type), f"scientific exploration references unknown operation: {definition_id}/{operation.operation_type}")
        validate_site_requirements(definition.origin_requirements, capabilities, f"scientific_exploration:{definition_id}:origin")
        validate_site_requirements(definition.destination_requirements, capabilities, f"scientific_exploration:{definition_id}:destination")


def validate_runtime(sim: Any) -> None:
    service = sim.scientific_exploration
    for definition_id, state in service.campaigns.items():
        _require(definition_id in service.definitions, f"scientific exploration state references unknown definition: {definition_id}")
        definition = service.definitions[definition_id]
        _require(-1e-9 <= state.progress_days <= definition.duration_days + 1e-8, f"invalid scientific exploration progress: {definition_id}")
        _require(-1e-9 <= state.research_points_awarded <= definition.research_points_total + 1e-8, f"invalid scientific exploration RP award: {definition_id}")
        reservation_id = EntityId(f"scientific_exploration:{definition_id}")
        reservation = sim.logistics.fleet_reservation_snapshot(reservation_id)
        if state.vehicle_definition_id is None:
            _require(state.reserved_units == 0, f"unassigned scientific exploration retains reserved units: {definition_id}")
            _require(reservation is None, f"unassigned scientific exploration retains Fleet reservation: {definition_id}")
        elif state.phase is ScientificExplorationPhase.COMPLETE:
            _require(state.reserved_units > 0, f"completed scientific exploration lost Fleet usage record: {definition_id}")
            _require(reservation is None, f"completed scientific exploration retains Fleet reservation: {definition_id}")
        else:
            _require(state.vehicle_definition_id in sim.logistics.vehicle_defs, f"scientific exploration references unknown vehicle definition: {definition_id}")
            _require(state.reserved_units == definition.required_units, f"scientific exploration Fleet unit mismatch: {definition_id}")
            _require(reservation is not None, f"scientific exploration lacks Fleet reservation: {definition_id}")
            if reservation is not None:
                _require(reservation.kind is FleetReservationKind.SCIENTIFIC_EXPLORATION, f"scientific exploration reservation kind mismatch: {definition_id}")
                _require(reservation.vehicle_definition_id == state.vehicle_definition_id, f"scientific exploration reservation vehicle mismatch: {definition_id}")
                _require(reservation.location_id == definition.origin_id, f"scientific exploration reservation location mismatch: {definition_id}")
                _require(reservation.units == state.reserved_units, f"scientific exploration reservation unit mismatch: {definition_id}")
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
