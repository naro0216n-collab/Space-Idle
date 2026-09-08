from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .shared import DefinitionId
from .validation_support import ValidationContext, require as _require


def capture(sim: Any) -> dict[str, Any]:
    return {"completed": sorted(str(x) for x in sim.technology.completed)}


def restore(sim: Any, data: dict[str, Any]) -> None:
    sim.technology.replace({DefinitionId(value) for value in data.get("completed", [])})


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    consumers = [sim.projects.technology_state, sim.logistics.technology_state]
    if sim.research is not None:
        consumers.append(sim.research.technology_state)
    _require(all(state is sim.technology for state in consumers),
             "technology consumers do not reference simulation-owned technology state")


STATE_CODEC = StateCodec("technology", capture, restore)
DOMAIN_EXTENSION = DomainExtension("technology", state_codec=STATE_CODEC, configuration_validator=validate_configuration)
