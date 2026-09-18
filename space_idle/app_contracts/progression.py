from __future__ import annotations
from dataclasses import dataclass

from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY

@dataclass(frozen=True)
class StartResearch:
    research_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
@dataclass(frozen=True)
class PauseResearch: research_id: str
@dataclass(frozen=True)
class ResumeResearch: research_id: str
@dataclass(frozen=True)
class SetResearchPrototypeSite:
    research_id: str
    stage_id: str
    operational_node_id: str
    surface_cell_id: str | None = None
@dataclass(frozen=True)
class SetResearchPriority:
    research_id: str
    priority: ActivityPriority
@dataclass(frozen=True)
class SetResearchDemonstrationSite:
    research_id: str
    stage_id: str
    operational_node_id: str
    surface_cell_id: str | None = None

@dataclass(frozen=True)
class SetResearchProviderFleetQuantity:
    provider_definition_id: str
    operational_node_id: str
    vehicle_definition_id: str
    quantity: int

@dataclass(frozen=True)
class SetResearchProviderAssignmentPriority:
    assignment_id: str
    priority: ActivityPriority

@dataclass(frozen=True)
class PauseResearchProviderAssignment:
    assignment_id: str

@dataclass(frozen=True)
class ResumeResearchProviderAssignment:
    assignment_id: str

@dataclass(frozen=True)
class SetSurveyProviderFleetQuantity:
    provider_definition_id: str
    operational_node_id: str
    vehicle_definition_id: str
    quantity: int

@dataclass(frozen=True)
class SurveyProviderConstraintInput:
    provider_definition_id: str
    operational_node_id: str

@dataclass(frozen=True)
class StartSurvey:
    target_cell_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    goal_knowledge_level: int
    provider_constraint: SurveyProviderConstraintInput | None = None
    observation_mode_constraint: str | None = None
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY

@dataclass(frozen=True)
class UpdateSurvey:
    campaign_id: str
    target_cell_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    goal_knowledge_level: int
    provider_constraint: SurveyProviderConstraintInput | None = None
    observation_mode_constraint: str | None = None

@dataclass(frozen=True)
class PauseSurvey:
    campaign_id: str

@dataclass(frozen=True)
class ResumeSurvey:
    campaign_id: str

@dataclass(frozen=True)
class SetSurveyPriority:
    campaign_id: str
    priority: ActivityPriority

@dataclass(frozen=True)
class StartScientificExploration:
    exploration_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
@dataclass(frozen=True)
class SetScientificExplorationPriority:
    exploration_id: str
    priority: ActivityPriority
@dataclass(frozen=True)
class PauseScientificExploration:
    exploration_id: str
@dataclass(frozen=True)
class ResumeScientificExploration:
    exploration_id: str
@dataclass(frozen=True)
class AssignExplorationFleet:
    exploration_id: str
    vehicle_definition_id: str
@dataclass(frozen=True)
class UnassignExplorationFleet:
    exploration_id: str
