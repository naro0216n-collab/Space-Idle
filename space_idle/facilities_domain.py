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
                "id": str(f.id),
                "definition_id": str(f.definition_id),
                "location_id": str(f.location_id),
                "paused": f.paused,
                "power_priority": f.power_priority,
                "maintenance_priority": f.maintenance_priority,
                "level": f.level,
                "invested_resources": {str(resource_id): amount for resource_id, amount in sorted(f.invested_resources.items(), key=lambda row: str(row[0]))},
                "maintenance_satisfaction": f.maintenance_satisfaction,
            }
            for f in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id))
        ],
    }


def restore_facilities(sim: Any, data: dict[str, Any]) -> None:
    sim.facilities.facilities.clear()
    for row in data["items"]:
        fid = EntityId(row["id"])
        sim.facilities.facilities[fid] = FacilityState(
            id=fid,
            definition_id=DefinitionId(row["definition_id"]),
            location_id=SpatialNodeId(row["location_id"]),
            paused=bool(row["paused"]),
            power_priority=row["power_priority"],
            maintenance_priority=int(row["maintenance_priority"]),
            level=int(row["level"]),
            invested_resources={DefinitionId(key): float(value) for key, value in row["invested_resources"].items()},
            maintenance_satisfaction=float(row["maintenance_satisfaction"]),
        )
    sim.facilities._counter = int(data["counter"])


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return {
        resource_id
        for facility in sim.facilities.facilities.values()
        for resource_id in facility.invested_resources
    }


STATE_CODEC = StateCodec("facilities", capture_facilities, restore_facilities)


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    nodes = ctx.nodes
    facility_defs = ctx.facility_defs
    for key, definition in facility_defs.items():
        _require(key == definition.id, f"facility definition key mismatch: {key}")
        _require(definition.maintenance_fraction_per_year >= 0, f"negative maintenance fraction: {definition.id}")
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
        _require(facility.level >= 1, f"facility has invalid level: {facility.id}")
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
        _require(sim.graph.has_operational_node(facility.location_id), f"facility state has unknown location: {facility_id}")
        _require(facility.level >= 1, f"facility state has invalid level: {facility_id}")
        _require(isinstance(facility.maintenance_priority, int), f"facility maintenance priority must be an integer: {facility_id}")
        _require(all(amount >= -1e-9 for amount in facility.invested_resources.values()), f"facility has negative invested resource: {facility_id}")
        _require(-1e-9 <= facility.maintenance_satisfaction <= 1.0 + 1e-9, f"facility maintenance satisfaction out of range: {facility_id}")
        if sim.research is not None and facility.definition_id in sim.research.providers:
            provider = sim.research.providers[facility.definition_id]
            _require(any(level.level == facility.level for level in provider.levels), f"research provider does not define facility level: {facility_id}/{facility.level}")


DOMAIN_EXTENSION = DomainExtension(
    "facilities",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
