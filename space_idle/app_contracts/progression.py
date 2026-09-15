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
    research_id: str; operational_node_id: str
@dataclass(frozen=True)
class SetResearchPriority:
    research_id: str
    priority: ActivityPriority
@dataclass(frozen=True)
class SetResearchDemonstrationSite:
    research_id: str; operational_node_id: str

@dataclass(frozen=True)
class StartSurvey:
    provider_operational_node_id: str
    cell_id: str
    resource_id: str
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
