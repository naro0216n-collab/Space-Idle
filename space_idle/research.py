from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .knowledge import ExperienceContributionRule, KnowledgeState
from .power import PowerService
from .service_capacity import ServiceCapacityRegistry
from .shared import DefinitionId, EntityId
from .technology import TechnologyState
from .research_models import (
    ResearchDefinition,
    ResearchTheoryStageSpec,
    ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec,
    ResearchOperationalExperienceStageSpec,
    ResearchStageSpec,
    ResearchProviderLevelSpec,
    ResearchProviderSourceKind,
    ResearchProviderSpec,
    ResearchExecutionSite,
    ResearchStage,
    ResearchState,
)
from .research_workflow import ResearchWorkflowMixin
from .research_capacity import ResearchCapacityMixin
from .research_execution import ResearchExecutionMixin


@dataclass
class ResearchProviderAssignmentState:
    id: EntityId
    provider_definition_id: DefinitionId
    vehicle_definition_id: DefinitionId
    operational_node_id: object
    priority: int
    paused: bool = False
    fleet_commitment_ref: EntityId | None = None


@dataclass
class ResearchService(ResearchWorkflowMixin, ResearchCapacityMixin, ResearchExecutionMixin):
    definitions: dict[DefinitionId, ResearchDefinition]
    providers: dict[DefinitionId, ResearchProviderSpec]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    service_capacity_registry: ServiceCapacityRegistry
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    active: dict[DefinitionId, ResearchState] = field(default_factory=dict)
    stored_points: float = 0.0
    knowledge_state: KnowledgeState = field(default_factory=KnowledgeState)
    experience_rules: tuple[ExperienceContributionRule, ...] = ()
    provider_assignments: dict[EntityId, ResearchProviderAssignmentState] = field(default_factory=dict)
    last_point_allocations: dict[DefinitionId, float] = field(default_factory=dict, init=False)
    last_point_requests: dict[DefinitionId, float] = field(default_factory=dict, init=False)
    last_execution_allocations: dict[DefinitionId, float] = field(default_factory=dict, init=False)
    last_execution_requests: dict[DefinitionId, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.stored_points < 0:
            raise ValueError("stored research points must be non-negative")

    @property
    def completed(self) -> set[DefinitionId]:
        return self.technology_state.completed


__all__ = [
    "ResearchDefinition", "ResearchTheoryStageSpec", "ResearchPrototypeStageSpec",
    "ResearchDemonstrationStageSpec", "ResearchOperationalExperienceStageSpec",
    "ResearchStageSpec", "ResearchProviderLevelSpec", "ResearchProviderSourceKind",
    "ResearchProviderSpec", "ResearchExecutionSite", "ResearchStage", "ResearchState",
    "ResearchProviderAssignmentState", "ResearchService",
]
