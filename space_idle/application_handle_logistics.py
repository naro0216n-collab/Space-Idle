from __future__ import annotations

from .application_commands import (
    AssignLogisticsPolicy,
    Command,
    CommandResult,
    CreateLogisticsPolicy,
    DeleteLogisticsPolicy,
    DeleteTargetStock,
    SetGlobalLogisticsPolicy,
    SetTargetStock,
    UnassignLogisticsPolicy,
    UpdateLogisticsPolicy,
)
from .shared import DefinitionId, EntityId, MovementPlanId
from .supply import PathSelectionMode, SourceSelectionMode
from .transport.models import PathPolicy


class LogisticsCommandHandlerMixin:
    def _policy_source(self, value: str | None):
        return None if value is None else self._require_operational_node(value)

    def _policy_sources(self, values: tuple[str, ...] | None):
        return None if values is None else tuple(self._require_operational_node(value) for value in values)

    @staticmethod
    def _policy_path(value: tuple[str, ...] | None):
        return None if value is None else tuple(MovementPlanId(item) for item in value)

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
        if isinstance(command, CreateLogisticsPolicy):
            policy_id = sim.logistics.create_logistics_policy(
                EntityId(command.policy_id),
                source_mode=SourceSelectionMode(command.source_mode),
                allowed_source_ids=self._policy_sources(command.allowed_source_ids),
                preferred_source_id=self._policy_source(command.preferred_source_id),
                path_mode=PathSelectionMode(command.path_mode),
                explicit_path=self._policy_path(command.explicit_path),
                allowed_handoff_ids=self._policy_sources(command.allowed_handoff_ids),
                allowed_service_ids=command.allowed_service_ids,
                path_preference=PathPolicy(command.path_preference),
            )
            return CommandResult(str(policy_id))
        if isinstance(command, UpdateLogisticsPolicy):
            sim.logistics.update_logistics_policy(
                EntityId(command.policy_id),
                source_mode=SourceSelectionMode(command.source_mode),
                allowed_source_ids=self._policy_sources(command.allowed_source_ids),
                preferred_source_id=self._policy_source(command.preferred_source_id),
                path_mode=PathSelectionMode(command.path_mode),
                explicit_path=self._policy_path(command.explicit_path),
                allowed_handoff_ids=self._policy_sources(command.allowed_handoff_ids),
                allowed_service_ids=command.allowed_service_ids,
                path_preference=PathPolicy(command.path_preference),
            )
            return CommandResult()
        if isinstance(command, AssignLogisticsPolicy):
            sim.logistics.assign_logistics_policy(
                command.owner_kind, EntityId(command.owner_id), EntityId(command.policy_id)
            )
            return CommandResult()
        if isinstance(command, UnassignLogisticsPolicy):
            sim.logistics.unassign_logistics_policy(command.owner_kind, EntityId(command.owner_id))
            return CommandResult()
        if isinstance(command, SetGlobalLogisticsPolicy):
            sim.logistics.set_global_logistics_policy(
                None if command.policy_id is None else EntityId(command.policy_id)
            )
            return CommandResult()
        if isinstance(command, DeleteLogisticsPolicy):
            sim.logistics.delete_logistics_policy(EntityId(command.policy_id))
            return CommandResult()
        return NotImplemented
