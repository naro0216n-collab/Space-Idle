from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateExternalServicePolicy:
    enabled: bool
    allowed_service_ids: tuple[str, ...]
    scope_kind: str = "global"
    scope_id: str | None = None
    spending_cap_musd: float | None = None
    period_budget_musd: float | None = None
    period_days: int = 30
    minimum_reserve_musd: float = 0.0


@dataclass(frozen=True)
class SetExternalServicePolicy:
    policy_id: str
    enabled: bool
    allowed_service_ids: tuple[str, ...]
    scope_kind: str = "global"
    scope_id: str | None = None
    spending_cap_musd: float | None = None
    period_budget_musd: float | None = None
    period_days: int = 30
    minimum_reserve_musd: float = 0.0


@dataclass(frozen=True)
class DeleteExternalServicePolicy:
    policy_id: str
