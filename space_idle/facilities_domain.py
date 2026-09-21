from __future__ import annotations

from typing import Any

from .domain import (
    DomainExtension, StateCodec, decode_bool, decode_dict, decode_float, decode_int,
    decode_list, decode_str, require_fields,
)
from .validation_support import (
    ValidationContext,
    require as _require,
    validate_generated_id_counter as _validate_counter,
    validate_site_requirements as _validate_site_requirements,
)
from .facilities import FacilityLifecycle, FacilityPlacementScope, FacilityState
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId


def capture_facilities(sim: Any) -> dict[str, Any]:
    return {
        "counter": sim.facilities._counter,
        "items": [
            {
                "id": str(f.id),
                "definition_id": str(f.definition_id),
                "operational_node_id": str(f.operational_node_id),
                "site_cell_id": None if f.site_cell_id is None else str(f.site_cell_id),
                "paused": f.paused,
                "activity_priority": int(f.activity_priority),
                "maintenance_priority": f.maintenance_priority,
                "level": f.level,
                "lifecycle": f.lifecycle.value,
                "selected_process_id": None if f.selected_process_id is None else str(f.selected_process_id),
                "invested_resources": {str(resource_id): amount for resource_id, amount in sorted(f.invested_resources.items(), key=lambda row: str(row[0]))},
            }
            for f in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id))
        ],
    }


def restore_facilities(sim: Any, data: dict[str, Any]) -> None:
    sim.facilities.facilities.clear()
    fields = {
        "id", "definition_id", "operational_node_id", "site_cell_id", "paused",
        "activity_priority", "maintenance_priority", "level", "lifecycle",
        "selected_process_id", "invested_resources",
    }
    for index, raw in enumerate(decode_list(data["items"], "facility items")):
        row = require_fields(raw, fields, f"facility[{index}]")
        fid = EntityId(decode_str(row["id"], "facility id"))
        if fid in sim.facilities.facilities:
            raise ValueError(f"duplicate facility: {fid}")
        site_cell_id = row["site_cell_id"]
        selected_process_id = row["selected_process_id"]
        invested_resources = decode_dict(row["invested_resources"], "facility invested_resources")
        sim.facilities.facilities[fid] = FacilityState(
            id=fid,
            definition_id=DefinitionId(decode_str(row["definition_id"], "facility definition_id")),
            operational_node_id=SpatialNodeId(
                decode_str(row["operational_node_id"], "facility operational_node_id")
            ),
            site_cell_id=(
                None if site_cell_id is None
                else SurfaceCellId(decode_str(site_cell_id, "facility site_cell_id"))
            ),
            paused=decode_bool(row["paused"], "facility paused"),
            activity_priority=decode_int(row["activity_priority"], "facility activity_priority"),
            maintenance_priority=decode_int(
                row["maintenance_priority"], "facility maintenance_priority"
            ),
            level=decode_int(row["level"], "facility level"),
            lifecycle=FacilityLifecycle(decode_str(row["lifecycle"], "facility lifecycle")),
            selected_process_id=(
                None if selected_process_id is None
                else DefinitionId(decode_str(selected_process_id, "facility selected_process_id"))
            ),
            invested_resources={
                DefinitionId(key): decode_float(value, "facility invested resource")
                for key, value in invested_resources.items()
            },
        )
    sim.facilities._counter = decode_int(data["counter"], "facility counter")


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return {
        resource_id
        for facility in sim.facilities.facilities.values()
        for resource_id in facility.invested_resources
    }


STATE_CODEC = StateCodec("facilities", capture_facilities, restore_facilities)


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    nodes = ctx.operational_nodes
    facility_defs = ctx.facility_defs
    for key, definition in facility_defs.items():
        _require(key == definition.id, f"facility definition key mismatch: {key}")
        _require(definition.maintenance_fraction_per_year >= 0, f"negative maintenance fraction: {definition.id}")
        _require(0 <= definition.decommission_recovery_fraction <= 1, f"invalid decommission recovery fraction: {definition.id}")
        _require(isinstance(definition.placement_scope, FacilityPlacementScope), f"invalid facility placement scope: {definition.id}")
        seen_caps: set[str] = set()
        for supply in definition.capability_supplies:
            _require(supply.id not in seen_caps, f"duplicate capability {supply.id} on {definition.id}")
            seen_caps.add(supply.id)
        _validate_site_requirements(
            definition.installation_requirements,
            ctx.known_capabilities,
            f"facility:{definition.id}:installation",
        )
        _validate_site_requirements(
            definition.operating_requirements,
            ctx.known_capabilities,
            f"facility:{definition.id}:operating",
        )
    for facility in sim.facilities.facilities.values():
        _require(facility.definition_id in facility_defs, f"facility references unknown definition: {facility.id}")
        _require(facility.operational_node_id in nodes, f"facility references unknown operational node: {facility.id}")
        _require(not sim.facilities.placement_failures(facility.definition_id, facility.operational_node_id, facility.site_cell_id), f"facility has invalid placement: {facility.id}")
        _require(facility.level >= 1, f"facility has invalid level: {facility.id}")
        _require(isinstance(facility.lifecycle, FacilityLifecycle), f"facility has invalid lifecycle: {facility.id}")
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
    _validate_counter(
        sim.facilities._counter, sim.facilities.facilities, "facility.", "facility"
    )
    for facility_id, facility in sim.facilities.facilities.items():
        _require(facility_id == facility.id, f"facility state key mismatch: {facility_id}")
        _require(facility.definition_id in sim.facilities.definitions, f"facility state has unknown definition: {facility_id}")
        _require(sim.graph.has_operational_node(facility.operational_node_id), f"facility state has unknown operational node: {facility_id}")
        _require(not sim.facilities.placement_failures(facility.definition_id, facility.operational_node_id, facility.site_cell_id), f"facility state has invalid placement: {facility_id}")
        _require(facility.level >= 1, f"facility state has invalid level: {facility_id}")
        _require(1 <= int(facility.activity_priority) <= 5, f"facility activity priority must be 1..5: {facility_id}")
        _require(1 <= int(facility.maintenance_priority) <= 5, f"facility maintenance priority must be 1..5: {facility_id}")
        _require(all(amount >= -1e-9 for amount in facility.invested_resources.values()), f"facility has negative invested resource: {facility_id}")


DOMAIN_EXTENSION = DomainExtension(
    "facilities",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
    service_capacity_provider=lambda sim: sim.facilities,
)
