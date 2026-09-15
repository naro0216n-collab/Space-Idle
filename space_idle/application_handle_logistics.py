from __future__ import annotations

from .application_commands import (
    Command,
    CommandResult,
    DeleteSupplyPolicy,
    DeleteTargetStock,
    SetSupplyPolicy,
    SetTargetStock,
)
from .shared import DefinitionId, RouteId
from .transport.models import PathPolicy


class LogisticsCommandHandlerMixin:
    def _handle_logistics_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, SetTargetStock):
            policy_id = sim.logistics.set_target_stock(
                self._require_operational_node(command.destination_id),
                DefinitionId(command.resource_id),
                command.target_quantity_t,
                command.priority,
            )
            return CommandResult(str(policy_id))
        if isinstance(command, DeleteTargetStock):
            sim.logistics.delete_target_stock(
                self._require_operational_node(command.destination_id),
                DefinitionId(command.resource_id),
            )
            return CommandResult()
        if isinstance(command, SetSupplyPolicy):
            policy_id = sim.logistics.set_supply_policy(
                self._require_operational_node(command.destination_id),
                DefinitionId(command.resource_id),
                preferred_source_id=(
                    None
                    if command.preferred_source_id is None
                    else self._require_operational_node(command.preferred_source_id)
                ),
                path_policy=PathPolicy(command.path_policy),
                explicit_path=(
                    None
                    if command.explicit_path is None
                    else tuple(RouteId(value) for value in command.explicit_path)
                ),
            )
            return CommandResult(str(policy_id))
        if isinstance(command, DeleteSupplyPolicy):
            sim.logistics.delete_supply_policy(
                self._require_operational_node(command.destination_id),
                DefinitionId(command.resource_id),
            )
            return CommandResult()
        return NotImplemented
