from __future__ import annotations

from dataclasses import dataclass, field

from .shared import AccountState, DefinitionId, EntityId


@dataclass
class ExternalServicePolicy:
    id: EntityId
    enabled: bool
    allowed_service_ids: tuple[DefinitionId, ...]
    scope_kind: str = "global"
    scope_id: EntityId | None = None
    spending_cap_musd: float | None = None
    period_budget_musd: float | None = None
    period_days: int = 30
    minimum_reserve_musd: float = 0.0
    period_start_day: int = 0
    spent_in_period_musd: float = 0.0

    def __post_init__(self) -> None:
        if not self.scope_kind:
            raise ValueError("external service policy scope_kind must be non-empty")
        if self.scope_kind == "global" and self.scope_id is not None:
            raise ValueError("global external service policy cannot have scope_id")
        if self.scope_kind != "global" and self.scope_id is None:
            raise ValueError("scoped external service policy requires scope_id")
        if self.spending_cap_musd is not None and self.spending_cap_musd < -1e-9:
            raise ValueError("external service spending cap must be non-negative")
        if self.period_budget_musd is not None and self.period_budget_musd < -1e-9:
            raise ValueError("external service period budget must be non-negative")
        if self.period_days <= 0:
            raise ValueError("external service policy period_days must be positive")
        if self.minimum_reserve_musd < -1e-9:
            raise ValueError("external service minimum reserve must be non-negative")
        if self.period_start_day < 0:
            raise ValueError("external service period start must be non-negative")
        if self.spent_in_period_musd < -1e-9:
            raise ValueError("external service period spend must be non-negative")
        if (
            self.period_budget_musd is not None
            and self.spent_in_period_musd > self.period_budget_musd + 1e-9
        ):
            raise ValueError("external service period spend exceeds period budget")

    def applies_to(self, service_id: DefinitionId, owner_kind: str, owner_id: EntityId) -> bool:
        if not self.enabled or service_id not in self.allowed_service_ids:
            return False
        if self.scope_kind == "global":
            return True
        return self.scope_kind == owner_kind and self.scope_id == owner_id

    def effective_period_spend(self, day: int) -> float:
        if day < self.period_start_day:
            return self.spent_in_period_musd
        if day >= self.period_start_day + self.period_days:
            return 0.0
        return self.spent_in_period_musd

    def period_remaining_musd(self, day: int) -> float:
        if self.period_budget_musd is None:
            return float("inf")
        return max(0.0, self.period_budget_musd - self.effective_period_spend(day))


@dataclass(frozen=True)
class FundsRequest:
    id: EntityId
    policy_id: EntityId
    service_id: DefinitionId
    requested_musd: float
    priority: int
    owner_kind: str
    owner_id: EntityId
    purpose: str

    def __post_init__(self) -> None:
        if self.requested_musd < -1e-9:
            raise ValueError("funds request amount must be non-negative")


@dataclass(frozen=True)
class FundsAuthorization:
    request_id: EntityId
    policy_id: EntityId
    service_id: DefinitionId
    requested_musd: float
    authorized_musd: float
    unmet_musd: float
    priority: int
    owner_kind: str
    owner_id: EntityId
    purpose: str
    limiting_factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class FundsAllocationPlan:
    rows: tuple[FundsAuthorization, ...]

    def authorization(self, request_id: EntityId) -> FundsAuthorization:
        for row in self.rows:
            if row.request_id == request_id:
                return row
        raise KeyError(request_id)

    def authorized(self, request_id: EntityId) -> float:
        return self.authorization(request_id).authorized_musd


