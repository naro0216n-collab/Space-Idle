from __future__ import annotations

from .application_commands import (
    ChangeTransportAllocationMode, Command, CommandResult, CreateLogisticsLane,
    CreateTransportAllocation, DeleteLogisticsLane, DeleteTransportAllocation,
    PauseLogisticsLane, PauseTransportAllocation, ProduceVehicle,
    PauseVehicleProduction, RelocateFleet, ResumeVehicleProduction,
    ResumeLogisticsLane, ResumeTransportAllocation, SetVehicleProductionSettings,
    UpdateLogisticsLane, UpdateTransportAllocation,
)
from .logistics import PathPolicy
from .shared import DefinitionId, EntityId, RouteId
from .transport.models import DirectionalCapacity, TransportControlMode


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
            production_id = sim.logistics.plan_vehicle_production(
                DefinitionId(command.vehicle_definition_id),
                self._require_location(command.location_id),
                priority=command.priority,
                allocation_weight=command.allocation_weight,
                day=sim.day,
            )
            return CommandResult(str(production_id))
        if isinstance(command, PauseVehicleProduction):
            sim.logistics.pause_vehicle_production(EntityId(command.production_id)); return CommandResult()
        if isinstance(command, ResumeVehicleProduction):
            sim.logistics.resume_vehicle_production(EntityId(command.production_id)); return CommandResult()
        if isinstance(command, SetVehicleProductionSettings):
            sim.logistics.set_vehicle_production_settings(
                EntityId(command.production_id), priority=command.priority,
                allocation_weight=command.allocation_weight,
            )
            return CommandResult()
        if isinstance(command, CreateTransportAllocation):
            mode = TransportControlMode(command.control_mode)
            target_capacity = self._capacity_target(
                command.target_forward_t_per_day, command.target_reverse_t_per_day
            )
            if mode is TransportControlMode.UNITS:
                if target_capacity is not None:
                    raise ValueError("UNITS allocation cannot accept a capacity target")
                target_units = 0 if command.target_units is None else command.target_units
            else:
                if command.target_units is not None:
                    raise ValueError("CAPACITY allocation cannot accept target_units")
                if target_capacity is None:
                    raise ValueError("CAPACITY allocation requires directional targets")
                target_units = None
            allocation_id = sim.logistics.create_transport_allocation(
                DefinitionId(command.vehicle_definition_id),
                self._require_location(command.anchor_location_id),
                self._require_location(command.destination_id),
                priority=command.priority, control_mode=mode,
                target_units=target_units, target_capacity=target_capacity,
                path=None if command.path is None else tuple(RouteId(value) for value in command.path),
                path_policy=PathPolicy(command.path_policy), paused=command.paused, day=sim.day,
            )
            return CommandResult(str(allocation_id))
        if isinstance(command, UpdateTransportAllocation):
            target_capacity = self._capacity_target(
                command.target_forward_t_per_day, command.target_reverse_t_per_day
            )
            sim.logistics.update_transport_allocation(
                EntityId(command.allocation_id), priority=command.priority,
                target_units=command.target_units, target_capacity=target_capacity,
                path_policy=None if command.path_policy is None else PathPolicy(command.path_policy),
                day=sim.day,
            )
            return CommandResult()
        if isinstance(command, ChangeTransportAllocationMode):
            sim.logistics.change_transport_allocation_mode(
                EntityId(command.allocation_id), TransportControlMode(command.control_mode), day=sim.day
            )
            return CommandResult()
        if isinstance(command, PauseTransportAllocation):
            sim.logistics.update_transport_allocation(EntityId(command.allocation_id), paused=True, day=sim.day); return CommandResult()
        if isinstance(command, ResumeTransportAllocation):
            sim.logistics.update_transport_allocation(EntityId(command.allocation_id), paused=False, day=sim.day); return CommandResult()
        if isinstance(command, DeleteTransportAllocation):
            sim.logistics.delete_transport_allocation(EntityId(command.allocation_id), day=sim.day); return CommandResult()
        if isinstance(command, RelocateFleet):
            relocation_id = sim.logistics.relocate_fleet(
                DefinitionId(command.vehicle_definition_id), command.units,
                self._require_location(command.source_id), self._require_location(command.destination_id),
                path=None if command.path is None else tuple(RouteId(value) for value in command.path),
                path_policy=PathPolicy(command.path_policy), day=sim.day,
            )
            return CommandResult(str(relocation_id))
        if isinstance(command, CreateLogisticsLane):
            lane_id = sim.logistics.create_lane(
                self._require_location(command.source_id), self._require_location(command.destination_id),
                command.requested_capacity_t_per_day, command.priority,
                None if command.path is None else tuple(RouteId(value) for value in command.path),
                PathPolicy(command.path_policy),
            )
            return CommandResult(str(lane_id))
        if isinstance(command, UpdateLogisticsLane):
            sim.logistics.update_lane(EntityId(command.lane_id), command.requested_capacity_t_per_day, command.priority)
            return CommandResult()
        if isinstance(command, PauseLogisticsLane):
            sim.logistics.pause_lane(EntityId(command.lane_id)); return CommandResult()
        if isinstance(command, ResumeLogisticsLane):
            sim.logistics.resume_lane(EntityId(command.lane_id)); return CommandResult()
        if isinstance(command, DeleteLogisticsLane):
            sim.logistics.delete_lane(EntityId(command.lane_id)); return CommandResult()
        return NotImplemented
