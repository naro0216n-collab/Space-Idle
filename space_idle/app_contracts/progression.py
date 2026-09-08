from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class StartResearch:
    research_id: str
@dataclass(frozen=True)
class PauseResearch: research_id: str
@dataclass(frozen=True)
class ResumeResearch: research_id: str
@dataclass(frozen=True)
class FundResearchPrototype:
    research_id: str; location_id: str
@dataclass(frozen=True)
class SetResearchDemonstrationSite:
    research_id: str; location_id: str
@dataclass(frozen=True)
class StartSurvey:
    location_id: str; resource_id: str; allocation_weight: float = 1.0
@dataclass(frozen=True)
class PauseSurvey:
    location_id: str; resource_id: str
@dataclass(frozen=True)
class ResumeSurvey:
    location_id: str; resource_id: str
@dataclass(frozen=True)
class SetSurveyAllocation:
    location_id: str; resource_id: str; weight: float
