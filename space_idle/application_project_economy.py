from __future__ import annotations

import math

from .application_views import (
    ExternalEconomyView,
    ExternalServicePolicyRow,
    FundsAuthorizationRow,
)


class ExternalEconomyProjectorMixin:
    def _external_economy_view(self) -> ExternalEconomyView:
        sim = self._simulation
        state = sim.external_economy
        _requests, allocation = sim.external_funds_projection()
        policies = tuple(
            ExternalServicePolicyRow(
                id=str(policy.id),
                enabled=policy.enabled,
                allowed_service_ids=tuple(map(str, policy.allowed_service_ids)),
                scope_kind=policy.scope_kind,
                scope_id=None if policy.scope_id is None else str(policy.scope_id),
                spending_cap_musd=policy.spending_cap_musd,
                period_budget_musd=policy.period_budget_musd,
                period_days=policy.period_days,
                minimum_reserve_musd=policy.minimum_reserve_musd,
                period_start_day=policy.period_start_day,
                spent_in_period_musd=policy.effective_period_spend(sim.day),
                remaining_period_budget_musd=(
                    None
                    if math.isinf(policy.period_remaining_musd(sim.day))
                    else policy.period_remaining_musd(sim.day)
                ),
            )
            for policy in sorted(state.policies.values(), key=lambda row: str(row.id))
        )
        rows = tuple(
            FundsAuthorizationRow(
                request_id=str(row.request_id),
                policy_id=str(row.policy_id),
                service_id=str(row.service_id),
                requested_musd=row.requested_musd,
                authorized_musd=row.authorized_musd,
                unmet_musd=row.unmet_musd,
                priority=row.priority,
                owner_kind=row.owner_kind,
                owner_id=str(row.owner_id),
                purpose=row.purpose,
                limiting_factors=row.limiting_factors,
            )
            for row in allocation.rows
        )
        return ExternalEconomyView(
            state.account.funds_musd,
            policies,
            rows,
            sim.external_economy.spent_on_day(sim.day - 1),
        )
