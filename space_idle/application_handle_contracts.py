from __future__ import annotations

from .application_commands import AcceptContract, Command, CommandResult, DeclineContract
from .shared import ContractId


class ContractCommandHandlerMixin:
    def _handle_contract_command(self, command: Command):
        sim = self._simulation
        if not isinstance(command, (AcceptContract, DeclineContract)):
            return NotImplemented
        if sim.contracts is None:
            raise RuntimeError("contracts are not configured")
        cid = ContractId(command.contract_id)
        if isinstance(command, AcceptContract):
            sim.contracts.accept(cid, sim.day)
        else:
            sim.contracts.decline(cid)
        return CommandResult()
