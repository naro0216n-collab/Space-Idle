from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .execution_requirements import AllocationConstraintKey
from .validation_support import ValidationContext, require as _require


def capture_core_state(sim: Any) -> dict[str, Any]:
    """Capture authoritative canonical-boundary state owned by the Simulation core."""
    return {
        "day": sim.day,
        "pending_offline_game_days": sim.pending_offline_game_days,
        "boundary_service_usage": [
            {
                "kind": key.kind,
                "scope_id": key.scope_id,
                "name": key.name,
                "amount": amount,
            }
            for key, amount in sim.boundary_service_usage_snapshot()
        ],
    }


def restore_core_state(sim: Any, data: dict[str, Any]) -> None:
    fields = {"day", "pending_offline_game_days", "boundary_service_usage"}
    if set(data) != fields:
        raise ValueError("core state has invalid fields")

    day = data["day"]
    if isinstance(day, bool) or not isinstance(day, int):
        raise ValueError("core day must be an integer")
    pending = data["pending_offline_game_days"]
    if isinstance(pending, bool) or not isinstance(pending, (int, float)):
        raise ValueError("pending offline game days must be numeric")
    usage_rows = data["boundary_service_usage"]
    if not isinstance(usage_rows, list):
        raise ValueError("boundary service usage must be a list")

    restored_usage: list[tuple[AllocationConstraintKey, float]] = []
    for row in usage_rows:
        if not isinstance(row, dict) or set(row) != {"kind", "scope_id", "name", "amount"}:
            raise ValueError("boundary service usage row has invalid fields")
        if not all(isinstance(row[key], str) for key in ("kind", "scope_id", "name")):
            raise ValueError("boundary service usage identity fields must be strings")
        amount = row["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError("boundary service usage amount must be numeric")
        restored_usage.append(
            (
                AllocationConstraintKey(row["kind"], row["scope_id"], row["name"]),
                float(amount),
            )
        )

    sim.day = day
    sim.restore_boundary_settled_day(day)
    sim.pending_offline_game_days = float(pending)
    sim.restore_boundary_service_usage(tuple(restored_usage))


def validate_core_configuration(sim: Any, ctx: ValidationContext) -> None:
    _require(sim.environment.graph is sim.graph, "simulation/environment spatial graph mismatch")
    _require(sim.facilities.environment is sim.environment, "facility/environment resolver mismatch")
    _require(sim.power.environment is sim.environment, "power/environment resolver mismatch")


def validate_core_runtime(sim: Any) -> None:
    _require(sim.runtime_state_initialized, "runtime state has not been initialized")
    _require(sim.day >= 0, "negative simulation day")
    _require(
        sim.boundary_settled_day == sim.day,
        "simulation is externally visible before canonical boundary settlement",
    )
    _require(0 <= sim.pending_offline_game_days < 1.0 + 1e-9, "invalid pending offline fraction")


CORE_STATE_CODEC = StateCodec("core", capture_core_state, restore_core_state)

DOMAIN_EXTENSION = DomainExtension(
    "core",
    state_codec=CORE_STATE_CODEC,
    configuration_validator=validate_core_configuration,
    runtime_validator=validate_core_runtime,
)