@dataclass
class ExternalEconomyState:
    account: AccountState
    policies: dict[EntityId, ExternalServicePolicy] = field(default_factory=dict)
    known_service_ids: set[DefinitionId] = field(default_factory=set)
    _policy_counter: int = 0
    _spent_by_day_musd: dict[int, float] = field(default_factory=dict, repr=False)

    def register_service(self, service_id: DefinitionId) -> None:
        self.known_service_ids.add(service_id)

    def create_policy(
        self,
        *,
        enabled: bool,
        allowed_service_ids: tuple[DefinitionId, ...],
        scope_kind: str = "global",
        scope_id: EntityId | None = None,
        spending_cap_musd: float | None = None,
        period_budget_musd: float | None = None,
        period_days: int = 30,
        minimum_reserve_musd: float = 0.0,
        day: int = 0,
    ) -> EntityId:
        self._policy_counter += 1
        policy_id = EntityId(f"external.policy.{self._policy_counter}")
        self.set_policy(
            ExternalServicePolicy(
                policy_id,
                enabled,
                tuple(sorted(set(allowed_service_ids), key=str)),
                scope_kind,
                scope_id,
                spending_cap_musd,
                period_budget_musd,
                period_days,
                minimum_reserve_musd,
                day,
                0.0,
            )
        )
        return policy_id

    def set_policy(self, policy: ExternalServicePolicy) -> None:
        unknown = set(policy.allowed_service_ids) - self.known_service_ids
        if unknown:
            raise ValueError(
                "external service policy references unknown service: "
                + ", ".join(sorted(map(str, unknown)))
            )
        if policy.enabled:
            for other in self.policies.values():
                if other.id == policy.id or not other.enabled:
                    continue
                if (other.scope_kind, other.scope_id) != (policy.scope_kind, policy.scope_id):
                    continue
                overlap = set(other.allowed_service_ids) & set(policy.allowed_service_ids)
                if overlap:
                    raise ValueError(
                        "ambiguous external service policy scope for service: "
                        + ", ".join(sorted(map(str, overlap)))
                    )
        self.policies[policy.id] = policy

    def delete_policy(self, policy_id: EntityId) -> None:
        if policy_id not in self.policies:
            raise KeyError(policy_id)
        del self.policies[policy_id]

    def settle_periods(self, day: int) -> None:
        self._spent_by_day_musd = {
            spent_day: amount
            for spent_day, amount in self._spent_by_day_musd.items()
            if spent_day >= day - 1
        }
        for policy in self.policies.values():
            if day < policy.period_start_day + policy.period_days:
                continue
            elapsed = day - policy.period_start_day
            periods = max(1, elapsed // policy.period_days)
            policy.period_start_day += periods * policy.period_days
            policy.spent_in_period_musd = 0.0

    def resolve_policy(
        self,
        service_id: DefinitionId,
        owner_kind: str,
        owner_id: EntityId,
    ) -> ExternalServicePolicy | None:
        matches = [
            policy
            for policy in self.policies.values()
            if policy.applies_to(service_id, owner_kind, owner_id)
        ]
        if not matches:
            return None
        specificity = max(0 if policy.scope_kind == "global" else 1 for policy in matches)
        matches = [
            policy
            for policy in matches
            if (0 if policy.scope_kind == "global" else 1) == specificity
        ]
        if len(matches) != 1:
            raise ValueError(
                f"ambiguous external service policy for {service_id}/{owner_kind}/{owner_id}"
            )
        return matches[0]

    def service_allowed(
        self,
        service_id: DefinitionId,
        owner_kind: str,
        owner_id: EntityId,
    ) -> bool:
        return self.resolve_policy(service_id, owner_kind, owner_id) is not None

    def allocate(
        self,
        requests: tuple[FundsRequest, ...],
        day: int,
    ) -> FundsAllocationPlan:
        if not requests:
            return FundsAllocationPlan(())
        seen: set[EntityId] = set()
        for request in requests:
            if request.id in seen:
                raise ValueError(f"duplicate funds request id: {request.id}")
            seen.add(request.id)
            policy = self.policies.get(request.policy_id)
            if policy is None or not policy.applies_to(
                request.service_id, request.owner_kind, request.owner_id
            ):
                raise ValueError(f"funds request is not authorized by policy: {request.id}")

        authorized: dict[EntityId, float] = {request.id: 0.0 for request in requests}
        factors: dict[EntityId, set[str]] = {request.id: set() for request in requests}
        funds_remaining = max(0.0, self.account.funds_musd)
        policy_remaining: dict[EntityId, float] = {
            policy_id: policy.period_remaining_musd(day)
            for policy_id, policy in self.policies.items()
        }

        priorities = sorted({request.priority for request in requests}, reverse=True)
        for priority in priorities:
            group = tuple(
                sorted(
                    (request for request in requests if request.priority == priority),
                    key=lambda request: (
                        request.owner_kind,
                        str(request.owner_id),
                        str(request.service_id),
                        str(request.id),
                    ),
                )
            )
            ceilings: dict[EntityId, float] = {}
            by_policy: dict[EntityId, list[FundsRequest]] = {}
            for request in group:
                policy = self.policies[request.policy_id]
                ceiling = request.requested_musd
                if policy.spending_cap_musd is not None:
                    if ceiling > policy.spending_cap_musd + 1e-9:
                        factors[request.id].add("spending_cap")
                    ceiling = min(ceiling, policy.spending_cap_musd)
                ceilings[request.id] = max(0.0, ceiling)
                by_policy.setdefault(policy.id, []).append(request)

            for policy_id, policy_requests in by_policy.items():
                remaining_budget = policy_remaining[policy_id]
                total = sum(ceilings[request.id] for request in policy_requests)
                if total <= remaining_budget + 1e-9:
                    continue
                factor = 0.0 if total <= 1e-12 else remaining_budget / total
                for request in policy_requests:
                    ceilings[request.id] *= factor
                    factors[request.id].add("period_budget")

            positive = [request for request in group if ceilings[request.id] > 1e-12]
            if not positive:
                continue
            reserve = max(
                self.policies[request.policy_id].minimum_reserve_musd
                for request in positive
            )
            spendable = max(0.0, funds_remaining - reserve)
            total = sum(ceilings[request.id] for request in positive)
            cash_factor = 1.0 if total <= spendable + 1e-9 else (0.0 if total <= 1e-12 else spendable / total)
            for request in positive:
                amount = ceilings[request.id] * cash_factor
                authorized[request.id] = amount
                if cash_factor < 1.0 - 1e-12:
                    factors[request.id].add("funds")
                    if reserve > 0:
                        factors[request.id].add("minimum_reserve")
            authorized_this_priority = sum(authorized[request.id] for request in positive)
            funds_remaining = max(0.0, funds_remaining - authorized_this_priority)
            for request in positive:
                remaining = policy_remaining[request.policy_id]
                if remaining != float("inf"):
                    policy_remaining[request.policy_id] = max(
                        0.0, remaining - authorized[request.id]
                    )

        rows = tuple(
            FundsAuthorization(
                request.id,
                request.policy_id,
                request.service_id,
                request.requested_musd,
                authorized[request.id],
                max(0.0, request.requested_musd - authorized[request.id]),
                request.priority,
                request.owner_kind,
                request.owner_id,
                request.purpose,
                tuple(sorted(factors[request.id])),
            )
            for request in sorted(requests, key=lambda request: str(request.id))
        )
        return FundsAllocationPlan(rows)

    def spend_authorized(
        self,
        authorization: FundsAuthorization,
        amount_musd: float,
        day: int,
    ) -> None:
        if amount_musd < -1e-9:
            raise ValueError("authorized external spend must be non-negative")
        if amount_musd > authorization.authorized_musd + 1e-8:
            raise RuntimeError("external spend exceeded authorization")
        if amount_musd <= 1e-12:
            return
        policy = self.policies.get(authorization.policy_id)
        if policy is None or not policy.applies_to(
            authorization.service_id,
            authorization.owner_kind,
            authorization.owner_id,
        ):
            raise RuntimeError("external service policy changed after allocation")
        if not self.account.spend(amount_musd):
            raise RuntimeError("external funds changed after allocation")
        if day >= policy.period_start_day + policy.period_days:
            self.settle_periods(day)
        policy.spent_in_period_musd += amount_musd
        self._spent_by_day_musd[day] = (
            self._spent_by_day_musd.get(day, 0.0) + amount_musd
        )

    def spent_on_day(self, day: int) -> float:
        return self._spent_by_day_musd.get(day, 0.0)
