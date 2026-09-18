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
class CreateResearchProviderAssignment:
    provider_definition_id: str
    operational_node_id: str
    quantity: int
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY

@dataclass(frozen=True)
class ResizeResearchProviderAssignment:
    assignment_id: str
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
class ReleaseResearchProviderAssignment:
    assignment_id: str

@dataclass(frozen=True)
class CreateSurveyProviderAssignment:
    provider_definition_id: str
    operational_node_id: str
    quantity: int
@dataclass(frozen=True)
class ResizeSurveyProviderAssignment:
    assignment_id: str
    quantity: int
@dataclass(frozen=True)
class ReleaseSurveyProviderAssignment:
    assignment_id: str

@dataclass(frozen=True)
class StartSurvey:
    provider_operational_node_id: str
    provider_definition_id: str
    observation_mode_id: str
    cell_id: str
    resource_id: str
    target_knowledge_level: int
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
@dataclass(frozen=True)
class PauseSurvey:
    cell_id: str
    resource_id: str
@dataclass(frozen=True)
class ResumeSurvey:
    cell_id: str
    resource_id: str
@dataclass(frozen=True)
class SetSurveyPriority:
    cell_id: str
    resource_id: str
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
