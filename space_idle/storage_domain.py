from __future__ import annotations

from typing import Any

from .domain import DomainExtension
from .validation_support import ValidationContext, require as _require


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    facility_defs = ctx.facility_defs
    _require(sim.storage.inventory is sim.inventory, "storage/inventory service mismatch")
    _require(sim.storage.facilities is sim.facilities, "storage/facility service mismatch")
    for definition_id, spec in sim.storage.providers.items():
        _require(definition_id == spec.facility_def_id, f"storage provider key mismatch: {definition_id}")
        _require(definition_id in facility_defs, f"storage provider references unknown facility: {definition_id}")
        _require(all(v >= 0 for v in spec.capacity_t_by_class.values()), f"negative storage capacity: {definition_id}")
        _require(spec.power_sensitive_classes.issubset(spec.capacity_t_by_class), f"unknown power-sensitive storage class: {definition_id}")


DOMAIN_EXTENSION = DomainExtension("storage", configuration_validator=validate_configuration)
