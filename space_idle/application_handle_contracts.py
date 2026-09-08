from __future__ import annotations

from .application_commands import AcceptContract, Command, CommandResult, DeclineContract, DispatchContractCargo
from .shared import ContractId, RouteId


class ContractCommandHandlerMixin:
    def _handle_contract_command(self, command: Command):
        sim = self._simulation
        if not isinstance(command, (AcceptContract, DispatchContractCargo, DeclineContract)):
            return NotImplemented
        if sim.contracts is None:
            raise RuntimeError("contracts are not configured")
        cid = ContractId(command.contract_id)
        if isinstance(command, AcceptContract): sim.contracts.accept(cid, sim.day); return CommandResult()
        if isinstance(command, DeclineContract): sim.contracts.decline(cid); return CommandResult()
        oid = sim.contracts.dispatch_cargo(
            cid, sim.day, path=None if command.path is None else tuple(RouteId(x) for x in command.path),
            mode_by_route=self._route_mode_map(command.route_modes),
        )
        return CommandResult(str(oid))
