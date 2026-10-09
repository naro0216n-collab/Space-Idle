from __future__ import annotations

from typing import Any

from ..domain import DomainExtension
from ..validation_support import ValidationContext, require as _require
from ..shared import DefinitionId


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    for process in sim.industry.processes.values():
        result.update(process.inputs_per_day)
        result.update(process.outputs_per_day)
    return result


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    for process_id, process in sim.industry.processes.items():
        _require(process_id == process.id, f"process definition key mismatch: {process_id}")
        _require(bool(process.required_capabilities), f"process has no required capability: {process_id}")
        _require(all(isinstance(cap, str) and cap for cap in process.required_capabilities),
                 f"invalid process capability: {process_id}")
        _require(bool(sim.industry.service_capacity_provider_definition_ids(
            sim.industry.process_service_type(process_id))),
            f"process has no compatible facility: {process_id}")
        _require(all(v >= 0 for v in process.inputs_per_day.values()), f"negative process input: {process_id}")
        _require(all(v >= 0 for v in process.outputs_per_day.values()), f"negative process output: {process_id}")
        _require(any(v > 0 for v in process.outputs_per_day.values()), f"process has no positive output: {process_id}")
    validate_runtime(sim)


def validate_runtime(sim: Any) -> None:
    for facility in sim.facilities.facilities.values():
        process_id = facility.selected_process_id
        if process_id is None:
            continue
        _require(process_id in sim.industry.processes, f"process selection references unknown process: {process_id}")
        _require(process_id in {row.id for row in sim.industry.compatible_processes(facility.definition_id)},
                 f"selected process incompatible with facility: {facility.id}/{process_id}")


DOMAIN_EXTENSION = DomainExtension(
    "production", configuration_validator=validate_configuration, runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
    service_capacity_provider=lambda sim: sim.industry,
)
