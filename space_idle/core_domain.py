from __future__ import annotations

from typing import Any

from .domain import DomainExtension
from .validation_support import ValidationContext, require as _require


def validate_core_configuration(sim: Any, ctx: ValidationContext) -> None:
    _require(sim.environment.graph is sim.graph, "simulation/environment spatial graph mismatch")
    _require(sim.facilities.environment is sim.environment, "facility/environment resolver mismatch")
    _require(sim.power.environment is sim.environment, "power/environment resolver mismatch")
    _require(sim.account.funds_musd >= 0, "negative initial account funds")


def validate_core_runtime(sim: Any) -> None:
    _require(sim.day >= 0, "negative simulation day")
    _require(sim.account.funds_musd >= -1e-9, "negative account funds")
    _require(0 <= sim.pending_offline_game_days < 1.0 + 1e-9, "invalid pending offline fraction")


DOMAIN_EXTENSION = DomainExtension(
    "core", configuration_validator=validate_core_configuration, runtime_validator=validate_core_runtime
)
