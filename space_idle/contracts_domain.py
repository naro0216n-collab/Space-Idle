from __future__ import annotations

from typing import Any

from .contracts import ContractState, ContractStatus
from .domain import DomainExtension, StateCodec
from .shared import ContractId, DefinitionId
from .validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)


def capture_contracts(sim: Any) -> dict[str, Any]:
    if sim.contracts is None:
        return {"counter": 0, "items": []}
    return {
        "counter": sim.contracts._counter,
        "items": [
            {
                "id": str(state.id),
                "template_id": str(state.template_id),
                "offered_day": state.offered_day,
                "deadline_day": state.deadline_day,
                "status": state.status.value,
            }
            for state in sorted(
                sim.contracts.contracts.values(), key=lambda row: str(row.id)
            )
        ],
    }


def restore_contracts(sim: Any, data: dict[str, Any]) -> None:
    if sim.contracts is None:
        return
    sim.contracts._counter = int(data.get("counter", 0))
    sim.contracts.contracts = {
        ContractId(row["id"]): ContractState(
            ContractId(row["id"]),
            DefinitionId(row["template_id"]),
            int(row["offered_day"]),
            int(row["deadline_day"]),
            ContractStatus(row["status"]),
        )
        for row in data.get("items", [])
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    return set()


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.contracts is None:
        return
    for template_id, template in sim.contracts.templates.items():
        _require(template_id == template.id, f"contract template key mismatch: {template_id}")
        _require(template.duration_days >= 0, f"negative contract duration: {template_id}")
        _require(template.reward_musd >= 0, f"negative contract reward: {template_id}")
        _validate_site_requirements(
            template.site_requirements, ctx.known_capabilities, f"contract:{template_id}"
        )
        if template.target_location_id is not None:
            _require(
                template.target_location_id in ctx.nodes,
                f"contract references unknown location: {template_id}",
            )


def validate_runtime(sim: Any) -> None:
    if sim.contracts is None:
        return
    for contract_id, state in sim.contracts.contracts.items():
        _require(contract_id == state.id, f"contract state key mismatch: {contract_id}")
        _require(
            state.template_id in sim.contracts.templates,
            f"contract references unknown template: {contract_id}",
        )
        _require(
            state.deadline_day >= state.offered_day,
            f"contract deadline precedes offer: {contract_id}",
        )


STATE_CODEC = StateCodec("contracts", capture_contracts, restore_contracts, True)
DOMAIN_EXTENSION = DomainExtension(
    "contracts",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
