from __future__ import annotations

from .application_commands import (
    ClearTransportMovementConstraint, Command, CommandResult,
    CreateTransportAllocation, DeleteTransportAllocation,
    PauseTransportAllocation, ProduceVehicle, PauseVehicleProduction, RelocateFleet,
    RetireFleet, CancelFleetRetirement, SetFleetRetirementPriority, ResumeVehicleProduction, ResumeTransportAllocation, SetVehicleProductionSettings,
    SetTransportMovementConstraint, UpdateTransportAllocation,
)
from .shared import DefinitionId, EntityId, MovementPlanId
from .transport.models import DirectionalCapacity


class TransportCommandHandlerMixin:
    @staticmethod
    def _capacity_target(forward: float | None, reverse: float | None) -> DirectionalCapacity | None:
        if forward is None and reverse is None:
            return None
        if forward is None or reverse is None:
            raise ValueError("both directional capacity targets must be supplied")
        return DirectionalCapacity(float(forward), float(reverse))

    def _handle_transport_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, ProduceVehicle):
            production_id = sim.transport.plan_vehicle_production(
                DefinitionId(command.vehicle_definition_id),
                self._require_operational_node(command.operational_node_id),
                priority=command.priority,
                day=sim.day,
            )
            return CommandResult(str(production_id))
        if isinstance(command, PauseVehicleProduction):
            sim.transport.pause_vehicle_production(EntityId(command.production_id)); return CommandResult()
        if isinstance(command, ResumeVehicleProduction):
            sim.transport.resume_vehicle_production(EntityId(command.production_id)); return CommandResult()
        if isinstance(command, SetVehicleProductionSettings):
            sim.transport.set_vehicle_production_settings(
                EntityId(command.production_id), priority=command.priority
            )
            return CommandResult()
        if isinstance(command, CreateTransportAllocation):
            target_capacity = self._capacity_target(
                command.target_forward_t_per_day, command.target_reverse_t_per_day
            )
            if target_capacity is None:
                raise ValueError("transport allocation requires directional capacity targets")
            allocation_id = sim.transport.create_transport_allocation(
                DefinitionId(command.vehicle_definition_id),
                self._require_operational_node(command.anchor_node_id),
                self._require_operational_node(command.destination_id),
                target_capacity=target_capacity,
                provisioning_priority=command.provisioning_priority,
                movement_hard_constraint=(
                    None
                    if command.movement_hard_constraint is None
                    else tuple(MovementPlanId(value) for value in command.movement_hard_constraint)
                ),
                paused=command.paused, day=sim.day,
            )
            return CommandResult(str(allocation_id))
        if isinstance(command, UpdateTransportAllocation):
            target_capacity = self._capacity_target(
                command.target_forward_t_per_day, command.target_reverse_t_per_day
            )
            sim.transport.update_transport_allocation(
                EntityId(command.allocation_id), provisioning_priority=command.provisioning_priority,
                target_capacity=target_capacity, day=sim.day,
            )
            return CommandResult()
        if isinstance(command, SetTransportMovementConstraint):
            sim.transport.set_transport_movement_constraint(
                EntityId(command.allocation_id),
                tuple(MovementPlanId(value) for value in command.movement_plan_ids),
                day=sim.day,
            )
            return CommandResult()
        if isinstance(command, ClearTransportMovementConstraint):
            sim.transport.clear_transport_movement_constraint(
                EntityId(command.allocation_id), day=sim.day
            )
            return CommandResult()
        if isinstance(command, PauseTransportAllocation):
            sim.transport.update_transport_allocation(EntityId(command.allocation_id), paused=True, day=sim.day); return CommandResult()
        if isinstance(command, ResumeTransportAllocation):
            sim.transport.update_transport_allocation(EntityId(command.allocation_id), paused=False, day=sim.day); return CommandResult()
        if isinstance(command, DeleteTransportAllocation):
            sim.transport.delete_transport_allocation(EntityId(command.allocation_id), day=sim.day); return CommandResult()
        if isinstance(command, RetireFleet):
            retirement_id = sim.transport.plan_fleet_retirement(
                DefinitionId(command.vehicle_definition_id), command.units,
                self._require_operational_node(command.operational_node_id),
                priority=command.priority, day=sim.day,
            )
            return CommandResult(str(retirement_id))
        if isinstance(command, CancelFleetRetirement):
            sim.transport.cancel_fleet_retirement(EntityId(command.retirement_id))
            return CommandResult()
        if isinstance(command, SetFleetRetirementPriority):
            sim.transport.set_fleet_retirement_priority(EntityId(command.retirement_id), command.priority)
            return CommandResult()
        if isinstance(command, RelocateFleet):
            relocation_id = sim.transport.relocate_fleet(
                DefinitionId(command.vehicle_definition_id), command.units,
                self._require_operational_node(command.source_id), self._require_operational_node(command.destination_id),
                movement_hard_constraint=(
                    None
                    if command.movement_hard_constraint is None
                    else tuple(MovementPlanId(value) for value in command.movement_hard_constraint)
                ),
                day=sim.day,
            )
            return CommandResult(str(relocation_id))
        return NotImplemented
