from __future__ import annotations

from .application_commands import (
    ClearSupplyRoutingConstraint,
    Command,
    CommandResult,
    DeleteTargetStock,
    SetSupplyRoutingConstraint,
    SetTargetStock,
)
from .shared import DefinitionId, EntityId
from .supply import SupplyRoutingConstraintScope


class LogisticsCommandHandlerMixin:
    def _routing_constraint_scope(
        self,
        *,
        destination_id: str,
        owner_kind: str | None,
        owner_id: str | None,
        resource_id: str | None,
    ) -> SupplyRoutingConstraintScope:
        return SupplyRoutingConstraintScope(
            destination_id=self._require_operational_node(destination_id),
            owner_kind=owner_kind,
            owner_id=None if owner_id is None else EntityId(owner_id),
            resource_id=None if resource_id is None else DefinitionId(resource_id),
        )

    def _handle_logistics_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, SetTargetStock):
            target_stock_id = sim.logistics.set_target_stock(
                self._require_operational_node(command.destination_id),
                DefinitionId(command.resource_id),
                command.target_quantity_t,
                command.priority,
            )
            return CommandResult(str(target_stock_id))
        if isinstance(command, DeleteTargetStock):
            sim.logistics.delete_target_stock(
                self._require_operational_node(command.destination_id),
                DefinitionId(command.resource_id),
            )
            return CommandResult()
        if isinstance(command, SetSupplyRoutingConstraint):
            scope = self._routing_constraint_scope(
                destination_id=command.destination_id,
                owner_kind=command.owner_kind,
                owner_id=command.owner_id,
                resource_id=command.resource_id,
            )
            sim.logistics.set_supply_routing_constraint(
                scope,
                source_node_id=(
                    None
                    if command.source_node_id is None
                    else self._require_operational_node(command.source_node_id)
                ),
                required_via_node_ids=tuple(
                    self._require_operational_node(value)
                    for value in command.required_via_node_ids
                ),
                required_transport_allocation_ids=tuple(
                    EntityId(value) for value in command.required_transport_allocation_ids
                ),
            )
            return CommandResult()
        if isinstance(command, ClearSupplyRoutingConstraint):
            scope = self._routing_constraint_scope(
                destination_id=command.destination_id,
                owner_kind=command.owner_kind,
                owner_id=command.owner_id,
                resource_id=command.resource_id,
            )
            sim.logistics.clear_supply_routing_constraint(scope)
            return CommandResult()
        return NotImplemented
