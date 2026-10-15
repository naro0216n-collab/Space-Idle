"""Ownership, persistence and validation for explicitly assigned remote power links."""
from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec, decode_float, decode_list, decode_str, require_fields
from .shared import EntityId
from .power import PowerLink
from .validation_support import ValidationContext, require as _require


def capture_power(sim: Any) -> dict[str, Any]:
    return {"links": [
        {
            "source_facility_id": str(link.source_facility_id),
            "receiver_facility_id": str(link.receiver_facility_id),
            "requested_mw": link.requested_mw,
        }
        for link in sorted(sim.power.links.values(), key=lambda row:
                           (str(row.source_facility_id), str(row.receiver_facility_id)))
    ]}


def restore_power(sim: Any, data: dict[str, Any]) -> None:
    result: dict[tuple[EntityId, EntityId], PowerLink] = {}
    for index, raw in enumerate(decode_list(data["links"], "power links")):
        row = require_fields(raw, {"source_facility_id", "receiver_facility_id", "requested_mw"},
                             f"power links[{index}]")
        source = EntityId(decode_str(row["source_facility_id"], "power source"))
        receiver = EntityId(decode_str(row["receiver_facility_id"], "power receiver"))
        link = PowerLink(source, receiver, decode_float(row["requested_mw"], "power requested_mw"))
        key = (source, receiver)
        if key in result:
            raise ValueError(f"duplicate power link: {key}")
        result[key] = link
    sim.power.links = result


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    for identity, spec in sim.power.specs.items():
        _require(identity in ctx.facility_defs, f"power spec references unknown Facility: {identity}")
        _require(spec.beam_transfer_efficiency > 0, "remote power must have finite positive efficiency")


def validate_runtime(sim: Any) -> None:
    for key, link in sim.power.links.items():
        _require(key == (link.source_facility_id, link.receiver_facility_id),
                 f"power link key mismatch: {key}")
        _require(link.source_facility_id in sim.facilities.facilities,
                 f"power transmitter no longer installed: {link.source_facility_id}")
        _require(link.receiver_facility_id in sim.facilities.facilities,
                 f"power receiver no longer installed: {link.receiver_facility_id}")
        sender = sim.facilities.facilities[link.source_facility_id]
        receiver = sim.facilities.facilities[link.receiver_facility_id]
        _require(sender.operational_node_id != receiver.operational_node_id,
                 "power link must connect distinct Operational Nodes")
        _require(sim.power.specs[sender.definition_id].beam_transmit_capacity_mw > 0,
                 f"power link source cannot transmit: {sender.id}")
        _require(sim.power.specs[receiver.definition_id].beam_receive_capacity_mw > 0,
                 f"power link destination cannot receive: {receiver.id}")


DOMAIN_EXTENSION = DomainExtension(
    "power", state_codec=StateCodec("power", capture_power, restore_power),
    configuration_validator=validate_configuration, runtime_validator=validate_runtime,
)
