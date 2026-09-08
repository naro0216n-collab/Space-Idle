from __future__ import annotations

from .application_commands import Command, CommandResult, CreateLogisticsRule, DeleteLogisticsRule, DispatchVehicle, PauseLogisticsRule, ProduceVehicle, RefuelVehicle, ResumeLogisticsRule, SubmitCargo
from .logistics import PathPolicy
from .shared import DefinitionId, EntityId, RouteId


class TransportCommandHandlerMixin:
    def _handle_transport_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, DispatchVehicle):
            sim.logistics.dispatch_vehicle(EntityId(command.vehicle_id), RouteId(command.route_id), sim.day, None if command.carrier_vehicle_id is None else EntityId(command.carrier_vehicle_id)); return CommandResult()
        if isinstance(command, RefuelVehicle):
            sim.logistics.refuel_vehicle(EntityId(command.vehicle_id), command.amount_t, sim.day); return CommandResult()
        if isinstance(command, ProduceVehicle):
            vid = sim.logistics.produce_vehicle(DefinitionId(command.vehicle_definition_id), self._require_location(command.location_id), sim.day); return CommandResult(str(vid))
        if isinstance(command, SubmitCargo):
            source_id = self._require_location(command.source_id); destination_id = self._require_location(command.destination_id)
            if source_id == destination_id: raise ValueError("cargo endpoints must differ")
            oid = sim.logistics.submit_order(
                source_id, destination_id, self._require_resource(command.resource_id), command.amount_t,
                command.priority, "player", EntityId("player"), day=sim.day,
                path=None if command.path is None else tuple(RouteId(x) for x in command.path),
                mode_by_route=self._route_mode_map(command.route_modes), path_policy=PathPolicy(command.path_policy),
            ); return CommandResult(str(oid))
        if isinstance(command, CreateLogisticsRule):
            rid = sim.logistics.create_recurring_rule(
                self._require_location(command.source_id), self._require_location(command.destination_id), self._require_resource(command.resource_id),
                command.target_stock_t, command.batch_t, command.priority,
                None if command.path is None else tuple(RouteId(x) for x in command.path), self._route_mode_map(command.route_modes),
                PathPolicy(command.path_policy),
            ); return CommandResult(str(rid))
        if isinstance(command, PauseLogisticsRule): sim.logistics.pause_recurring_rule(EntityId(command.rule_id)); return CommandResult()
        if isinstance(command, ResumeLogisticsRule): sim.logistics.resume_recurring_rule(EntityId(command.rule_id)); return CommandResult()
        if isinstance(command, DeleteLogisticsRule): sim.logistics.delete_recurring_rule(EntityId(command.rule_id)); return CommandResult()
        return NotImplemented
