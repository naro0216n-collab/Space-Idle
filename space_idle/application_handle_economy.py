from __future__ import annotations

from .application_commands import (
    Command,
    CommandResult,
    CreateExternalServicePolicy,
    DeleteExternalServicePolicy,
    SetExternalServicePolicy,
)
from .external_economy import ExternalServicePolicy
from .shared import DefinitionId, EntityId


class ExternalEconomyCommandHandlerMixin:
    def _handle_external_economy_command(self, command: Command):
        sim = self._simulation
        state = sim.external_economy
        if isinstance(command, CreateExternalServicePolicy):
            policy_id = state.create_policy(
                enabled=command.enabled,
                allowed_service_ids=tuple(
                    DefinitionId(value) for value in command.allowed_service_ids
                ),
                scope_kind=command.scope_kind,
                scope_id=None if command.scope_id is None else EntityId(command.scope_id),
                spending_cap_musd=command.spending_cap_musd,
                period_budget_musd=command.period_budget_musd,
                period_days=command.period_days,
                minimum_reserve_musd=command.minimum_reserve_musd,
                day=sim.day,
            )
            return CommandResult(str(policy_id))
        if isinstance(command, SetExternalServicePolicy):
            policy_id = EntityId(command.policy_id)
            current = state.policies.get(policy_id)
            if current is None:
                raise KeyError(policy_id)
            state.settle_periods(sim.day)
            state.set_policy(
                ExternalServicePolicy(
                    policy_id,
                    command.enabled,
                    tuple(DefinitionId(value) for value in command.allowed_service_ids),
                    command.scope_kind,
                    None if command.scope_id is None else EntityId(command.scope_id),
                    command.spending_cap_musd,
                    command.period_budget_musd,
                    command.period_days,
                    command.minimum_reserve_musd,
                    current.period_start_day,
                    current.spent_in_period_musd,
                )
            )
            return CommandResult()
        if isinstance(command, DeleteExternalServicePolicy):
            state.delete_policy(EntityId(command.policy_id))
            return CommandResult()
        return NotImplemented
