from __future__ import annotations

from typing import Any

from .contracts import CapabilityContractTemplate, CargoContractTemplate, ContractState, ContractStatus
from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require, validate_site_requirements as _validate_site_requirements
from .shared import CargoOrderId, ContractId, DefinitionId


def capture_contracts(sim: Any) -> dict[str, Any]:
    if sim.contracts is None:
        return {"counter": 0, "items": []}
    return {
        "counter": sim.contracts._counter,
        "items": [
            {
                "id": str(c.id), "template_id": str(c.template_id), "offered_day": c.offered_day,
                "deadline_day": c.deadline_day, "status": c.status.value,
                "cargo_order_id": None if c.cargo_order_id is None else str(c.cargo_order_id),
            }
            for c in sorted(sim.contracts.contracts.values(), key=lambda row: str(row.id))
        ],
    }


def restore_contracts(sim: Any, data: dict[str, Any]) -> None:
    if sim.contracts is None:
        return
    sim.contracts._counter = int(data.get("counter", 0))
    sim.contracts.contracts.clear()
    for r in data.get("items", []):
        cid = ContractId(r["id"])
        sim.contracts.contracts[cid] = ContractState(
            cid, DefinitionId(r["template_id"]), int(r["offered_day"]), int(r["deadline_day"]),
            ContractStatus(r["status"]), None if r["cargo_order_id"] is None else CargoOrderId(r["cargo_order_id"]),
        )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    if sim.contracts is not None:
        for template in sim.contracts.templates.values():
            if isinstance(template, CargoContractTemplate):
                result.add(template.resource_id)
    return result


STATE_CODEC = StateCodec("contracts", capture_contracts, restore_contracts, True)
def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.contracts is None:
        return
    for template_id, template in sim.contracts.templates.items():
        _require(template_id == template.id, f"contract template key mismatch: {template_id}")
        _require(template.duration_days >= 0, f"negative contract duration: {template_id}")
        _require(template.reward_musd >= 0, f"negative contract reward: {template_id}")
        if isinstance(template, CapabilityContractTemplate):
            _validate_site_requirements(template.site_requirements, ctx.known_capabilities, f"contract:{template_id}")
            if template.target_location_id is not None:
                _require(template.target_location_id in ctx.nodes, f"contract references unknown location: {template_id}")
        elif isinstance(template, CargoContractTemplate):
            _require(template.source_id in ctx.nodes and template.destination_id in ctx.nodes,
                     f"cargo contract references unknown location: {template_id}")
            _require(template.source_id != template.destination_id, f"cargo contract has identical endpoints: {template_id}")
            _require(template.cargo_t > 0, f"non-positive contract cargo: {template_id}")


def validate_runtime(sim: Any) -> None:
    if sim.contracts is None:
        return
    from .shared import EntityId
    for contract_id, state in sim.contracts.contracts.items():
        _require(contract_id == state.id, f"contract state key mismatch: {contract_id}")
        _require(state.template_id in sim.contracts.templates, f"contract references unknown template: {contract_id}")
        _require(state.deadline_day >= state.offered_day, f"contract deadline precedes offer: {contract_id}")
        template = sim.contracts.templates[state.template_id]
        if isinstance(template, CargoContractTemplate) and state.status is ContractStatus.COMPLETED:
            _require(state.cargo_order_id is not None, f"completed cargo contract lacks cargo order: {contract_id}")
            _require(sim.logistics.order_complete(state.cargo_order_id), f"completed cargo contract has incomplete order: {contract_id}")
        if state.cargo_order_id is not None:
            _require(state.cargo_order_id in sim.logistics.orders, f"contract references unknown cargo order: {contract_id}")
            order = sim.logistics.orders[state.cargo_order_id]
            _require(order.owner_kind == "contract" and order.owner_id == EntityId(contract_id), f"contract cargo order owner mismatch: {contract_id}")
            if isinstance(template, CargoContractTemplate):
                _require(order.source_id == template.source_id and order.destination_id == template.destination_id,
                         f"contract cargo order endpoint mismatch: {contract_id}")
                _require(order.resource_id == template.resource_id, f"contract cargo order resource mismatch: {contract_id}")
                _require(abs(order.amount_t - template.cargo_t) <= 1e-7, f"contract cargo order amount mismatch: {contract_id}")


DOMAIN_EXTENSION = DomainExtension(
    "contracts", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    runtime_validator=validate_runtime, referenced_resources=referenced_resources,
)
