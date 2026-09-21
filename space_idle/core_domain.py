from __future__ import annotations

from typing import Any

from .domain import (
    DomainExtension, StateCodec, decode_float, decode_int, decode_list, decode_str,
    require_fields,
)
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
    row = require_fields(
        data, {"day", "pending_offline_game_days", "boundary_service_usage"},
        "core state",
    )
    day = decode_int(row["day"], "core day")
    pending = decode_float(row["pending_offline_game_days"], "pending offline game days")

    restored_usage: list[tuple[AllocationConstraintKey, float]] = []
    for index, raw_usage in enumerate(
        decode_list(row["boundary_service_usage"], "boundary service usage")
    ):
        usage = require_fields(
            raw_usage, {"kind", "scope_id", "name", "amount"},
            f"boundary service usage[{index}]",
        )
        restored_usage.append(
            (
                AllocationConstraintKey(
                    decode_str(usage["kind"], "boundary service usage kind"),
                    decode_str(usage["scope_id"], "boundary service usage scope_id"),
                    decode_str(usage["name"], "boundary service usage name"),
                ),
                decode_float(usage["amount"], "boundary service usage amount"),
            )
        )

    sim.day = day
    sim.restore_boundary_settled_day(day)
    sim.pending_offline_game_days = pending
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
