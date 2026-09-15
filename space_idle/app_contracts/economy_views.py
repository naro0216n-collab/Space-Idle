from __future__ import annotations

from dataclasses import dataclass

from ..priority import ActivityPriority, ProvisioningPriority


@dataclass(frozen=True)
class ExternalServicePolicyRow:
    id: str
    enabled: bool
    allowed_service_ids: tuple[str, ...]
    scope_kind: str
    scope_id: str | None
    spending_cap_musd: float | None
    period_budget_musd: float | None
    period_days: int
    minimum_reserve_musd: float
    period_start_day: int
    spent_in_period_musd: float
    remaining_period_budget_musd: float | None


@dataclass(frozen=True)
class FundsAuthorizationRow:
    request_id: str
    policy_id: str
    service_id: str
    requested_musd: float
    authorized_musd: float
    unmet_musd: float
    priority: ActivityPriority
    owner_kind: str
    owner_id: str
    purpose: str
    limiting_factors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalEconomyView:
    funds_musd: float
    policies: tuple[ExternalServicePolicyRow, ...]
    authorizations: tuple[FundsAuthorizationRow, ...]
    last_tick_spent_musd: float
