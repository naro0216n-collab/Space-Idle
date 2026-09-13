from __future__ import annotations

from .application_commands import AdvanceTime, Command, CommandResult
from .application_command_support import ApplicationCommandSupportMixin
from .application_handle_construction import ConstructionCommandHandlerMixin
from .application_handle_operations import OperationsCommandHandlerMixin
from .application_handle_progression import ProgressionCommandHandlerMixin
from .application_handle_transport import TransportCommandHandlerMixin
from .application_handle_contracts import ContractCommandHandlerMixin


class ApplicationCommandMixin(
    ApplicationCommandSupportMixin,
    ConstructionCommandHandlerMixin,
    OperationsCommandHandlerMixin,
    ProgressionCommandHandlerMixin,
    TransportCommandHandlerMixin,
    ContractCommandHandlerMixin,
):
    def _execute(self, command: Command) -> CommandResult:
        for handler in (
            self._handle_construction_command,
            self._handle_operations_command,
            self._handle_progression_command,
            self._handle_transport_command,
            self._handle_contract_command,
        ):
            result = handler(command)
            if result is not NotImplemented:
                return result
        if isinstance(command, AdvanceTime):
            self._simulation.advance_days(command.days)
            return CommandResult()
        raise TypeError(f"unsupported command: {type(command).__name__}")
