from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService
from .shared import DefinitionId
from .technology import TechnologyState
from .research_models import (
    ResearchDefinition,
    ResearchPrototypeSpec,
    ResearchDemonstrationSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSpec,
    ResearchPhase,
    ResearchState,
)
from .research_workflow import ResearchWorkflowMixin
from .research_capacity import ResearchCapacityMixin
from .research_execution import ResearchExecutionMixin


@dataclass
class ResearchService(ResearchWorkflowMixin, ResearchCapacityMixin, ResearchExecutionMixin):
    definitions: dict[DefinitionId, ResearchDefinition]
    providers: dict[DefinitionId, ResearchProviderSpec]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    active: dict[DefinitionId, ResearchState] = field(default_factory=dict)
    stored_points: float = 0.0

    def __post_init__(self) -> None:
        if self.stored_points < 0:
            raise ValueError("stored research points must be non-negative")

    @property
    def completed(self) -> set[DefinitionId]:
        return self.technology_state.completed


__all__ = [
    "ResearchDefinition", "ResearchPrototypeSpec", "ResearchDemonstrationSpec",
    "ResearchProviderLevelSpec", "ResearchProviderSpec", "ResearchPhase",
    "ResearchState", "ResearchService",
]
