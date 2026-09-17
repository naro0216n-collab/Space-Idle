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
    facility_defs = ctx.facility_defs
    for process_id, process in sim.industry.processes.items():
        _require(process_id == process.id, f"process definition key mismatch: {process_id}")
        _require(process.facility_def_id in facility_defs, f"process references unknown facility: {process_id}")
        _require(all(v >= 0 for v in process.inputs_per_day.values()), f"negative process input: {process_id}")
        _require(all(v >= 0 for v in process.outputs_per_day.values()), f"negative process output: {process_id}")
        _require(any(v > 0 for v in process.outputs_per_day.values()), f"process has no positive output: {process_id}")
    for facility in sim.facilities.facilities.values():
        process_id = facility.selected_process_id
        if process_id is None:
            continue
        _require(process_id in sim.industry.processes, f"process selection references unknown process: {process_id}")
        _require(
            sim.industry.processes[process_id].facility_def_id == facility.definition_id,
            f"selected process incompatible with facility: {facility.id}/{process_id}",
        )


def validate_runtime(sim: Any) -> None:
    for facility in sim.facilities.facilities.values():
        process_id = facility.selected_process_id
        if process_id is None:
            continue
        _require(process_id in sim.industry.processes, f"process selection references unknown process: {process_id}")
        _require(
            sim.industry.processes[process_id].facility_def_id == facility.definition_id,
            f"selected process incompatible with facility: {facility.id}/{process_id}",
        )


DOMAIN_EXTENSION = DomainExtension(
    "production", configuration_validator=validate_configuration, runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
    service_capacity_provider=lambda sim: sim.industry,
)
