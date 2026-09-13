from __future__ import annotations

from dataclasses import dataclass

from ..shared import DefinitionId, EntityId

@dataclass(frozen=True)
class ProcessSpec:
    id: DefinitionId
    display_name: str
    facility_def_id: DefinitionId
    inputs_per_day: dict[DefinitionId, float]
    outputs_per_day: dict[DefinitionId, float]

@dataclass(frozen=True)
class ProcessSnapshot:
    facility_id: EntityId
    facility_def_id: DefinitionId
    process_id: DefinitionId
    scale: float
    limiting_factors: tuple[str, ...]
    input_rates_per_day: dict[DefinitionId, float]
    output_rates_per_day: dict[DefinitionId, float]
