from __future__ import annotations

from .application_commands import (
    Command,
    CommandResult,
    PauseFacility,
    ResumeFacility,
    SetFacilityProcess,
    SetFacilityActivityPriority,
    SetMaintenancePriority,
    SetTimeControl,
    SetPopulationTarget, ClearPopulationTarget,
)
from .shared import DefinitionId, EntityId, SpatialNodeId


class OperationsCommandHandlerMixin:
    def _handle_operations_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, SetPopulationTarget):
            sim.population.set_target(SpatialNodeId(command.operational_node_id), command.desired_count)
            return CommandResult()
        if isinstance(command, ClearPopulationTarget):
            sim.population.clear_target(SpatialNodeId(command.operational_node_id))
            return CommandResult()
        if isinstance(command, PauseFacility):
            sim.facilities.pause(EntityId(command.facility_id))
            sim.refresh_storage()
            return CommandResult()
        if isinstance(command, ResumeFacility):
            sim.facilities.resume(EntityId(command.facility_id))
            sim.refresh_storage()
            return CommandResult()
        if isinstance(command, SetFacilityProcess):
            facility = sim.facilities.facilities[EntityId(command.facility_id)]
            sim.industry.set_process(facility, DefinitionId(command.process_id))
            return CommandResult()
        if isinstance(command, SetFacilityActivityPriority):
            sim.facilities.set_activity_priority(
                EntityId(command.facility_id), command.priority
            )
            sim.refresh_storage()
            return CommandResult()
        if isinstance(command, SetMaintenancePriority):
            sim.facilities.set_maintenance_priority(
                EntityId(command.facility_id), command.priority
            )
            return CommandResult()
        if isinstance(command, SetTimeControl):
            if command.paused is not None:
                self._time_paused = command.paused
            if command.speed_multiplier is not None:
                self._time_speed_multiplier = command.speed_multiplier
            return CommandResult()
        return NotImplemented
