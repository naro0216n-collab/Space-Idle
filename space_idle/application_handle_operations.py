from __future__ import annotations

from .application_commands import Command, CommandResult, PauseFacility, ResumeFacility, SetFacilityProcess, SetPowerPriority, SetMaintenancePriority
from .shared import DefinitionId, EntityId


class OperationsCommandHandlerMixin:
    def _handle_operations_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, PauseFacility):
            sim.facilities.pause(EntityId(command.facility_id)); sim.refresh_storage(); return CommandResult()
        if isinstance(command, ResumeFacility):
            sim.facilities.resume(EntityId(command.facility_id)); sim.refresh_storage(); return CommandResult()
        if isinstance(command, SetFacilityProcess):
            facility = sim.facilities.facilities[EntityId(command.facility_id)]
            sim.industry.set_process(facility, DefinitionId(command.process_id)); return CommandResult()
        if isinstance(command, SetPowerPriority):
            sim.facilities.set_power_priority(EntityId(command.facility_id), command.priority); sim.refresh_storage(); return CommandResult()
        if isinstance(command, SetMaintenancePriority):
            sim.facilities.set_maintenance_priority(EntityId(command.facility_id), command.priority); return CommandResult()
        return NotImplemented
