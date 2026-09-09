from __future__ import annotations

from .application_commands import (
    Command, CommandResult, CreateLogisticsLane, DeleteLogisticsLane, DispatchVehicle,
    PauseLogisticsLane, ProduceVehicle, RefuelVehicle, ResumeLogisticsLane, SubmitCargo,
    UpdateLogisticsLane,
)
from .logistics import PathPolicy
from .shared import DefinitionId, EntityId, RouteId


class TransportCommandHandlerMixin:
    def _handle_transport_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, DispatchVehicle):
            sim.logistics.dispatch_vehicle(
                EntityId(command.vehicle_id), RouteId(command.route_id), sim.day,
                None if command.carrier_vehicle_id is None else EntityId(command.carrier_vehicle_id),
            )
            return CommandResult()
        if isinstance(command, RefuelVehicle):
            sim.logistics.refuel_vehicle(EntityId(command.vehicle_id), command.amount_t, sim.day)
            return CommandResult()
        if isinstance(command, ProduceVehicle):
            vehicle_id = sim.logistics.produce_vehicle(
                DefinitionId(command.vehicle_definition_id), self._require_location(command.location_id), sim.day
            )
            return CommandResult(str(vehicle_id))
        if isinstance(command, SubmitCargo):
            source_id = self._require_location(command.source_id)
            destination_id = self._require_location(command.destination_id)
            if source_id == destination_id:
                raise ValueError("cargo endpoints must differ")
            order_id = sim.logistics.submit_order(
                source_id, destination_id, self._require_resource(command.resource_id), command.amount_t,
                command.priority, "player", EntityId("player"), day=sim.day,
                path=None if command.path is None else tuple(RouteId(value) for value in command.path),
                mode_by_route=self._route_mode_map(command.route_modes),
                path_policy=PathPolicy(command.path_policy),
            )
            return CommandResult(str(order_id))
        if isinstance(command, CreateLogisticsLane):
            lane_id = sim.logistics.create_lane(
                self._require_location(command.source_id), self._require_location(command.destination_id),
                command.requested_capacity_t_per_day, command.priority,
                None if command.path is None else tuple(RouteId(value) for value in command.path),
                self._route_mode_map(command.route_modes), PathPolicy(command.path_policy),
            )
            return CommandResult(str(lane_id))
        if isinstance(command, UpdateLogisticsLane):
            sim.logistics.update_lane(
                EntityId(command.lane_id), command.requested_capacity_t_per_day, command.priority
            )
            return CommandResult()
        if isinstance(command, PauseLogisticsLane):
            sim.logistics.pause_lane(EntityId(command.lane_id)); return CommandResult()
        if isinstance(command, ResumeLogisticsLane):
            sim.logistics.resume_lane(EntityId(command.lane_id)); return CommandResult()
        if isinstance(command, DeleteLogisticsLane):
            sim.logistics.delete_lane(EntityId(command.lane_id)); return CommandResult()
        return NotImplemented
