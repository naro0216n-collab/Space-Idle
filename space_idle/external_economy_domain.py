from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .external_economy import ExternalServicePolicy
from .shared import DefinitionId, EntityId
from .validation_support import require as _require


def capture_external_economy(sim: Any) -> dict[str, Any]:
    state = sim.external_economy
    return {
        "funds_musd": state.account.funds_musd,
        "policy_counter": state._policy_counter,
        "policies": [
            {
                "id": str(policy.id),
                "enabled": policy.enabled,
                "allowed_service_ids": [str(value) for value in policy.allowed_service_ids],
                "scope_kind": policy.scope_kind,
                "scope_id": None if policy.scope_id is None else str(policy.scope_id),
                "spending_cap_musd": policy.spending_cap_musd,
                "period_budget_musd": policy.period_budget_musd,
                "period_days": policy.period_days,
                "minimum_reserve_musd": policy.minimum_reserve_musd,
                "period_start_day": policy.period_start_day,
                "spent_in_period_musd": policy.spent_in_period_musd,
            }
            for policy in sorted(state.policies.values(), key=lambda row: str(row.id))
        ],
    }


def restore_external_economy(sim: Any, data: dict[str, Any]) -> None:
    state = sim.external_economy
    state.account.funds_musd = float(data["funds_musd"])
    state._policy_counter = int(data.get("policy_counter", 0))
    state.policies = {}
    state._spent_by_day_musd = {}
    for row in data.get("policies", []):
        policy = ExternalServicePolicy(
            EntityId(row["id"]),
            bool(row["enabled"]),
            tuple(DefinitionId(value) for value in row.get("allowed_service_ids", [])),
            str(row.get("scope_kind", "global")),
            None if row.get("scope_id") is None else EntityId(row["scope_id"]),
            None if row.get("spending_cap_musd") is None else float(row["spending_cap_musd"]),
            None if row.get("period_budget_musd") is None else float(row["period_budget_musd"]),
            int(row.get("period_days", 30)),
            float(row.get("minimum_reserve_musd", 0.0)),
            int(row.get("period_start_day", 0)),
            float(row.get("spent_in_period_musd", 0.0)),
        )
        state.set_policy(policy)


def validate_configuration(sim: Any, _ctx) -> None:
    state = sim.external_economy
    _require(state.account.funds_musd >= 0.0, "negative initial external economy funds")
    for policy_id, policy in state.policies.items():
        _require(policy_id == policy.id, f"external policy key mismatch: {policy_id}")
        unknown = set(policy.allowed_service_ids) - state.known_service_ids
        _require(not unknown, f"external policy references unknown service: {policy_id}")


def validate_runtime(sim: Any) -> None:
    state = sim.external_economy
    _require(state.account.funds_musd >= -1e-9, "negative external economy funds")
    for policy_id, policy in state.policies.items():
        _require(policy_id == policy.id, f"external policy key mismatch: {policy_id}")
        _require(policy.spent_in_period_musd >= -1e-9, f"negative external policy spend: {policy_id}")
        if policy.period_budget_musd is not None:
            _require(
                policy.spent_in_period_musd <= policy.period_budget_musd + 1e-8,
                f"external policy period budget exceeded: {policy_id}",
            )


STATE_CODEC = StateCodec("external_economy", capture_external_economy, restore_external_economy)
DOMAIN_EXTENSION = DomainExtension(
    "external_economy",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
)
