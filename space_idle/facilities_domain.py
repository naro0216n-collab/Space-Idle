from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require, validate_environment_condition as _validate_environment_condition
from .facilities import FacilityState
from .shared import DefinitionId, EntityId, SpatialNodeId


def capture_facilities(sim: Any) -> dict[str, Any]:
    return {
        "counter": sim.facilities._counter,
        "items": [
            {
                "id": str(f.id), "definition_id": str(f.definition_id), "location_id": str(f.location_id),
                "paused": f.paused, "power_priority": f.power_priority,
            }
            for f in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id))
        ],
    }


def restore_facilities(sim: Any, data: dict[str, Any]) -> None:
    sim.facilities.facilities.clear()
    for row in data["items"]:
        fid = EntityId(row["id"])
        sim.facilities.facilities[fid] = FacilityState(
            fid, DefinitionId(row["definition_id"]), SpatialNodeId(row["location_id"]),
            bool(row["paused"]), row["power_priority"],
        )
    sim.facilities._counter = int(data["counter"])


STATE_CODEC = StateCodec("facilities", capture_facilities, restore_facilities)
def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    nodes = ctx.nodes
    facility_defs = ctx.facility_defs
    for key, definition in facility_defs.items():
        _require(key == definition.id, f"facility definition key mismatch: {key}")
        seen_caps: set[str] = set()
        for supply in definition.capability_supplies:
            _require(supply.id not in seen_caps, f"duplicate capability {supply.id} on {definition.id}")
            seen_caps.add(supply.id)
        for phase, conditions in (("installation", definition.installation_environment), ("operating", definition.operating_environment)):
            seen_condition_codes: set[str] = set()
            for condition in conditions:
                _validate_environment_condition(condition, f"facility:{definition.id}:{phase}")
                code = getattr(condition, "code", "")
                _require(code not in seen_condition_codes, f"duplicate facility {phase} condition: {definition.id}/{code}")
                seen_condition_codes.add(code)
    for facility in sim.facilities.facilities.values():
        _require(facility.definition_id in facility_defs, f"facility references unknown definition: {facility.id}")
        _require(facility.location_id in nodes, f"facility references unknown location: {facility.id}")
    for definition_id, spec in sim.power.specs.items():
        _require(definition_id in facility_defs, f"power spec references unknown facility: {definition_id}")
        _require(spec.load_mw >= 0, f"negative power load: {definition_id}")
        _require(spec.standby_load_mw >= 0, f"negative standby power load: {definition_id}")
        _require(spec.standby_load_mw <= spec.load_mw + 1e-12, f"standby load exceeds active load: {definition_id}")
        model = spec.generation
        if model is not None:
            if hasattr(model, "mw"):
                _require(model.mw >= 0, f"negative fixed generation: {definition_id}")
            else:
                _require(model.rated_mw_at_reference_flux >= 0, f"negative solar generation: {definition_id}")
                _require(model.reference_flux_w_m2 > 0, f"non-positive solar reference flux: {definition_id}")


def validate_runtime(sim: Any) -> None:
    for facility_id, facility in sim.facilities.facilities.items():
        _require(facility_id == facility.id, f"facility state key mismatch: {facility_id}")
        _require(facility.definition_id in sim.facilities.definitions, f"facility state has unknown definition: {facility_id}")
        _require(facility.location_id in sim.graph.nodes, f"facility state has unknown location: {facility_id}")


DOMAIN_EXTENSION = DomainExtension(
    "facilities", state_codec=STATE_CODEC,
    configuration_validator=validate_configuration, runtime_validator=validate_runtime,
)
