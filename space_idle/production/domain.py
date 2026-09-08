from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import ValidationContext, require as _require
from ..shared import DefinitionId, EntityId


def capture_industry(sim: Any) -> dict[str, Any]:
    return {
        "selected_process_by_facility": [
            {"facility_id": str(fid), "process_id": str(pid)}
            for fid, pid in sorted(sim.industry.selected_process_by_facility.items(), key=lambda x: str(x[0]))
        ]
    }


def restore_industry(sim: Any, data: dict[str, Any]) -> None:
    sim.industry.selected_process_by_facility = {
        EntityId(r["facility_id"]): DefinitionId(r["process_id"])
        for r in data.get("selected_process_by_facility", [])
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    for process in sim.industry.processes.values():
        result.update(process.inputs_per_day)
        result.update(process.outputs_per_day)
    return result


STATE_CODEC = StateCodec("industry", capture_industry, restore_industry)
def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    facility_defs = ctx.facility_defs
    for process_id, process in sim.industry.processes.items():
        _require(process_id == process.id, f"process definition key mismatch: {process_id}")
        _require(process.facility_def_id in facility_defs, f"process references unknown facility: {process_id}")
        _require(all(v >= 0 for v in process.inputs_per_day.values()), f"negative process input: {process_id}")
        _require(all(v >= 0 for v in process.outputs_per_day.values()), f"negative process output: {process_id}")
        _require(any(v > 0 for v in process.outputs_per_day.values()), f"process has no positive output: {process_id}")
    for facility_id, process_id in sim.industry.selected_process_by_facility.items():
        _require(facility_id in sim.facilities.facilities, f"process selection references unknown facility: {facility_id}")
        _require(process_id in sim.industry.processes, f"process selection references unknown process: {process_id}")
        _require(sim.industry.processes[process_id].facility_def_id == sim.facilities.facilities[facility_id].definition_id,
                 f"selected process incompatible with facility: {facility_id}/{process_id}")


DOMAIN_EXTENSION = DomainExtension(
    "production", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    referenced_resources=referenced_resources,
)
